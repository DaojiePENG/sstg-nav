import { useEffect, useRef, useState } from "react";
import { useRosStore } from "../../store/rosStore";
import * as ROSLIB from "roslib";

/**
 * 压缩 JPEG 降级面板
 * 通过 rosbridge 订阅 /camera/color/image_raw/compressed
 * 显示实时延迟 + 局域网提示
 */
export default function CompressedImageFallback() {
  const imgRef = useRef<HTMLImageElement>(null);
  const ros = useRosStore((s) => s.ros);
  const isConnected = useRosStore((s) => s.isConnected);
  const subRef = useRef<ROSLIB.Topic | null>(null);
  const lastFrameTime = useRef(0);
  const fpsCount = useRef(0);
  const fpsTime = useRef(Date.now());
  const [stats, setStats] = useState({ fps: 0, latency: 0 });

  useEffect(() => {
    if (!ros || !isConnected) return;

    const topic = new ROSLIB.Topic({
      ros,
      name: "/camera/color/image_raw/compressed",
      messageType: "sensor_msgs/msg/CompressedImage",
      throttle_rate: 100, // ~10fps
    } as any);

    topic.subscribe((msg: any) => {
      const now = Date.now();
      const src = `data:image/jpeg;base64,${msg.data}`;
      if (imgRef.current) {
        imgRef.current.src = src;
      }

      // 计算帧间隔作为延迟估算
      if (lastFrameTime.current > 0) {
        const interval = now - lastFrameTime.current;
        fpsCount.current++;
        // 每秒更新一次统计
        if (now - fpsTime.current > 1000) {
          const elapsed = (now - fpsTime.current) / 1000;
          setStats({
            fps: Math.round(fpsCount.current / elapsed),
            latency: Math.round(interval),
          });
          fpsCount.current = 0;
          fpsTime.current = now;
        }
      }
      lastFrameTime.current = now;
    });

    subRef.current = topic;

    return () => {
      topic.unsubscribe();
      subRef.current = null;
    };
  }, [ros, isConnected]);

  return (
    <div className="relative w-full h-full bg-black flex items-center justify-center">
      <img
        ref={imgRef}
        alt="Camera"
        className="w-full h-full object-contain"
      />
      {/* 状态栏：模式 + 延迟 + FPS */}
      <div className="absolute top-2 left-2 flex items-center gap-1.5 text-xs bg-black/70 px-2 py-1 rounded">
        <span className={`w-2 h-2 rounded-full ${stats.fps > 0 ? "bg-green-500" : "bg-amber-500 animate-pulse"}`} />
        <span className="text-slate-300">
          {stats.fps > 0 ? `${stats.fps}fps` : "连接中..."}
          {stats.latency > 0 && <span className="text-slate-400 ml-1">~{stats.latency}ms</span>}
        </span>
      </div>
      <div className="absolute bottom-2 left-2 right-2 text-[10px] text-slate-500 bg-black/60 px-2 py-1 rounded text-center">
        JPEG: rosbridge 压缩传输 若需要实时性能，请勿打开太多通道
      </div>
    </div>
  );
}
