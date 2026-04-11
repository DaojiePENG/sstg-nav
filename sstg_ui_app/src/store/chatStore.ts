import { create } from "zustand";
import { useRosStore } from "./rosStore";

export type MessageRole = "user" | "system" | "robot";

export interface StatusStep {
  state: string;
  text: string;
  timestamp: number;
}

export interface ImageAttachment {
  id: string;
  url: string;
  thumbnail?: string;
  width?: number;
  height?: number;
  alt?: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
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
  };
}

/** 本地队列项 —— 排队中的消息，尚未进入聊天区 */
export interface QueueItem {
  text: string;
  taskId: string;
  position: number;
  sender: string;
  timestamp: number;
}

export interface ChatSession {
  id: string;
  title: string;
  updatedAt: number;
}

export interface LLMConfig {
  baseUrl: string;
  apiKey: string;
  model: string;
  backupModel: string;
}

const DEFAULT_PROVIDERS: Record<string, LLMConfig> = {
  "DashScope (阿里云)": { baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", apiKey: "", model: "qwen-max", backupModel: "qwen-plus" },
  "DeepSeek (深度求索)": { baseUrl: "https://api.deepseek.com/v1", apiKey: "", model: "deepseek-chat", backupModel: "deepseek-coder" },
  "ZhipuAI (智谱清言)": { baseUrl: "https://open.bigmodel.cn/api/paas/v4", apiKey: "", model: "glm-4", backupModel: "glm-3-turbo" },
  "Ollama (本地私有化)": { baseUrl: "http://localhost:11434/v1", apiKey: "ollama", model: "llama3", backupModel: "qwen" },
  "OpenAI": { baseUrl: "https://api.openai.com/v1", apiKey: "", model: "gpt-4o", backupModel: "gpt-4-turbo" }
};

// ── LLM 配置：服务端持久化（所有浏览器共享） ──

async function fetchLLMConfig(): Promise<{ activeProvider: string; providers: Record<string, LLMConfig> }> {
  try {
    const res = await fetch("/api/llm-config");
    const data = await res.json();
    if (data.providers && Object.keys(data.providers).length > 0) return data;
  } catch {}
  return { activeProvider: "DashScope (阿里云)", providers: DEFAULT_PROVIDERS };
}

async function saveLLMConfigToServer(activeProvider: string, providers: Record<string, LLMConfig>) {
  try {
    await fetch("/api/llm-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ activeProvider, providers }),
    });
  } catch (err) {
    console.error("[chatStore] saveLLMConfig to server failed:", err);
  }
}

// ── Username ──

const USERNAME_KEY = "sstg_username";

export function getUsername(): string {
  return localStorage.getItem(USERNAME_KEY) || "";
}

export function setUsername(name: string) {
  localStorage.setItem(USERNAME_KEY, name);
}

// ── Chat State ──

interface ChatState {
  // Server-synced state
  sessions: ChatSession[];
  activeSessionId: string;
  messages: ChatMessage[];  // Messages for active session
  initialized: boolean;

  // Task owner tracking
  isTaskOwner: boolean;
  currentRobotMsgId: string | null;

  // Local message queue: messages waiting to be processed
  localQueue: QueueItem[];
  canceledTaskIds: Set<string>;  // tasks user canceled from queue (方案B: frontend-ignore)

  // Local UI state
  isTyping: boolean;

  // LLM Settings (browser-local)
  activeProvider: string;
  providers: Record<string, LLMConfig>;

  // Actions
  init: () => Promise<void>;
  createSession: () => Promise<void>;
  switchSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  addMessage: (msg: Pick<ChatMessage, "role" | "content" | "meta">) => Promise<ChatMessage | null>;
  updateLastRobotMessage: (meta: Partial<ChatMessage["meta"]>, newContent?: string) => void;
  finalizeLastRobotMessage: () => void;
  addToLocalQueue: (item: QueueItem) => void;
  removeFromLocalQueue: (taskId: string) => void;
  promoteFromQueue: (taskId: string) => void;
  decrementQueuePositions: () => void;
  setTyping: (typing: boolean) => void;

  setActiveProvider: (provider: string) => void;
  updateProviderConfig: (provider: string, config: Partial<LLMConfig>) => void;
  addProvider: (name: string, config: LLMConfig) => void;
  removeProvider: (name: string) => void;

  // SSE internal
  _applySSE: (event: any) => void;
}

let eventSource: EventSource | null = null;

async function fetchJSON(url: string, options?: RequestInit) {
  const res = await fetch(url, options);
  return res.json();
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: "",
  messages: [],
  initialized: false,
  isTaskOwner: false,
  currentRobotMsgId: null,
  localQueue: [],
  canceledTaskIds: new Set(),
  isTyping: false,

  activeProvider: "DashScope (阿里云)",
  providers: DEFAULT_PROVIDERS,

  // ── Init: 从服务端加载 + 启动 SSE ──

  init: async () => {
    if (get().initialized) return;

    try {
      // 并行加载会话列表 + LLM 配置
      const [data, llmConfig] = await Promise.all([
        fetchJSON("/api/chat/sessions"),
        fetchLLMConfig(),
      ]);
      const activeId = data.activeSessionId || (data.sessions[0]?.id ?? "");

      // 加载当前会话消息
      let msgs: ChatMessage[] = [];
      if (activeId) {
        const msgData = await fetchJSON(`/api/chat/sessions/${activeId}/messages`);
        msgs = msgData.messages || [];
      }

      set({
        sessions: data.sessions || [],
        activeSessionId: activeId,
        messages: msgs,
        activeProvider: llmConfig.activeProvider,
        providers: llmConfig.providers,
        initialized: true,
      });
    } catch (err) {
      console.error("[chatStore] init failed, creating default session:", err);
      set({ initialized: true, sessions: [], messages: [] });
    }

    // Connect SSE
    if (eventSource) { eventSource.close(); eventSource = null; }
    eventSource = new EventSource("/api/chat/events");
    eventSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        get()._applySSE(event);
      } catch {}
    };
    eventSource.onerror = () => {
      // EventSource auto-reconnects. On reconnect, refetch state.
      setTimeout(async () => {
        if (eventSource?.readyState === EventSource.OPEN) {
          try {
            const [data, llmConfig] = await Promise.all([
              fetchJSON("/api/chat/sessions"),
              fetchLLMConfig(),
            ]);
            const activeId = data.activeSessionId;
            let msgs: ChatMessage[] = [];
            if (activeId) {
              const msgData = await fetchJSON(`/api/chat/sessions/${activeId}/messages`);
              msgs = msgData.messages || [];
            }
            set({
              sessions: data.sessions || [],
              activeSessionId: activeId,
              messages: msgs,
              activeProvider: llmConfig.activeProvider,
              providers: llmConfig.providers,
            });
          } catch {}
        }
      }, 1000);
    };
  },

  // ── SSE event handler ──

  _applySSE: (event: any) => {
    const state = get();
    switch (event.type) {
      case "message_added": {
        if (event.sessionId === state.activeSessionId) {
          // Dedup: don't add if already exists (we added it optimistically)
          const exists = state.messages.some(m => m.id === event.message.id);
          if (!exists) {
            set({ messages: [...state.messages, event.message] });
          }
        }
        break;
      }
      case "message_updated": {
        if (event.sessionId === state.activeSessionId) {
          set({
            messages: state.messages.map(m =>
              m.id === event.messageId ? event.message : m
            ),
          });
        }
        break;
      }
      case "session_created": {
        const exists = state.sessions.some(s => s.id === event.session.id);
        if (!exists) {
          set({ sessions: [event.session, ...state.sessions] });
        }
        break;
      }
      case "session_switched": {
        if (event.activeSessionId !== state.activeSessionId) {
          // Load messages for the new active session
          fetchJSON(`/api/chat/sessions/${event.activeSessionId}/messages`)
            .then(data => {
              set({
                activeSessionId: event.activeSessionId,
                messages: data.messages || [],
              });
            })
            .catch(() => {
              set({ activeSessionId: event.activeSessionId, messages: [] });
            });
        }
        break;
      }
      case "session_deleted": {
        const newSessions = state.sessions.filter(s => s.id !== event.sessionId);
        const updates: Partial<ChatState> = { sessions: newSessions };
        if (state.activeSessionId === event.sessionId) {
          updates.activeSessionId = event.activeSessionId || newSessions[0]?.id || "";
          // Reload messages for new active session
          fetchJSON(`/api/chat/sessions/${updates.activeSessionId}/messages`)
            .then(data => set({ messages: data.messages || [] }))
            .catch(() => set({ messages: [] }));
        }
        set(updates);
        break;
      }
      case "session_renamed": {
        set({
          sessions: state.sessions.map(s =>
            s.id === event.sessionId ? { ...s, title: event.title } : s
          ),
        });
        break;
      }
      case "llm_config_updated": {
        if (event.config) {
          set({
            activeProvider: event.config.activeProvider,
            providers: event.config.providers,
          });
        }
        break;
      }
    }
  },

  // ── Session Actions ──

  createSession: async () => {
    try {
      const session = await fetchJSON("/api/chat/sessions", { method: "POST" });
      // SSE will broadcast the creation to all browsers
      // But switch locally immediately for responsiveness
      const msgData = await fetchJSON(`/api/chat/sessions/${session.id}/messages`);
      set(state => ({
        sessions: state.sessions.some(s => s.id === session.id)
          ? state.sessions
          : [session, ...state.sessions],
        activeSessionId: session.id,
        messages: msgData.messages || [],
      }));
    } catch (err) {
      console.error("[chatStore] createSession failed:", err);
    }
  },

  switchSession: async (id: string) => {
    try {
      await fetchJSON("/api/chat/sessions/active", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: id }),
      });
      const msgData = await fetchJSON(`/api/chat/sessions/${id}/messages`);
      set({ activeSessionId: id, messages: msgData.messages || [] });
    } catch (err) {
      console.error("[chatStore] switchSession failed:", err);
    }
  },

  deleteSession: async (id: string) => {
    // Notify ROS backend too
    useRosStore.getState().deleteChatSession(id);

    try {
      await fetchJSON(`/api/chat/sessions/${id}`, { method: "DELETE" });
      // SSE will handle state update
    } catch (err) {
      console.error("[chatStore] deleteSession failed:", err);
    }
  },

  renameSession: async (id: string, title: string) => {
    // Optimistic update
    set(state => ({
      sessions: state.sessions.map(s => s.id === id ? { ...s, title } : s),
    }));
    try {
      await fetchJSON(`/api/chat/sessions/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
    } catch (err) {
      console.error("[chatStore] renameSession failed:", err);
    }
  },

  // ── Message Actions ──

  addMessage: async (msg) => {
    const state = get();
    const sid = state.activeSessionId;
    if (!sid) return null;

    try {
      const newMsg = await fetchJSON(`/api/chat/sessions/${sid}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role: msg.role,
          content: msg.content,
          sender: msg.role === "user" ? getUsername() : undefined,
          meta: msg.meta,
        }),
      });

      // Optimistically add (SSE will dedup)
      set(state => ({
        messages: state.messages.some(m => m.id === newMsg.id)
          ? state.messages
          : [...state.messages, newMsg],
      }));

      // Track robot message for task owner updates
      if (msg.role === "robot") {
        set({ isTaskOwner: true, currentRobotMsgId: newMsg.id });
      }

      return newMsg;
    } catch (err) {
      console.error("[chatStore] addMessage failed:", err);
      return null;
    }
  },

  updateLastRobotMessage: (metaUpdates, newContent) => {
    const state = get();

    // Only the task owner pushes updates to the server
    if (!state.isTaskOwner || !state.currentRobotMsgId) return;

    const msgId = state.currentRobotMsgId;
    const sid = state.activeSessionId;

    // Fire-and-forget server update (SSE will broadcast the result)
    fetch(`/api/chat/messages/${msgId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sessionId: sid,
        meta: metaUpdates,
        content: newContent,
      }),
    }).catch(err => {
      console.error("[chatStore] updateLastRobotMessage failed:", err);
    });
  },

  finalizeLastRobotMessage: () => {
    const state = get();
    if (!state.isTaskOwner || !state.currentRobotMsgId) return;

    const msgId = state.currentRobotMsgId;
    const sid = state.activeSessionId;

    // Check if the current robot message is in progress
    const msg = state.messages.find(m => m.id === msgId);
    const IN_PROGRESS = new Set(['understanding', 'planning', 'navigating', 'exploring', 'searching', 'checking']);
    if (msg?.meta?.status && IN_PROGRESS.has(msg.meta.status)) {
      fetch(`/api/chat/messages/${msgId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: sid,
          meta: { status: "completed" },
        }),
      }).catch(() => {});
    }

    // Clear task ownership
    set({ isTaskOwner: false, currentRobotMsgId: null });
  },

  // ── Local Queue Management ──

  addToLocalQueue: (item: QueueItem) => {
    set(state => ({ localQueue: [...state.localQueue, item] }));
  },

  removeFromLocalQueue: (taskId: string) => {
    set(state => ({
      localQueue: state.localQueue.filter(q => q.taskId !== taskId),
      canceledTaskIds: new Set([...state.canceledTaskIds, taskId]),
    }));
  },

  promoteFromQueue: (taskId: string) => {
    // Move a queued message into the chat area: remove from localQueue
    set(state => ({
      localQueue: state.localQueue.filter(q => q.taskId !== taskId),
    }));
  },

  decrementQueuePositions: () => {
    if (get().localQueue.length === 0) return;  // no-op when empty — avoids new ref
    set(state => ({
      localQueue: state.localQueue.map((q, i) => ({ ...q, position: i + 1 })),
    }));
  },

  setTyping: (typing) => set({ isTyping: typing }),

  // ── LLM Config (服务端持久化 + SSE 多端同步) ──

  setActiveProvider: (provider) => {
    set({ activeProvider: provider });
    saveLLMConfigToServer(provider, get().providers);
  },

  updateProviderConfig: (provider, config) => {
    set(state => {
      const newProviders = {
        ...state.providers,
        [provider]: { ...state.providers[provider], ...config },
      };
      saveLLMConfigToServer(state.activeProvider, newProviders);
      return { providers: newProviders };
    });
  },

  addProvider: (name, config) => {
    set(state => {
      const newProviders = { ...state.providers, [name]: config };
      saveLLMConfigToServer(state.activeProvider, newProviders);
      return { providers: newProviders };
    });
  },

  removeProvider: (name) => {
    set(state => {
      const { [name]: _, ...rest } = state.providers;
      const newActive = state.activeProvider === name
        ? Object.keys(rest)[0] || ""
        : state.activeProvider;
      saveLLMConfigToServer(newActive, rest);
      return { providers: rest, activeProvider: newActive };
    });
  },
}));
