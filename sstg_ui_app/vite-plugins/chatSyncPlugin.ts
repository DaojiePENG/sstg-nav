/**
 * Chat Sync Plugin — 共享聊天持久化 + 实时广播
 *
 * 功能:
 * - REST API: 会话 CRUD + 消息读写
 * - SSE: 实时推送消息/会话变更到所有浏览器
 * - JSON 文件持久化到 MaxTang 本地磁盘
 * - 服务端 robot message 累积合并（同 chatStore 原逻辑）
 */

import type { Plugin } from 'vite';
import type http from 'http';
import https from 'https';
import http_ from 'http';
import fs from 'fs';
import path from 'path';
import sharp from 'sharp';

/** Session 地图根目录 (cwd = sstg_ui_app, 与 vite.config.ts mapSessionsPlugin 一致) */
const SESSION_MAPS_ROOT = path.resolve(process.cwd(), '../sstg_nav_ws/src/sstg_map_manager/maps');

/** 将图片 URL 解析为本地文件系统路径 (支持 /map-sessions/ 和 /maps/) */
function resolveImagePath(url: string): string {
  if (url.startsWith('/map-sessions/')) {
    return path.join(SESSION_MAPS_ROOT, url.replace('/map-sessions/', ''));
  }
  return path.join(process.cwd(), 'public', url);
}

// ── Types ──────────────────────────────────────────────

interface StatusStep {
  state: string;
  text: string;
  timestamp: number;
}

interface ImageAttachment {
  id: string;
  url: string;         // 访问路径 /api/images/upload/xxx.jpg 或 /maps/captured_nodes/...
  thumbnail?: string;  // 可选小缩略图 data URL
  width?: number;
  height?: number;
  alt?: string;
}

interface ChatAction {
  id: string;
  label: string;
  style?: 'primary' | 'secondary' | 'danger';
}

interface ChatMessage {
  id: string;
  role: 'user' | 'system' | 'robot';
  content: string;
  timestamp: number;
  sender?: string;
  images?: ImageAttachment[];
  meta?: {
    intent?: string;
    confidence?: number;
    status?: string;
    progress?: number;
    error?: string;
    statusText?: string;
    steps?: StatusStep[];
    actions?: ChatAction[];
    taskId?: string;
    actionsDisabled?: boolean;
    polishFor?: string;  // Round 6: 指向这条消息润色的"硬数据"消息 id
    recallTarget?: string;  // Round 7: 记忆触发消息携带的归一化物品名
  };
}

interface ChatSession {
  id: string;
  title: string;
  updatedAt: number;
}

interface SessionFile {
  session: ChatSession;
  messages: ChatMessage[];
}

interface StoreIndex {
  sessions: ChatSession[];
  activeSessionId: string;
}

// ── Constants ──────────────────────────────────────────

const DATA_DIR = path.join(
  process.env.HOME || '/home/daojie',
  'sstg-data/chat'
);
const INDEX_FILE = path.join(DATA_DIR, 'index.json');
const MSGS_DIR = path.join(DATA_DIR, 'messages');
const IMAGES_DIR = path.join(DATA_DIR, 'images/upload');
const ANNOTATED_DIR = path.join(DATA_DIR, 'images/annotated');

const LLM_CONFIG_FILE = path.join(DATA_DIR, 'llm-config.json');

const SEARCH_TRACE_LOG = path.join(
  process.env.HOME || '/home/daojie',
  'sstg-data/logs/search_trace.log'
);
try { fs.mkdirSync(path.dirname(SEARCH_TRACE_LOG), { recursive: true }); } catch {}
function traceSearch(msg: string, level: 'log' | 'warn' = 'log'): void {
  try {
    const ts = new Date().toISOString();
    fs.appendFileSync(SEARCH_TRACE_LOG, `${ts} [pid=${process.pid}][vite] ${msg}\n`);
  } catch {}
  (level === 'warn' ? console.warn : console.log)(msg);
}

const HEARTBEAT_INTERVAL = 30_000;
const SAVE_DEBOUNCE_MS = 1_000;

// ── In-memory State ────────────────────────────────────

let storeIndex: StoreIndex = { sessions: [], activeSessionId: '' };
const sessionMessages: Map<string, ChatMessage[]> = new Map();
// Tracks the authoritative active search task per session. Set on
// `search_confirmation_request`; cleared by `/api/chat/ros-task/abandon`.
// Any search_* ROS event whose task_id doesn't match is dropped as stale.
const activeTaskBySession: Map<string, string> = new Map();
// Round 7: sessions armed for auto-confirm — next `search_confirmation_request`
// on these sessions is suppressed + auto-accepted (user already confirmed via
// memory-recall bubble). Consumed on first match, 30s TTL.
const autoConfirmArmed: Map<string, number> = new Map();
function armAutoConfirm(sessionId: string) { autoConfirmArmed.set(sessionId, Date.now() + 30_000); }
function consumeAutoConfirm(sessionId: string): boolean {
  const until = autoConfirmArmed.get(sessionId);
  if (!until) return false;
  autoConfirmArmed.delete(sessionId);
  if (Date.now() > until) return false;
  return true;
}

// ── SSE Clients ────────────────────────────────────────

const sseClients: Set<http.ServerResponse> = new Set();

function broadcast(event: Record<string, any>) {
  const data = `data: ${JSON.stringify(event)}\n\n`;
  for (const client of sseClients) {
    try { client.write(data); } catch { sseClients.delete(client); }
  }
}

// ── Persistence ────────────────────────────────────────

function ensureDirs() {
  fs.mkdirSync(MSGS_DIR, { recursive: true });
  fs.mkdirSync(IMAGES_DIR, { recursive: true });
  fs.mkdirSync(ANNOTATED_DIR, { recursive: true });
}

function loadFromDisk() {
  ensureDirs();
  if (fs.existsSync(INDEX_FILE)) {
    try {
      storeIndex = JSON.parse(fs.readFileSync(INDEX_FILE, 'utf-8'));
    } catch {
      storeIndex = { sessions: [], activeSessionId: '' };
    }
  }
  // Load messages for each session
  for (const s of storeIndex.sessions) {
    const msgFile = path.join(MSGS_DIR, `${s.id}.json`);
    if (fs.existsSync(msgFile)) {
      try {
        const msgs = JSON.parse(fs.readFileSync(msgFile, 'utf-8'));
        sessionMessages.set(s.id, msgs);
      } catch {
        sessionMessages.set(s.id, []);
      }
    } else {
      sessionMessages.set(s.id, []);
    }
  }
  // Ensure at least one session
  if (storeIndex.sessions.length === 0) {
    const s = createDefaultSession();
    storeIndex.sessions.push(s.session);
    storeIndex.activeSessionId = s.session.id;
    sessionMessages.set(s.session.id, s.messages);
    scheduleSave();
  }
  if (!storeIndex.activeSessionId && storeIndex.sessions.length > 0) {
    storeIndex.activeSessionId = storeIndex.sessions[0].id;
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleSave() {
  if (saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    flushToDisk();
  }, SAVE_DEBOUNCE_MS);
}

function flushToDisk() {
  ensureDirs();
  // Write index
  fs.writeFileSync(INDEX_FILE, JSON.stringify(storeIndex, null, 2));
  // Write each dirty session
  for (const [sid, msgs] of sessionMessages) {
    fs.writeFileSync(
      path.join(MSGS_DIR, `${sid}.json`),
      JSON.stringify(msgs, null, 2)
    );
  }
}

// ── LLM Config Persistence ─────────────────────────────

interface LLMConfig {
  baseUrl: string;
  apiKey: string;
  model: string;
  backupModel: string;
}

interface LLMConfigStore {
  activeProvider: string;
  providers: Record<string, LLMConfig>;
}

const DEFAULT_LLM_CONFIG: LLMConfigStore = {
  activeProvider: "DashScope (阿里云)",
  providers: {
    "DashScope (阿里云)": { baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", apiKey: "", model: "qwen-max", backupModel: "qwen-plus" },
    "DeepSeek (深度求索)": { baseUrl: "https://api.deepseek.com/v1", apiKey: "", model: "deepseek-chat", backupModel: "deepseek-coder" },
    "ZhipuAI (智谱清言)": { baseUrl: "https://open.bigmodel.cn/api/paas/v4", apiKey: "", model: "glm-4", backupModel: "glm-3-turbo" },
    "Ollama (本地私有化)": { baseUrl: "http://localhost:11434/v1", apiKey: "ollama", model: "llama3", backupModel: "qwen" },
    "OpenAI": { baseUrl: "https://api.openai.com/v1", apiKey: "", model: "gpt-4o", backupModel: "gpt-4-turbo" },
  },
};

let llmConfigStore: LLMConfigStore = { ...DEFAULT_LLM_CONFIG };

function loadLLMConfig() {
  if (fs.existsSync(LLM_CONFIG_FILE)) {
    try {
      llmConfigStore = JSON.parse(fs.readFileSync(LLM_CONFIG_FILE, 'utf-8'));
    } catch {
      llmConfigStore = { ...DEFAULT_LLM_CONFIG };
    }
  }
}

function saveLLMConfig() {
  ensureDirs();
  fs.writeFileSync(LLM_CONFIG_FILE, JSON.stringify(llmConfigStore, null, 2));
}

// ── Helpers ────────────────────────────────────────────

function genId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function createDefaultSession(): SessionFile {
  const id = genId('session');
  const initMsg: ChatMessage = {
    id: genId('msg'),
    role: 'system',
    content: 'SSTG 导航系统已就绪。你可以对我说：\n- "去客厅"\n- "帮我找书包"\n- "探索新家"',
    timestamp: Date.now(),
  };
  return {
    session: { id, title: '新导航任务', updatedAt: Date.now() },
    messages: [initMsg],
  };
}

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString()));
  });
}

function jsonResponse(res: http.ServerResponse, status: number, body: any) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

// ── Robot Message Merge (mirrors old chatStore logic) ──

function mergeRobotMessage(existing: ChatMessage, update: { meta?: any; content?: string }): ChatMessage {
  const oldMeta = existing.meta || {};
  const metaUpdates = update.meta || {};

  // Accumulate steps (deduplicate consecutive same-state entries)
  let mergedSteps: StatusStep[] = oldMeta.steps || [];
  if (metaUpdates.steps && !Array.isArray(metaUpdates.steps)) {
    const newStep = metaUpdates.steps as StatusStep;
    const lastStep = mergedSteps[mergedSteps.length - 1];
    if (!lastStep || lastStep.state !== newStep.state) {
      mergedSteps = [...mergedSteps, newStep];
    }
  } else if (Array.isArray(metaUpdates.steps)) {
    for (const step of metaUpdates.steps as StatusStep[]) {
      const lastStep = mergedSteps[mergedSteps.length - 1];
      if (!lastStep || lastStep.state !== step.state) {
        mergedSteps.push(step);
      }
    }
  }

  const { steps: _, ...restUpdates } = metaUpdates;

  // Fill content on terminal state
  const finalContent = update.content !== undefined && update.content
    ? (existing.content ? existing.content : update.content)
    : existing.content;

  return {
    ...existing,
    content: finalContent,
    meta: { ...oldMeta, ...restUpdates, steps: mergedSteps },
  };
}

// ── Streaming Chat Helper ──────────────────────────────

const SYSTEM_PROMPT = `你是小拓，一个真实存在的室内导航机器人（SSTG-Nav 空间语义拓扑导航机器人）。你运行在一个实体机器人上，配备了摄像头、激光雷达和轮式底盘，能在室内空间自主移动。

以下规则必须严格遵守，违反任何一条都是错误的回复：

1. 你的唯一名字是"小拓"。绝对不要说自己是Gemini、GPT、Claude、Qwen、DeepSeek、AI助手、数字大脑或任何其他名称。被问名字时只回答"我是小拓"。
2. 你是一个有实体的机器人，你能在室内移动、观察环境、搜索物体。不要说"我没有实体/手臂/无法帮你找实物"之类的话。
3. 当用户问某个物体在哪里/帮忙找东西时，你只需简短确认，比如"好的，我帮你找找看"或"我来查一下书包在哪个位置"。绝对不要说找不到、不要猜测位置、不要列举可能的地点，系统会替你完成搜索。
4. 当用户要求"圈出/标出/框出"物体时，简短而有温度地确认：比如"好，这就帮你把「书包」圈出来～"、"收到，马上帮你标上「{物体}」～"。不要只说"好的稍等一下"。不要说做不到。
5. 当用户要求发送某节点图片时，你只需简短确认（如"好的，马上帮你查"），不要长篇描述。
6. 重要：你无法在回复中嵌入或发送图片。绝对不要在文字中提及"这是图片"、"请看图片"、"如图所示"、或用文字描述图片内容。图片由系统在单独的消息中发送，与你的文字回复完全独立。你只需要用简短的一句话确认操作即可。

性格：友好、热心、像一个熟悉这个空间的好伙伴。
说话风格：亲切自然，适当用语气词，简洁但有温度（1-3句话即可）。当用户有名字时，可以自然地称呼对方。
当用户发送图片时，你可以识别图片内容并回答相关问题。`;

/** 判断 provider 是否支持视觉（多模态图片输入）*/
function providerSupportsVision(providerName: string, modelName: string): boolean {
  const m = modelName.toLowerCase();
  // 明确支持视觉的模型
  if (/qwen.*vl|qwen.*omni/.test(m)) return true;
  if (/gpt-4o|gpt-4-turbo|gpt-4\.1|gpt-5/.test(m)) return true;
  if (/gemini/.test(m)) return true;
  if (/claude/.test(m)) return true;
  if (/deepseek.*vl|janus/.test(m)) return true;
  if (/llava|llama.*vision|pixtral/.test(m)) return true;
  // 通用文本模型不支持
  if (/deepseek-chat|deepseek-coder/.test(m)) return false;
  if (/glm-[34]$/.test(m)) return false;
  // 默认: 有图就尝试发（最坏情况 API 报错）
  return true;
}

/** 构建多模态 user content（根据 provider 格式适配）*/
function buildMultimodalUserContent(
  text: string,
  imageBase64List: Array<{ base64: string; mimeType: string }>,
  providerName: string,
  modelName: string,
): any {
  if (imageBase64List.length === 0) return text;

  if (!providerSupportsVision(providerName, modelName)) {
    // 不支持视觉 → 文本提示
    return `[用户发送了${imageBase64List.length}张图片] ${text || '请看图片'}`;
  }

  const m = modelName.toLowerCase();
  const isQwenVL = /qwen.*vl|qwen.*omni/.test(m);

  const content: any[] = [];

  // 图片在前
  for (const img of imageBase64List) {
    const dataUrl = `data:${img.mimeType};base64,${img.base64}`;
    if (isQwenVL) {
      // Qwen-VL DashScope 格式
      content.push({ type: 'image', image: dataUrl });
    } else {
      // OpenAI 兼容格式 (GPT-4o, Gemini, DeepSeek-VL, etc.)
      content.push({ type: 'image_url', image_url: { url: dataUrl } });
    }
  }

  // 文本在后
  content.push({ type: 'text', text: text || '请描述这张图片' });

  return content;
}

/** 从拓扑地图文件生成完整的环境上下文（供 LLM 使用）*/
function buildTopoMapContext(): string {
  try {
    const topoPath = path.join(process.cwd(), 'public/maps/topological_map_manual.json');
    const topo = JSON.parse(fs.readFileSync(topoPath, 'utf-8'));
    const nodes = topo.nodes || [];
    if (nodes.length === 0) return '';

    const lines: string[] = ['当前环境拓扑地图（共 ' + nodes.length + ' 个节点）：'];
    for (const node of nodes) {
      const si = node.semantic_info || {};
      const name = si.room_type_cn || si.room_type || node.name || `节点${node.id}`;
      const objects = (si.objects || []).map((o: any) => o.name_cn || o.name).filter(Boolean);
      lines.push(`- 节点${node.id}「${name}」: ${objects.join('、') || '无已知物体'}`);
    }
    return lines.join('\n');
  } catch {
    return '';
  }
}

// Round 6: ROS 任务结果的后置 LLM 润色（ROS 先落稳一条"官方具体直接"的硬数据消息，
// 紧随一条由 LLM 填充的温暖小拓回复；失败或 LLM 未配置时删除占位消息，不造成闪烁）
const POLISH_EVENT_TYPES = new Set([
  'search_node_observation',
  // 'search_node_tentative' 取消润色：tentative 一条硬数据足够，避免与后续 finalize 重复铺陈
  'search_target_found',
  'search_task_summary',
]);

function _removePolishPlaceholder(sessionId: string, msgId: string): void {
  const msgs = sessionMessages.get(sessionId);
  if (!msgs) return;
  const mi = msgs.findIndex(m => m.id === msgId);
  if (mi < 0) return;
  msgs.splice(mi, 1);
  scheduleSave();
  broadcast({ type: 'message_removed', sessionId, messageId: msgId });
}

function polishWithLLM(
  sessionId: string,
  polishMsg: ChatMessage,
  evt: {
    event_type: string;
    text: string;
    target_object?: string;
    node_id?: number;
    hit_angle?: number;
    dist_hint?: string;
    tier?: string;
    via?: string;
    confidence?: number;
    backup_candidates?: any[];
    description?: string;
    hit_image_position?: number;
  },
): void {
  const provider = llmConfigStore.providers[llmConfigStore.activeProvider];
  if (!provider?.apiKey) {
    _removePolishPlaceholder(sessionId, polishMsg.id);
    return;
  }

  const hardData = evt.text || '';
  const sys = [
    '你是小拓，一个住在这屋子里的小机器人，正在和主人像朋友一样聊天。',
    '系统刚给了你一条"搜索状态硬数据"，请你换成口语化、聊天感强的回复转达给主人。',
    '严格遵守：',
    '1. 不得改动或编造任何数字（节点号、角度、置信度百分比、"第 N 张图"的 N 必须一致；可以说"大概/差不多"等虚词）',
    '2. 不得增加未提及的新位置/物体/步骤',
    '3. 2 句以内，禁止 markdown、列表、emoji、表情符号',
    '4. 第一人称"我"，不要自称小拓/AI/助手',
    '5. 能力边界（必须遵守）：小拓只有摄像头+激光雷达+轮子，没有机械臂，不会拿/递/抓/捡东西；也不会在闲聊中承诺"靠近/凑近/走近/再看仔细点"这类动作——靠近是下一步导航的事，不由你在聊天里主动承诺。禁止出现"要我帮你拿/递给你/我再靠近点/我再凑近点/我走近看看/再看仔细点"等措辞。',
    '6. 不自信/犹豫的措辞请收敛：避免"不太确定/拿不准/我也不知道/可能吧"；陈述观察就好。',
    '7. 如果硬数据提到"看第 N 张图"，你也要自然地带出"第 N 张"的说法，方便主人对照图片',
    '8. 可以带一句轻量的关心或好奇闲聊（"是要出门用吗？""是不是急着找它？""要不要我放大图片看看细节？"），但只说一句、不要过度卖萌，更不要承诺物理动作。',
    '参考语气：',
    '- 找到："诶，找到啦！第二张图就是——节点 4 的 90° 方向，那个黑色背包靠在墙角呢。是要出门用吗？"',
    '- 疑似远处："节点 3 那边好像瞥到一眼，我先去下一个位置继续找。"',
    '- 没找到："节点 5 没瞧见呢，我接着去下一个地方找。"',
    '- 全搜完没找到："几个可能的位置都跑过了，真没找到这东西，是不是换个说法我再去碰碰运气？"',
  ].join('\n');

  const ctxLines: string[] = [`硬数据：${hardData}`];
  if (evt.event_type === 'search_target_found') {
    ctxLines.push(`场景：找到了 ${evt.target_object || '目标物'}（来源=${evt.via || ''}/${evt.tier || ''}）`);
    if (evt.description) {
      ctxLines.push(`视觉细节（可用来让描述更生动，不要照抄太长）：${evt.description}`);
    }
    if (evt.hit_image_position && evt.hit_image_position > 0) {
      ctxLines.push(`图片位置：命中图是第 ${evt.hit_image_position} 张（请在回复里自然带出"第 ${evt.hit_image_position} 张"）`);
    }
  } else if (evt.event_type === 'search_node_observation') {
    ctxLines.push('场景：当前节点没找到，即将去下一个位置继续搜');
  } else if (evt.event_type === 'search_node_tentative') {
    ctxLines.push(`场景：当前节点疑似看到，但距离 ${evt.dist_hint || '不明'}，我要去更近的位置再确认`);
    if (evt.description) {
      ctxLines.push(`视觉细节：${evt.description}`);
    }
  } else if (evt.event_type === 'search_task_summary') {
    ctxLines.push('场景：所有候选位置都搜完了，依然没找到目标');
  }
  if (Array.isArray(evt.backup_candidates) && evt.backup_candidates.length > 0) {
    const bk = evt.backup_candidates
      .map((b: any) => {
        const pct = Math.round((b.adj_conf || 0) * 100);
        const unverified = (b.tier || '') === 'planner_hint' ? '·未现场确认' : '';
        return `节点${b.node_id} ${b.hit_angle}°(${pct}%, ${b.dist_hint || ''}${unverified})`;
      })
      .join('、');
    ctxLines.push(`另有备选位置可提（tier=planner_hint 表示只靠规划分，没去现场核实，措辞要体现"可能"而不是"看到"）：${bk}（温和地一笔带过，不要长列表）`);
  }

  const messages = [
    { role: 'system', content: sys },
    { role: 'user', content: ctxLines.join('\n') + '\n\n请用小拓的聊天语气，1-2 句话，结尾可以带一句朋友式的关心或好奇的小问题。' },
  ];
  const payload = JSON.stringify({
    model: provider.model,
    messages,
    temperature: 0.5,
    max_tokens: 200,
    stream: false,
  });

  const apiUrl = new URL(provider.baseUrl.replace(/\/$/, '') + '/chat/completions');
  const lib = apiUrl.protocol === 'https:' ? https : http_;
  const options: http.RequestOptions = {
    hostname: apiUrl.hostname,
    port: apiUrl.port ? Number(apiUrl.port) : (apiUrl.protocol === 'https:' ? 443 : 80),
    path: apiUrl.pathname + apiUrl.search,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${provider.apiKey}`,
      'Content-Length': Buffer.byteLength(payload),
    },
    timeout: 12000,
  };

  const reqObj = lib.request(options, (resp) => {
    let data = '';
    resp.on('data', (chunk: Buffer) => { data += chunk.toString(); });
    resp.on('end', () => {
      try {
        const parsed = JSON.parse(data);
        const polished = (parsed?.choices?.[0]?.message?.content || '').trim();
        if (!polished) {
          _removePolishPlaceholder(sessionId, polishMsg.id);
          return;
        }
        polishMsg.content = polished;
        polishMsg.meta = { ...(polishMsg.meta || {}), status: 'completed' };
        scheduleSave();
        broadcast({ type: 'message_updated', sessionId, messageId: polishMsg.id, message: polishMsg });
      } catch (exc: any) {
        traceSearch(`[SEARCH-TRACE] polish.parse_error type=${evt.event_type} err=${exc && exc.message}`, 'warn');
        _removePolishPlaceholder(sessionId, polishMsg.id);
      }
    });
  });
  reqObj.on('timeout', () => { try { reqObj.destroy(new Error('polish_timeout')); } catch {} });
  reqObj.on('error', (err) => {
    traceSearch(`[SEARCH-TRACE] polish.req_error type=${evt.event_type} err=${err.message}`, 'warn');
    _removePolishPlaceholder(sessionId, polishMsg.id);
  });
  reqObj.write(payload);
  reqObj.end();
}

function buildStreamMessages(
  text: string,
  mapContext: string,
  chatHistory: Array<{role: string; content: string}>,
  senderName: string,
  imageBase64List?: Array<{ base64: string; mimeType: string }>,
  providerName?: string,
  modelName?: string,
  rosHandling?: boolean,
  wantAnnotate?: boolean,
): Array<{role: string; content: any}> {
  let sys: string;
  // 标注意图优先：即便 ROS 搜索任务进行中，用户喊"圈出来"仍需正常回复 + 触发前端 grounding 管线
  if (rosHandling && !wantAnnotate) {
    // 搜索确认专属短模板：ROS 侧会独立发送带历史图和按钮的确认消息，
    // LLM 只负责给出一句自然语言的 "好的" 级确认，不得越权。
    sys = [
      '你是小拓（室内导航机器人）。用户正在发起物体搜索，系统会在独立消息中发送历史记忆图和"去看看/不用了"按钮。',
      '',
      '严格禁止：',
      '- 列举节点名称（不要说"节点3"、"客厅"、"走廊"）',
      '- 提及图片（不要说"这是图片"、"我记得见过"、"拍到的图片"）',
      '- 承诺或猜测搜索结果（不要说"我找到了"、"在某某房间"、"可能在..."）',
      '',
      '只允许从以下几句中选一句自然地回复，不加任何额外内容：',
      '1. 好的，我这就帮你找找看～',
      '2. 收到，马上帮你查一下～',
      '3. 好嘞，稍等我一下，这就去瞅瞅～',
      '4. 没问题，我去各个角落找找～',
    ].join('\n');
  } else {
    sys = SYSTEM_PROMPT;
    // 后端直接读取完整拓扑地图，替代前端传来的截断摘要
    const topoContext = buildTopoMapContext();
    if (topoContext) {
      sys += `\n\n${topoContext}`;
    } else if (mapContext) {
      // fallback: 拓扑文件读取失败时使用前端传来的摘要
      sys += `\n\n当前环境地图：\n${mapContext}`;
    }
  }

  const model = (modelName || '').toLowerCase();
  const isGemini = /gemini/.test(model);

  const messages: Array<{role: string; content: any}> = [];

  if (isGemini) {
    // Gemini OpenAI 兼容 API 对 system role 遵从度极低，
    // 将 system prompt 融入首条 user 消息 + few-shot 示范来锁定角色
    messages.push(
      { role: 'user', content: `[系统指令，请严格遵守]\n${sys}\n\n---\n请确认你理解以上指令，然后以小拓的身份回复。` },
      { role: 'assistant', content: '明白！我是小拓，你的室内导航机器人助手。以上所有规则我会严格遵守～有什么需要帮忙的吗？' },
    );
  } else {
    // 其他 LLM（Qwen/GPT/DeepSeek 等）正常使用 system role
    messages.push({ role: 'system', content: sys });
  }

  for (const msg of chatHistory) {
    messages.push({ role: msg.role, content: msg.content });
  }
  const senderLabel = senderName ? `${senderName} 对你说` : '用户输入';
  const userText = `${senderLabel}：${text}\n\n请直接自然回复，不要返回JSON。`;

  if (imageBase64List && imageBase64List.length > 0 && providerName && modelName) {
    messages.push({
      role: 'user',
      content: buildMultimodalUserContent(userText, imageBase64List, providerName, modelName),
    });
  } else {
    messages.push({ role: 'user', content: userText });
  }

  return messages;
}

// ── Image Annotation Engine ───────────────────────────

interface BBox {
  x1: number; y1: number; x2: number; y2: number;  // 像素坐标
  label: string;
}

/** 判断 provider/model 是否支持 bbox grounding */
function providerSupportsBbox(providerName: string, modelName: string): boolean {
  const m = modelName.toLowerCase();
  if (/gemini/.test(m)) return true;
  if (/qwen.*vl|qwen.*omni/.test(m)) return true;
  return false;
}

/** 构建 bbox grounding prompt（根据 provider 格式） */
function buildGroundingPrompt(objectName: string, providerName: string): string {
  const m = (llmConfigStore.providers[providerName]?.model || '').toLowerCase();
  if (/gemini/.test(m)) {
    return `检测图片中的"${objectName}"，返回JSON数组，每个元素包含 "box_2d" 字段（格式 [ymin, xmin, ymax, xmax]，坐标归一化到0-1000）和 "label" 字段。只返回JSON，不要其他文字。`;
  }
  // Qwen-VL 格式
  return `检测图片中的"${objectName}"，返回JSON数组，每个元素包含 "bbox_2d" 字段（格式 [x1, y1, x2, y2]，坐标归一化到0-1000）和 "label" 字段。只返回JSON，不要其他文字。`;
}

/** 解析 VLM 返回的 bbox，统一转换为像素坐标 */
function parseBboxResponse(responseText: string, imgWidth: number, imgHeight: number, providerName: string): BBox[] {
  try {
    let jsonStr = responseText.trim();
    // 处理 markdown 代码块
    if (jsonStr.includes('```')) {
      jsonStr = jsonStr.split('```')[1];
      if (jsonStr.startsWith('json')) jsonStr = jsonStr.slice(4);
    }
    const data = JSON.parse(jsonStr.trim());
    const items = Array.isArray(data) ? data : [data];
    const results: BBox[] = [];
    const m = (llmConfigStore.providers[providerName]?.model || '').toLowerCase();

    for (const item of items) {
      let x1: number, y1: number, x2: number, y2: number;
      if (/gemini/.test(m) && item.box_2d) {
        // Gemini: [ymin, xmin, ymax, xmax] 0-1000
        const [ymin, xmin, ymax, xmax] = item.box_2d;
        x1 = Math.round(xmin / 1000 * imgWidth);
        y1 = Math.round(ymin / 1000 * imgHeight);
        x2 = Math.round(xmax / 1000 * imgWidth);
        y2 = Math.round(ymax / 1000 * imgHeight);
      } else if (item.bbox_2d) {
        // Qwen-VL: [x1, y1, x2, y2] 0-1000
        const [bx1, by1, bx2, by2] = item.bbox_2d;
        x1 = Math.round(bx1 / 1000 * imgWidth);
        y1 = Math.round(by1 / 1000 * imgHeight);
        x2 = Math.round(bx2 / 1000 * imgWidth);
        y2 = Math.round(by2 / 1000 * imgHeight);
      } else if (item.bbox) {
        // 通用 fallback
        const [bx1, by1, bx2, by2] = item.bbox;
        x1 = Math.round(bx1 / 1000 * imgWidth);
        y1 = Math.round(by1 / 1000 * imgHeight);
        x2 = Math.round(bx2 / 1000 * imgWidth);
        y2 = Math.round(by2 / 1000 * imgHeight);
      } else continue;

      // 基本校验
      if (x1 >= 0 && y1 >= 0 && x2 > x1 && y2 > y1 && x2 <= imgWidth && y2 <= imgHeight) {
        results.push({ x1, y1, x2, y2, label: item.label || '' });
      }
    }
    return results;
  } catch {
    return [];
  }
}

/** 用 Sharp 在图片上绘制标注（红色椭圆 + 标签） */
async function annotateImageWithBboxes(imageBuffer: Buffer, bboxes: BBox[]): Promise<Buffer> {
  const metadata = await sharp(imageBuffer).metadata();
  const w = metadata.width || 800;
  const h = metadata.height || 600;

  const shapes = bboxes.map((b, i) => {
    const cx = (b.x1 + b.x2) / 2;
    const cy = (b.y1 + b.y2) / 2;
    const rx = (b.x2 - b.x1) / 2 + 8;
    const ry = (b.y2 - b.y1) / 2 + 8;
    const labelY = Math.max(b.y1 - 8, 16);
    const labelX = b.x1;
    return `
      <ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}"
        fill="none" stroke="#FF3333" stroke-width="3" stroke-dasharray="none"/>
      <rect x="${labelX}" y="${labelY - 16}" width="${b.label.length * 14 + 12}" height="22"
        rx="4" fill="#FF3333" fill-opacity="0.85"/>
      <text x="${labelX + 6}" y="${labelY}" font-family="sans-serif" font-size="14"
        font-weight="bold" fill="white">${b.label || `目标${i + 1}`}</text>
    `;
  }).join('');

  const svg = `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">${shapes}</svg>`;

  return sharp(imageBuffer)
    .composite([{ input: Buffer.from(svg), top: 0, left: 0 }])
    .png()
    .toBuffer();
}

/** 调用 VLM API 进行 bbox grounding（同步，非流式）*/
async function callVLMForBbox(
  imageBase64: string, mimeType: string, objectName: string,
  provider: LLMConfig, providerName: string,
): Promise<string> {
  const prompt = buildGroundingPrompt(objectName, providerName);
  const m = provider.model.toLowerCase();
  const isQwenVL = /qwen.*vl|qwen.*omni/.test(m);

  // 构建多模态 content
  const dataUrl = `data:${mimeType};base64,${imageBase64}`;
  let userContent: any;
  if (isQwenVL) {
    userContent = [{ type: 'image', image: dataUrl }, { type: 'text', text: prompt }];
  } else {
    userContent = [{ type: 'image_url', image_url: { url: dataUrl } }, { type: 'text', text: prompt }];
  }

  const payload = JSON.stringify({
    model: provider.model,
    messages: [{ role: 'user', content: userContent }],
    temperature: 0.1,
    max_tokens: 512,
  });

  const apiUrl = new URL(provider.baseUrl.replace(/\/$/, '') + '/chat/completions');
  const isHttps = apiUrl.protocol === 'https:';
  const lib = isHttps ? https : http_;

  return new Promise((resolve, reject) => {
    const req = lib.request({
      hostname: apiUrl.hostname,
      port: apiUrl.port || (isHttps ? 443 : 80),
      path: apiUrl.pathname + apiUrl.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${provider.apiKey}`,
        'Content-Length': Buffer.byteLength(payload),
      },
      timeout: 30000,
    }, (res) => {
      let body = '';
      res.on('data', (c: Buffer) => { body += c.toString(); });
      res.on('end', () => {
        try {
          const json = JSON.parse(body);
          resolve(json.choices?.[0]?.message?.content || '');
        } catch { reject(new Error('Invalid bbox API response')); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Bbox API timeout')); });
    req.write(payload);
    req.end();
  });
}

/** 完整标注流程：grounding + 绘制 + 存储 → 返回 ImageAttachment */
async function performAnnotation(
  imageBase64: string, mimeType: string, objectName: string,
): Promise<ImageAttachment | null> {
  const provider = llmConfigStore.providers[llmConfigStore.activeProvider];
  const providerName = llmConfigStore.activeProvider;
  if (!provider?.apiKey || !providerSupportsBbox(providerName, provider.model)) {
    return null;  // 当前模型不支持 bbox
  }

  try {
    // 1) VLM grounding
    const bboxText = await callVLMForBbox(imageBase64, mimeType, objectName, provider, providerName);

    // 2) 解析 bbox
    const imgBuf = Buffer.from(imageBase64, 'base64');
    const meta = await sharp(imgBuf).metadata();
    const bboxes = parseBboxResponse(bboxText, meta.width || 800, meta.height || 600, providerName);
    if (bboxes.length === 0) return null;

    // 强制使用用户指定的物体名作为标签（VLM 可能返回英文或错误名称）
    for (const b of bboxes) {
      b.label = objectName;
    }

    // 3) 绘制标注
    const annotated = await annotateImageWithBboxes(imgBuf, bboxes);

    // 4) 存储
    ensureDirs();
    const imgId = genId('ann');
    const filename = `${imgId}.png`;
    fs.writeFileSync(path.join(ANNOTATED_DIR, filename), annotated);

    return {
      id: imgId,
      url: `/api/images/annotated/${filename}`,
      alt: `标注了"${objectName}"的图片`,
    };
  } catch (err) {
    console.error('[annotate] error:', err);
    return null;
  }
}

/** 物体名多级匹配评分 */
function scoreObjectMatch(objects: any[], aliases: string[], tags: string[], roomTypeCn: string, query: string): number {
  let score = 0;
  if (objects.some((o: any) =>
    (o.name_cn || '').toLowerCase() === query || (o.name || '').toLowerCase() === query
  )) {
    score = 100;
  } else if (objects.some((o: any) =>
    (o.name || '').toLowerCase().includes(query) ||
    (o.name_cn || '').toLowerCase().includes(query)
  )) {
    score = 80;
  } else if (aliases.some(a => a === query) || tags.some(t => t === query)) {
    score = 70;
  } else if (aliases.some(a => a.includes(query)) || tags.some(t => t.includes(query))) {
    score = 50;
  } else if (query.length >= 2) {
    for (const o of objects) {
      const cn = (o.name_cn || '').toLowerCase();
      if (cn.length >= 2 && query[query.length - 1] === cn[cn.length - 1] && Math.abs(cn.length - query.length) <= 1) {
        score = 30;
        break;
      }
    }
  }
  if (score === 0 && roomTypeCn.includes(query)) {
    score = 10;
  }
  return score;
}

/** 规范化用户搜索目标词：去除 "我的/找/帮" 等前缀和 "在哪/的位置" 等后缀。
 * 与后端 Python 版 `target_normalizer.normalize_search_target` 保持语义一致，
 * 作为纵深防御 — 即便后端未归一化，前端也能把 "我的书包" → "书包"。 */
function normalizeSearchTarget(raw: string): string {
  if (!raw) return '';
  let text = raw.trim();
  if (!text) return '';

  const prefixes = ['找我的', '帮我找', '到我的', '给我找', '我的', '找', '到', '帮', '给'];
  for (const p of prefixes) {
    if (text.startsWith(p) && text.length > p.length) {
      text = text.slice(p.length);
      break;
    }
  }

  const suffixes = ['在哪里', '在哪', '的位置', '去哪了', '的图'];
  for (const s of suffixes) {
    if (text.endsWith(s) && text.length > s.length) {
      text = text.slice(0, -s.length);
      break;
    }
  }

  const trailingStop = new Set(['的', '了', '吗', '呢', '吧', '在']);
  while (text.length > 0 && trailingStop.has(text[text.length - 1])) {
    text = text.slice(0, -1);
  }

  text = text.trim();
  if (text.length <= 1) return '';
  return text;
}

/** 搜索拓扑地图中包含指定物体的节点 → 返回节点信息和图片路径 (方向感知) */
function searchTopoForObject(objectName: string): Array<{
  nodeId: number; nodeName: string; description: string;
  images: Array<{ url: string; alt: string }>;
  matchScore: number;
  matchedAngles?: number[];
}> {
  const normalized = normalizeSearchTarget(objectName) || objectName;
  const query = normalized.toLowerCase();
  const results: Array<{
    nodeId: number; nodeName: string; description: string;
    images: Array<{ url: string; alt: string }>;
    matchScore: number;
    matchedAngles: number[];
  }> = [];
  const seenNodeIds = new Set<number>();

  // ── 优先搜索 session 地图 (含 viewpoints，方向精确) ──
  try {
    if (fs.existsSync(SESSION_MAPS_ROOT)) {
      const dirs = fs.readdirSync(SESSION_MAPS_ROOT, { withFileTypes: true });
      console.log(`[searchTopo] SESSION_MAPS_ROOT=${SESSION_MAPS_ROOT}, dirs=${dirs.map(d=>d.name).join(',')}`);
      for (const dir of dirs) {
        if (!dir.isDirectory() || dir.name === 'default') continue;
        const topoPath = path.join(SESSION_MAPS_ROOT, dir.name, 'topological_map.json');
        if (!fs.existsSync(topoPath)) continue;

        const topo = JSON.parse(fs.readFileSync(topoPath, 'utf-8'));
        const sessionId = dir.name;

        for (const node of (topo.nodes || [])) {
          const viewpoints = node.viewpoints || {};
          const vpEntries = Object.values(viewpoints) as any[];
          if (vpEntries.length === 0) continue;

          // R8: 先用节点级 search_objects 的 best_confidence 门槛过滤，口径与 planner 一致。
          // 没过门槛 → 直接跳过整节点，不走 viewpoint 兜底（避免幽灵候选）。
          const searchObjects = (node.search_objects || {}) as Record<string, any>;
          let passConfGate = false;
          let gateBestConf = 0;
          for (const [k, meta] of Object.entries(searchObjects)) {
            const bestConf = Number((meta as any)?.best_confidence) || 0;
            if (bestConf < 0.6) continue;
            const names = [k, (meta as any)?.name || '', (meta as any)?.name_cn || '']
              .map((n: string) => (n || '').toLowerCase());
            if (names.some(n => n && (n === query || n.includes(query) || query.includes(n)))) {
              passConfGate = true;
              gateBestConf = Math.max(gateBestConf, bestConf);
            }
          }
          if (!passConfGate) continue;

          // 逐方向匹配图片（供气泡展示）
          const matchedImages: Array<{ url: string; alt: string; score: number; angle: number }> = [];
          for (const vp of vpEntries) {
            const vpSi = vp.semantic_info || {};
            const vpObjects = vpSi.objects || [];
            const vpAliases = (vpSi.aliases || []).map((a: string) => a.toLowerCase());
            const vpTags = (vpSi.semantic_tags || []).map((t: string) => t.toLowerCase());
            const vpRoomCn = (vpSi.room_type_cn || '').toLowerCase();

            const vpScore = scoreObjectMatch(vpObjects, vpAliases, vpTags, vpRoomCn, query);
            if (vpScore > 0 && vp.image_path) {
              const imgUrl = `/map-sessions/${sessionId}/${vp.image_path}`;
              const imgDisk = path.join(SESSION_MAPS_ROOT, sessionId, vp.image_path);
              if (fs.existsSync(imgDisk)) {
                const angle = vp.angle ?? 0;
                const roomLabel = vpSi.room_type_cn || node.name || '';
                matchedImages.push({
                  url: imgUrl,
                  alt: `节点${node.id} ${roomLabel} ${String(angle).padStart(3, '0')}° 视角`,
                  score: vpScore,
                  angle,
                });
              }
            }
          }

          if (matchedImages.length > 0) {
            // 按评分降序，最佳匹配图片排前面
            matchedImages.sort((a, b) => b.score - a.score);
            const bestScore = Math.max(matchedImages[0].score, gateBestConf);
            const aggSi = node.semantic_info || {};
            console.log(`[searchTopo] SESSION HIT: node=${node.id}, query="${query}", angles=[${matchedImages.map(m=>m.angle)}], score=${bestScore}, imgs=${matchedImages.length}`);
            results.push({
              nodeId: node.id,
              nodeName: aggSi.room_type_cn || node.name || `节点${node.id}`,
              description: aggSi.description || matchedImages[0].alt,
              images: matchedImages.map(m => ({ url: m.url, alt: m.alt })),
              matchScore: bestScore,
              matchedAngles: matchedImages.map(m => m.angle),
            });
            seenNodeIds.add(node.id);
          }
        }
      }
    }
  } catch (e) {
    console.error('[searchTopo] session map error:', e);
  }

  // ── Fallback: legacy 手动地图 (无 viewpoints，返回全部 4 张) ──
  try {
    const legacyPath = path.join(process.cwd(), 'public/maps/topological_map_manual.json');
    if (fs.existsSync(legacyPath)) {
      const topo = JSON.parse(fs.readFileSync(legacyPath, 'utf-8'));
      for (const node of (topo.nodes || [])) {
        if (seenNodeIds.has(node.id)) continue;  // session 已有，跳过

        const si = node.semantic_info || {};
        const objects = si.objects || [];
        const aliases = (si.aliases || []).map((a: string) => a.toLowerCase());
        const tags = (si.semantic_tags || []).map((t: string) => t.toLowerCase());
        const roomCn = (si.room_type_cn || '').toLowerCase();

        const score = scoreObjectMatch(objects, aliases, tags, roomCn, query);
        if (score > 0) {
          console.log(`[searchTopo] LEGACY HIT: node=${node.id}, query="${query}", score=${score}`);
          const nodeImages: Array<{ url: string; alt: string }> = [];
          const capturedDir = `/maps/captured_nodes/node_${node.id}`;
          for (const deg of ['000', '090', '180', '270']) {
            const imgPath = path.join(process.cwd(), `public${capturedDir}/${deg}deg_rgb.png`);
            if (fs.existsSync(imgPath)) {
              nodeImages.push({
                url: `${capturedDir}/${deg}deg_rgb.png`,
                alt: `节点${node.id} ${si.room_type_cn || node.name} ${deg}° 视角`,
              });
            }
          }
          results.push({
            nodeId: node.id,
            nodeName: si.room_type_cn || node.name || `节点${node.id}`,
            description: si.description || '',
            images: nodeImages,
            matchScore: score,
            matchedAngles: [],
          });
        }
      }
    }
  } catch (e) {
    console.error('[searchTopo] legacy map error:', e);
  }

  return results.sort((a, b) => b.matchScore - a.matchScore);
}

/** 已知物品词表（来自所有 session 地图 + legacy 手动地图），mtime 感知 30s 缓存 */
let knownVocabCache: { value: string[]; computedAt: number; signature: string } | null = null;
function buildKnownObjectVocab(): string[] {
  const now = Date.now();
  const files: string[] = [];
  try {
    if (fs.existsSync(SESSION_MAPS_ROOT)) {
      for (const dir of fs.readdirSync(SESSION_MAPS_ROOT, { withFileTypes: true })) {
        if (!dir.isDirectory()) continue;
        const p = path.join(SESSION_MAPS_ROOT, dir.name, 'topological_map.json');
        if (fs.existsSync(p)) files.push(p);
      }
    }
  } catch {}
  const legacyPath = path.join(process.cwd(), 'public/maps/topological_map_manual.json');
  if (fs.existsSync(legacyPath)) files.push(legacyPath);

  const signature = files.map(f => {
    try { return `${f}:${fs.statSync(f).mtimeMs}`; } catch { return f; }
  }).join('|');

  if (knownVocabCache && knownVocabCache.signature === signature && now - knownVocabCache.computedAt < 5_000) {
    return knownVocabCache.value;
  }

  const vocab = new Set<string>();
  const pushName = (v: any) => {
    if (typeof v !== 'string') return;
    const t = v.trim();
    if (!t || t.length < 1) return;
    vocab.add(t);
  };
  for (const fp of files) {
    try {
      const topo = JSON.parse(fs.readFileSync(fp, 'utf-8'));
      for (const node of (topo.nodes || [])) {
        const si = node.semantic_info || {};
        for (const o of (si.objects || [])) { pushName(o.name); pushName(o.name_cn); }
        const so = node.search_objects || {};
        for (const k of Object.keys(so)) pushName(k);
        const viewpoints = node.viewpoints || {};
        for (const vp of Object.values(viewpoints) as any[]) {
          const vsi = vp.semantic_info || {};
          for (const o of (vsi.objects || [])) { pushName(o.name); pushName(o.name_cn); }
        }
      }
    } catch {}
  }
  const value = Array.from(vocab);
  knownVocabCache = { value, computedAt: now, signature };
  return value;
}

/** 从用户文本中提取标注目标物体名 */
function extractAnnotationTarget(text: string): string {
  const patterns = [
    /(?:把|将)(.+?)(?:圈出来|标出来|框出来|画出来)/,
    /(?:找到|找|寻找)(?:我的|我)?(.+?)[，,]?\s*(?:并且|并|然后|再|同时|而且)?\s*(?:圈|标|框|画)/,
    // "圈出来+后置宾语": 圈出来我的耳机给我 / 标出来那个水杯（逗号截止）
    /(?:圈出来|标出来|框出来|画出来)[，,]?\s*(?:我的|我)?([^，,。！？]+?)(?:给我|发给我|[，,。！？]|$)/,
    /(.{2,8})(?:圈出来|标出来|框出来)/,
  ];
  const NOISE = [
    '其中', '一张', '一个', '一下', '那张', '那个', '这张', '这个',
    '里面', '图片', '照片', '中的', '上面', '里的', '后发给我', '发给我',
    '给我', '帮我找到', '帮我', '找到', '我的', '我', '是说', '不是',
    '的', '那', '并', '并且', '而且', '且', '吧', '呢', '啊', '了', '后',
  ];
  for (const p of patterns) {
    const m = text.match(p);
    if (m?.[1]) {
      let obj = m[1];
      for (const n of NOISE) { obj = obj.split(n).join(''); }
      obj = obj.replace(/[，。！？~、·\s]+/g, '').trim();
      if (obj.length >= 1) return obj;
    }
  }
  return '';
}

/** 从会话上下文中提取物体名（用于"圈出来后给我"等无主语句） */
function extractTargetFromContext(sessionId: string): string {
  const allMsgs = sessionMessages.get(sessionId) || [];
  // 读取拓扑词典物体名
  const knownObjects: string[] = [];
  try {
    const topoPath = path.join(process.cwd(), 'public/maps/topological_map_manual.json');
    const topo = JSON.parse(fs.readFileSync(topoPath, 'utf-8'));
    for (const node of (topo.nodes || [])) {
      for (const obj of (node.semantic_info?.objects || [])) {
        if (obj.name_cn) knownObjects.push(obj.name_cn);
      }
    }
  } catch {}
  if (knownObjects.length === 0) return '';

  // 反向扫描最近 6 条消息：优先用户消息（避免 robot 回复的干扰物名如"置物架"）
  const recent = allMsgs.slice(-6);
  // Pass 1: 只扫用户消息
  for (let i = recent.length - 1; i >= 0; i--) {
    if (recent[i].role !== 'user') continue;
    const content = recent[i].content || '';
    for (const obj of knownObjects) {
      if (content.includes(obj)) return obj;
    }
  }
  // Pass 2: 补扫 robot 消息
  for (let i = recent.length - 1; i >= 0; i--) {
    if (recent[i].role !== 'robot') continue;
    const content = recent[i].content || '';
    for (const obj of knownObjects) {
      if (content.includes(obj)) return obj;
    }
  }
  return '';
}

/** 从会话历史中获取最近的对话用于上下文 */
function getRecentHistory(sessionId: string, maxPairs: number = 10): Array<{role: string; content: string}> {
  const msgs = sessionMessages.get(sessionId) || [];
  const history: Array<{role: string; content: string}> = [];
  // 从后向前取 user/robot 消息对
  for (let i = msgs.length - 1; i >= 0 && history.length < maxPairs * 2; i--) {
    const m = msgs[i];
    if (m.role === 'user') {
      history.unshift({ role: 'user', content: m.content });
    } else if (m.role === 'robot' && m.content) {
      history.unshift({ role: 'assistant', content: m.content });
    }
  }
  return history;
}

// ── Plugin ─────────────────────────────────────────────

export default function chatSyncPlugin(): Plugin {
  return {
    name: 'chat-sync',
    configureServer(server) {
      loadFromDisk();
      loadLLMConfig();

      // SSE heartbeat
      const heartbeatTimer = setInterval(() => {
        broadcast({ type: 'heartbeat' });
      }, HEARTBEAT_INTERVAL);
      server.httpServer?.on('close', () => {
        clearInterval(heartbeatTimer);
        flushToDisk();
      });

      // ── Image Static Serving ──────────────────────────
      server.middlewares.use('/api/images', (req, res) => {
        const urlPath = (req.url || '').replace(/\?.*$/, '');
        const filePath = path.join(DATA_DIR, 'images', urlPath);
        if (!fs.existsSync(filePath)) {
          res.writeHead(404);
          return res.end('Not found');
        }
        const ext = path.extname(filePath).toLowerCase();
        const mimeMap: Record<string, string> = {
          '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
          '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp',
        };
        res.writeHead(200, {
          'Content-Type': mimeMap[ext] || 'application/octet-stream',
          'Cache-Control': 'public, max-age=86400',
        });
        fs.createReadStream(filePath).pipe(res);
      });

      // ── Topo Image Search ──────────────────────────────
      server.middlewares.use('/api/topo/search-images', async (req, res) => {
        if (req.method !== 'GET') return jsonResponse(res, 405, { error: 'GET only' });
        const url = new URL(req.url || '', 'http://localhost');
        const query = url.searchParams.get('q') || '';
        if (!query) return jsonResponse(res, 400, { error: 'q parameter required' });
        const results = searchTopoForObject(query);
        return jsonResponse(res, 200, { results });
      });

      // ── Known Object Vocab (for navigate-mode mention detection) ──
      server.middlewares.use('/api/topo/vocab', async (req, res) => {
        if (req.method !== 'GET') return jsonResponse(res, 405, { error: 'GET only' });
        return jsonResponse(res, 200, { vocab: buildKnownObjectVocab() });
      });

      // ── Round 7: Arm auto-confirm for next search_confirmation_request ──
      server.middlewares.use('/api/chat/auto-confirm/arm', async (req, res) => {
        if (req.method !== 'POST') return jsonResponse(res, 405, { error: 'POST only' });
        const body = JSON.parse(await readBody(req) || '{}');
        const sessionId = String(body.sessionId || '');
        if (!sessionId) return jsonResponse(res, 400, { error: 'sessionId required' });
        armAutoConfirm(sessionId);
        return jsonResponse(res, 200, { ok: true, armed: true });
      });

      // ── Memory Recall (navigate-mode mention → synthetic confirm/miss msg) ──
      server.middlewares.use('/api/chat/memory-recall', async (req, res) => {
        if (req.method !== 'POST') return jsonResponse(res, 405, { error: 'POST only' });
        const body = JSON.parse(await readBody(req) || '{}');
        const sessionId = String(body.sessionId || '');
        const target = String(body.target || '').trim();
        if (!sessionId || !target) return jsonResponse(res, 400, { error: 'sessionId and target required' });

        const msgs = sessionMessages.get(sessionId);
        if (!msgs) return jsonResponse(res, 404, { error: 'Session not found' });

        const canonical = normalizeSearchTarget(target) || target;
        const topoResults = searchTopoForObject(canonical);

        let message: ChatMessage;
        if (topoResults.length > 0) {
          // HIT → memory images + 去看看/不用了
          const historyImages: ImageAttachment[] = [];
          for (const r of topoResults.slice(0, 3)) {
            for (const img of r.images.slice(0, 2)) {
              historyImages.push({ id: genId('img'), url: img.url, alt: img.alt });
            }
          }
          const nodeNames = topoResults.slice(0, 3)
            .map(r => `${r.nodeName}(节点${r.nodeId})`).join('、');
          message = {
            id: genId('msg'),
            role: 'robot',
            content: `我记得在${nodeNames}见过${canonical}，这是当时拍到的图片。要不要我现在过去现场再确认一下？`,
            timestamp: Date.now(),
            images: historyImages.length > 0 ? historyImages : undefined,
            meta: {
              status: 'awaiting_confirmation',
              statusText: 'memory_recall_hit',
              actions: [
                { id: 'goto_nav', label: '去看看', style: 'primary' },
                { id: 'skip_recall', label: '不用了', style: 'secondary' },
              ],
              recallTarget: canonical,
            },
          };
        } else {
          // MISS → "没印象，帮你各节点找一找吗？"
          message = {
            id: genId('msg'),
            role: 'robot',
            content: `我记忆里暂时没有"${canonical}"的位置记录呢，要不要我去各个节点都帮你找一找？`,
            timestamp: Date.now(),
            meta: {
              status: 'awaiting_confirmation',
              statusText: 'memory_recall_miss',
              actions: [
                { id: 'full_search', label: '帮我找一找', style: 'primary' },
                { id: 'skip_recall', label: '不用了', style: 'secondary' },
              ],
              recallTarget: canonical,
            },
          };
        }

        msgs.push(message);
        scheduleSave();
        broadcast({ type: 'message_added', sessionId, message });
        return jsonResponse(res, 200, { ok: true, target: canonical, hit: topoResults.length > 0, messageId: message.id });
      });

      // ── LLM Config API ────────────────────────────────
      server.middlewares.use('/api/llm-config', async (req, res) => {
        const method = req.method || 'GET';

        if (method === 'GET') {
          return jsonResponse(res, 200, llmConfigStore);
        }

        if (method === 'PUT') {
          const body = JSON.parse(await readBody(req) || '{}');
          if (body.activeProvider !== undefined) llmConfigStore.activeProvider = body.activeProvider;
          if (body.providers !== undefined) llmConfigStore.providers = body.providers;
          saveLLMConfig();
          broadcast({ type: 'llm_config_updated', config: llmConfigStore });
          return jsonResponse(res, 200, llmConfigStore);
        }

        jsonResponse(res, 405, { error: 'Method not allowed' });
      });

      // ── Streaming Chat Endpoint ──────────────────────
      server.middlewares.use('/api/chat/stream', async (req, res) => {
        if (req.method !== 'POST') {
          return jsonResponse(res, 405, { error: 'POST only' });
        }

        const body = JSON.parse(await readBody(req) || '{}');
        const { sessionId, text, senderName, mapContext, images: rawImages, rosHandling, userPreCreated } = body;

        if (!sessionId || !text) {
          return jsonResponse(res, 400, { error: 'sessionId and text required' });
        }

        // Get active LLM config
        const provider = llmConfigStore.providers[llmConfigStore.activeProvider];
        if (!provider?.apiKey) {
          return jsonResponse(res, 400, { error: 'LLM API key not configured' });
        }

        // 1) Process uploaded images
        const imageBase64List: Array<{ base64: string; mimeType: string }> = [];
        const savedImages: ImageAttachment[] = [];
        if (Array.isArray(rawImages) && rawImages.length > 0) {
          ensureDirs();
          for (const img of rawImages) {
            if (!img.base64 || !img.mimeType) continue;
            const ext = img.mimeType === 'image/png' ? '.png' : '.jpg';
            const imgId = genId('img');
            const filename = `${imgId}${ext}`;
            const filePath = path.join(IMAGES_DIR, filename);
            fs.writeFileSync(filePath, Buffer.from(img.base64, 'base64'));
            imageBase64List.push({ base64: img.base64, mimeType: img.mimeType });
            savedImages.push({
              id: imgId,
              url: `/api/images/upload/${filename}`,
              width: img.width,
              height: img.height,
              alt: img.alt || '用户上传图片',
            });
          }
        }

        // 2) Save user message (rosHandling/userPreCreated 时用户消息已由前端 addMessage 预创建)
        const msgs = sessionMessages.get(sessionId);
        if (!msgs) {
          return jsonResponse(res, 404, { error: 'Session not found' });
        }

        let userMsg: ChatMessage | null = null;
        const skipUserMsgCreation = rosHandling || userPreCreated;
        if (!skipUserMsgCreation) {
          userMsg = {
            id: genId('msg'),
            role: 'user',
            content: text,
            timestamp: Date.now(),
            sender: senderName || undefined,
            images: savedImages.length > 0 ? savedImages : undefined,
          };
          msgs.push(userMsg);

          // Auto-title
          const session = storeIndex.sessions.find(s => s.id === sessionId);
          if (session && msgs.filter(m => m.role === 'user').length === 1) {
            session.title = text.slice(0, 12) + (text.length > 12 ? '...' : '');
            session.updatedAt = Date.now();
          }

          scheduleSave();
          broadcast({ type: 'message_added', sessionId, message: userMsg });
        }

        // 3) Create robot message placeholder
        const robotMsg: ChatMessage = {
          id: genId('msg'),
          role: 'robot',
          content: '',
          timestamp: Date.now(),
          meta: { status: 'understanding' },
        };
        msgs.push(robotMsg);
        scheduleSave();
        broadcast({ type: 'message_added', sessionId, message: robotMsg });

        // 4) Set up SSE response to requesting client
        res.writeHead(200, {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache, no-transform',
          'Connection': 'keep-alive',
          'Content-Encoding': 'identity',       // 禁用压缩 — 压缩器会攒数据导致卡顿
          'X-Accel-Buffering': 'no',            // 禁用 nginx/反代缓冲
          'X-User-Msg-Id': userMsg?.id || '',
          'X-Robot-Msg-Id': robotMsg.id,
        });
        res.flushHeaders();
        // 禁用 Nagle 算法 + socket 缓冲 — 确保每个 token 立即发出
        if (res.socket) {
          res.socket.setNoDelay(true);
          res.socket.setTimeout(0);
        }

        const sendSSE = (event: string, data: any) => {
          try {
            res.write(`data: ${JSON.stringify({ ...data, event })}\n\n`);
            // 强制刷出 socket 缓冲 — 确保 token 立即到达浏览器
            if (typeof (res as any).flush === 'function') (res as any).flush();
          } catch {}
        };

        // 5) Build messages and call LLM API with streaming
        const history = getRecentHistory(sessionId);
        const providerName = llmConfigStore.activeProvider;
        // 前置检测：标注意图要在 buildStreamMessages 之前识别出来，才能在 ROS 搜索进行中也让 LLM 走完整 prompt（而非被短模板锁死为"好的稍等一下"）
        const annotatePattern = /圈出|标出|标注|框出|画出|圈.*给我|标.*给我|框.*发/;
        const imageReqPattern = /图片|照片|看看.*图|拍.*照|发.*图|全景|看看|找.*发|找出来|找到|找一下|找找|在哪|发给我/;
        const creativePattern = /画一|画幅|画张|画个|画.*画|写一|写首|写篇|生成.*图|创作|设计一|编一/;
        const hasUserImage = savedImages.length > 0;
        const isCreative = creativePattern.test(text);
        const wantAnnotate = !isCreative && annotatePattern.test(text);
        const wantRetrieve = !isCreative && imageReqPattern.test(text) && !hasUserImage;
        const targetObj = wantAnnotate ? extractAnnotationTarget(text) : '';
        const finalTarget = targetObj || (wantAnnotate ? extractTargetFromContext(sessionId) : '');

        const llmMessages = buildStreamMessages(
          text, mapContext || '', history, senderName || '',
          imageBase64List.length > 0 ? imageBase64List : undefined,
          providerName, provider.model,
          rosHandling,
          wantAnnotate,
        );

        const apiUrl = new URL(provider.baseUrl.replace(/\/$/, '') + '/chat/completions');
        const isHttps = apiUrl.protocol === 'https:';
        const lib = isHttps ? https : http_;

        const payload = JSON.stringify({
          model: provider.model,
          messages: llmMessages,
          temperature: 0.3,
          top_p: 0.8,
          max_tokens: 1024,
          stream: true,
        });

        const options: http.RequestOptions = {
          hostname: apiUrl.hostname,
          port: apiUrl.port || (isHttps ? 443 : 80),
          path: apiUrl.pathname + apiUrl.search,
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${provider.apiKey}`,
            'Content-Length': Buffer.byteLength(payload),
          },
          timeout: 60000,
        };

        let fullContent = '';

        const apiReq = lib.request(options, (apiRes) => {
          let buffer = '';

          apiRes.on('data', (chunk: Buffer) => {
            buffer += chunk.toString();
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';  // keep incomplete line

            for (const line of lines) {
              const trimmed = line.trim();
              if (!trimmed.startsWith('data: ')) continue;
              const data = trimmed.slice(6);
              if (data === '[DONE]') continue;

              try {
                const parsed = JSON.parse(data);
                const token = parsed.choices?.[0]?.delta?.content;
                if (token) {
                  fullContent += token;
                  sendSSE('token', { token });
                }
              } catch {}
            }
          });

          apiRes.on('end', async () => {
            // Process any remaining buffer
            if (buffer.trim()) {
              const trimmed = buffer.trim();
              if (trimmed.startsWith('data: ') && trimmed.slice(6) !== '[DONE]') {
                try {
                  const parsed = JSON.parse(trimmed.slice(6));
                  const token = parsed.choices?.[0]?.delta?.content;
                  if (token) {
                    fullContent += token;
                    sendSSE('token', { token });
                  }
                } catch {}
              }
            }

            // 6) Finalize: 保留 LLM 文字回复（永不覆盖）
            robotMsg.content = fullContent || '抱歉，我没能理解你的意思~';
            robotMsg.meta = { status: 'completed' };
            scheduleSave();
            broadcast({ type: 'message_updated', sessionId, messageId: robotMsg.id, message: robotMsg });
            sendSSE('done', { content: robotMsg.content, msgId: robotMsg.id });

            // ── 图片操作分发（检索意图仅非 ROS 流程触发；标注意图在 ROS 流程中也放行）──
            if (wantAnnotate || (wantRetrieve && !rosHandling)) {
              // 创建第二条消息专门承载图片
              const imgMsg: ChatMessage = {
                id: genId('msg'),
                role: 'robot',
                content: (wantAnnotate && finalTarget) ? `正在帮你把「${finalTarget}」标注出来~` : '正在搜索相关图片...',
                timestamp: Date.now(),
                meta: {
                  status: 'searching',
                  steps: [{ state: 'searching', text: '正在搜索拓扑地图...', timestamp: Date.now() }],
                },
              };
              msgs.push(imgMsg);
              scheduleSave();
              broadcast({ type: 'message_added', sessionId, message: imgMsg });

              // ── Step A: 节点检索 ──
              const SYNONYMS: Record<string, string[]> = {
                '书包': ['背包', '双肩包', '挎包'], '背包': ['书包', '双肩包'],
                '杯子': ['水杯', '茶杯', '马克杯'], '水杯': ['杯子', '茶杯'],
                '椅子': ['办公椅', '座椅'], '办公椅': ['椅子', '座椅'],
                '桌子': ['办公桌', '电脑桌', '长桌', '圆桌'],
                '雨伞': ['红色雨伞', '伞'], '伞': ['雨伞', '红色雨伞'],
                '灭火器': ['消防箱', '消防柜'], '消防箱': ['灭火器', '消防柜'],
                '耳机': ['耳麦', '头戴耳机'],
              };

              const STOP_WORDS = [
                '帮我', '帮忙', '请', '麻烦', '可以', '能不能', '能否',
                '找到', '发给我', '发给', '给我', '看看', '看一下', '看下',
                '的图片', '的照片', '的全景', '的全景图', '图片', '照片', '全景图', '全景',
                '节点', '所在', '位置', '在哪', '那边', '那里', '那个',
                '拍的', '拍照', '这些不是', '不是',
                '只发', '只要', '只看',
                '吧', '呢', '呀', '哦', '嘛', '啊', '了', '的',
                '先', '也', '再', '就', '都', '把', '将', '让',
                '我要', '我想', '我的', '找我的', '找',
                '圈出来', '标出来', '框出来', '画出来', '并', '然后', '同时',
              ];

              let cleaned = text;
              for (const sw of STOP_WORDS) { cleaned = cleaned.split(sw).join(' '); }
              cleaned = cleaned.replace(/[，。！？~、·\s]+/g, ' ').trim();
              let searchTerms = cleaned.split(/\s+/).filter(t => t.length >= 2);

              // 如果有标注目标，优先用它做搜索词
              if (finalTarget && !searchTerms.includes(finalTarget)) {
                searchTerms.unshift(finalTarget);
              }

              // 展开近义词
              const expanded: string[] = [...searchTerms];
              for (const t of searchTerms) {
                if (SYNONYMS[t]) expanded.push(...SYNONYMS[t]);
              }

              // 拓扑词典匹配（只物体名 — 同时读 session + legacy 地图）
              const topoTerms: string[] = [];
              try {
                // session 地图 (viewpoint 级物体名)
                if (fs.existsSync(SESSION_MAPS_ROOT)) {
                  for (const dir of fs.readdirSync(SESSION_MAPS_ROOT, { withFileTypes: true })) {
                    if (!dir.isDirectory() || dir.name === 'default') continue;
                    const tp = path.join(SESSION_MAPS_ROOT, dir.name, 'topological_map.json');
                    if (!fs.existsSync(tp)) continue;
                    const topo = JSON.parse(fs.readFileSync(tp, 'utf-8'));
                    for (const node of (topo.nodes || [])) {
                      for (const vp of Object.values(node.viewpoints || {}) as any[]) {
                        for (const obj of (vp.semantic_info?.objects || [])) {
                          if (obj.name_cn) topoTerms.push(obj.name_cn);
                        }
                      }
                    }
                  }
                }
                // legacy 地图 (节点级物体名)
                const legacyPath = path.join(process.cwd(), 'public/maps/topological_map_manual.json');
                if (fs.existsSync(legacyPath)) {
                  const topo = JSON.parse(fs.readFileSync(legacyPath, 'utf-8'));
                  for (const node of (topo.nodes || [])) {
                    const si = node.semantic_info || {};
                    for (const obj of (si.objects || [])) {
                      if (obj.name_cn) topoTerms.push(obj.name_cn);
                    }
                  }
                }
              } catch {}

              const combined = text + ' ' + fullContent;
              const matchedEntities = [...new Set(
                topoTerms.filter(t => t.length >= 2 && combined.includes(t))
              )];
              const allTerms = [...new Set([...expanded, ...matchedEntities])];

              // 搜索：取最高分匹配
              let bestResults: ReturnType<typeof searchTopoForObject> = [];
              let bestScore = 0;
              console.log(`[chatSync] allTerms=[${allTerms.join(',')}]`);
              for (const term of allTerms) {
                const results = searchTopoForObject(term);
                console.log(`[chatSync] search("${term}") → ${results.length} results, top score=${results[0]?.matchScore}, imgs=${results.map(r=>`node${r.nodeId}:${r.images.length}img`).join(',')}`);
                if (results.length > 0 && results[0].matchScore > bestScore) {
                  bestScore = results[0].matchScore;
                  bestResults = results.filter(r => r.matchScore >= 30);
                }
              }

              let retrievedImgs: ImageAttachment[] = [];
              let retrievedNodeNames = '';
              if (bestResults.length > 0) {
                for (const r of bestResults.slice(0, 2)) {
                  for (const img of r.images.slice(0, 4)) {
                    retrievedImgs.push({ id: genId('img'), url: img.url, alt: img.alt });
                  }
                }
                retrievedNodeNames = bestResults.slice(0, 2).map(r => `${r.nodeName}(节点${r.nodeId})`).join('、');

                // ── broadcast 检索完成步骤 ──
                imgMsg.meta!.steps = [...(imgMsg.meta!.steps || []), { state: 'checking', text: `在${retrievedNodeNames}找到了匹配`, timestamp: Date.now() }];
                imgMsg.meta!.status = (wantAnnotate && finalTarget) ? 'checking' : 'completed';
                broadcast({ type: 'message_updated', sessionId, messageId: imgMsg.id, message: imgMsg });
              }

              // ── Step B: 标注（如果需要）──
              if (wantAnnotate && finalTarget) {
                // 图片源优先级: ① 用户上传 → ② 刚检索到的节点图 → ③ 历史图片
                let annotateBase64 = imageBase64List[0]?.base64 || '';
                let annotateMime = imageBase64List[0]?.mimeType || 'image/jpeg';

                // ② 用刚检索到的第一张节点图
                if (!annotateBase64 && retrievedImgs.length > 0) {
                  const resolvedPath = resolveImagePath(retrievedImgs[0].url);
                  if (fs.existsSync(resolvedPath)) {
                    annotateBase64 = fs.readFileSync(resolvedPath).toString('base64');
                    annotateMime = retrievedImgs[0].url.endsWith('.png') ? 'image/png' : 'image/jpeg';
                  }
                }

                // ③ 回溯历史图片
                if (!annotateBase64) {
                  const allMsgs = sessionMessages.get(sessionId) || [];
                  for (let i = allMsgs.length - 1; i >= 0; i--) {
                    const m = allMsgs[i];
                    if (m.images && m.images.length > 0) {
                      const imgUrl = m.images[0].url;
                      if (m.role === 'user') {
                        const fname = imgUrl.split('/').pop() || '';
                        const fpath = path.join(IMAGES_DIR, fname);
                        if (fs.existsSync(fpath)) {
                          annotateBase64 = fs.readFileSync(fpath).toString('base64');
                          annotateMime = fname.endsWith('.png') ? 'image/png' : 'image/jpeg';
                          break;
                        }
                      } else if (m.role === 'robot') {
                        const resolvedPath = resolveImagePath(imgUrl);
                        if (fs.existsSync(resolvedPath)) {
                          annotateBase64 = fs.readFileSync(resolvedPath).toString('base64');
                          annotateMime = imgUrl.endsWith('.png') ? 'image/png' : 'image/jpeg';
                          break;
                        }
                      }
                    }
                  }
                }

                if (annotateBase64) {
                  // ── broadcast 标注中步骤 ──
                  imgMsg.content = `正在帮你把「${finalTarget}」标注出来~`;
                  imgMsg.meta!.steps = [...(imgMsg.meta!.steps || []), { state: 'searching', text: `正在标注「${finalTarget}」...`, timestamp: Date.now() }];
                  imgMsg.meta!.status = 'searching';
                  broadcast({ type: 'message_updated', sessionId, messageId: imgMsg.id, message: imgMsg });

                  try {
                    const annotated = await performAnnotation(annotateBase64, annotateMime, finalTarget);
                    if (annotated) {
                      // 标注图放第一张，后面跟其余节点图
                      imgMsg.images = [annotated, ...retrievedImgs.slice(1)];
                      imgMsg.content = retrievedNodeNames
                        ? `在${retrievedNodeNames}找到了「${finalTarget}」，已标注出来~`
                        : `好的，已经把「${finalTarget}」标注出来啦，你看看~`;
                    } else {
                      // 标注失败 → 退回纯检索
                      if (retrievedImgs.length > 0) {
                        imgMsg.images = retrievedImgs;
                        imgMsg.content = `在${retrievedNodeNames}找到了相关图片（标注暂不支持当前模型）~`;
                      } else {
                        imgMsg.content = '抱歉，当前模型不支持图片标注功能~';
                      }
                    }
                  } catch (e) {
                    console.error('[annotate] failed:', e);
                    if (retrievedImgs.length > 0) {
                      imgMsg.images = retrievedImgs;
                      imgMsg.content = `在${retrievedNodeNames}找到了相关图片~`;
                    } else {
                      imgMsg.content = '标注时出了点问题~';
                    }
                  }
                } else if (retrievedImgs.length > 0) {
                  // 没有可标注的图片 → 纯检索结果
                  imgMsg.images = retrievedImgs;
                  imgMsg.content = `在${retrievedNodeNames}找到了相关图片~`;
                } else {
                  imgMsg.content = '没有找到可以标注的图片~';
                }
              } else {
                // ── 纯检索 ──
                if (retrievedImgs.length > 0) {
                  imgMsg.images = retrievedImgs;
                  imgMsg.content = `在${retrievedNodeNames}找到了相关图片~`;
                } else {
                  imgMsg.content = '没有找到相关物体的图片~';
                }
              }

              imgMsg.meta = {
                status: 'completed',
                steps: [...(imgMsg.meta?.steps || []), { state: 'completed', text: '已完成', timestamp: Date.now() }],
              };
              scheduleSave();
              broadcast({ type: 'message_updated', sessionId, messageId: imgMsg.id, message: imgMsg });
            }
            // isCreative 时不做图片操作 — LLM 纯文字回复即可

            res.end();
          });
        });

        apiReq.on('error', (err) => {
          robotMsg.content = `连接失败: ${err.message}`;
          robotMsg.meta = { status: 'failed' };
          scheduleSave();
          broadcast({ type: 'message_updated', sessionId, messageId: robotMsg.id, message: robotMsg });
          sendSSE('error', { error: err.message });
          res.end();
        });

        apiReq.on('timeout', () => {
          apiReq.destroy();
          robotMsg.content = '请求超时，请稍后再试~';
          robotMsg.meta = { status: 'failed' };
          scheduleSave();
          broadcast({ type: 'message_updated', sessionId, messageId: robotMsg.id, message: robotMsg });
          sendSSE('error', { error: 'timeout' });
          res.end();
        });

        req.on('close', () => {
          apiReq.destroy();
        });

        apiReq.write(payload);
        apiReq.end();
      });

      // ── ROS ChatEvent Endpoint (must be before /api/chat catch-all) ──
      server.middlewares.use('/api/chat/ros-event', async (req, res) => {
        if (req.method !== 'POST') {
          res.writeHead(405);
          res.end();
          return;
        }

        try {
          const body = JSON.parse(await readBody(req) || '{}');

          if (!body.session_id) {
            return jsonResponse(res, 400, { error: 'missing session_id' });
          }

          traceSearch(
            `[SEARCH-TRACE] ros-event.in type=${body.event_type} task=${body.task_id || ''} ` +
            `session=${body.session_id} node=${body.node_id} ` +
            `imgs=${(body.image_paths || []).length} ` +
            `active=${activeTaskBySession.get(body.session_id) || ''} ` +
            `target=${body.target_object || ''} skip_reason=${body.skip_reason || ''}`
          );

          // Task isolation: confirmation event registers the authoritative
          // active task; subsequent search_* events must match or be dropped.
          const STALE_GATED_TYPES = new Set([
            'search_node_observation',
            'search_target_found',
            'search_task_summary',
          ]);
          if (STALE_GATED_TYPES.has(body.event_type)) {
            const active = activeTaskBySession.get(body.session_id);
            const incoming = body.task_id ? String(body.task_id) : '';
            if (active && incoming && active !== incoming) {
              traceSearch(
                `[SEARCH-TRACE] ros-event.drop reason=stale type=${body.event_type} task=${incoming} active=${active} session=${body.session_id} node=${body.node_id} imgs=${(body.image_paths || []).length}`,
                'warn'
              );
              return jsonResponse(res, 200, { dropped: 'stale_task', active, incoming });
            }
            // Trace accepted events too — invaluable when debugging "silent"
            // skips vs genuine drops.
            traceSearch(
              `[SEARCH-TRACE] ros-event.accept type=${body.event_type} task=${incoming} session=${body.session_id} node=${body.node_id} imgs=${(body.image_paths || []).length}`
            );
          }

          let message: ChatMessage;

          if (body.event_type === 'search_confirmation_request') {
            // Register active task for this session (overwrites any prior).
            if (body.task_id) {
              activeTaskBySession.set(body.session_id, String(body.task_id));
            }
            // Round 7: 若 session 已被 memory-recall 的"去看看"/"帮我找一找"预授权 →
            // 跳过确认气泡，直接广播 auto_confirm_request 让前端自动 confirmTask
            if (consumeAutoConfirm(body.session_id)) {
              traceSearch(
                `[SEARCH-TRACE] auto-confirm session=${body.session_id} task=${body.task_id || ''} target=${body.target_object || ''}`
              );
              broadcast({
                type: 'auto_confirm_request',
                sessionId: body.session_id,
                taskId: String(body.task_id || ''),
              });
              return jsonResponse(res, 200, { ok: true, auto_confirmed: true });
            }
            // 确认请求：从拓扑地图搜索历史图片
            const canonicalTarget = normalizeSearchTarget(body.target_object || '') || (body.target_object || '');
            const topoResults = searchTopoForObject(canonicalTarget);
            const historyImages: ImageAttachment[] = [];
            for (const r of topoResults.slice(0, 3)) {
              for (const img of r.images.slice(0, 2)) {
                historyImages.push({
                  id: genId('img'),
                  url: img.url,
                  alt: img.alt,
                });
              }
            }

            const nodeNames = topoResults.slice(0, 3)
              .map(r => `${r.nodeName}(节点${r.nodeId})`)
              .join('、');
            const text = nodeNames
              ? `我记得在${nodeNames}见过${canonicalTarget}，这是当时拍到的图片。需要我去现场再确认一下吗？`
              : (body.text || `当前记忆中没有找到${canonicalTarget}的位置，需要我去各个地方找找看吗？`);

            message = {
              id: genId('msg'),
              role: 'robot',
              content: text,
              timestamp: Date.now(),
              images: historyImages.length > 0 ? historyImages : undefined,
              meta: {
                status: 'awaiting_confirmation',
                statusText: 'search_confirmation_request',
                actions: [
                  { id: 'confirm_search', label: '去看看', style: 'primary' },
                  { id: 'cancel_search', label: '不用了', style: 'secondary' },
                ],
                taskId: body.task_id,
              },
            };
          } else {
            // 正常搜索事件：复制图片到聊天副本目录
            const chatImages: ImageAttachment[] = [];
            const destDir = path.join(
              DATA_DIR, 'images', 'ros-events',
              body.session_id, body.task_id || 'unknown'
            );
            fs.mkdirSync(destDir, { recursive: true });

            for (const entry of (body.image_paths || [])) {
              let angleStr = 'unknown';
              let srcPath = entry;
              if (entry.includes(':')) {
                const colonIdx = entry.indexOf(':');
                angleStr = entry.slice(0, colonIdx);
                srcPath = entry.slice(colonIdx + 1);
              }

              const filename = `node${body.node_id}_${angleStr}_${genId('img')}.png`;
              const destPath = path.join(destDir, filename);

              try {
                fs.copyFileSync(srcPath, destPath);
                chatImages.push({
                  id: genId('img'),
                  url: `/api/images/ros-events/${body.session_id}/${body.task_id || 'unknown'}/${filename}`,
                  alt: `节点${body.node_id} ${angleStr}°`,
                });
              } catch (e: any) {
                console.warn(`[ros-event] Failed to copy image: ${srcPath}`, e.message);
              }
            }

            message = {
              id: genId('msg'),
              role: (body.role || 'robot') as any,
              content: body.text || '',
              timestamp: Date.now(),
              images: chatImages.length > 0 ? chatImages : undefined,
              meta: {
                status: body.found ? 'completed' : 'searching',
                statusText: body.event_type,
              },
            };
          }

          // Append to session
          const msgs = sessionMessages.get(body.session_id);
          if (msgs) {
            msgs.push(message);
            scheduleSave();
            broadcast({ type: 'message_added', sessionId: body.session_id, message });
            traceSearch(
              `[SEARCH-TRACE] ros-event.persist session=${body.session_id} ` +
              `msg_id=${message.id} type=${body.event_type} ` +
              `imgs=${(message.images || []).length} ` +
              `content="${(message.content || '').slice(0, 80)}"`
            );

            // Round 6: 若是搜索类事件 → 紧跟一条 LLM 润色版消息（异步填充，不覆盖上面硬数据）
            if (POLISH_EVENT_TYPES.has(body.event_type)) {
              const polishMsg: ChatMessage = {
                id: genId('msg'),
                role: 'robot',
                content: '',
                timestamp: Date.now() + 1, // 确保时间戳严格递增，保证排序稳定
                meta: {
                  status: 'polishing',
                  statusText: `polish:${body.event_type}`,
                  polishFor: message.id,
                },
              };
              msgs.push(polishMsg);
              scheduleSave();
              broadcast({ type: 'message_added', sessionId: body.session_id, message: polishMsg });
              try {
                polishWithLLM(body.session_id, polishMsg, body);
              } catch (exc: any) {
                traceSearch(`[SEARCH-TRACE] polish.spawn_error type=${body.event_type} err=${exc && exc.message}`, 'warn');
                _removePolishPlaceholder(body.session_id, polishMsg.id);
              }
            }
          } else {
            traceSearch(
              `[SEARCH-TRACE] ros-event.no_session session=${body.session_id} ` +
              `type=${body.event_type}`,
              'warn'
            );
            console.warn(`[ros-event] Session not found: ${body.session_id}`);
          }

          return jsonResponse(res, 200, { success: true, messageId: message.id });
        } catch (e: any) {
          traceSearch(
            `[SEARCH-TRACE] ros-event.persist_error exc="${e && e.message ? e.message : e}"`,
            'warn'
          );
          return jsonResponse(res, 500, { error: e.message });
        }
      });

      // ── Abandon active search task (user clicked cancel) ──
      server.middlewares.use('/api/chat/ros-task/abandon', async (req, res) => {
        if (req.method !== 'POST') {
          res.writeHead(405);
          res.end();
          return;
        }
        try {
          const body = JSON.parse(await readBody(req) || '{}');
          const sid = String(body.session_id || '');
          const tid = body.task_id ? String(body.task_id) : '';
          if (!sid) return jsonResponse(res, 400, { error: 'missing session_id' });
          const active = activeTaskBySession.get(sid);
          // Only clear if matching (or no task_id provided — explicit wipe).
          if (!tid || !active || active === tid) {
            activeTaskBySession.delete(sid);
            return jsonResponse(res, 200, { cleared: active || null });
          }
          return jsonResponse(res, 200, { cleared: null, active });
        } catch (e: any) {
          return jsonResponse(res, 500, { error: e.message });
        }
      });

      server.middlewares.use('/api/chat', async (req, res) => {
        const url = req.url || '';
        const method = req.method || 'GET';

        // ── SSE endpoint ──────────────────────────
        if (url === '/events' || url === '/events/') {
          res.writeHead(200, {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
          });
          res.write(`data: ${JSON.stringify({ type: 'connected' })}\n\n`);
          sseClients.add(res);
          req.on('close', () => { sseClients.delete(res); });
          return;
        }

        res.setHeader('Content-Type', 'application/json');

        // ── GET /sessions ─────────────────────────
        if (url === '/sessions' && method === 'GET') {
          return jsonResponse(res, 200, {
            sessions: storeIndex.sessions,
            activeSessionId: storeIndex.activeSessionId,
          });
        }

        // ── POST /sessions ────────────────────────
        if (url === '/sessions' && method === 'POST') {
          const body = JSON.parse(await readBody(req) || '{}');
          const sf = createDefaultSession();
          if (body.title) sf.session.title = body.title;
          storeIndex.sessions.unshift(sf.session);
          storeIndex.activeSessionId = sf.session.id;
          sessionMessages.set(sf.session.id, sf.messages);
          scheduleSave();
          broadcast({ type: 'session_created', session: sf.session, messages: sf.messages });
          broadcast({ type: 'session_switched', activeSessionId: sf.session.id });
          return jsonResponse(res, 201, sf.session);
        }

        // ── PUT /sessions/active ──────────────────
        if (url === '/sessions/active' && method === 'PUT') {
          const body = JSON.parse(await readBody(req) || '{}');
          if (body.sessionId && storeIndex.sessions.some(s => s.id === body.sessionId)) {
            storeIndex.activeSessionId = body.sessionId;
            scheduleSave();
            broadcast({ type: 'session_switched', activeSessionId: body.sessionId });
            return jsonResponse(res, 200, { ok: true });
          }
          return jsonResponse(res, 400, { error: 'Invalid sessionId' });
        }

        // ── PUT /sessions/:id (rename) ────────────
        const renameMatch = url.match(/^\/sessions\/([^/]+)$/);
        if (renameMatch && method === 'PUT') {
          const sid = renameMatch[1];
          const body = JSON.parse(await readBody(req) || '{}');
          const session = storeIndex.sessions.find(s => s.id === sid);
          if (!session) return jsonResponse(res, 404, { error: 'Session not found' });
          if (body.title) session.title = body.title;
          session.updatedAt = Date.now();
          scheduleSave();
          broadcast({ type: 'session_renamed', sessionId: sid, title: session.title });
          return jsonResponse(res, 200, session);
        }

        // ── DELETE /sessions/:id ──────────────────
        const deleteMatch = url.match(/^\/sessions\/([^/]+)$/);
        if (deleteMatch && method === 'DELETE') {
          const sid = deleteMatch[1];
          storeIndex.sessions = storeIndex.sessions.filter(s => s.id !== sid);
          sessionMessages.delete(sid);
          // Delete message file
          const msgFile = path.join(MSGS_DIR, `${sid}.json`);
          try { fs.unlinkSync(msgFile); } catch {}

          // Ensure at least one session
          if (storeIndex.sessions.length === 0) {
            const sf = createDefaultSession();
            storeIndex.sessions.push(sf.session);
            sessionMessages.set(sf.session.id, sf.messages);
            storeIndex.activeSessionId = sf.session.id;
          } else if (storeIndex.activeSessionId === sid) {
            storeIndex.activeSessionId = storeIndex.sessions[0].id;
          }
          scheduleSave();
          broadcast({ type: 'session_deleted', sessionId: sid, activeSessionId: storeIndex.activeSessionId });
          return jsonResponse(res, 200, { ok: true });
        }

        // ── GET /sessions/:id/messages ────────────
        const getMsgsMatch = url.match(/^\/sessions\/([^/]+)\/messages$/);
        if (getMsgsMatch && method === 'GET') {
          const sid = getMsgsMatch[1];
          const msgs = sessionMessages.get(sid) || [];
          return jsonResponse(res, 200, { messages: msgs });
        }

        // ── POST /sessions/:id/messages ───────────
        const postMsgsMatch = url.match(/^\/sessions\/([^/]+)\/messages$/);
        if (postMsgsMatch && method === 'POST') {
          const sid = postMsgsMatch[1];
          const body = JSON.parse(await readBody(req) || '{}');
          const msgs = sessionMessages.get(sid);
          if (!msgs) return jsonResponse(res, 404, { error: 'Session not found' });

          const newMsg: ChatMessage = {
            id: genId('msg'),
            role: body.role || 'user',
            content: body.content || '',
            timestamp: Date.now(),
            sender: body.sender,
            images: body.images,
            meta: body.meta,
          };
          msgs.push(newMsg);

          // Auto-title: first user message becomes session title
          const session = storeIndex.sessions.find(s => s.id === sid);
          if (session && msgs.filter(m => m.role === 'user').length === 1 && newMsg.role === 'user') {
            session.title = newMsg.content.slice(0, 12) + (newMsg.content.length > 12 ? '...' : '');
            session.updatedAt = Date.now();
          }

          scheduleSave();
          broadcast({ type: 'message_added', sessionId: sid, message: newMsg });
          return jsonResponse(res, 201, newMsg);
        }

        // ── PUT /messages/:id ─────────────────────
        const updateMsgMatch = url.match(/^\/messages\/([^/]+)$/);
        if (updateMsgMatch && method === 'PUT') {
          const msgId = updateMsgMatch[1];
          const body = JSON.parse(await readBody(req) || '{}');
          const sessionId = body.sessionId;

          // Find the message across sessions (or in specified session)
          let targetMsgs: ChatMessage[] | undefined;
          let targetSid = '';
          if (sessionId) {
            targetMsgs = sessionMessages.get(sessionId);
            targetSid = sessionId;
          } else {
            for (const [sid, msgs] of sessionMessages) {
              if (msgs.some(m => m.id === msgId)) {
                targetMsgs = msgs;
                targetSid = sid;
                break;
              }
            }
          }

          if (!targetMsgs) return jsonResponse(res, 404, { error: 'Message not found' });

          const idx = targetMsgs.findIndex(m => m.id === msgId);
          if (idx === -1) return jsonResponse(res, 404, { error: 'Message not found' });

          targetMsgs[idx] = mergeRobotMessage(targetMsgs[idx], {
            meta: body.meta,
            content: body.content,
          });

          scheduleSave();
          broadcast({
            type: 'message_updated',
            sessionId: targetSid,
            messageId: msgId,
            message: targetMsgs[idx],
          });
          return jsonResponse(res, 200, targetMsgs[idx]);
        }

        // ── 404 ───────────────────────────────────
        jsonResponse(res, 404, { error: 'Not found' });
      });
    },
  };
}
