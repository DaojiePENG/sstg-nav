import { useEffect, useState, useRef, useCallback } from "react";
import { useRosStore } from "./store/rosStore";
import { useChatStore, getUsername } from "./store/chatStore";
import { BrowserRouter, Routes, Route, Link, useLocation, useNavigate } from "react-router-dom";
import { Map as MapIcon, MessageSquare, Activity, Power, Lock, LogOut, BookOpen, HelpCircle } from "lucide-react";
import { cn } from "./lib/utils";
import ChatView from "./components/ChatView";
import MapView from "./components/MapView";
import RobotView from "./components/RobotView";
import ArchitectureView from "./components/ArchitectureView";
import GuideView from "./components/GuideView";
import UsernameModal from "./components/UsernameModal";
import appLogo from "./assets/LOGO.png";
import FloatingPiPManager from "./components/vision/FloatingPiPManager";

/* ── 访问密钥门禁 ── */
const ACCESS_KEY = "sstg2026";   // 共享密钥，改这里即可
const AUTH_STORAGE_KEY = "sstg_auth";

function AuthGate({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState(() => localStorage.getItem(AUTH_STORAGE_KEY) === ACCESS_KEY);
  const [input, setInput] = useState("");
  const [error, setError] = useState(false);

  if (authed) return <>{children}</>;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() === ACCESS_KEY) {
      localStorage.setItem(AUTH_STORAGE_KEY, ACCESS_KEY);
      setAuthed(true);
    } else {
      setError(true);
      setTimeout(() => setError(false), 1500);
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-950 flex items-center justify-center z-[9999]">
      <form onSubmit={handleSubmit} className="bg-slate-900 border border-slate-700 rounded-2xl p-8 w-80 shadow-2xl flex flex-col items-center gap-5">
        <div className="w-14 h-14 rounded-full bg-blue-600/20 flex items-center justify-center">
          <Lock size={28} className="text-blue-400" />
        </div>
        <div className="text-center">
          <h2 className="text-lg font-semibold text-slate-100">SSTG-Nav</h2>
          <p className="text-sm text-slate-400 mt-1">请输入访问密钥</p>
        </div>
        <input
          type="password"
          value={input}
          onChange={e => { setInput(e.target.value); setError(false); }}
          placeholder="Access Key"
          autoFocus
          className={cn(
            "w-full px-4 py-2.5 rounded-lg bg-slate-800 border text-slate-100 text-center tracking-widest placeholder:text-slate-500 outline-none transition-colors",
            error ? "border-red-500 shake" : "border-slate-600 focus:border-blue-500"
          )}
        />
        {error && <p className="text-red-400 text-sm -mt-2">密钥错误</p>}
        <button type="submit" className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors">
          进入系统
        </button>
      </form>
      <style>{`@keyframes shake{0%,100%{transform:translateX(0)}20%,60%{transform:translateX(-6px)}40%,80%{transform:translateX(6px)}}.shake{animation:shake .4s ease-in-out}`}</style>
    </div>
  );
}

/** 退出登录按钮（放在侧边栏底部） */
function LogoutButton() {
  return (
    <button
      onClick={() => { localStorage.removeItem(AUTH_STORAGE_KEY); location.reload(); }}
      title="退出登录"
      className="w-10 h-10 rounded-xl flex items-center justify-center text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors border border-transparent hover:border-slate-700"
    >
      <LogOut size={18} />
    </button>
  );
}

function SidebarLink({ to, icon: Icon }: { to: string, icon: any }) {
  const location = useLocation();
  const isActive = location.pathname === to;
  
  return (
    <Link 
      to={to} 
      className={cn(
        "p-3 rounded-xl transition-all duration-200 relative group",
        isActive ? "bg-blue-600 text-white shadow-md shadow-blue-900/20" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
      )}
    >
      <Icon size={24} strokeWidth={isActive ? 2.5 : 2} />
      {isActive && (
        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-white rounded-r-full"></span>
      )}
    </Link>
  );
}

function AppLayout({ children }: { children: React.ReactNode }) {
  const isConnected = useRosStore((state) => state.isConnected);
  const connect = useRosStore((state) => state.connect);
  const launchMode = useRosStore((state) => state.launchMode);
  const updateLLMConfig = useRosStore((state) => state.updateLLMConfig);
  const initChat = useChatStore((state) => state.init);
  const navigate = useNavigate();

  const [backendState, setBackendState] = useState<"off" | "starting" | "running" | "stopping">("off");
  const startedByButton = useRef(false);
  const autoInitDone = useRef(false);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isLongPress = useRef(false);

  useEffect(() => {
    connect();  // 自动检测：本地 → ws://localhost:9090，公网 → wss://域名/rosbridge
    initChat(); // 初始化共享聊天（从服务端加载 + SSE 连接）
    // 检查后端是否已在运行
    fetch("/api/system/backend-status").then(r => r.json()).then(d => {
      if (d.running) setBackendState("running");
    }).catch(() => {});
  }, [connect, initChat]);

  // 连接成功后自动推送 LLM 配置 + 启动硬件
  useEffect(() => {
    if (!isConnected || autoInitDone.current) return;
    autoInitDone.current = true;

    // 推送 LLM 配置
    const chatState = useChatStore.getState();
    const config = chatState.providers[chatState.activeProvider];
    if (config?.apiKey) {
      updateLLMConfig(config.baseUrl, config.apiKey, config.model)
        .then(() => console.log("[App] LLM config synced to backend:", chatState.activeProvider, config.model))
        .catch((err) => console.warn("[App] LLM config sync failed (will retry on next connect):", err));
    }

    // 如果是通过电源按钮启动的，自动启动导航模式
    if (startedByButton.current) {
      startedByButton.current = false;
      setTimeout(() => {
        launchMode("navigation").catch(() => {});
      }, 2000);
    }

    setBackendState("running");
  }, [isConnected, launchMode, updateLLMConfig]);

  // 连接断开时重置
  useEffect(() => {
    if (!isConnected) {
      autoInitDone.current = false;
    }
  }, [isConnected]);

  // ── 长按检测：2 秒长按 = 强制清杀 ──
  const handlePointerDown = useCallback(() => {
    isLongPress.current = false;
    longPressTimer.current = setTimeout(async () => {
      isLongPress.current = true;
      // 第三层：长按触发一键清杀
      console.log("[Power] Long press → force cleanup");
      navigate("/robot");
      setBackendState("stopping");
      try {
        await fetch("/api/system/force-cleanup", { method: "POST" });
      } catch {}
      setBackendState("off");
    }, 2000);
  }, [navigate]);

  const handlePointerUp = useCallback(() => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
  }, []);

  const handlePowerToggle = useCallback(async () => {
    // 长按触发的不响应短按
    if (isLongPress.current) { isLongPress.current = false; return; }
    if (backendState === "starting" || backendState === "stopping") return;

    // 跳转到系统控制中心，方便查看启动/关闭情况
    navigate("/robot");

    if (backendState === "running" || isConnected) {
      // 停止（优雅关闭链）
      setBackendState("stopping");
      try { await fetch("/api/system/stop-backend", { method: "POST" }); } catch {}
      setBackendState("off");
      return;
    }

    // 启动
    setBackendState("starting");
    startedByButton.current = true;
    try {
      const res = await fetch("/api/system/start-backend", { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (res.status === 409) { setBackendState("running"); return; }
        console.error("Failed to start backend:", data);
        setBackendState("off");
        return;
      }
      // 等待 rosbridge 连接（connect 会自动重试）
      connect();
    } catch (e) {
      console.error("Failed to start backend:", e);
      setBackendState("off");
    }
  }, [backendState, isConnected, connect, navigate]);

  return (
    <div className="flex h-screen w-full bg-slate-900 text-slate-100 font-sans overflow-hidden">
      <aside className="w-[72px] flex flex-col items-center py-5 bg-slate-950 border-r border-slate-800 z-50">
        <div className="w-12 h-12 rounded-xl overflow-hidden mb-8 shadow-sm ring-1 ring-slate-700/60 bg-slate-900">
          <img
            src={appLogo}
            alt="SSTG logo"
            className="w-full h-full object-cover object-center scale-110"
          />
        </div>
        <div className="flex flex-col gap-4">
          <SidebarLink to="/" icon={MessageSquare} />
          <SidebarLink to="/map" icon={MapIcon} />
          <SidebarLink to="/robot" icon={Activity} />
          <SidebarLink to="/guide" icon={HelpCircle} />
          <SidebarLink to="/arch" icon={BookOpen} />
        </div>
        <div className="mt-auto mb-2 flex flex-col items-center gap-3">
          {/* 电源按钮：短按=正常开关，长按2s=强制清杀 */}
          <button
            onClick={handlePowerToggle}
            onPointerDown={handlePointerDown}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
            title={
              backendState === "running" ? "短按停止 / 长按2s强制清杀"
              : backendState === "starting" ? "启动中..."
              : backendState === "stopping" ? "正在停止..."
              : "短按启动 / 长按2s清理残留"
            }
            className={cn(
              "w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-300 border select-none",
              backendState === "running"
                ? "bg-green-600/20 border-green-500/50 text-green-400 hover:bg-red-600/20 hover:border-red-500/50 hover:text-red-400"
                : backendState === "starting"
                ? "bg-amber-600/20 border-amber-500/50 text-amber-400 animate-pulse cursor-wait"
                : backendState === "stopping"
                ? "bg-red-600/20 border-red-500/50 text-red-400 animate-pulse cursor-wait"
                : "bg-slate-800 border-slate-700 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
            )}
          >
            <Power size={20} />
          </button>
          {/* 退出登录 */}
          <LogoutButton />
          {/* 连接状态 */}
          <div className={cn(
            "w-3.5 h-3.5 rounded-full transition-all duration-500",
            isConnected ? "bg-green-500 shadow-[0_0_12px_rgba(34,197,94,0.6)]" : "bg-red-500 shadow-[0_0_12px_rgba(239,68,68,0.4)]"
          )} title={isConnected ? "ROS2 Connected" : "Disconnected"} />
        </div>
      </aside>
      <main className="flex-1 relative flex flex-col min-w-0 bg-slate-900">
        {children}
      </main>
    </div>
  );
}

function App() {
  const [hasUsername, setHasUsername] = useState(() => !!getUsername());

  return (
    <AuthGate>
      {!hasUsername && <UsernameModal onDone={() => setHasUsername(true)} />}
      <BrowserRouter>
        <AppLayout>
          <Routes>
            <Route path="/" element={<ChatView />} />
            <Route path="/map" element={<MapView />} />
            <Route path="/robot" element={<RobotView />} />
            <Route path="/guide" element={<GuideView />} />
            <Route path="/arch" element={<ArchitectureView />} />
          </Routes>
        </AppLayout>
      </BrowserRouter>
      {/* PiP 浮动窗口 — Portal 到 body，不受路由切换影响 */}
      <FloatingPiPManager />
    </AuthGate>
  );
}

export default App;
