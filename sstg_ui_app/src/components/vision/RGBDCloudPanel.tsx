import { useRef, useEffect, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Grid } from "@react-three/drei";
import * as THREE from "three";
import { useVisionStore } from "../../store/visionStore";
import { useWebRTCDualStream } from "../../hooks/useWebRTCDualStream";

const STEP = 2;
const MAX_POINTS = 20000;

interface PointCloudFrame {
  positions: Float32Array;
  colors: Float32Array;
  count: number;
  seq: number;
}

function PointCloudRenderer({ dataRef }: { dataRef: React.RefObject<PointCloudFrame | null> }) {
  const pointsRef = useRef<THREE.Points>(null);
  const lastSeq = useRef(-1);
  useFrame(() => {
    const data = dataRef.current;
    if (!data || !pointsRef.current || data.seq === lastSeq.current) return;
    lastSeq.current = data.seq;
    const geom = pointsRef.current.geometry;
    const n = Math.min(data.count, MAX_POINTS);
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = data.positions[i * 3];
      pos[i * 3 + 1] = data.positions[i * 3 + 2];
      pos[i * 3 + 2] = -data.positions[i * 3 + 1];
    }
    geom.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geom.setAttribute("color", new THREE.BufferAttribute(data.colors.slice(0, n * 3), 3));
    geom.setDrawRange(0, n);
    geom.computeBoundingSphere();
  });
  return (
    <>
      <points ref={pointsRef}>
        <bufferGeometry />
        <pointsMaterial size={2} vertexColors sizeAttenuation />
      </points>
      <mesh position={[0, 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.1, 0.2, 4]} />
        <meshBasicMaterial color="#3b82f6" />
      </mesh>
    </>
  );
}

// ── 主组件 ──
// RGB: <video> 播放 rgbStream（浏览器自动选第一个 track）
// Depth: 从 stream 取第二个 track，用 MediaStreamTrackProcessor 或 rAF 兜底解码

export default function RGBDCloudPanel() {
  const setDepthEnabled = useVisionStore((s) => s.setDepthEnabled);
  const setCameraEnabled = useVisionStore((s) => s.setCameraEnabled);
  useEffect(() => { setDepthEnabled(true); setCameraEnabled(true); }, [setDepthEnabled, setCameraEnabled]);

  const { connected, cameraInfo, depthStream, rgbStream } = useWebRTCDualStream();
  const rgbVideoRef = useRef<HTMLVideoElement>(null);
  const frameRef = useRef<PointCloudFrame | null>(null);
  const seqRef = useRef(0);
  const animRef = useRef(0);
  const [debugText, setDebugText] = useState("初始化...");

  // RGB video 绑定
  useEffect(() => {
    const rv = rgbVideoRef.current;
    if (!rv || !rgbStream) return;
    rv.srcObject = rgbStream;
    rv.play().catch(() => {});
  }, [rgbStream]);

  // Depth 解码 + 点云生成
  useEffect(() => {
    if (!cameraInfo || !depthStream) return;

    const cancelledRef = { current: false };

    // 包装成 async IIFE（useEffect 不能直接 async）
    (async () => {
    const { fx, fy, cx, cy, width: nomW, height: nomH } = cameraInfo;

    const allTracks = depthStream.getVideoTracks();
    const depthTrack = allTracks.length >= 2 ? allTracks[1] : allTracks[0];
    if (!depthTrack) { setDebugText("无 depth track"); return; }

    const trackInfo = `id=${depthTrack.id.slice(0,8)} muted=${depthTrack.muted} state=${depthTrack.readyState}`;
    console.log(`[RGBD] depthTrack: ${trackInfo} allTracks=${allTracks.length}`);
    setDebugText(`depth track: ${trackInfo} tracks=${allTracks.length}`);

    const dc = document.createElement("canvas");
    const rc = document.createElement("canvas");
    const maxPts = Math.ceil(nomW / STEP) * Math.ceil(nomH / STEP) * 4;
    const positions = new Float32Array(maxPts * 3);
    const colors = new Float32Array(maxPts * 3);
    let framesProcessed = 0;

    // 检查 track 是否 muted（cloudflared 等隧道下 RTP 媒体无法穿透）
    if (depthTrack.muted) {
      setDebugText("等待媒体流... (track muted, 5s 后超时)");
      // 等待 unmute 或超时
      const unmuted = await new Promise<boolean>((resolve) => {
        if (!depthTrack.muted) { resolve(true); return; }
        const timer = setTimeout(() => resolve(false), 6000);
        depthTrack.addEventListener("unmute", () => {
          clearTimeout(timer);
          resolve(true);
        }, { once: true });
      });
      if (cancelledRef.current) return;
      if (!unmuted) {
        setDebugText("WebRTC 媒体流不通 — 可能因为通过 cloudflared 隧道访问。请在局域网内直接访问 http://<机器人IP>:5173");
        console.warn("[RGBD] Depth track stayed muted — media not flowing through tunnel");
        return;
      }
    }

    setDebugText("媒体流已通，开始解码...");

    // MediaStreamTrackProcessor（Chrome 94+）
    const MSTP = (globalThis as any).MediaStreamTrackProcessor;
    if (MSTP) {
      console.log("[RGBD] Using MediaStreamTrackProcessor for depth");
      startProcessorLoop();
    } else {
      setDebugText("浏览器不支持 MediaStreamTrackProcessor — 需要 Chrome 94+");
    }

    // ── MediaStreamTrackProcessor 解码循环 ──
    async function startProcessorLoop() {
      try {
        const processor = new MSTP({ track: depthTrack });
        const reader = processor.readable.getReader();
        while (!cancelledRef.current) {
          const { value: vf, done } = await reader.read();
          if (done || cancelledRef.current) { vf?.close(); break; }
          const dw = vf.displayWidth, dh = vf.displayHeight;
          dc.width = dw; dc.height = dh;
          const dctx = dc.getContext("2d", { willReadFrequently: true })!;
          dctx.drawImage(vf, 0, 0);
          vf.close();
          const depthData = dctx.getImageData(0, 0, dw, dh).data;
          const rv = rgbVideoRef.current;
          if (!rv || rv.readyState < 2) continue;
          const rw = rv.videoWidth, rh = rv.videoHeight;
          if (rw === 0 || rh === 0) continue;
          rc.width = rw; rc.height = rh;
          const rctx = rc.getContext("2d", { willReadFrequently: true })!;
          rctx.drawImage(rv, 0, 0, rw, rh);
          const rgbData = rctx.getImageData(0, 0, rw, rh).data;
          buildPointCloud(depthData, dw, dh, rgbData, rw, rh);
        }
      } catch (e) {
        console.error("[RGBD] Processor error:", e);
        if (!cancelledRef.current) setDebugText(`Processor 错误: ${e}`);
      }
    }

    function buildPointCloud(depthData: Uint8ClampedArray, dw: number, dh: number, rgbData: Uint8ClampedArray, rw: number, rh: number) {
      const fxS = fx * (dw / nomW), fyS = fy * (dh / nomH);
      const cxS = cx * (dw / nomW), cyS = cy * (dh / nomH);
      const sX = rw / dw, sY = rh / dh;
      let count = 0;
      for (let v = 0; v < dh; v += STEP) {
        for (let u = 0; u < dw; u += STEP) {
          const di = (v * dw + u) * 4;
          const mm = (depthData[di] << 8) | depthData[di + 1];
          if (mm < 100 || mm > 8000) continue;
          const z = mm / 1000;
          positions[count * 3] = z;
          positions[count * 3 + 1] = -(((u - cxS) * z) / fxS);
          positions[count * 3 + 2] = -(((v - cyS) * z) / fyS);
          const ru = Math.min(Math.round(u * sX), rw - 1);
          const rv2 = Math.min(Math.round(v * sY), rh - 1);
          const ri = (rv2 * rw + ru) * 4;
          colors[count * 3] = rgbData[ri] / 255;
          colors[count * 3 + 1] = rgbData[ri + 1] / 255;
          colors[count * 3 + 2] = rgbData[ri + 2] / 255;
          count++;
        }
      }
      framesProcessed++;
      seqRef.current++;
      frameRef.current = { positions, colors, count, seq: seqRef.current };
      setDebugText(`${count} 点 | ${framesProcessed} 帧 | depth=${dw}×${dh} rgb=${rw}×${rh}`);
    }

    })(); // end async IIFE

    return () => { cancelledRef.current = true; cancelAnimationFrame(animRef.current); };
  }, [cameraInfo, depthStream]);

  return (
    <div className="w-full h-full bg-black relative">
      <video ref={rgbVideoRef} autoPlay playsInline muted
        style={{ position: "absolute", width: 1, height: 1, opacity: 0, pointerEvents: "none" }} />
      <Canvas camera={{ position: [2, 2, 2], fov: 60, near: 0.1, far: 50 }}
        gl={{ antialias: true, alpha: false }} style={{ background: "#0a0a0a" }}>
        <ambientLight intensity={0.3} />
        <Grid args={[20, 20]} cellSize={1} cellThickness={0.5} cellColor="#1a2a1a"
          sectionSize={5} sectionThickness={1} sectionColor="#334155"
          fadeDistance={15} position={[0, -0.01, 0]} />
        <PointCloudRenderer dataRef={frameRef} />
        <OrbitControls enableDamping dampingFactor={0.1} minDistance={0.3} maxDistance={20} maxPolarAngle={Math.PI * 0.85} />
      </Canvas>
      <div className="absolute top-2 left-2 text-[10px] font-mono bg-black/80 px-2.5 py-1.5 rounded leading-relaxed max-w-[90%]">
        <Row ok={connected} label="WebRTC" val={connected ? "已连接" : "未连接"} />
        <Row ok={!!depthStream} label="Depth" val={depthStream ? `收到(${depthStream.getVideoTracks().length}t)` : "等待"} />
        <Row ok={!!rgbStream} label="RGB" val={rgbStream ? `收到(${rgbStream.getVideoTracks().length}t)` : "等待"} />
        <Row ok={!!cameraInfo} label="内参" val={cameraInfo ? `fx=${cameraInfo.fx.toFixed(0)}` : "等待"} />
        <div className="border-t border-slate-700/50 my-0.5" />
        <div className="text-slate-300 break-all">{debugText}</div>
      </div>
      <div className="absolute bottom-2 right-2 text-xs text-slate-500 bg-black/60 px-2 py-0.5 rounded">
        拖拽旋转 / 滚轮缩放
      </div>
    </div>
  );
}

function Row({ ok, label, val }: { ok: boolean; label: string; val: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? "bg-green-500" : "bg-amber-500"}`} />
      <span className="text-slate-500 w-12">{label}</span>
      <span className="text-slate-300">{val}</span>
    </div>
  );
}
