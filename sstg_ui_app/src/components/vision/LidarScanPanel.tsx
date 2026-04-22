import { useEffect, useRef, useCallback } from "react";
import { useVisionStore } from "../../store/visionStore";
import { useLaserScan, type LaserScanData } from "../../hooks/useLaserScan";

/**
 * LiDAR 2D 俯视扫描图 — Canvas 渲染
 *
 * 极坐标 → 笛卡尔坐标，绿色扫描点 + 黑色背景
 * 机器人位置居中，鼠标滚轮缩放
 */

const BG_COLOR = "#0a0a0a";
const GRID_COLOR = "#1a2a1a";
const DOT_COLOR = "#22c55e";
const ROBOT_COLOR = "#3b82f6";

export default function LidarScanPanel() {
  const enabled = useVisionStore((s) => s.lidarEnabled);
  const setLidarEnabled = useVisionStore((s) => s.setLidarEnabled);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const scaleRef = useRef(30); // pixels per meter

  // 面板挂载时确保数据源启用
  useEffect(() => {
    setLidarEnabled(true);
  }, [setLidarEnabled]);

  const { onData } = useLaserScan(enabled);

  const draw = useCallback((data: LaserScanData) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const scale = scaleRef.current;

    // 清空
    ctx.fillStyle = BG_COLOR;
    ctx.fillRect(0, 0, w, h);

    // 网格（每 1m 一条线）
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 0.5;
    const gridStep = scale; // 1m
    for (let x = cx % gridStep; x < w; x += gridStep) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = cy % gridStep; y < h; y += gridStep) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // 扫描点
    ctx.fillStyle = DOT_COLOR;
    const { ranges, angleMin, angleIncrement, rangeMin, rangeMax } = data;
    for (let i = 0; i < ranges.length; i++) {
      const r = ranges[i];
      if (r < rangeMin || r > rangeMax || !isFinite(r)) continue;

      const angle = angleMin + i * angleIncrement;
      // 激光雷达安装旋转 180°：scan angle=π 是车头
      // 要让车头朝上(Canvas -Y)：px = cx - y_ros, py = cy - x_ros
      // 等效于对 angle 加 π 后标准映射
      const corrected = angle + Math.PI;
      const px = cx - r * Math.sin(corrected) * scale;
      const py = cy - r * Math.cos(corrected) * scale;

      ctx.beginPath();
      ctx.arc(px, py, 1.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // 机器人位置标记（三角形箭头，朝上 = 车头）
    ctx.fillStyle = ROBOT_COLOR;
    ctx.beginPath();
    ctx.moveTo(cx, cy - 10);      // 顶点朝上
    ctx.lineTo(cx - 6, cy + 5);
    ctx.lineTo(cx + 6, cy + 5);
    ctx.closePath();
    ctx.fill();

    // 车头方向标注
    ctx.fillStyle = "#60a5fa";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("车头 ▲", cx, cy - 14);

    // 距离环标注
    ctx.strokeStyle = "#334155";
    ctx.lineWidth = 0.5;
    ctx.fillStyle = "#475569";
    ctx.font = "10px monospace";
    for (let m = 2; m <= 10; m += 2) {
      const r = m * scale;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillText(`${m}m`, cx + r + 3, cy - 3);
    }
  }, []);

  // 注册数据回调
  useEffect(() => {
    onData(draw);
  }, [onData, draw]);

  // Canvas 尺寸自适应
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      canvas.width = width * window.devicePixelRatio;
      canvas.height = height * window.devicePixelRatio;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
      // 重置 canvas size 为 CSS pixels for drawing logic
      canvas.width = width;
      canvas.height = height;
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // 鼠标滚轮缩放
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      scaleRef.current = Math.max(5, Math.min(100, scaleRef.current - e.deltaY * 0.05));
    };

    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, []);

  if (!enabled) {
    return (
      <div className="w-full h-full flex items-center justify-center text-slate-500 text-sm">
        LiDAR 未启用
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full h-full bg-black relative">
      <canvas ref={canvasRef} className="w-full h-full" />
      <div className="absolute top-2 left-2 flex items-center gap-1.5 text-xs bg-black/60 px-2 py-1 rounded">
        <span className="w-2 h-2 rounded-full bg-green-500" />
        <span className="text-slate-300">/scan 2D</span>
      </div>
      <div className="absolute bottom-2 right-2 text-xs text-slate-500 bg-black/60 px-2 py-0.5 rounded">
        滚轮缩放
      </div>
    </div>
  );
}
