import { useCallback, memo } from "react";
import { Rnd } from "react-rnd";
import { X, Minus, Maximize2, Camera, Radar, Box, Layers, Gamepad2 } from "lucide-react";
import { useVisionStore, type VisionTab } from "../../store/visionStore";
import { cn } from "../../lib/utils";
import LidarScanPanel from "./LidarScanPanel";
import CameraStreamPanel from "./CameraStreamPanel";
import DepthCloudPanel from "./DepthCloudPanel";
import DepthColorPanel from "./DepthColorPanel";
import TeleopPanel from "./TeleopPanel";

const TABS: { key: VisionTab; label: string; Icon: typeof Camera }[] = [
  { key: "camera", label: "相机", Icon: Camera },
  { key: "rgbd", label: "深度", Icon: Layers },
  { key: "lidar", label: "LiDAR", Icon: Radar },
  { key: "pointcloud", label: "伪3D", Icon: Box },
  { key: "teleop", label: "遥控", Icon: Gamepad2 },
];

const MIN_W = 360;
const MIN_H = 280;

function FloatingPiPWindow() {
  const {
    pipPosition,
    pipSize,
    pipActivePanels,
    pipMinimized,
    closePiP,
    toggleMinimize,
    setPiPPosition,
    setPiPSize,
    togglePanel,
  } = useVisionStore();

  const handleDragStop = useCallback(
    (_: unknown, d: { x: number; y: number }) => setPiPPosition({ x: d.x, y: d.y }),
    [setPiPPosition],
  );

  const handleResizeStop = useCallback(
    (_: unknown, __: unknown, ref: HTMLElement, ___: unknown, pos: { x: number; y: number }) => {
      setPiPSize({ width: ref.offsetWidth, height: ref.offsetHeight });
      setPiPPosition(pos);
    },
    [setPiPSize, setPiPPosition],
  );

  const count = pipActivePanels.length;
  // 网格布局：1个=1列, 2个=2列, 3-4个=2x2
  const cols = count <= 1 ? 1 : 2;
  const rows = count <= 2 ? 1 : 2;

  // 根据选中面板数量动态调整最小尺寸
  const dynMinW = cols === 1 ? MIN_W : MIN_W * 2;
  const dynMinH = rows === 1 ? MIN_H : MIN_H * 2;

  return (
    <Rnd
      position={pipPosition}
      size={pipMinimized ? { width: 320, height: 36 } : pipSize}
      minWidth={pipMinimized ? 320 : dynMinW}
      minHeight={pipMinimized ? 36 : dynMinH}
      bounds="window"
      dragHandleClassName="pip-drag-handle"
      enableResizing={!pipMinimized}
      onDragStop={handleDragStop}
      onResizeStop={handleResizeStop}
      style={{ zIndex: 9000 }}
    >
      <div className="flex flex-col w-full h-full rounded-xl overflow-hidden border border-slate-600/80 bg-slate-900/95 backdrop-blur-sm shadow-2xl">
        {/* ── 标题栏 ── */}
        <div className="pip-drag-handle flex items-center justify-between h-9 px-2 bg-slate-800/90 cursor-move select-none shrink-0 border-b border-slate-700/60">
          {/* Checkbox 多选 */}
          <div className="flex gap-0.5">
            {TABS.map(({ key, label, Icon }) => {
              const active = pipActivePanels.includes(key);
              return (
                <button
                  key={key}
                  onClick={() => togglePanel(key)}
                  className={cn(
                    "flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition-colors",
                    active
                      ? "bg-blue-600/30 text-blue-300"
                      : "text-slate-500 hover:text-slate-300 hover:bg-slate-700/60",
                  )}
                >
                  <span className={cn(
                    "w-3 h-3 rounded-sm border flex items-center justify-center text-[8px]",
                    active ? "border-blue-400 bg-blue-500/40 text-white" : "border-slate-600"
                  )}>
                    {active && "✓"}
                  </span>
                  <Icon size={11} />
                  {label}
                </button>
              );
            })}
          </div>

          {/* 窗口控制 */}
          <div className="flex gap-1">
            <button
              onClick={toggleMinimize}
              className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
              title={pipMinimized ? "恢复" : "最小化"}
            >
              {pipMinimized ? <Maximize2 size={12} /> : <Minus size={12} />}
            </button>
            <button
              onClick={closePiP}
              className="p-1 rounded hover:bg-red-600/40 text-slate-400 hover:text-red-300 transition-colors"
              title="关闭"
            >
              <X size={12} />
            </button>
          </div>
        </div>

        {/* ── 内容区：网格多面板 ── */}
        {!pipMinimized && count > 0 && (
          <div
            className="flex-1 min-h-0 overflow-hidden"
            style={{
              display: "grid",
              gridTemplateColumns: `repeat(${cols}, 1fr)`,
              gridTemplateRows: `repeat(${rows}, 1fr)`,
              gap: "1px",
              background: "#1e293b", // gap 颜色 = slate-800
            }}
          >
            {pipActivePanels.map((tab) => (
              <div key={tab} className="min-h-0 min-w-0 overflow-hidden relative">
                {/* 面板小标题 */}
                {count > 1 && (
                  <div className="absolute top-0 right-0 z-10 text-[9px] text-slate-500 bg-black/50 px-1.5 py-0.5 rounded-bl">
                    {TABS.find((t) => t.key === tab)?.label}
                  </div>
                )}
                <PanelContent tab={tab} />
              </div>
            ))}
          </div>
        )}

        {/* 无选中面板提示 */}
        {!pipMinimized && count === 0 && (
          <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
            点击上方按钮选择要显示的传感器
          </div>
        )}
      </div>
    </Rnd>
  );
}

/** 根据 tab key 渲染对应面板 */
function PanelContent({ tab }: { tab: VisionTab }) {
  switch (tab) {
    case "camera":
      return <CameraStreamPanel />;
    case "lidar":
      return <LidarScanPanel />;
    case "pointcloud":
      return <DepthCloudPanel />;
    case "rgbd":
      return <DepthColorPanel />;
    case "teleop":
      return <TeleopPanel />;
    default:
      return null;
  }
}

export default memo(FloatingPiPWindow);
