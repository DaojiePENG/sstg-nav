import { useState, useEffect, useRef } from "react";
import {
  Play, Square, Compass, Search, Cpu, HardDrive, Wifi, WifiOff,
  Activity, MemoryStick, Server, Terminal, CheckCircle2, XCircle,
  Loader2, AlertTriangle, Radio, ChevronDown, ChevronUp,
} from "lucide-react";
import { useRosStore } from "../store/rosStore";
import { cn } from "../lib/utils";

const MODE_CONFIG = {
  idle: { label: "空闲", color: "slate", icon: Square },
  exploration: { label: "探索模式", color: "amber", icon: Search },
  navigation: { label: "导航模式", color: "blue", icon: Compass },
} as const;

export default function RobotView() {
  const {
    isConnected,
    systemStatus,
    systemLogs,
    launchMode,
    getSystemStatus,
  } = useRosStore();

  const [launching, setLaunching] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [showNodes, setShowNodes] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  // 进入页面时拉一次完整状态，展开节点时定时刷新
  useEffect(() => {
    if (isConnected) {
      getSystemStatus().catch(() => {});
    }
  }, [isConnected, getSystemStatus]);

  useEffect(() => {
    if (!isConnected || !showNodes) return;
    getSystemStatus().catch(() => {});
    const interval = setInterval(() => {
      getSystemStatus().catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, [isConnected, showNodes, getSystemStatus]);

  // 日志自动滚动
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [systemLogs]);

  const handleLaunch = async (mode: string) => {
    setLaunching(mode);
    setActionMsg(null);
    try {
      const res = await launchMode(mode);
      if (res.success) {
        setActionMsg({ type: "ok", text: res.message });
      } else {
        setActionMsg({ type: "err", text: res.message });
      }
    } catch (err) {
      setActionMsg({ type: "err", text: String(err) });
    } finally {
      setLaunching(null);
      // 刷新状态
      setTimeout(() => getSystemStatus().catch(() => {}), 1500);
    }
  };

  const currentMode = systemStatus?.mode || "idle";
  const modeInfo = MODE_CONFIG[currentMode as keyof typeof MODE_CONFIG] || MODE_CONFIG.idle;

  return (
    <div className="flex h-full w-full bg-slate-950 text-slate-200 overflow-hidden">
      <div className="flex-1 overflow-y-auto p-6 max-w-5xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-blue-600/20 flex items-center justify-center text-blue-500 shadow-lg shadow-blue-900/20">
            <Radio size={28} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-100 tracking-wide">
              机器人控制中心
            </h1>
            <p className="text-xs text-slate-500">
              硬件管理 / 系统监控 / 模式切换
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div className={cn(
              "w-2.5 h-2.5 rounded-full",
              isConnected ? "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]" : "bg-red-500"
            )} />
            <span className="text-xs text-slate-400 font-mono">
              {isConnected ? "ROS2 ONLINE" : "DISCONNECTED"}
            </span>
          </div>
        </div>

        {/* ── 运行模式切换 ── */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Activity size={16} className="text-blue-400" />
            运行模式
          </h2>

          <div className="flex gap-3 mb-4">
            {(["exploration", "navigation"] as const).map(mode => {
              const cfg = MODE_CONFIG[mode];
              const Icon = cfg.icon;
              const isActive = currentMode === mode;
              const isLoading = launching === mode;
              return (
                <button
                  key={mode}
                  disabled={!isConnected || launching !== null}
                  onClick={() => handleLaunch(mode)}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-medium transition-all border",
                    isActive
                      ? `bg-${cfg.color}-500/20 border-${cfg.color}-500/40 text-${cfg.color}-400 shadow-lg`
                      : "bg-slate-950 border-slate-800 text-slate-400 hover:bg-slate-800 hover:border-slate-700",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  style={isActive ? {
                    backgroundColor: mode === 'exploration' ? 'rgba(245,158,11,0.15)' : 'rgba(59,130,246,0.15)',
                    borderColor: mode === 'exploration' ? 'rgba(245,158,11,0.4)' : 'rgba(59,130,246,0.4)',
                    color: mode === 'exploration' ? '#f59e0b' : '#3b82f6',
                  } : undefined}
                >
                  {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Icon size={16} />}
                  {cfg.label}
                </button>
              );
            })}

            <button
              disabled={!isConnected || launching !== null || currentMode === 'idle'}
              onClick={() => handleLaunch('stop')}
              className="px-6 py-3 rounded-xl text-sm font-medium bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {launching === 'stop' ? <Loader2 size={16} className="animate-spin" /> : <Square size={16} />}
              <span className="ml-2">停止</span>
            </button>
          </div>

          {/* 状态指示 */}
          <div className="flex items-center gap-3 px-1">
            <span className="text-xs text-slate-500">当前:</span>
            <span className={cn(
              "text-xs font-bold uppercase tracking-wider px-2.5 py-1 rounded-md",
              currentMode === 'idle' ? "bg-slate-800 text-slate-500" :
              currentMode === 'exploration' ? "bg-amber-500/20 text-amber-400" :
              "bg-blue-500/20 text-blue-400"
            )}>
              {modeInfo.label}
            </span>
          </div>

          {actionMsg && (
            <div className={cn(
              "mt-3 px-4 py-2.5 rounded-lg text-xs flex items-center gap-2 border",
              actionMsg.type === "ok"
                ? "bg-green-500/10 border-green-500/20 text-green-400"
                : "bg-red-500/10 border-red-500/20 text-red-400"
            )}>
              {actionMsg.type === "ok" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
              {actionMsg.text}
            </div>
          )}
        </section>

        {/* ── 硬件设备 ── */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <HardDrive size={16} className="text-blue-400" />
            硬件设备
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {(systemStatus?.devices || [
              { name: "底盘 CH340", path: "/dev/ttyUSB1", ok: false },
              { name: "雷达 RPLidar S2", path: "/dev/rplidar", ok: false },
              { name: "相机 Gemini 336L", path: "/dev/Gemini_336L", ok: false },
            ]).map((dev, i) => (
              <div key={i} className={cn(
                "flex items-center gap-3 p-3.5 rounded-xl border transition-all",
                dev.ok
                  ? "bg-green-500/5 border-green-500/20"
                  : "bg-red-500/5 border-red-500/20"
              )}>
                <div className={cn(
                  "w-2.5 h-2.5 rounded-full shrink-0",
                  dev.ok
                    ? "bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]"
                    : "bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.4)]"
                )} />
                <div className="min-w-0">
                  <div className="text-xs font-medium text-slate-300 truncate">{dev.name}</div>
                  <div className="text-[10px] font-mono text-slate-500 truncate">{dev.path}</div>
                </div>
                <div className="ml-auto shrink-0">
                  {dev.ok
                    ? <CheckCircle2 size={14} className="text-green-500" />
                    : <XCircle size={14} className="text-red-500" />}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ── 系统资源 ── */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Cpu size={16} className="text-blue-400" />
            系统资源
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {/* CPU */}
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase">CPU</span>
                <span className="text-sm font-mono text-slate-300">
                  {systemStatus ? `${systemStatus.cpu.toFixed(0)}%` : '--'}
                </span>
              </div>
              <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-700",
                    (systemStatus?.cpu ?? 0) > 80 ? "bg-red-500" :
                    (systemStatus?.cpu ?? 0) > 60 ? "bg-amber-500" : "bg-blue-500"
                  )}
                  style={{ width: `${systemStatus?.cpu ?? 0}%` }}
                />
              </div>
            </div>

            {/* Memory */}
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase">RAM</span>
                <span className="text-sm font-mono text-slate-300">
                  {systemStatus ? `${systemStatus.memory.toFixed(0)}%` : '--'}
                </span>
              </div>
              <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-700",
                    (systemStatus?.memory ?? 0) > 80 ? "bg-red-500" :
                    (systemStatus?.memory ?? 0) > 60 ? "bg-amber-500" : "bg-emerald-500"
                  )}
                  style={{ width: `${systemStatus?.memory ?? 0}%` }}
                />
              </div>
            </div>

            {/* Node Count */}
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase">NODES</span>
                <span className="text-sm font-mono text-slate-300">
                  {systemStatus?.nodeCount ?? '--'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                  <Server size={12} className="text-slate-600" />
                  <span className="text-[10px] text-slate-500">活跃 ROS2 节点</span>
                </div>
                <button
                  onClick={() => setShowNodes(v => !v)}
                  className="flex items-center gap-0.5 text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
                >
                  {showNodes ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  {showNodes ? '收起' : '展开'}
                </button>
              </div>
            </div>
          </div>

          {/* 展开的节点列表 */}
          {showNodes && (
            <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
              {(systemStatus?.activeNodes || []).length > 0 ? (
                systemStatus!.activeNodes.map((node, i) => (
                  <div key={i} className="flex items-center gap-2 px-3 py-2 bg-slate-950 rounded-lg border border-slate-800/50 text-[11px] font-mono text-slate-400 truncate">
                    <CheckCircle2 size={10} className="text-green-500 shrink-0" />
                    {node.replace(/^\//, '')}
                  </div>
                ))
              ) : (
                <div className="col-span-full text-center text-[11px] text-slate-600 py-3">
                  {isConnected ? '加载中...' : '未连接'}
                </div>
              )}
            </div>
          )}
        </section>

        {/* ── 系统日志 ── */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Terminal size={16} className="text-blue-400" />
            系统日志
          </h2>
          <div className="bg-slate-950 rounded-xl border border-slate-800/50 p-3 h-52 overflow-y-auto font-mono text-[11px] leading-relaxed text-slate-400 space-y-0.5">
            {systemLogs.length === 0 ? (
              <div className="flex items-center justify-center h-full text-slate-600 text-xs">
                {isConnected ? "等待日志..." : "未连接 ROS2"}
              </div>
            ) : (
              systemLogs.map((log, i) => {
                const isErr = /error|fail|exception/i.test(log);
                const isWarn = /warn|timeout/i.test(log);
                return (
                  <div key={i} className={cn(
                    "px-2 py-0.5 rounded",
                    isErr ? "text-red-400 bg-red-500/5" :
                    isWarn ? "text-amber-400 bg-amber-500/5" : ""
                  )}>
                    {log}
                  </div>
                );
              })
            )}
            <div ref={logEndRef} />
          </div>
        </section>

      </div>
    </div>
  );
}
