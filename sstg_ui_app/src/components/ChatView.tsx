import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { Send, Bot, User, Cpu, MapPin, Activity, AlertCircle, Loader2, Navigation, Plus, MessageSquare, Trash2, Edit2, BrainCircuit, Globe, ShieldAlert, Key, Zap, Server, Timer, X, Eye, EyeOff, Map as MapIcon, Save, CheckCircle2, Mic, Clock, MessageCircle, Compass, Route, Paperclip, Image as ImageIcon } from "lucide-react";
import { useRosStore } from "../store/rosStore";
import { useChatStore, getUsername } from "../store/chatStore";
import type { QueueItem, ImageAttachment } from "../store/chatStore";
import { useMapStore } from "../store/mapStore";
import { useVoiceInput } from "../hooks/useVoiceInput";
import { cn } from "../lib/utils";

const DIAGNOSTIC_TIMEOUT_SEC = 45;
const DIAGNOSTIC_RETRIES = 2;
const TTFT_THRESHOLD_MS = 5000;      // 首字延迟告警阈值
const TEST_PROMPT = "你是谁？请简短介绍。";

/** 模式定义 */
type ChatMode = "chat" | "navigate" | "explore";

const MODE_CONFIG: Record<ChatMode, {
  label: string;
  icon: typeof MessageCircle;
  color: string;
  allowedIntents: Set<string>;
  placeholder: string;
}> = {
  chat: {
    label: "聊天",
    icon: MessageCircle,
    color: "text-green-400",
    allowedIntents: new Set(["conversation", "chat", "query_info"]),
    placeholder: "和小拓聊天吧~",
  },
  navigate: {
    label: "导航",
    icon: Route,
    color: "text-blue-400",
    allowedIntents: new Set(["conversation", "chat", "query_info", "navigate_to", "locate_object", "describe_scene", "stop_task"]),
    placeholder: "输入导航指令 (如: 去客厅、帮我找书包)...",
  },
  explore: {
    label: "探索",
    icon: Compass,
    color: "text-amber-400",
    allowedIntents: new Set(["conversation", "chat", "query_info", "explore_new_home", "describe_scene", "stop_task"]),
    placeholder: "探索新环境或和小拓聊天~",
  },
};

/** 被拒绝意图的友好回复 */
const MODE_REJECT_MESSAGES: Record<ChatMode, Record<string, string>> = {
  chat: {
    navigate_to: "我现在是纯聊天模式哦～要导航的话请切换到导航模式~",
    locate_object: "找东西需要切换到导航模式才行呢~",
    explore_new_home: "探索新环境需要切换到探索模式哦~",
    describe_scene: "看看周围需要切换到导航或探索模式~",
    stop_task: "我现在没有在执行任务哦~",
  },
  navigate: {
    explore_new_home: "导航模式下不能探索新环境，请切换到探索模式~",
  },
  explore: {
    navigate_to: "我正在探索模式呢，等探索完再带你去吧~ 请切换到导航模式~",
    locate_object: "探索模式下不能定点找东西，请切换到导航模式~",
  },
};

// ── 图片压缩 ──
const MAX_IMAGE_DIM = 1280;
const JPEG_QUALITY = 0.8;

interface PendingImage {
  id: string;
  file: File;
  previewUrl: string;
  base64?: string;
  mimeType: string;
  width?: number;
  height?: number;
}

async function compressImage(file: File): Promise<PendingImage> {
  return new Promise((resolve) => {
    const img = new window.Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      let { width, height } = img;
      const scale = Math.min(1, MAX_IMAGE_DIM / Math.max(width, height));
      width = Math.round(width * scale);
      height = Math.round(height * scale);
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d')!;
      ctx.drawImage(img, 0, 0, width, height);
      const mimeType = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
      canvas.toBlob((blob) => {
        if (!blob) { resolve({ id: crypto.randomUUID(), file, previewUrl: url, mimeType, width, height }); return; }
        const reader = new FileReader();
        reader.onloadend = () => {
          const dataUrl = reader.result as string;
          const base64 = dataUrl.split(',')[1];
          resolve({ id: crypto.randomUUID(), file, previewUrl: url, base64, mimeType, width, height });
        };
        reader.readAsDataURL(blob);
      }, mimeType, mimeType === 'image/jpeg' ? JPEG_QUALITY : undefined);
    };
    img.onerror = () => {
      resolve({ id: crypto.randomUUID(), file, previewUrl: url, mimeType: file.type || 'image/jpeg' });
    };
    img.src = url;
  });
}

/** 用户名 → 稳定颜色（哈希映射到预设调色盘） */
const AVATAR_COLORS = [
  "bg-rose-600",    "bg-pink-600",   "bg-fuchsia-600", "bg-purple-600",
  "bg-violet-600",  "bg-indigo-600", "bg-sky-600",     "bg-cyan-600",
  "bg-teal-600",    "bg-emerald-600","bg-green-600",   "bg-lime-600",
  "bg-amber-600",   "bg-orange-600", "bg-red-600",     "bg-blue-600",
];

function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function avatarFor(name: string): { letter: string; color: string } {
  const letter = (name[0] || "?").toUpperCase();
  const color = AVATAR_COLORS[hashName(name) % AVATAR_COLORS.length];
  return { letter, color };
}

/** 状态是否为进行中 */
const IN_PROGRESS_STATES = new Set(['queued', 'understanding', 'planning', 'navigating', 'exploring', 'searching', 'checking']);
const TERMINAL_STATES = new Set(['completed', 'failed', 'canceled']);

/** 状态标签 — 用于思考过程指示条，不是聊天正文 */
function statusLabel(state: string, _message: string): string {
  switch (state) {
    case 'queued':        return '排队等待中...';
    case 'understanding': return '正在理解意图...';
    case 'planning':      return '规划路线中...';
    case 'navigating':    return '导航中...';
    case 'exploring':     return '探索环境中...';
    case 'searching':     return '搜索中...';
    case 'checking':      return '确认目标中...';
    case 'completed':     return '任务完成';
    case 'failed':        return '任务失败';
    case 'canceled':      return '已取消';
    default:              return state;
  }
}

export default function ChatView() {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  
  const { startTask, cancelTask, taskStatus, robotPose, isConnected, updateLLMConfig } = useRosStore();
  
  const {
    sessions,
    activeSessionId,
    messages,
    isTyping,
    activeProvider,
    providers,
    localQueue,
    canceledTaskIds,
    addMessage,
    setTyping,
    updateLastRobotMessage,
    finalizeLastRobotMessage,
    addToLocalQueue,
    removeFromLocalQueue,
    promoteFromQueue,
    decrementQueuePositions,
    createSession,
    switchSession,
    deleteSession,
    renameSession,
    setActiveProvider,
    updateProviderConfig,
    addProvider,
    removeProvider
  } = useChatStore();

  const { maps, activeMapId, setActiveMapId } = useMapStore();

  const { isSupported: voiceSupported, isListening, transcript, startListening, stopListening } = useVoiceInput();

  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editTitleText, setEditTitleText] = useState("");

  const [showSettings, setShowSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"config" | "test">("config");
  const [showApiKey, setShowApiKey] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveSyncStatus, setSaveSyncStatus] = useState<"" | "synced" | "local-only" | "error">("");

  const [selectedProvider, setSelectedProvider] = useState(activeProvider);
  const [tempConfig, setTempConfig] = useState<any>(providers[activeProvider]);
  const [addingProvider, setAddingProvider] = useState(false);
  const [newProviderName, setNewProviderName] = useState("");

  // 模式切换 — localStorage 持久化，默认聊天模式
  const [chatMode, setChatMode] = useState<ChatMode>(
    () => (localStorage.getItem("sstg_chat_mode") as ChatMode) || "chat"
  );
  useEffect(() => {
    localStorage.setItem("sstg_chat_mode", chatMode);
  }, [chatMode]);

  // 流式消息
  const [streamingMsgId, setStreamingMsgId] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");
  const streamAbortRef = useRef<AbortController | null>(null);
  // 流式 token 批量更新：用 ref 累积，rAF 合并渲染
  const streamBufferRef = useRef("");
  const rafIdRef = useRef<number>(0);
  // 跟踪用户是否在底部（用于后台标签页回来时判断）
  const wasAtBottomRef = useRef(true);

  // 图片上传
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

  const [testState, setTestState] = useState<{
    status: "idle" | "testing" | "success" | "error" | "degraded";
    ms?: number;
    msg?: string;
  }>({ status: "idle" });

  // 自动滚动：新消息/流式输出时平滑跟随底部
  const autoScrollToBottom = useCallback((force = false) => {
    const el = chatContainerRef.current;
    if (!el) return;
    // 只在用户没有手动上滑时自动滚动（距底部 150px 以内视为"在底部"）
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
    wasAtBottomRef.current = isNearBottom;
    if (isNearBottom || force) {
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  // 切换会话时强制滚到底部
  const prevSessionRef = useRef(activeSessionId);
  useEffect(() => {
    if (prevSessionRef.current !== activeSessionId) {
      prevSessionRef.current = activeSessionId;
      // 用 rAF 确保 DOM 已更新
      requestAnimationFrame(() => autoScrollToBottom(true));
    }
  }, [activeSessionId, autoScrollToBottom]);

  // 页面从后台回到前台时：如果离开前在底部，则强制滚到底
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible' && wasAtBottomRef.current) {
        requestAnimationFrame(() => autoScrollToBottom(true));
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [autoScrollToBottom]);

  // 持续追踪用户滚动位置（用于判断后台切回时是否要强制到底）
  useEffect(() => {
    const el = chatContainerRef.current;
    if (!el) return;
    const onScroll = () => {
      wasAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // 新消息到达 / 切换会话时滚动
  useEffect(() => {
    autoScrollToBottom();
    // 保持输入框 focus
    requestAnimationFrame(() => {
      if (document.activeElement === document.body || document.activeElement === null) {
        inputRef.current?.focus();
      }
    });
  }, [messages, isTyping, activeSessionId, autoScrollToBottom]);

  // 流式输出时持续跟随滚动
  useEffect(() => {
    if (streamingText) autoScrollToBottom();
  }, [streamingText, autoScrollToBottom]);

  const prevTaskStateRef = useRef<string | null>(null);
  useEffect(() => {
    if (!taskStatus) return;

    // 从 store 读取最新值，避免把队列状态放入 useEffect 依赖导致循环
    const {
      localQueue: queue,
      canceledTaskIds: canceled,
      promoteFromQueue: promote,
      decrementQueuePositions: decrement,
      addMessage: addMsg,
    } = useChatStore.getState();

    // 队列任务激活：后端开始处理排队消息时，把它从队列栏"弹入"聊天区
    const tid = taskStatus.taskId;
    const queueItem = tid ? queue.find(q => q.taskId === tid) : null;
    if (queueItem && taskStatus.state === 'understanding') {
      // 如果用户已取消此消息（方案B），忽略它
      if (canceled.has(tid)) {
        promote(tid);  // 清理即可
        return;
      }
      // "弹入"聊天区：先加用户消息，再加 robot 占位
      promote(tid);
      decrement();
      (async () => {
        await addMsg({ role: "user", content: queueItem.text });
        finalizeLastRobotMessage();
        await addMsg({ role: "robot", content: '', meta: { status: "understanding", steps: [] } });
        // ownership 已由 addMessage(robot) 自动设置
      })();
      return;  // 后续 taskStatus 更新会在下一次 useEffect 中处理
    }

    // 终态通知：当某个 task 完成，递减队列位置
    const isTerminal = TERMINAL_STATES.has(taskStatus.state);
    if (isTerminal && tid && queue.length > 0 && !queue.find(q => q.taskId === tid)) {
      // 不是队列中的项目完成了（是当前正在执行的任务完成了）
      decrement();
    }

    const prevState = prevTaskStateRef.current;
    prevTaskStateRef.current = taskStatus.state;

    const label = statusLabel(taskStatus.state, taskStatus.message || '');

    // 状态变化时追加一条 step 到思考轨迹
    const newStep = prevState !== taskStatus.state
      ? { state: taskStatus.state, text: label, timestamp: Date.now() }
      : undefined;

    // 终态时，如果当前 robot 消息 content 为空，把后端的有意义 message 补充为正文
    const msg = taskStatus.message || '';
    const isStatusKeyword = /^(idle|understanding|planning|navigating|exploring|searching|checking|completed|failed|canceled|查询完成|任务完成|任务失败|已取消)$/i.test(msg.trim());
    const contentFill = isTerminal && msg && !isStatusKeyword ? msg : undefined;

    updateLastRobotMessage(
      {
        status: taskStatus.state,
        progress: taskStatus.progress,
        statusText: label,
        ...(newStep ? { steps: newStep } : {}),
      } as any,
      contentFill
    );

    // Auto-clear ownership on terminal state — prevents stale updates to old messages
    if (TERMINAL_STATES.has(taskStatus.state)) {
      finalizeLastRobotMessage();
    }
  }, [taskStatus, updateLastRobotMessage, finalizeLastRobotMessage]);

  useEffect(() => {
    setTempConfig(providers[selectedProvider]);
    setTestState({ status: "idle" }); 
  }, [selectedProvider, providers]);

  useEffect(() => {
    if (showSettings) {
      setSelectedProvider(activeProvider);
    }
  }, [showSettings, activeProvider]);

  // ── 流式聊天发送（绕过 ROS，直接 HTTP SSE）──
  const handleStreamChat = useCallback(async (text: string, mapContext: string, images?: PendingImage[]) => {
    const controller = new AbortController();
    streamAbortRef.current = controller;
    setStreamingText("");
    streamBufferRef.current = "";

    // 准备图片数据
    const imagePayload = images?.filter(i => i.base64).map(i => ({
      base64: i.base64!,
      mimeType: i.mimeType,
      width: i.width,
      height: i.height,
    }));

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: activeSessionId,
          text,
          senderName: getUsername(),
          mapContext,
          images: imagePayload,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        await addMessage({ role: "user", content: text });
        await addMessage({ role: "robot", content: err.error || "流式连接失败", meta: { status: "failed" } });
        return;
      }

      // 读取响应头中的消息 ID
      const robotMsgId = response.headers.get("X-Robot-Msg-Id") || "";
      setStreamingMsgId(robotMsgId);

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      // 用 rAF 批量刷新：token 先写入 ref，每帧最多触发一次 setState
      const scheduleFlush = () => {
        if (rafIdRef.current) return; // 已有待刷新的帧
        rafIdRef.current = requestAnimationFrame(() => {
          rafIdRef.current = 0;
          setStreamingText(streamBufferRef.current);
        });
      };

      if (reader) {
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const parsed = JSON.parse(line.slice(6));
              if (parsed.token) {
                streamBufferRef.current += parsed.token;
                scheduleFlush();
              }
            } catch {}
          }
        }
      }

      // 最终刷新：确保最后的 token 不丢失
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = 0;
      }
      setStreamingText(streamBufferRef.current);
    } catch (err: any) {
      if (err.name !== "AbortError") {
        console.error("[stream] error:", err);
      }
    } finally {
      setStreamingMsgId(null);
      setStreamingText("");
      streamBufferRef.current = "";
      streamAbortRef.current = null;
      // 流式结束后恢复输入框 focus
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [activeSessionId, addMessage]);

  // 语音识别结果自动填入输入框
  useEffect(() => {
    if (transcript) {
      setInput(transcript);
    }
  }, [transcript]);

  // ── 图片处理 ──
  const addImages = useCallback(async (files: File[]) => {
    const imageFiles = files.filter(f => f.type.startsWith('image/'));
    if (imageFiles.length === 0) return;
    const compressed = await Promise.all(imageFiles.map(compressImage));
    setPendingImages(prev => [...prev, ...compressed].slice(0, 4)); // 最多 4 张
  }, []);

  const removeImage = useCallback((id: string) => {
    setPendingImages(prev => {
      const removed = prev.find(p => p.id === id);
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return prev.filter(p => p.id !== id);
    });
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    addImages(files);
    e.target.value = ''; // reset for re-select
  }, [addImages]);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const imageFiles: File[] = [];
    for (const item of Array.from(items)) {
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) imageFiles.push(file);
      }
    }
    if (imageFiles.length > 0) {
      e.preventDefault();
      addImages(imageFiles);
    }
  }, [addImages]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
    addImages(files);
  }, [addImages]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
  }, []);

  const handleSend = async () => {
    if (!input.trim() && pendingImages.length === 0) return;
    const text = input.trim();
    const images = [...pendingImages];
    setInput("");
    setPendingImages([]);
    // 清理 preview URLs
    images.forEach(i => URL.revokeObjectURL(i.previewUrl));

    // 快速 stop 关键词检测 — 零延迟取消，不走 VLM
    const stopPattern = /^(停[下止]|取消|别走了?|不要去了?|算了|不去了|别去了?)$/;
    if (stopPattern.test(text) && chatMode !== "chat") {
      await addMessage({ role: "user", content: text });
      try {
        await cancelTask();
        await addMessage({ role: "robot", content: '好的，已经停下来了~', meta: { status: 'completed' } });
      } catch {
        await addMessage({ role: "robot", content: '我现在没有在执行任务哦~', meta: { status: 'completed' } });
      }
      return;
    }

    // 构建当前地图上下文
    let mapContext = 'home';
    try {
      const activeMap = maps.find(m => m.id === activeMapId) || maps[0];
      if (activeMap?.topoJson) {
        const topoRes = await fetch(activeMap.topoJson);
        const topoData = await topoRes.json();
        const nodes = topoData.nodes || [];
        const nodeDescs = nodes.map((n: any) => {
          const si = n.semantic_info || {};
          const name = si.room_type_cn || si.room_type || n.name || `节点${n.id}`;
          const objs = (si.objects || []).slice(0, 3).map((o: any) => o.name).filter(Boolean);
          return objs.length > 0 ? `${name}(${objs.join(',')})` : name;
        });
        mapContext = `当前地图: ${activeMap.label}\n可用位置: ${nodeDescs.join(', ')}`;
      }
    } catch {}

    // ── 纯聊天模式：所有消息走流式 ──
    if (chatMode === "chat") {
      handleStreamChat(text, mapContext, images.length > 0 ? images : undefined);
      return;
    }

    // 有图片时，直接走流式（图片不走 ROS）
    if (images.length > 0) {
      handleStreamChat(text || '请看这张图片', mapContext, images);
      return;
    }

    // ── 导航/探索模式：走 ROS 链路 ──
    if (!isConnected) return;
    if (!text) return; // 没有文字也没有图片了（图片已上面处理）

    try {
      const result = await startTask(text, mapContext, activeSessionId, getUsername());

      if (!result.success) {
        await addMessage({ role: "user", content: text });
        await addMessage({ role: "robot", content: `任务启动失败: ${result.error_message}`, meta: { status: 'failed' } });

      } else if (result.intent === 'queued') {
        let position = 0;
        let queuedId = '';
        try {
          const qj = JSON.parse(result.query_json);
          position = qj.position || 0;
          queuedId = qj.task_id || '';
        } catch {}
        if (queuedId) {
          addToLocalQueue({
            text,
            taskId: queuedId,
            position,
            sender: getUsername() || '我',
            timestamp: Date.now(),
          });
        }

      } else {
        // 检查意图是否被当前模式允许
        const intent = result.intent || 'conversation';
        const modeConf = MODE_CONFIG[chatMode];
        const isConversation = new Set(["conversation", "chat", "query_info"]).has(intent);

        if (isConversation) {
          // conversation 意图：走流式（即使在导航/探索模式下）
          handleStreamChat(text, mapContext);
          return;
        }

        if (!modeConf.allowedIntents.has(intent)) {
          // 意图被当前模式拒绝 → 友好回复
          const rejectMsg = MODE_REJECT_MESSAGES[chatMode]?.[intent] || "当前模式不支持这个操作哦~";
          await addMessage({ role: "user", content: text });
          await addMessage({ role: "robot", content: rejectMsg, meta: { status: 'completed' } });
          return;
        }

        // 正常处理 → 消息进聊天区 + robot 占位
        await addMessage({ role: "user", content: text });
        finalizeLastRobotMessage();
        await addMessage({
          role: "robot",
          content: '',
          meta: { status: "understanding", steps: [] }
        });
      }
    } catch (err) {
      const errMsg = String(err);
      console.error("startTask error:", err);
      await addMessage({ role: "user", content: text });
      await addMessage({ role: "robot", content: errMsg, meta: { status: 'failed' } });
    }
  };

  const handleSaveSettings = async () => {
    updateProviderConfig(selectedProvider, tempConfig);
    setActiveProvider(selectedProvider);
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 3000);

    // 推送 LLM 配置到后端 NLP 节点
    if (!isConnected) {
      setSaveSyncStatus("local-only");
      setTimeout(() => setSaveSyncStatus(""), 4000);
      return;
    }
    if (!tempConfig.apiKey) {
      setSaveSyncStatus("local-only");
      setTimeout(() => setSaveSyncStatus(""), 4000);
      return;
    }
    try {
      const result = await updateLLMConfig(tempConfig.baseUrl, tempConfig.apiKey, tempConfig.model);
      if (result?.success) {
        setSaveSyncStatus("synced");
      } else {
        setSaveSyncStatus("error");
        console.warn("[LLM sync] Backend rejected:", result?.message);
      }
    } catch (err) {
      setSaveSyncStatus("local-only");
      console.warn("[LLM sync] ROS service call failed:", err);
    }
    setTimeout(() => setSaveSyncStatus(""), 4000);
  };

  const handleDiagnosticTest = async () => {
    setTestState({ status: "testing" });

    let attempt = 0;
    const maxAttempts = DIAGNOSTIC_RETRIES + 1;

    while (attempt < maxAttempts) {
      const startTime = Date.now();
      try {
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), DIAGNOSTIC_TIMEOUT_SEC * 1000);

        const response = await fetch(`/api/llm-proxy/chat/completions`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${tempConfig.apiKey}`,
            "X-Target-Url": tempConfig.baseUrl,
          },
          body: JSON.stringify({
            model: tempConfig.model,
            messages: [{ role: "user", content: TEST_PROMPT }],
            stream: true,
          }),
          signal: controller.signal
        });

        if (!response.ok) {
          clearTimeout(id);
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.error?.message || `HTTP 错误 ${response.status}`);
        }

        // 流式读取：测首字 Token 延迟 (TTFT) + 收集完整回复
        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        let ttft = 0;
        let fullText = "";
        let gotFirstToken = false;

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });

            // 记录首字 Token 时间
            if (!gotFirstToken && chunk.includes('"delta"')) {
              ttft = Date.now() - startTime;
              gotFirstToken = true;
            }

            // 解析 SSE 行，提取文字
            for (const line of chunk.split('\n')) {
              const trimmed = line.trim();
              if (!trimmed.startsWith('data: ') || trimmed === 'data: [DONE]') continue;
              try {
                const parsed = JSON.parse(trimmed.slice(6));
                const content = parsed.choices?.[0]?.delta?.content;
                if (content) fullText += content;
              } catch {}
            }
          }
        }

        clearTimeout(id);
        const totalTime = Date.now() - startTime;

        // 如果没有检测到流式 delta（可能是非流式回退），用总时间
        if (!gotFirstToken) {
          ttft = totalTime;
          // 尝试从非流式格式中提取内容
          if (!fullText) {
            try {
              const data = JSON.parse(decoder.decode());
              fullText = data.choices?.[0]?.message?.content || "";
            } catch {}
          }
        }

        const replyPreview = fullText.slice(0, 100) || "成功收到响应";
        const detail = `首字延迟: ${ttft}ms | 总耗时: ${totalTime}ms\n回复: ${replyPreview}`;

        if (ttft > TTFT_THRESHOLD_MS) {
          setTestState({ status: "degraded", ms: ttft, msg: `首字延迟过高 (阈值: ${TTFT_THRESHOLD_MS}ms)\n${detail}` });
        } else {
          setTestState({ status: "success", ms: ttft, msg: detail });
        }
        return;

      } catch (err: any) {
        attempt++;
        if (attempt >= maxAttempts) {
          setTestState({ status: "error", msg: err.name === "AbortError" ? `请求超时 (${DIAGNOSTIC_TIMEOUT_SEC}s)` : (err.message || "网络请求失败或跨域被拦截") });
        }
      }
    }
  };

  return (
    <div className="flex h-full w-full bg-slate-950 text-slate-200">
      
      {/* LEFT: Session History Sidebar */}
      <div className="w-48 lg:w-64 border-r border-slate-800 bg-slate-950/50 flex flex-col shrink-0">
        <div className="h-16 flex items-center px-4 border-b border-slate-800 shrink-0">
          <button 
            onClick={createSession}
            className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 text-white py-2 rounded-lg text-sm font-medium transition-colors shadow-sm"
          >
            <Plus size={16} /> 新建导航对话
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3 px-2 mt-2">
            历史会话
          </div>
          {sessions.map(session => (
            <div 
              key={session.id}
              onClick={() => { if (editingSessionId !== session.id) switchSession(session.id); }}
              className={cn(
                "group flex items-center justify-between p-3 rounded-xl cursor-pointer transition-all duration-200 border",
                activeSessionId === session.id 
                  ? "bg-slate-800/80 border-slate-700 shadow-sm" 
                  : "bg-transparent border-transparent hover:bg-slate-900 hover:border-slate-800"
              )}
            >
              <div className="flex items-center gap-3 overflow-hidden flex-1">
                <MessageSquare size={16} className={activeSessionId === session.id ? "text-blue-400 shrink-0" : "text-slate-500 shrink-0"} />
                {editingSessionId === session.id ? (
                  <input
                    autoFocus
                    className="w-full bg-slate-950 text-white text-sm border border-slate-600 rounded px-1.5 py-0.5 outline-none"
                    value={editTitleText}
                    onChange={(e) => setEditTitleText(e.target.value)}
                    onBlur={() => {
                      if (editTitleText.trim()) renameSession(session.id, editTitleText.trim());
                      setEditingSessionId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        if (editTitleText.trim()) renameSession(session.id, editTitleText.trim());
                        setEditingSessionId(null);
                      }
                    }}
                  />
                ) : (
                  <span className={cn("text-sm truncate select-none", activeSessionId === session.id ? "text-slate-200" : "text-slate-400")}>
                    {session.title}
                  </span>
                )}
              </div>

              {editingSessionId !== session.id && (
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                  <button 
                    onClick={(e) => { 
                      e.stopPropagation(); 
                      setEditTitleText(session.title);
                      setEditingSessionId(session.id); 
                    }}
                    className="p-1.5 text-slate-500 hover:text-blue-400 hover:bg-slate-800 rounded-md transition-all"
                    title="重命名"
                  >
                    <Edit2 size={14} />
                  </button>
                  <button 
                    onClick={(e) => { e.stopPropagation(); deleteSession(session.id); }}
                    className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-slate-800 rounded-md transition-all"
                    title="删除会话"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* CENTER: Chat Conversation Area */}
      <div className="flex-1 flex flex-col relative min-w-0 bg-slate-950">
        
        <header className="h-16 flex items-center justify-between px-3 sm:px-6 border-b border-slate-800 bg-slate-950/80 backdrop-blur-md z-10 sticky top-0 shrink-0">
          
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-600/20 flex items-center justify-center text-blue-500 shadow-[0_0_10px_rgba(37,99,235,0.4)]">
              <Bot size={20} />
            </div>
            <div>
              <h1 className="font-medium text-slate-100 flex items-center gap-2 tracking-wide">
                SSTG <span className="font-light text-slate-400">CORE</span>
              </h1>
              <p className="text-xs text-slate-500 truncate max-w-md hidden sm:block">自然语言导航与编排大脑</p>
            </div>

            {/* Map Selector inside Header */}
            <div className="ml-4 lg:ml-8 flex items-center gap-2 bg-slate-900/50 border border-slate-700/50 rounded-lg px-2 sm:px-3 py-1.5 shadow-sm">
              <MapIcon size={14} className="text-blue-400" />
              <select
                value={activeMapId}
                onChange={(e) => setActiveMapId(e.target.value)}
                className="bg-slate-900 text-xs text-slate-300 font-medium focus:outline-none cursor-pointer max-w-[160px] truncate"
              >
                {maps.map(m => (
                  <option key={m.id} value={m.id} className="bg-slate-900 text-slate-300">{m.label}</option>
                ))}
              </select>
              <button
                onClick={() => { window.location.href = '/map'; }}
                className="p-0.5 rounded hover:bg-slate-700 transition-colors text-slate-500 hover:text-blue-400"
                title="管理地图"
              >
                <Plus size={14} />
              </button>
            </div>
          </div>

          <div className="relative z-50">
            <button 
              className={cn("flex items-center gap-2 px-3 py-1.5 rounded-lg cursor-pointer transition-all shadow-sm group", showSettings ? "bg-indigo-600/10 border-indigo-500/30 border" : "bg-slate-900 hover:bg-slate-800 border border-slate-700/50 hover:shadow-indigo-900/20")}
              onClick={() => setShowSettings(!showSettings)}
              title="展开云端/本地大模型控制台"
            >
              <Server size={14} className={cn("transition-colors", showSettings ? "text-indigo-400" : "text-indigo-400 group-hover:text-indigo-300")} />
              <div className="flex flex-col items-start">
                <span className="text-[10px] text-slate-500 font-bold uppercase leading-none mb-0.5">AI ENGINE</span>
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_5px_rgba(16,185,129,0.5)]"></span>
                  <span className="text-xs text-slate-300 font-mono leading-none">CONNECTED</span>
                </div>
              </div>
            </button>

            {/* SINGLE TAB SETTINGS POPOVER */}
            {showSettings && (
              <div className="absolute top-full right-0 mt-3 w-[28rem] bg-slate-900/95 backdrop-blur-xl border border-slate-700/50 rounded-2xl shadow-2xl overflow-hidden animate-in slide-in-from-top-2 flex flex-col">
                
                <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-950/50 shrink-0">
                  <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded bg-indigo-500/20 text-indigo-400 flex items-center justify-center">
                      <BrainCircuit size={14} />
                    </div>
                    <span className="text-sm font-bold text-slate-200">大模型引擎配置与诊断</span>
                  </div>
                  <button onClick={() => setShowSettings(false)} className="text-slate-500 hover:text-white p-1 rounded hover:bg-slate-800 transition-colors"><X size={16}/></button>
                </div>

                <div className="p-5 overflow-y-auto max-h-[60vh] space-y-4">
                  <div>
                    <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5 mb-1.5"><Globe size={12}/> 选择 API 供应商 (自动切换配置)</label>
                    <div className="flex items-center gap-2">
                      <select
                        className="flex-1 bg-slate-950 border border-slate-800 rounded p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 transition-colors"
                        value={selectedProvider}
                        onChange={(e) => setSelectedProvider(e.target.value)}
                      >
                        {Object.keys(providers).map(p => (
                          <option key={p} value={p}>{p}</option>
                        ))}
                      </select>
                      <button
                        onClick={() => setAddingProvider(true)}
                        className="p-2 rounded bg-slate-800 text-slate-400 hover:text-emerald-400 hover:bg-emerald-500/10 transition-colors border border-slate-700/50"
                        title="添加新供应商"
                      >
                        <Plus size={14} />
                      </button>
                      {Object.keys(providers).length > 1 && (
                        <button
                          onClick={() => {
                            if (confirm(`确定删除「${selectedProvider}」？`)) {
                              removeProvider(selectedProvider);
                              const remaining = Object.keys(providers).filter(p => p !== selectedProvider);
                              if (remaining.length) {
                                setSelectedProvider(remaining[0]);
                                setTempConfig(providers[remaining[0]]);
                              }
                            }
                          }}
                          className="p-2 rounded bg-slate-800 text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors border border-slate-700/50"
                          title="删除当前供应商"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                    {addingProvider && (
                      <div className="flex items-center gap-2 mt-2">
                        <input
                          autoFocus
                          type="text"
                          placeholder="输入新供应商名称"
                          value={newProviderName}
                          onChange={(e) => setNewProviderName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && newProviderName.trim()) {
                              addProvider(newProviderName.trim(), { baseUrl: "", apiKey: "", model: "", backupModel: "" });
                              setSelectedProvider(newProviderName.trim());
                              setTempConfig({ baseUrl: "", apiKey: "", model: "", backupModel: "" });
                              setNewProviderName("");
                              setAddingProvider(false);
                            } else if (e.key === 'Escape') {
                              setAddingProvider(false);
                              setNewProviderName("");
                            }
                          }}
                          className="flex-1 bg-slate-950 border border-indigo-500/50 rounded p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 transition-colors"
                        />
                        <button
                          onClick={() => {
                            if (newProviderName.trim()) {
                              addProvider(newProviderName.trim(), { baseUrl: "", apiKey: "", model: "", backupModel: "" });
                              setSelectedProvider(newProviderName.trim());
                              setTempConfig({ baseUrl: "", apiKey: "", model: "", backupModel: "" });
                              setNewProviderName("");
                              setAddingProvider(false);
                            }
                          }}
                          className="p-2 rounded bg-indigo-600 text-white hover:bg-indigo-500 transition-colors text-xs"
                        >
                          <CheckCircle2 size={14} />
                        </button>
                        <button
                          onClick={() => { setAddingProvider(false); setNewProviderName(""); }}
                          className="p-2 rounded bg-slate-800 text-slate-400 hover:text-white transition-colors text-xs"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    )}
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5 mb-1.5"><Globe size={12}/> Base URL</label>
                    <input 
                      type="text" 
                      className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 transition-colors"
                      value={tempConfig?.baseUrl || ""}
                      onChange={(e) => setTempConfig({...tempConfig, baseUrl: e.target.value})}
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5 mb-1.5"><Key size={12}/> API Key</label>
                    <div className="relative">
                      <input 
                        type={showApiKey ? "text" : "password"} 
                        className="w-full bg-slate-950 border border-slate-800 rounded p-2 pr-8 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 transition-colors"
                        value={tempConfig?.apiKey || ""}
                        onChange={(e) => setTempConfig({...tempConfig, apiKey: e.target.value})}
                      />
                      <button 
                        onClick={() => setShowApiKey(!showApiKey)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                      >
                        {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5 mb-1.5"><BrainCircuit size={12}/> 核心主模型</label>
                      <input 
                        type="text" 
                        className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 transition-colors"
                        value={tempConfig?.model || ""}
                        onChange={(e) => setTempConfig({...tempConfig, model: e.target.value})}
                      />
                    </div>
                    <div>
                      <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5 mb-1.5"><ShieldAlert size={12}/> 备用容灾模型</label>
                      <input 
                        type="text" 
                        className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 transition-colors"
                        value={tempConfig?.backupModel || ""}
                        onChange={(e) => setTempConfig({...tempConfig, backupModel: e.target.value})}
                      />
                    </div>
                  </div>

                  {/* Inline Test Result Area */}
                  {testState.status !== "idle" && (
                    <div className={cn(
                      "p-3 rounded-lg border transition-all mt-4",
                      testState.status === "testing" ? "bg-blue-500/10 border-blue-500/30" :
                      testState.status === "success" ? "bg-emerald-500/10 border-emerald-500/30" :
                      testState.status === "degraded" ? "bg-orange-500/10 border-orange-500/30" :
                      "bg-red-500/10 border-red-500/30"
                    )}>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className={cn(
                          "text-[10px] font-bold uppercase flex items-center gap-1",
                          testState.status === "testing" ? "text-blue-400" :
                          testState.status === "success" ? "text-emerald-400" :
                          testState.status === "degraded" ? "text-orange-400" :
                          "text-red-400"
                        )}>
                          {testState.status === "testing" && <Loader2 size={10} className="animate-spin" />}
                          {testState.status === "testing" ? "正在连接当前模型进行诊断..." :
                           testState.status === "success" ? "连接畅通" :
                           testState.status === "degraded" ? "连接延迟告警" :
                           "连接失败"}
                        </span>
                        {(testState.status === "success" || testState.status === "degraded") && (
                          <span className={cn("font-mono text-[10px] px-1.5 py-0.5 rounded", testState.status === "success" ? "bg-emerald-500/20 text-emerald-400" : "bg-orange-500/20 text-orange-400")}>
                            {testState.ms} ms
                          </span>
                        )}
                      </div>
                      {testState.msg && (
                        <p className={cn("text-[10px] leading-relaxed whitespace-pre-wrap break-all", testState.status === "error" ? "text-red-400/90" : "text-slate-300")}>{testState.msg}</p>
                      )}
                    </div>
                  )}

                </div>
                
                {/* BOTTOM ACTIONS */}
                <div className="p-4 border-t border-slate-800 bg-slate-950/50 space-y-2 shrink-0">
                  <div className="flex items-center justify-between gap-3">
                  <button
                    onClick={handleSaveSettings}
                    className="flex-1 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg transition-colors flex items-center justify-center gap-2 border border-slate-700/50"
                  >
                    {saveSuccess ? <CheckCircle2 size={14} className="text-green-400" /> : <Save size={14} />}
                    {saveSuccess ? "已设为激活配置" : "保存并启用该配置"}
                  </button>
                  <button
                    onClick={handleDiagnosticTest}
                    disabled={testState.status === "testing"}
                    className="flex-1 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-lg transition-colors shadow-lg shadow-indigo-900/30 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {testState.status === "testing" ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                    基于当前填写诊断
                  </button>
                  </div>
                  {saveSyncStatus && (
                    <p className={cn("text-[10px] text-center", {
                      "text-green-400": saveSyncStatus === "synced",
                      "text-amber-400": saveSyncStatus === "local-only",
                      "text-red-400": saveSyncStatus === "error",
                    })}>
                      {saveSyncStatus === "synced" && "已同步到后端 NLP 节点，立即生效"}
                      {saveSyncStatus === "local-only" && "仅保存到浏览器本地，后端未连接，重启后端后自动同步"}
                      {saveSyncStatus === "error" && "后端同步失败，请检查配置是否正确"}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </header>

        {/* Message Scroll Area */}
        <div ref={chatContainerRef} className="flex-1 overflow-y-auto px-3 py-4 sm:p-6 space-y-6">
          {messages.map((msg) => (
            <div key={msg.id} className={cn("flex gap-3 sm:gap-4 max-w-[calc(100%-1rem)] sm:max-w-xl md:max-w-2xl lg:max-w-3xl", msg.role === "user" ? "ml-auto flex-row-reverse" : "")}>

              {msg.role === "user" && msg.sender ? (() => {
                const { letter, color } = avatarFor(msg.sender);
                return (
                  <div className={cn("w-8 h-8 shrink-0 rounded-full flex items-center justify-center mt-1 text-white font-bold text-xs shadow-md", color)}
                       title={msg.sender}>
                    {letter}
                  </div>
                );
              })() : (
                <div className={cn(
                  "w-8 h-8 shrink-0 rounded-full flex items-center justify-center mt-1",
                  msg.role === "user" ? "bg-slate-800 border border-slate-700 text-slate-300" :
                  msg.role === "robot" ? "bg-blue-600 text-white shadow-lg shadow-blue-900/30" : "bg-slate-900 border border-slate-800 text-slate-400"
                )}>
                  {msg.role === "user" ? <User size={16} /> : msg.role === "robot" ? <Bot size={16} /> : <Cpu size={16} />}
                </div>
              )}

              <div className="flex flex-col gap-1 min-w-0">
                {/* 发送者标签 */}
                {msg.role === "user" && msg.sender && (
                  <span className={cn("text-[10px] px-1 text-right font-medium",
                    (() => { const c = AVATAR_COLORS[hashName(msg.sender) % AVATAR_COLORS.length]; return c.replace('bg-', 'text-').replace('-600', '-400'); })()
                  )}>{msg.sender}</span>
                )}

                {/* 图片展示 */}
                {msg.images && msg.images.length > 0 && (
                  <div className={cn(
                    "grid gap-1.5 rounded-xl overflow-hidden",
                    msg.images.length === 1 ? "grid-cols-1 max-w-xs" :
                    msg.images.length === 2 ? "grid-cols-2 max-w-sm" :
                    msg.images.length <= 4 ? "grid-cols-2 max-w-md" :
                    "grid-cols-3 max-w-lg"
                  )}>
                    {msg.images.map((img) => (
                      <button
                        key={img.id}
                        onClick={() => setLightboxUrl(img.url)}
                        className="relative overflow-hidden rounded-lg hover:opacity-90 transition-opacity focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <img
                          src={img.url}
                          alt={img.alt || '图片'}
                          className={cn(
                            "w-full object-cover bg-slate-800",
                            msg.images!.length === 1 ? "max-h-64" : "h-32"
                          )}
                          loading="lazy"
                        />
                      </button>
                    ))}
                  </div>
                )}

                {/* 小拓回复正文 — 大模型的自然语言回复 */}
                {(msg.content || streamingMsgId === msg.id || (msg.role === 'robot' && msg.meta?.status && IN_PROGRESS_STATES.has(msg.meta.status))) && (
                  <div className={cn(
                    "px-5 py-3.5 rounded-2xl text-sm leading-relaxed shadow-sm",
                    msg.role === "user" ? "bg-blue-600 text-white rounded-tr-sm whitespace-pre-wrap" :
                    "bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-sm prose prose-sm prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-strong:text-white"
                  )}>
                    {streamingMsgId === msg.id ? (
                      <span>
                        <ReactMarkdown>{streamingText}</ReactMarkdown>
                        <span className="inline-block w-1.5 h-4 bg-blue-400 ml-0.5 animate-pulse align-text-bottom" />
                      </span>
                    ) : msg.content ? (
                      msg.role === 'robot'
                        ? <ReactMarkdown>{msg.content}</ReactMarkdown>
                        : <span className="whitespace-pre-wrap">{msg.content}</span>
                    ) : (
                      <span className="inline-flex items-center gap-2 text-slate-400">
                        <Loader2 size={14} className="animate-spin text-blue-400" />
                        <span className="text-xs">小拓正在思考...</span>
                      </span>
                    )}
                  </div>
                )}

                {/* 思考过程轨迹 — 终态时只显示终态 step，进行中时显示全部 */}
                {msg.meta?.steps && msg.meta.steps.length > 0 && msg.role === 'robot' && (() => {
                  const isTerminal = msg.meta?.status && TERMINAL_STATES.has(msg.meta.status);
                  // 终态：只保留最后一条终态 step（如"任务完成"），隐藏中间过程
                  const visibleSteps = isTerminal
                    ? msg.meta.steps.filter((s: any) => TERMINAL_STATES.has(s.state))
                    : msg.meta.steps;
                  if (visibleSteps.length === 0) return null;
                  return (
                    <div className="mt-1.5 ml-1 space-y-0.5">
                      {visibleSteps.map((step: any, idx: number) => {
                        const isLast = idx === visibleSteps.length - 1;
                        const isActive = isLast && msg.meta?.status && IN_PROGRESS_STATES.has(msg.meta.status);
                        const isFail = step.state === 'failed';
                        const isDone = step.state === 'completed';
                        return (
                          <div key={idx} className={cn(
                            "flex items-center gap-1.5 text-[11px] py-0.5 px-2 rounded-md transition-all",
                            isActive ? "text-blue-400 bg-blue-500/5" :
                            isFail ? "text-red-400/70" :
                            isDone ? "text-green-400/70" :
                            "text-slate-500"
                          )}>
                            {isActive ? <Loader2 size={10} className="animate-spin shrink-0" /> :
                             isFail ? <AlertCircle size={10} className="shrink-0" /> :
                             isDone ? <CheckCircle2 size={10} className="shrink-0" /> :
                             <CheckCircle2 size={10} className="shrink-0 opacity-50" />}
                            <span>{step.text}</span>
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}
              </div>
            </div>
          ))}

          {isTyping && (
            <div className="flex gap-4 max-w-3xl">
              <div className="w-8 h-8 shrink-0 rounded-full bg-blue-600 flex items-center justify-center mt-1 text-white">
                <Loader2 size={16} className="animate-spin" />
              </div>
              <div className="px-5 py-4 rounded-2xl bg-slate-900 border border-slate-800 text-slate-400 rounded-tl-sm flex items-center gap-2 shadow-sm">
                <span className="w-1.5 h-1.5 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "0ms" }}></span>
                <span className="w-1.5 h-1.5 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "150ms" }}></span>
                <span className="w-1.5 h-1.5 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "300ms" }}></span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} className="h-4" />
        </div>

        {/* Queue Bar — 排队消息堆叠在输入框上方 */}
        {localQueue.length > 0 && (
          <div className="px-4 pt-2 pb-0 bg-slate-950 shrink-0 border-t border-amber-500/20">
            <div className="max-w-4xl mx-auto space-y-1.5">
              <div className="flex items-center gap-1.5 px-1 mb-1">
                <Clock size={12} className="text-amber-400" />
                <span className="text-[10px] font-semibold text-amber-400 uppercase tracking-wider">
                  排队中 ({localQueue.length}条)
                </span>
              </div>
              {localQueue.map((item) => (
                <div key={item.taskId}
                  className="flex items-center gap-3 px-3 py-2 bg-amber-500/5 border border-amber-500/15 rounded-xl group transition-all"
                >
                  <span className="w-5 h-5 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-bold flex items-center justify-center shrink-0">
                    {item.position}
                  </span>
                  <span className="text-xs text-slate-300 truncate flex-1">{item.text}</span>
                  <span className="text-[10px] text-slate-500 shrink-0">{item.sender}</span>
                  <button
                    onClick={() => removeFromLocalQueue(item.taskId)}
                    className="p-1 text-slate-600 hover:text-red-400 hover:bg-red-500/10 rounded transition-all opacity-0 group-hover:opacity-100"
                    title="取消此消息"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Image Preview Bar — 选择的图片缩略图 */}
        {pendingImages.length > 0 && (
          <div className="px-4 pt-2 pb-0 bg-slate-950 shrink-0 border-t border-blue-500/20">
            <div className="max-w-4xl mx-auto flex items-center gap-2">
              <ImageIcon size={14} className="text-blue-400 shrink-0" />
              <div className="flex items-center gap-2 flex-1 overflow-x-auto">
                {pendingImages.map((img) => (
                  <div key={img.id} className="relative group shrink-0">
                    <img
                      src={img.previewUrl}
                      alt="预览"
                      className="w-16 h-16 rounded-lg object-cover border border-slate-700"
                    />
                    <button
                      onClick={() => removeImage(img.id)}
                      className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-red-500 text-white rounded-full flex items-center justify-center text-[10px] opacity-0 group-hover:opacity-100 transition-opacity shadow-md"
                    >
                      <X size={10} />
                    </button>
                  </div>
                ))}
              </div>
              <span className="text-[10px] text-slate-500 shrink-0">{pendingImages.length}/4</span>
            </div>
          </div>
        )}

        {/* Input Area */}
        <div className="p-4 bg-slate-950 shrink-0 border-t border-slate-800" onDrop={handleDrop} onDragOver={handleDragOver}>
          <div className="max-w-4xl mx-auto flex items-center gap-3">
            {/* Mode Switcher */}
            <div className="flex flex-col items-center gap-0.5 shrink-0">
              {(Object.keys(MODE_CONFIG) as ChatMode[]).map((mode) => {
                const conf = MODE_CONFIG[mode];
                const Icon = conf.icon;
                const isActive = chatMode === mode;
                return (
                  <button
                    key={mode}
                    onClick={() => setChatMode(mode)}
                    title={conf.label}
                    className={cn(
                      "w-8 h-8 rounded-lg flex items-center justify-center transition-all text-xs",
                      isActive
                        ? `${conf.color} bg-slate-800 shadow-sm ring-1 ring-slate-600`
                        : "text-slate-600 hover:text-slate-400 hover:bg-slate-900"
                    )}
                  >
                    <Icon size={15} />
                  </button>
                );
              })}
            </div>
            {/* Input + buttons */}
            <div className="relative flex-1 flex items-center">
              <input type="file" accept="image/*" multiple ref={fileInputRef} hidden onChange={handleFileSelect} />
              <input
                ref={inputRef}
                autoFocus
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSend()}
                onPaste={handlePaste}
                placeholder={isListening ? "正在聆听..." : (chatMode === "chat" || isConnected ? MODE_CONFIG[chatMode].placeholder : "等待 ROS2 系统连接...")}
                disabled={(chatMode !== "chat" && !isConnected) || isTyping || !!streamingMsgId}
                className="w-full bg-slate-900 border border-slate-700 rounded-2xl py-4 pl-6 pr-36 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
              />
              {/* Image upload button */}
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={!!streamingMsgId || pendingImages.length >= 4}
                title="上传图片 (也可粘贴或拖拽)"
                className="absolute right-24 w-10 h-10 rounded-xl flex items-center justify-center transition-all disabled:opacity-30 bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-blue-400"
              >
                <Paperclip size={18} />
              </button>
              {/* Voice input button — click to toggle */}
              {voiceSupported && (
                <button
                  onClick={() => { isListening ? stopListening() : startListening(); }}
                  disabled={!isConnected || isTyping}
                  title={isListening ? "点击结束语音" : "点击开始语音"}
                  className={cn(
                    "absolute right-14 w-9 h-9 rounded-xl flex items-center justify-center transition-all disabled:opacity-50",
                    isListening
                      ? "bg-red-500 text-white shadow-lg shadow-red-900/40 animate-pulse"
                      : "bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
                  )}
                >
                  <Mic size={16} />
                </button>
              )}
              <button
                onClick={handleSend}
                disabled={(!input.trim() && pendingImages.length === 0) || (chatMode !== "chat" && !isConnected && pendingImages.length === 0) || isTyping || !!streamingMsgId}
                className="absolute right-2 w-10 h-10 rounded-xl bg-blue-600 text-white flex items-center justify-center hover:bg-blue-500 transition-colors disabled:opacity-50 disabled:bg-slate-800 disabled:text-slate-500 shadow-md"
              >
                <Send size={18} className={cn((input.trim() || pendingImages.length > 0) ? "translate-x-0.5" : "")} />
              </button>
            </div>
            {/* User avatar + name */}
            {(() => {
              const name = getUsername();
              if (!name) return null;
              const { letter, color } = avatarFor(name);
              return (
                <div className="flex items-center gap-2 shrink-0 self-center">
                  <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center text-sm font-bold text-white shadow-md", color)}>
                    {letter}
                  </div>
                  <span className="text-sm text-slate-300 font-bold">{name}</span>
                </div>
              );
            })()}
          </div>
          <div className="text-center mt-2 text-xs text-slate-600 flex items-center justify-center gap-3">
            <span className={cn("flex items-center gap-1", MODE_CONFIG[chatMode].color)}>
              {(() => { const Icon = MODE_CONFIG[chatMode].icon; return <Icon size={11} />; })()}
              {MODE_CONFIG[chatMode].label}模式
            </span>
            <span className="text-slate-700">|</span>
            {isConnected ? <><div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></div> ROS2 Online</> : (chatMode === "chat" ? "ROS2 离线 (聊天可用)" : "等待 ROS2 连接...")}
          </div>
        </div>
      </div>

      {/* RIGHT: Active Task Panel */}
      <div className="w-64 xl:w-80 border-l border-slate-800 bg-slate-900/30 hidden xl:flex flex-col shrink-0">
        <div className="h-16 flex items-center px-5 border-b border-slate-800 shrink-0 bg-slate-950">
          <h2 className="font-medium text-sm text-slate-300">导航执行状态</h2>
        </div>
        
        <div className="p-5 flex-1 flex flex-col gap-6 overflow-y-auto">
          
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">执行阶段</span>
              <div className={cn(
                "flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold tracking-wide uppercase",
                !taskStatus ? "bg-slate-800 text-slate-500" :
                taskStatus.state === "completed" ? "bg-green-500/20 text-green-400" :
                taskStatus.state === "failed" ? "bg-red-500/20 text-red-400" :
                "bg-blue-500/20 text-blue-400"
              )}>
                {!taskStatus ? "IDLE" : taskStatus.state}
              </div>
            </div>
            
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">总进度</span>
                <span className="text-slate-300">{taskStatus?.progress ? (taskStatus.progress * 100).toFixed(0) : 0}%</span>
              </div>
              <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                <div 
                  className={cn(
                    "h-full rounded-full transition-all duration-500",
                    taskStatus?.state === "failed" ? "bg-red-500" :
                    taskStatus?.state === "completed" ? "bg-green-500" : "bg-blue-500 relative"
                  )}
                  style={{ width: `${taskStatus?.progress ? taskStatus.progress * 100 : 0}%` }}
                >
                  {taskStatus?.state !== "completed" && taskStatus?.state !== "failed" && taskStatus?.progress > 0 && (
                     <div className="absolute top-0 right-0 bottom-0 left-0 bg-white/20 animate-pulse"></div>
                  )}
                </div>
              </div>
            </div>

            {/* 右侧面板只显示状态标签，不显示聊天内容 */}
            {taskStatus?.state && taskStatus.state !== 'idle' && (
              <div className={cn(
                "mt-4 p-3 border rounded-lg flex items-start gap-2",
                taskStatus.state === "failed" ? "bg-red-500/10 border-red-500/20" :
                taskStatus.state === "completed" ? "bg-green-500/10 border-green-500/20" :
                "bg-blue-500/10 border-blue-500/20"
              )}>
                {taskStatus.state === "failed" ? (
                  <AlertCircle size={14} className="text-red-400 shrink-0 mt-0.5" />
                ) : taskStatus.state === "completed" ? (
                  <CheckCircle2 size={14} className="text-green-400 shrink-0 mt-0.5" />
                ) : (
                  <Activity size={14} className="text-blue-400 shrink-0 mt-0.5" />
                )}
                <p className={cn(
                  "text-xs leading-relaxed",
                  taskStatus.state === "failed" ? "text-red-400/90" :
                  taskStatus.state === "completed" ? "text-green-400/90" :
                  "text-blue-400/90"
                )}>{statusLabel(taskStatus.state, '')}</p>
              </div>
            )}
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
             <div className="flex items-center gap-2 mb-4">
               <MapPin size={16} className="text-slate-400" />
               <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">实时位姿</span>
             </div>
             
             <div className="grid grid-cols-2 gap-3">
               <div className="bg-slate-950 rounded-lg p-3 border border-slate-800/50">
                 <div className="text-[10px] text-slate-500 mb-1">X 坐标</div>
                 <div className="text-sm font-mono text-slate-300">{robotPose?.x.toFixed(2) || "0.00"}</div>
               </div>
               <div className="bg-slate-950 rounded-lg p-3 border border-slate-800/50">
                 <div className="text-[10px] text-slate-500 mb-1">Y 坐标</div>
                 <div className="text-sm font-mono text-slate-300">{robotPose?.y.toFixed(2) || "0.00"}</div>
               </div>
             </div>
          </div>
          
        </div>
      </div>

      {/* Lightbox — 图片放大预览 */}
      {lightboxUrl && (
        <div
          className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center cursor-pointer"
          onClick={() => setLightboxUrl(null)}
        >
          <button
            className="absolute top-4 right-4 w-10 h-10 rounded-full bg-white/10 text-white flex items-center justify-center hover:bg-white/20 transition-colors"
            onClick={() => setLightboxUrl(null)}
          >
            <X size={20} />
          </button>
          <img
            src={lightboxUrl}
            alt="放大预览"
            className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}

    </div>
  );
}
