import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from "react";
import ReactDOM from "react-dom";
import {
  Play, Square, Cpu, Wifi,
  Server, Terminal, CheckCircle2, XCircle,
  Loader2, AlertTriangle, Radio, ChevronDown, ChevronUp,
  Brain, Navigation, Package, RefreshCw, Power,
  Camera, Radar, Box, Layers, Gamepad2,
} from "lucide-react";
import { useRosStore } from "../store/rosStore";
import { useVisionStore } from "../store/visionStore";
import { cn } from "../lib/utils";

// ── 节点注册表 ─────────────────────────────────────────────

interface NodeDef {
  label: string;
  desc: string;
}

interface GroupDef {
  label: string;
  icon: React.ElementType;
  color: string;
  restartable: boolean; // 该组节点是否可逐个重启
  nodes: Record<string, NodeDef>;
}

// 导航栈：原"硬件驱动"+ "Nav2"合并为一组（由同一个 launch 文件管理）
const NODE_REGISTRY: Record<string, GroupDef> = {
  navstack: {
    label: "导航栈",
    icon: Navigation,
    color: "violet",
    restartable: false,
    nodes: {
      // 硬件驱动
      "driver_node":           { label: "麦克纳姆轮驱动", desc: "X3 底盘电机控制和运动学解算" },
      "base_node":             { label: "底盘通信",       desc: "CH340 串口数据收发" },
      "sllidar_node":          { label: "RPLidar S2",     desc: "360° 激光雷达扫描" },
      "camera/camera":         { label: "Gemini 336L",    desc: "RGB-D 深度相机" },
      "robot_state_publisher": { label: "TF 发布",        desc: "URDF → TF 坐标系广播" },
      "joint_state_publisher": { label: "关节状态",       desc: "关节角度发布" },
      // SLAM + 定位
      "amcl":                         { label: "AMCL 定位",     desc: "自适应蒙特卡洛粒子滤波定位" },
      "map_server":                   { label: "地图服务",       desc: "栅格地图加载和分发" },
      // Nav2
      "planner_server":               { label: "全局规划器",     desc: "A*/NavFn 全局路径规划" },
      "controller_server":            { label: "局部控制器",     desc: "DWB/MPPI 局部轨迹跟踪" },
      "bt_navigator":                 { label: "行为树导航",     desc: "BT XML 任务状态机" },
      "behavior_server":              { label: "恢复行为",       desc: "Spin/BackUp/Wait 恢复策略" },
      "lifecycle_manager_map":        { label: "地图生命周期",   desc: "map_server + amcl 生命周期管理" },
      "lifecycle_manager_navigation": { label: "导航生命周期",   desc: "Nav2 节点统一启停管理" },
      // 传感器融合
      "ekf_filter_node":             { label: "EKF 融合",       desc: "IMU + 里程计扩展卡尔曼融合" },
      "imu_filter_madgwick":         { label: "IMU 滤波",       desc: "Madgwick 姿态估计算法" },
      // 拓扑
      "topo_node_viz":               { label: "拓扑可视化",     desc: "RViz 拓扑节点 Marker 发布" },
    },
  },
  sstg: {
    label: "SSTG 核心",
    icon: Brain,
    color: "blue",
    restartable: true,
    nodes: {
      "interaction_manager_node":  { label: "任务编排",     desc: "自然语言 → NLP → 规划 → 执行全链路协调" },
      "map_manager_node":          { label: "拓扑地图",     desc: "语义拓扑图管理、节点查询、Web API" },
      "nlp_node":                  { label: "自然语言处理", desc: "意图识别、LLM 集成、多语言理解" },
      "planning_node":             { label: "语义路径规划", desc: "拓扑路径搜索、候选点生成" },
      "executor_node":             { label: "导航执行器",   desc: "Nav2 目标下发、执行状态反馈" },
      "perception_node":           { label: "视觉感知",     desc: "RGB-D 物体检测、场景理解" },
      "exploration_action_server": { label: "RRT 探索",     desc: "前沿点探测、自主环境探索" },
      "webrtc_camera_bridge":      { label: "WebRTC 桥",    desc: "相机画面 WebRTC 推流到浏览器" },
    },
  },
};

// 基础设施节点（常驻，不参与重启，UI 监控依赖）
const INFRA_NODES: Record<string, { label: string; desc: string }> = {
  "rosbridge_websocket": { label: "WebSocket 桥",  desc: "ROS2 ↔ 浏览器通信通道" },
  "system_manager_node": { label: "系统管理器",    desc: "设备检测、进程管理、状态发布" },
};

// 所有注册表节点名 + 基础设施节点（用于"其他"节点过滤）
const ALL_REGISTERED_NODES = new Set([
  ...Object.values(NODE_REGISTRY).flatMap(g => Object.keys(g.nodes)),
  ...Object.keys(INFRA_NODES),
]);

// ── 辅助：统计节点状态 ─────────────────────────────────────

function computeNodeStats(activeNodes: string[]) {
  const countMap: Record<string, number> = {};
  for (const raw of activeNodes) {
    const name = raw.replace(/^\//, "");
    countMap[name] = (countMap[name] || 0) + 1;
  }
  return countMap;
}

// ── Tooltip 组件 ────────────────────────────────────────────

function NodeTooltip({
  nodeName, def, count, isOnline, restartable, onRestart, anchorRef,
}: {
  nodeName: string;
  def: NodeDef | null;
  count: number;
  isOnline: boolean;
  restartable: boolean;
  onRestart?: (killDuplicates: boolean) => void;
  anchorRef: React.RefObject<HTMLDivElement | null>;
}) {
  const isDuplicate = count > 1;
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  useLayoutEffect(() => {
    if (anchorRef.current && tooltipRef.current) {
      const rect = anchorRef.current.getBoundingClientRect();
      const top = rect.bottom + 6;
      const left = Math.max(8, Math.min(rect.left + rect.width / 2 - 128, window.innerWidth - 272));
      tooltipRef.current.style.top = `${top}px`;
      tooltipRef.current.style.left = `${left}px`;
      setReady(true);
    }
  }, [anchorRef]);

  return ReactDOM.createPortal(
    <div
      ref={tooltipRef}
      className="fixed z-[9999] w-64 p-3 bg-slate-800 border border-slate-700 rounded-xl shadow-2xl text-left pointer-events-auto transition-opacity duration-100"
      style={{ top: -9999, left: -9999, opacity: ready ? 1 : 0 }}
      onClick={e => e.stopPropagation()}
      onMouseEnter={e => e.stopPropagation()}
    >
      <div className="text-xs font-mono text-slate-300 font-semibold mb-1">
        /{nodeName}
        {isDuplicate && <span className="ml-1.5 text-amber-400 font-bold">×{count}</span>}
      </div>
      {def && (
        <>
          <div className="text-[11px] text-blue-400 mb-1">{def.label}</div>
          <div className="text-[11px] text-slate-400 leading-relaxed">{def.desc}</div>
        </>
      )}
      <div className="mt-2 pt-2 border-t border-slate-700/50 flex items-center gap-2 text-[10px]">
        <span className={isOnline ? "text-green-400" : "text-red-400"}>
          {isOnline ? "● 运行中" : "● 未启动"}
        </span>
      </div>
      {restartable && onRestart && (
        <button
          onClick={() => onRestart(isDuplicate)}
          className={cn(
            "mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors",
            isOnline
              ? "bg-blue-500/15 border border-blue-500/30 text-blue-400 hover:bg-blue-500/25"
              : "bg-green-500/15 border border-green-500/30 text-green-400 hover:bg-green-500/25"
          )}
        >
          {isOnline ? <RefreshCw size={11} /> : <Play size={11} />}
          {isDuplicate ? "全部重启为 1 个" : isOnline ? "重启节点" : "启动节点"}
        </button>
      )}
    </div>,
    document.body
  );
}

function NodeItem({
  nodeName, def, count, restartable, onRestart, isRestarting,
}: {
  nodeName: string;
  def: NodeDef | null;
  count: number;
  restartable: boolean;
  onRestart?: (killDuplicates: boolean) => void;
  isRestarting?: boolean;
}) {
  const [showTip, setShowTip] = useState(false);
  const isOnline = count > 0;
  const isDuplicate = count > 1;
  const tipTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const anchorRef = useRef<HTMLDivElement>(null);

  const handleEnter = () => {
    clearTimeout(tipTimerRef.current);
    tipTimerRef.current = setTimeout(() => setShowTip(true), 300);
  };
  const handleLeave = () => {
    clearTimeout(tipTimerRef.current);
    tipTimerRef.current = setTimeout(() => setShowTip(false), 200);
  };

  return (
    <div onMouseEnter={handleEnter} onMouseLeave={handleLeave}>
      <div ref={anchorRef} className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-lg border text-[11px] font-mono transition-all cursor-default",
        isRestarting
          ? "bg-amber-500/10 border-amber-500/30 animate-pulse"
          : isDuplicate
            ? "bg-amber-500/5 border-amber-500/20"
            : isOnline
              ? "bg-slate-950 border-slate-800/50"
              : "bg-red-500/5 border-red-500/20"
      )}>
        {isRestarting ? (
          <Loader2 size={11} className="text-amber-400 shrink-0 animate-spin" />
        ) : isDuplicate ? (
          <AlertTriangle size={11} className="text-amber-400 shrink-0" />
        ) : isOnline ? (
          <CheckCircle2 size={10} className="text-green-500 shrink-0" />
        ) : (
          <XCircle size={10} className="text-red-500 shrink-0" />
        )}
        <span className={cn(
          "truncate",
          isRestarting ? "text-amber-300" : isDuplicate ? "text-amber-300" : isOnline ? "text-slate-400" : "text-red-400/70"
        )}>
          {def?.label || nodeName}
        </span>
        {isDuplicate && !isRestarting && (
          <span className="ml-auto shrink-0 text-[10px] font-bold text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded">
            ×{count}
          </span>
        )}
        {isRestarting && (
          <span className="ml-auto shrink-0 text-[10px] font-medium text-amber-400">重启中</span>
        )}
      </div>
      {showTip && (
        <NodeTooltip
          nodeName={nodeName} def={def} count={count}
          isOnline={isOnline} restartable={restartable}
          onRestart={onRestart} anchorRef={anchorRef}
        />
      )}
    </div>
  );
}

// ── 分组卡片 ────────────────────────────────────────────────

function NodeGroup({
  group, nodeCountMap, onRestart, onGroupRestart, restartingNodes,
}: {
  group: GroupDef;
  nodeCountMap: Record<string, number>;
  onRestart: (nodeName: string, killDuplicates: boolean) => void;
  onGroupRestart?: () => void;
  restartingNodes?: Set<string>;
}) {
  const [expanded, setExpanded] = useState(true);
  const Icon = group.icon;

  const total = Object.keys(group.nodes).length;
  const online = Object.keys(group.nodes).filter(n => (nodeCountMap[n] || 0) > 0).length;
  const duplicates = Object.keys(group.nodes).filter(n => (nodeCountMap[n] || 0) > 1).length;

  const colorMap: Record<string, { bg: string; border: string; icon: string }> = {
    blue:   { bg: "bg-blue-500/10",   border: "border-blue-500/20",   icon: "text-blue-400" },
    violet: { bg: "bg-violet-500/10", border: "border-violet-500/20", icon: "text-violet-400" },
    slate:  { bg: "bg-slate-500/10",  border: "border-slate-500/20",  icon: "text-slate-400" },
  };
  const c = colorMap[group.color] || colorMap.slate;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-sm">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-3 px-5 py-3.5 hover:bg-slate-800/50 transition-colors"
      >
        <div className={cn("w-7 h-7 rounded-lg flex items-center justify-center", c.bg)}>
          <Icon size={15} className={c.icon} />
        </div>
        <span className="text-sm font-semibold text-slate-200">{group.label}</span>
        <span className={cn(
          "text-[11px] font-mono px-2 py-0.5 rounded-md",
          online === total ? "bg-green-500/15 text-green-400" :
          online === 0 ? "bg-red-500/15 text-red-400" :
          "bg-amber-500/15 text-amber-400"
        )}>
          {online}/{total}
        </span>
        {duplicates > 0 && (
          <span className="flex items-center gap-1 text-[11px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-md">
            <AlertTriangle size={11} />
            {duplicates} 重复
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {onGroupRestart && online > 0 && (
            <span
              role="button"
              onClick={e => { e.stopPropagation(); onGroupRestart(); }}
              className="flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-lg border transition-colors cursor-pointer"
              style={{
                color: group.color === "blue" ? "rgb(96,165,250)" : "rgb(167,139,250)",
                backgroundColor: group.color === "blue" ? "rgba(59,130,246,0.1)" : "rgba(139,92,246,0.1)",
                borderColor: group.color === "blue" ? "rgba(59,130,246,0.2)" : "rgba(139,92,246,0.2)",
              }}
            >
              <RefreshCw size={10} />
              一键重启
            </span>
          )}
          {expanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
        </div>
      </button>
      {expanded && (
        <div className="px-5 pb-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
          {Object.entries(group.nodes).map(([nodeName, def]) => (
            <NodeItem
              key={nodeName}
              nodeName={nodeName}
              def={def}
              count={nodeCountMap[nodeName] || 0}
              restartable={group.restartable}
              onRestart={group.restartable ? (killDup) => onRestart(nodeName, killDup) : undefined}
              isRestarting={restartingNodes?.has(nodeName)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── "其他"节点折叠组 ────────────────────────────────────────

function OtherNodesGroup({ nodeCountMap }: { nodeCountMap: Record<string, number> }) {
  const [expanded, setExpanded] = useState(false);

  const otherNodes = Object.entries(nodeCountMap)
    .filter(([name]) => !ALL_REGISTERED_NODES.has(name))
    .sort(([a], [b]) => a.localeCompare(b));

  if (otherNodes.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-sm">
        <div className="flex items-center gap-3 px-5 py-3.5">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-slate-500/10">
            <Package size={15} className="text-slate-400" />
          </div>
          <span className="text-sm font-semibold text-slate-400">其他</span>
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-md bg-slate-800 text-slate-500">0</span>
          <span className="text-[10px] text-slate-600 ml-2">无额外运行节点</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-sm">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-3 px-5 py-3.5 hover:bg-slate-800/50 transition-colors"
      >
        <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-slate-500/10">
          <Package size={15} className="text-slate-400" />
        </div>
        <span className="text-sm font-semibold text-slate-400">其他</span>
        <span className="text-[11px] font-mono px-2 py-0.5 rounded-md bg-slate-800 text-slate-500">
          {otherNodes.length}
        </span>
        <div className="ml-auto">
          {expanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
        </div>
      </button>
      {expanded && (
        <div className="px-5 pb-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
          {otherNodes.map(([name, count]) => (
            <NodeItem key={name} nodeName={name} def={null} count={count} restartable={false} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── 视觉传感器按钮（toggle 勾选）────────────────────────────────

function VisionButton({ icon: Icon, label, desc, tab }: {
  icon: React.ElementType;
  label: string;
  desc: string;
  tab: "camera" | "lidar" | "pointcloud" | "rgbd" | "teleop";
}) {
  const togglePanel = useVisionStore((s) => s.togglePanel);
  const pipActivePanels = useVisionStore((s) => s.pipActivePanels);
  const isPiPVisible = useVisionStore((s) => s.isPiPVisible);
  const openPiP = useVisionStore((s) => s.openPiP);
  const isActive = isPiPVisible && pipActivePanels.includes(tab);

  const handleClick = () => {
    if (!isPiPVisible) {
      // 首次点击：打开 PiP 并选中该面板
      openPiP(tab);
    } else {
      // 已打开：toggle 该面板
      togglePanel(tab);
    }
  };

  return (
    <button
      onClick={handleClick}
      className={cn(
        "flex items-center gap-3 p-3.5 rounded-xl border transition-all text-left",
        isActive
          ? "bg-blue-500/10 border-blue-500/30"
          : "bg-slate-950 border-slate-800/50 hover:bg-slate-800/50 hover:border-slate-700"
      )}
    >
      <div className={cn(
        "w-9 h-9 rounded-lg flex items-center justify-center shrink-0",
        isActive ? "bg-blue-500/20" : "bg-slate-800"
      )}>
        <Icon size={18} className={isActive ? "text-blue-400" : "text-slate-400"} />
      </div>
      <div className="min-w-0">
        <div className={cn("text-xs font-medium truncate", isActive ? "text-blue-300" : "text-slate-300")}>
          {label}
        </div>
        <div className="text-[10px] text-slate-500 truncate">{desc}</div>
      </div>
    </button>
  );
}

// ── 主组件 ──────────────────────────────────────────────────

export default function RobotView() {
  const {
    isConnected,
    systemStatus,
    systemLogs,
    launchMode,
    getSystemStatus,
    restartNode,
  } = useRosStore();

  const [launching, setLaunching] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [confirmRestart, setConfirmRestart] = useState<{ nodeName: string; killDuplicates: boolean } | null>(null);
  const [confirmAction, setConfirmAction] = useState<"navstack" | "sstg" | "stop-all" | "start-all" | "restart-all" | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [fastPoll, setFastPoll] = useState(false);
  const [restartingNodes, setRestartingNodes] = useState<Set<string>>(new Set());
  const logContainerRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);

  const nodeCountMap = useMemo(
    () => computeNodeStats(systemStatus?.activeNodes || []),
    [systemStatus?.activeNodes]
  );

  // 导航栈是否在运行（至少有一个 navstack 节点在线）
  const navstackOnline = Object.keys(NODE_REGISTRY.navstack.nodes).some(n => (nodeCountMap[n] || 0) > 0);

  useEffect(() => {
    if (isConnected) {
      getSystemStatus().catch(() => {});
    }
  }, [isConnected, getSystemStatus]);

  useEffect(() => {
    if (!isConnected) return;
    const interval = setInterval(() => {
      getSystemStatus().catch(() => {});
    }, fastPoll ? 1500 : 5000);
    return () => clearInterval(interval);
  }, [isConnected, getSystemStatus, fastPoll]);

  const handleLogScroll = useCallback(() => {
    const el = logContainerRef.current;
    if (!el) return;
    userScrolledUpRef.current = el.scrollHeight - el.scrollTop - el.clientHeight > 40;
  }, []);

  useEffect(() => {
    const el = logContainerRef.current;
    if (!el || userScrolledUpRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [systemLogs]);

  // 单节点重启确认
  const handleRestartConfirm = async () => {
    if (!confirmRestart) return;
    setRestarting(true);
    try {
      const res = await restartNode(confirmRestart.nodeName, confirmRestart.killDuplicates);
      setActionMsg({ type: res.success ? "ok" : "err", text: res.message });
    } catch (err) {
      setActionMsg({ type: "err", text: String(err) });
    } finally {
      setRestarting(false);
      setConfirmRestart(null);
      setTimeout(() => getSystemStatus().catch(() => {}), 2000);
    }
  };

  // SSTG 逐个重启的内部逻辑（供全局和组级共用）
  // 排除 rosbridge_websocket（UI 通信通道）和 system_manager_node（它自己处理重启请求，自杀会卡死）
  const SSTG_SKIP_RESTART = new Set(["rosbridge_websocket", "system_manager_node"]);

  const restartSstgNodes = async () => {
    const restartableNodes = Object.keys(NODE_REGISTRY.sstg.nodes).filter(n => !SSTG_SKIP_RESTART.has(n));
    const onlineNodes = restartableNodes.filter(n => (nodeCountMap[n] || 0) > 0);
    if (onlineNodes.length === 0) return { ok: 0, fail: 0 };

    setRestartingNodes(new Set(onlineNodes));
    let ok = 0, fail = 0;
    for (let i = 0; i < onlineNodes.length; i++) {
      const nodeName = onlineNodes[i];
      const label = NODE_REGISTRY.sstg.nodes[nodeName]?.label || nodeName;
      setActionMsg({ type: "ok", text: `正在重启 ${label} (${i + 1}/${onlineNodes.length})...` });
      try {
        // 加 15s 超时保护，防止某个节点 service 无响应导致整个流程卡死
        const res = await Promise.race([
          restartNode(nodeName, true),
          new Promise<{ success: false; message: string }>((_, reject) =>
            setTimeout(() => reject(new Error(`重启 ${label} 超时 (15s)`)), 15000)
          ),
        ]);
        if (res.success) ok++; else fail++;
      } catch {
        fail++;
      }
      setRestartingNodes(prev => {
        const next = new Set(prev);
        next.delete(nodeName);
        return next;
      });
      await getSystemStatus().catch(() => {});
    }
    setRestartingNodes(new Set());
    return { ok, fail };
  };

  // 统一操作处理
  const handleConfirmAction = async () => {
    const action = confirmAction;
    if (!action) return;
    setRestarting(true);
    setConfirmAction(null);
    setFastPoll(true);

    try {
      if (action === "start-all") {
        // 全局启动：启动导航栈（SSTG 由 sstg_full.launch.py 管理，通常开机已在运行）
        setActionMsg({ type: "ok", text: "正在启动导航栈..." });
        const res = await launchMode("navigation");
        if (res.success) {
          setActionMsg({ type: "ok", text: "导航栈已启动" });
        } else {
          setActionMsg({ type: "err", text: res.message });
        }

      } else if (action === "stop-all") {
        // 全局停止：停止导航栈 + 逐个停止 SSTG（不含 rosbridge）
        setActionMsg({ type: "ok", text: "正在停止导航栈..." });
        await launchMode("stop");
        await getSystemStatus().catch(() => {});
        // 逐个停止 SSTG（restartNode 会 kill → restart，这里用来重启以便后续可恢复）
        // 注意：真正的"停止"只能停导航栈，SSTG 是常驻的只能"重启"不能"停止"
        setActionMsg({ type: "ok", text: "导航栈已停止，SSTG 核心保持运行" });

      } else if (action === "restart-all") {
        // 全局重启：重启导航栈 + 逐个重启 SSTG
        const mode = systemStatus?.mode;

        // 第一步：重启导航栈
        if (mode && mode !== "idle") {
          setActionMsg({ type: "ok", text: "正在停止导航栈..." });
          await launchMode("stop");
          await getSystemStatus().catch(() => {});
          await new Promise(r => setTimeout(r, 3000));
          setActionMsg({ type: "ok", text: "正在重新启动导航栈..." });
          await launchMode(mode);
        } else {
          setActionMsg({ type: "ok", text: "正在启动导航栈..." });
          await launchMode("navigation");
        }
        await getSystemStatus().catch(() => {});

        // 第二步：逐个重启 SSTG
        setActionMsg({ type: "ok", text: "导航栈已就绪，正在重启 SSTG 核心..." });
        const { ok, fail } = await restartSstgNodes();

        const navOk = true; // 导航栈已在上面启动
        setActionMsg({
          type: fail === 0 ? "ok" : "err",
          text: `全局重启完成: 导航栈已启动，SSTG ${ok} 成功${fail > 0 ? ` / ${fail} 失败` : ""}`,
        });

      } else if (action === "navstack") {
        // 仅重启导航栈
        const mode = systemStatus?.mode;
        if (!mode || mode === "idle") {
          setActionMsg({ type: "ok", text: "正在启动导航栈..." });
          const res = await launchMode("navigation");
          setActionMsg({ type: res.success ? "ok" : "err", text: res.success ? "导航栈已启动" : res.message });
        } else {
          setActionMsg({ type: "ok", text: "正在停止导航栈..." });
          await launchMode("stop");
          await getSystemStatus().catch(() => {});
          setActionMsg({ type: "ok", text: "正在重新启动导航栈..." });
          await new Promise(r => setTimeout(r, 3000));
          const res = await launchMode(mode);
          setActionMsg({ type: res.success ? "ok" : "err", text: res.success ? "导航栈已重启" : res.message });
        }

      } else if (action === "sstg") {
        // 仅重启 SSTG
        const { ok, fail } = await restartSstgNodes();
        setActionMsg({
          type: fail === 0 ? "ok" : "err",
          text: `SSTG 核心重启完成: ${ok} 成功${fail > 0 ? `, ${fail} 失败` : ""}`,
        });
      }
    } catch (err) {
      setActionMsg({ type: "err", text: String(err) });
    }

    setRestarting(false);
    setTimeout(() => setFastPoll(false), 15000);
  };

  const currentMode = systemStatus?.mode || "idle";

  return (
    <div className="flex h-full w-full bg-slate-950 text-slate-200 overflow-hidden">
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto p-6 space-y-6">

        {/* Header */}
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-blue-600/20 flex items-center justify-center text-blue-500 shadow-lg shadow-blue-900/20">
            <Radio size={28} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-100 tracking-wide">机器人控制中心</h1>
            <p className="text-xs text-slate-500">系统监控 / 节点管理 / 一键启停</p>
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

        {/* ── 基础设施（常驻，不参与重启）── */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Wifi size={16} className="text-blue-400" />
            基础设施
            <span className="text-[10px] font-normal normal-case text-slate-600 ml-2">常驻服务，不参与节点重启</span>
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {/* 基础设施节点（rosbridge + system_manager） */}
            {Object.entries(INFRA_NODES).map(([nodeName, def]) => {
              const online = (nodeCountMap[nodeName] || 0) > 0;
              return (
                <div key={nodeName} className={cn(
                  "flex items-center gap-3 p-3.5 rounded-xl border transition-all",
                  online ? "bg-green-500/5 border-green-500/20" : "bg-red-500/5 border-red-500/20"
                )}>
                  <div className={cn(
                    "w-2.5 h-2.5 rounded-full shrink-0",
                    online
                      ? "bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]"
                      : "bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.4)]"
                  )} />
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-slate-300 truncate">{def.label}</div>
                    <div className="text-[10px] font-mono text-slate-500 truncate">{def.desc}</div>
                  </div>
                  <div className="ml-auto shrink-0">
                    {online ? <CheckCircle2 size={14} className="text-green-500" /> : <XCircle size={14} className="text-red-500" />}
                  </div>
                </div>
              );
            })}

            {/* 硬件设备 */}
            {(systemStatus?.devices || [
              { name: "底盘 CH340", path: "/dev/chassis", ok: false },
              { name: "雷达 RPLidar S2", path: "/dev/rplidar", ok: false },
              { name: "相机 Gemini 336L", path: "/dev/Gemini_336L", ok: false },
            ]).map((dev, i) => (
              <div key={i} className={cn(
                "flex items-center gap-3 p-3.5 rounded-xl border transition-all",
                dev.ok ? "bg-green-500/5 border-green-500/20" : "bg-red-500/5 border-red-500/20"
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
                  {dev.ok ? <CheckCircle2 size={14} className="text-green-500" /> : <XCircle size={14} className="text-red-500" />}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ── 系统中控 ── */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Power size={16} className="text-blue-400" />
            系统中控
            <span className="text-[10px] font-normal normal-case text-slate-600 ml-2">导航栈 + SSTG 核心（不含 WebSocket 桥）</span>
          </h2>

          <div className="flex gap-3 mb-4">
            <button
              disabled={!isConnected || restarting}
              onClick={() => setConfirmAction("start-all")}
              className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-medium bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Play size={16} />
              一键启动
            </button>

            <button
              disabled={!isConnected || restarting}
              onClick={() => setConfirmAction("stop-all")}
              className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-medium bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Square size={16} />
              一键停止
            </button>

            <button
              disabled={!isConnected || restarting}
              onClick={() => setConfirmAction("restart-all")}
              className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-medium bg-amber-500/10 border border-amber-500/30 text-amber-400 hover:bg-amber-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {restarting ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
              一键重启
            </button>
          </div>

          {/* 状态指示 */}
          <div className="flex items-center gap-3 px-1">
            <span className="text-xs text-slate-500">导航栈:</span>
            <span className={cn(
              "text-xs font-bold tracking-wider px-2.5 py-1 rounded-md",
              navstackOnline ? "bg-green-500/15 text-green-400" : "bg-slate-800 text-slate-500"
            )}>
              {navstackOnline ? "运行中" : "未启动"}
            </span>
            <span className="text-xs text-slate-500 ml-2">SSTG:</span>
            <span className={cn(
              "text-xs font-bold tracking-wider px-2.5 py-1 rounded-md",
              Object.keys(NODE_REGISTRY.sstg.nodes).some(n => (nodeCountMap[n] || 0) > 0)
                ? "bg-green-500/15 text-green-400" : "bg-slate-800 text-slate-500"
            )}>
              {Object.keys(NODE_REGISTRY.sstg.nodes).some(n => (nodeCountMap[n] || 0) > 0) ? "运行中" : "未启动"}
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

        {/* ── 系统资源 ── */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Cpu size={16} className="text-blue-400" />
            系统资源
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase">CPU</span>
                <span className="text-sm font-mono text-slate-300">
                  {systemStatus ? `${systemStatus.cpu.toFixed(0)}%` : '--'}
                </span>
              </div>
              <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all duration-700",
                    (systemStatus?.cpu ?? 0) > 80 ? "bg-red-500" : (systemStatus?.cpu ?? 0) > 60 ? "bg-amber-500" : "bg-blue-500"
                  )}
                  style={{ width: `${systemStatus?.cpu ?? 0}%` }}
                />
              </div>
            </div>
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase">RAM</span>
                <span className="text-sm font-mono text-slate-300">
                  {systemStatus ? `${systemStatus.memory.toFixed(0)}%` : '--'}
                </span>
              </div>
              <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all duration-700",
                    (systemStatus?.memory ?? 0) > 80 ? "bg-red-500" : (systemStatus?.memory ?? 0) > 60 ? "bg-amber-500" : "bg-emerald-500"
                  )}
                  style={{ width: `${systemStatus?.memory ?? 0}%` }}
                />
              </div>
            </div>
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase">NODES</span>
                <span className="text-sm font-mono text-slate-300">{systemStatus?.nodeCount ?? '--'}</span>
              </div>
              <div className="flex items-center gap-1">
                <Server size={12} className="text-slate-600" />
                <span className="text-[10px] text-slate-500">活跃 ROS2 节点</span>
              </div>
            </div>
          </div>
        </section>

        {/* ── 视觉与传感器 ── */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Camera size={16} className="text-blue-400" />
            视觉与传感器
            <span className="text-[10px] font-normal normal-case text-slate-600 ml-2">实时画面 / LiDAR 扫描 / 3D 点云 / 遥控</span>
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <VisionButton
              icon={Camera}
              label="相机"
              desc="RGB 实时画面"
              tab="camera"
            />
            <VisionButton
              icon={Layers}
              label="深度"
              desc="深度伪彩色 (rosbridge)"
              tab="rgbd"
            />
            <VisionButton
              icon={Radar}
              label="LiDAR"
              desc="2D 俯视扫描图"
              tab="lidar"
            />
            <VisionButton
              icon={Box}
              label="伪3D"
              desc="LaserScan 伪3D"
              tab="pointcloud"
            />
            <VisionButton
              icon={Gamepad2}
              label="遥控"
              desc="键盘/触控全向遥控"
              tab="teleop"
            />
          </div>
        </section>

        {/* ── 节点仪表盘 ── */}
        <div className="space-y-3">
          {Object.entries(NODE_REGISTRY).map(([key, group]) => (
            <NodeGroup
              key={key}
              group={group}
              nodeCountMap={nodeCountMap}
              onRestart={(nodeName, killDup) => setConfirmRestart({ nodeName, killDuplicates: killDup })}
              onGroupRestart={
                (key === "navstack" && !restarting) ? () => setConfirmAction("navstack") :
                (key === "sstg" && !restarting) ? () => setConfirmAction("sstg") :
                undefined
              }
              restartingNodes={key === "sstg" ? restartingNodes : undefined}
            />
          ))}
          <OtherNodesGroup nodeCountMap={nodeCountMap} />
        </div>

        {/* ── 单节点重启确认 ── */}
        {confirmRestart && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 max-w-sm w-full mx-4 shadow-2xl">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-amber-500/15 flex items-center justify-center">
                  <RefreshCw size={20} className="text-amber-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-slate-200">确认重启节点</h3>
                  <p className="text-[11px] text-slate-400 font-mono">/{confirmRestart.nodeName}</p>
                </div>
              </div>
              <p className="text-xs text-slate-400 mb-5 leading-relaxed">
                {confirmRestart.killDuplicates
                  ? `将终止所有 ${confirmRestart.nodeName} 实例并重新启动 1 个。`
                  : `将终止当前 ${confirmRestart.nodeName} 实例并重新启动。正在执行的任务可能中断。`}
              </p>
              <div className="flex gap-3">
                <button onClick={() => setConfirmRestart(null)} className="flex-1 py-2.5 rounded-xl text-xs font-medium bg-slate-800 border border-slate-700 text-slate-400 hover:bg-slate-700 transition-colors">
                  取消
                </button>
                <button onClick={handleRestartConfirm} disabled={restarting} className="flex-1 py-2.5 rounded-xl text-xs font-medium bg-amber-500/15 border border-amber-500/30 text-amber-400 hover:bg-amber-500/25 transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5">
                  {restarting ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                  {restarting ? "重启中..." : "确认重启"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── 操作确认对话框（启动/停止/重启/SSTG）── */}
        {confirmAction && (() => {
          const cfg: Record<string, { title: string; desc: string; color: string; icon: React.ElementType; btnText: string }> = {
            "start-all": {
              title: "一键启动全部节点",
              desc: "将启动导航栈（硬件驱动 + SLAM + Nav2 + 相机 + 拓扑）。SSTG 核心通常开机已在运行。WebSocket 桥不受影响。",
              color: "green", icon: Play, btnText: "确认启动",
            },
            "stop-all": {
              title: "一键停止导航栈",
              desc: "将停止导航栈所有节点（硬件驱动 + SLAM + Nav2 + 相机）。SSTG 核心和 WebSocket 桥保持运行（常驻服务无法通过 UI 停止）。",
              color: "red", icon: Square, btnText: "确认停止",
            },
            "restart-all": {
              title: "一键重启全部节点",
              desc: "将重启导航栈（stop → 重新 launch）并逐个重启 SSTG 核心节点。WebSocket 桥不受影响。过程约需 20-30 秒，正在执行的任务将中断。",
              color: "amber", icon: RefreshCw, btnText: "确认重启",
            },
            "navstack": {
              title: "一键重启导航栈",
              desc: navstackOnline
                ? "将停止并重新启动导航栈（硬件驱动 + SLAM + Nav2 + 相机 + 拓扑）。过程约需 15-20 秒。SSTG 核心和 WebSocket 桥不受影响。"
                : "导航栈未启动，将直接启动。",
              color: "violet", icon: Navigation, btnText: navstackOnline ? "确认重启" : "确认启动",
            },
            "sstg": {
              title: "一键重启 SSTG 核心",
              desc: `将逐个重启 ${Object.keys(NODE_REGISTRY.sstg.nodes).filter(n => !SSTG_SKIP_RESTART.has(n) && (nodeCountMap[n] || 0) > 0).length} 个在线 SSTG 核心节点（不含 WebSocket 桥和系统管理器）。导航栈不受影响。重启期间 NLP/规划/执行链路会短暂中断。`,
              color: "blue", icon: Brain, btnText: "确认重启",
            },
          };
          const c = cfg[confirmAction];
          if (!c) return null;

          const colorStyles: Record<string, { bg: string; border: string; text: string; hover: string; iconBg: string }> = {
            green:  { bg: "bg-green-500/15",  border: "border-green-500/30",  text: "text-green-400",  hover: "hover:bg-green-500/25",  iconBg: "bg-green-500/15" },
            red:    { bg: "bg-red-500/15",    border: "border-red-500/30",    text: "text-red-400",    hover: "hover:bg-red-500/25",    iconBg: "bg-red-500/15" },
            amber:  { bg: "bg-amber-500/15",  border: "border-amber-500/30",  text: "text-amber-400",  hover: "hover:bg-amber-500/25",  iconBg: "bg-amber-500/15" },
            blue:   { bg: "bg-blue-500/15",   border: "border-blue-500/30",   text: "text-blue-400",   hover: "hover:bg-blue-500/25",   iconBg: "bg-blue-500/15" },
            violet: { bg: "bg-violet-500/15", border: "border-violet-500/30", text: "text-violet-400", hover: "hover:bg-violet-500/25", iconBg: "bg-violet-500/15" },
          };
          const s = colorStyles[c.color] || colorStyles.amber;
          const Icon = c.icon;

          return (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
              <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 max-w-sm w-full mx-4 shadow-2xl">
                <div className="flex items-center gap-3 mb-4">
                  <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", s.iconBg)}>
                    <Icon size={20} className={s.text} />
                  </div>
                  <h3 className="text-sm font-semibold text-slate-200">{c.title}</h3>
                </div>
                <p className="text-xs text-slate-400 mb-5 leading-relaxed">{c.desc}</p>
                <div className="flex gap-3">
                  <button
                    onClick={() => setConfirmAction(null)}
                    className="flex-1 py-2.5 rounded-xl text-xs font-medium bg-slate-800 border border-slate-700 text-slate-400 hover:bg-slate-700 transition-colors"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleConfirmAction}
                    disabled={restarting}
                    className={cn(
                      "flex-1 py-2.5 rounded-xl text-xs font-medium border transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5",
                      s.bg, s.border, s.text, s.hover
                    )}
                  >
                    {restarting ? <Loader2 size={13} className="animate-spin" /> : <Icon size={13} />}
                    {restarting ? "执行中..." : c.btnText}
                  </button>
                </div>
              </div>
            </div>
          );
        })()}

        {/* ── 系统日志 ── */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Terminal size={16} className="text-blue-400" />
            系统日志
          </h2>
          <div
            ref={logContainerRef}
            onScroll={handleLogScroll}
            className="bg-slate-950 rounded-xl border border-slate-800/50 p-3 h-52 overflow-y-auto font-mono text-[11px] leading-relaxed text-slate-400 space-y-0.5"
          >
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
                    isErr ? "text-red-400 bg-red-500/5" : isWarn ? "text-amber-400 bg-amber-500/5" : ""
                  )}>
                    {log}
                  </div>
                );
              })
            )}
          </div>
        </section>

        </div>
      </div>
    </div>
  );
}
