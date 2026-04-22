import { useRef, useCallback, useEffect, useState } from "react";
import type { CameraIntrinsics } from "./useWebRTCDualStream";

/**
 * useDepthToPointCloud — 将 WebRTC 深度视频 + RGB 视频转为 3D 彩色点云
 *
 * 深度编码: R=高8位, G=低8位 → depth_mm = (R << 8) | G
 * RGB: 从 RGB 视频帧同步采样
 * 反投影: x = (u - cx) * z / fx,  y = (v - cy) * z / fy
 */

export interface PointCloudData {
  positions: Float32Array;
  colors: Float32Array;
  count: number;
}

export interface DepthDebugInfo {
  depthVideoReady: boolean;
  rgbVideoReady: boolean;
  depthReadyState: number;
  rgbReadyState: number;
  lastPointCount: number;
  framesProcessed: number;
  depthVideoSize: string;
  rgbVideoSize: string;
}

const STEP = 2;

export function useDepthToPointCloud(
  depthStream: MediaStream | null,
  rgbStream: MediaStream | null,
  cameraInfo: CameraIntrinsics | null,
  enabled: boolean,
) {
  const depthVideoRef = useRef<HTMLVideoElement | null>(null);
  const rgbVideoRef = useRef<HTMLVideoElement | null>(null);
  const depthCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const rgbCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const callbackRef = useRef<((data: PointCloudData) => void) | null>(null);
  const animFrameRef = useRef<number>(0);
  const [debug, setDebug] = useState<DepthDebugInfo>({
    depthVideoReady: false,
    rgbVideoReady: false,
    depthReadyState: 0,
    rgbReadyState: 0,
    lastPointCount: 0,
    framesProcessed: 0,
    depthVideoSize: "?",
    rgbVideoSize: "?",
  });
  const debugRef = useRef(debug);
  debugRef.current = debug;

  // 创建隐藏的 video + canvas 元素
  useEffect(() => {
    if (!enabled) return;

    const dv = document.createElement("video");
    dv.autoplay = true;
    dv.playsInline = true;
    dv.muted = true;
    dv.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;z-index:-1";
    document.body.appendChild(dv);
    depthVideoRef.current = dv;

    const rv = document.createElement("video");
    rv.autoplay = true;
    rv.playsInline = true;
    rv.muted = true;
    rv.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;z-index:-1";
    document.body.appendChild(rv);
    rgbVideoRef.current = rv;

    depthCanvasRef.current = document.createElement("canvas");
    rgbCanvasRef.current = document.createElement("canvas");

    return () => {
      dv.srcObject = null;
      rv.srcObject = null;
      dv.remove();
      rv.remove();
      depthVideoRef.current = null;
      rgbVideoRef.current = null;
    };
  }, [enabled]);

  // 绑定 stream 到 video + 强制 play
  useEffect(() => {
    const dv = depthVideoRef.current;
    if (dv && depthStream) {
      dv.srcObject = depthStream;
      dv.play().catch(() => {});
    }
  }, [depthStream]);

  useEffect(() => {
    const rv = rgbVideoRef.current;
    if (rv && rgbStream) {
      rv.srcObject = rgbStream;
      rv.play().catch(() => {});
    }
  }, [rgbStream]);

  // 主处理循环
  useEffect(() => {
    if (!enabled || !cameraInfo) return;

    const { fx, fy, cx, cy, width: dw, height: dh } = cameraInfo;
    const rw = 320;
    const rh = 240;

    const maxPts = Math.ceil(dw / STEP) * Math.ceil(dh / STEP);
    const positions = new Float32Array(maxPts * 3);
    const colors = new Float32Array(maxPts * 3);

    let lastTime = 0;
    let framesProcessed = 0;
    const FRAME_INTERVAL = 1000 / 10;

    const process = (timestamp: number) => {
      animFrameRef.current = requestAnimationFrame(process);

      if (timestamp - lastTime < FRAME_INTERVAL) return;
      lastTime = timestamp;

      const dv = depthVideoRef.current;
      const rv = rgbVideoRef.current;
      const dc = depthCanvasRef.current;
      const rc = rgbCanvasRef.current;
      if (!dv || !rv || !dc || !rc) return;

      // 更新 debug 信息（每秒一次）
      if (framesProcessed % 10 === 0) {
        setDebug({
          depthVideoReady: dv.readyState >= 2,
          rgbVideoReady: rv.readyState >= 2,
          depthReadyState: dv.readyState,
          rgbReadyState: rv.readyState,
          lastPointCount: debugRef.current.lastPointCount,
          framesProcessed,
          depthVideoSize: `${dv.videoWidth}×${dv.videoHeight}`,
          rgbVideoSize: `${rv.videoWidth}×${rv.videoHeight}`,
        });
      }

      // 视频必须就绪才能 drawImage
      if (dv.readyState < 2 || rv.readyState < 2) {
        // 尝试强制播放
        if (dv.readyState < 2 && dv.srcObject) dv.play().catch(() => {});
        if (rv.readyState < 2 && rv.srcObject) rv.play().catch(() => {});
        return;
      }

      // 使用视频的实际尺寸而非假设值
      const actualDW = dv.videoWidth || dw;
      const actualDH = dv.videoHeight || dh;
      const actualRW = rv.videoWidth || rw;
      const actualRH = rv.videoHeight || rh;

      // 深度帧 → canvas → imageData
      dc.width = actualDW;
      dc.height = actualDH;
      const dctx = dc.getContext("2d", { willReadFrequently: true });
      if (!dctx) return;
      dctx.drawImage(dv, 0, 0, actualDW, actualDH);
      const depthData = dctx.getImageData(0, 0, actualDW, actualDH).data;

      // RGB 帧 → canvas → imageData
      rc.width = actualRW;
      rc.height = actualRH;
      const rctx = rc.getContext("2d", { willReadFrequently: true });
      if (!rctx) return;
      rctx.drawImage(rv, 0, 0, actualRW, actualRH);
      const rgbData = rctx.getImageData(0, 0, actualRW, actualRH).data;

      // 内参缩放比例（camera_info 是按 DEPTH_WIDTH/HEIGHT 缩放的）
      const fxScaled = fx * (actualDW / dw);
      const fyScaled = fy * (actualDH / dh);
      const cxScaled = cx * (actualDW / dw);
      const cyScaled = cy * (actualDH / dh);

      const scaleX = actualRW / actualDW;
      const scaleY = actualRH / actualDH;

      let count = 0;

      for (let v = 0; v < actualDH; v += STEP) {
        for (let u = 0; u < actualDW; u += STEP) {
          const di = (v * actualDW + u) * 4;
          const depthMM = (depthData[di] << 8) | depthData[di + 1];

          if (depthMM < 100 || depthMM > 8000) continue;

          const z = depthMM / 1000;
          const camX = ((u - cxScaled) * z) / fxScaled;
          const camY = ((v - cyScaled) * z) / fyScaled;

          // 相机坐标 → ROS 坐标 (x前 y左 z上)
          positions[count * 3] = z;
          positions[count * 3 + 1] = -camX;
          positions[count * 3 + 2] = -camY;

          // RGB 采样
          const ru = Math.min(Math.round(u * scaleX), actualRW - 1);
          const rv2 = Math.min(Math.round(v * scaleY), actualRH - 1);
          const ri = (rv2 * actualRW + ru) * 4;
          colors[count * 3] = rgbData[ri] / 255;
          colors[count * 3 + 1] = rgbData[ri + 1] / 255;
          colors[count * 3 + 2] = rgbData[ri + 2] / 255;

          count++;
        }
      }

      framesProcessed++;
      callbackRef.current?.({ positions, colors, count });

      // 更新 debug
      if (count !== debugRef.current.lastPointCount || framesProcessed % 10 === 0) {
        setDebug((prev) => ({
          ...prev,
          lastPointCount: count,
          framesProcessed,
          depthVideoSize: `${actualDW}×${actualDH}`,
          rgbVideoSize: `${actualRW}×${actualRH}`,
        }));
      }
    };

    animFrameRef.current = requestAnimationFrame(process);

    return () => {
      cancelAnimationFrame(animFrameRef.current);
    };
  }, [enabled, cameraInfo]);

  const onData = useCallback(
    (cb: (data: PointCloudData) => void) => {
      callbackRef.current = cb;
    },
    [],
  );

  return { onData, debug };
}
