import { useEffect, useRef, useCallback } from "react";
import { useVisionStore } from "../../store/visionStore";
import { useDepthImage, type DepthImageData } from "../../hooks/useDepthImage";

/**
 * 深度伪彩色面板 — 订阅 /camera/depth/image_raw 通过 rosbridge
 * 将 16bit 深度值渲染为 JET 伪彩色 Canvas
 * 不依赖 WebRTC，纯 rosbridge 传输
 */

const MAX_DEPTH_MM = 5000; // 5 米显示范围

/** JET colormap: 0→蓝, 0.25→青, 0.5→绿, 0.75→黄, 1→红 */
function jetColor(t: number): [number, number, number] {
  const r = Math.min(Math.max(1.5 - Math.abs(t * 4 - 3), 0), 1);
  const g = Math.min(Math.max(1.5 - Math.abs(t * 4 - 2), 0), 1);
  const b = Math.min(Math.max(1.5 - Math.abs(t * 4 - 1), 0), 1);
  return [r * 255, g * 255, b * 255];
}

// 预计算 LUT (256 级)
const JET_LUT = new Uint8Array(256 * 3);
for (let i = 0; i < 256; i++) {
  const [r, g, b] = jetColor(i / 255);
  JET_LUT[i * 3] = r;
  JET_LUT[i * 3 + 1] = g;
  JET_LUT[i * 3 + 2] = b;
}

export default function DepthColorPanel() {
  const depthEnabled = useVisionStore((s) => s.depthEnabled);
  const setDepthEnabled = useVisionStore((s) => s.setDepthEnabled);

  useEffect(() => {
    setDepthEnabled(true);
    return () => setDepthEnabled(false);
  }, [setDepthEnabled]);

  const { onData } = useDepthImage(depthEnabled);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const statsRef = useRef({ frames: 0, points: 0, w: 0, h: 0 });

  const draw = useCallback((data: DepthImageData) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;

    const { depth, width, height } = data;

    // 调整 canvas 尺寸
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }

    const imgData = ctx.createImageData(width, height);
    const pixels = imgData.data;

    let validCount = 0;

    for (let i = 0; i < depth.length; i++) {
      const mm = depth[i];
      const pi = i * 4;

      if (mm < 50 || mm > MAX_DEPTH_MM) {
        // 无效深度 → 深灰色
        pixels[pi] = 20;
        pixels[pi + 1] = 20;
        pixels[pi + 2] = 20;
        pixels[pi + 3] = 255;
      } else {
        validCount++;
        const t = Math.min(mm / MAX_DEPTH_MM, 1);
        const lutIdx = Math.round(t * 255) * 3;
        pixels[pi] = JET_LUT[lutIdx];
        pixels[pi + 1] = JET_LUT[lutIdx + 1];
        pixels[pi + 2] = JET_LUT[lutIdx + 2];
        pixels[pi + 3] = 255;
      }
    }

    ctx.putImageData(imgData, 0, 0);
    statsRef.current = { frames: statsRef.current.frames + 1, points: validCount, w: width, h: height };
  }, []);

  useEffect(() => {
    onData(draw);
  }, [onData, draw]);

  // Canvas 自适应容器
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const fit = () => {
      const { width, height } = container.getBoundingClientRect();
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    };

    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="w-full h-full bg-black relative">
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ objectFit: "contain", imageRendering: "auto" }}
      />
      <div className="absolute top-2 left-2 flex items-center gap-1.5 text-xs bg-black/60 px-2 py-1 rounded">
        <span className="w-2 h-2 rounded-full bg-green-500" />
        <span className="text-slate-300">深度伪彩色 (rosbridge)</span>
      </div>
      {/* 色标 */}
      <div className="absolute bottom-2 left-2 flex items-center gap-1 text-[10px] text-slate-400 bg-black/60 px-2 py-1 rounded">
        <span className="text-blue-400">近 0m</span>
        <div className="w-20 h-2 rounded-sm" style={{
          background: "linear-gradient(to right, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000)"
        }} />
        <span className="text-red-400">远 {MAX_DEPTH_MM / 1000}m</span>
      </div>
    </div>
  );
}
