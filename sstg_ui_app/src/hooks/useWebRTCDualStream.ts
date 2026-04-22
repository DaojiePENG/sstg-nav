import { useEffect, useRef, useCallback, useState } from "react";
import { useVisionStore } from "../store/visionStore";

/**
 * useWebRTCDualStream — WebRTC 双轨道连接管理
 *
 * 从 webrtc_camera_bridge 接收两路视频:
 *   Track 0: RGB 相机画面 (320×240)
 *   Track 1: 深度图编码为 RGB (160×120)  R=高8位, G=低8位
 *
 * 同时通过信令 WebSocket 接收 camera_info (fx, fy, cx, cy)。
 *
 * 单例模式：多个组件调用此 hook 共享同一条 WebRTC 连接。
 */

const SIGNALING_PORT = 8080;
const MAX_RETRIES = 3;

export interface CameraIntrinsics {
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  width: number;
  height: number;
}

// ── 模块级单例 ──

let sharedPC: RTCPeerConnection | null = null;
let sharedWS: WebSocket | null = null;
let sharedRGBStream: MediaStream | null = null;
let sharedDepthStream: MediaStream | null = null;
let sharedCameraInfo: CameraIntrinsics | null = null;
let connectingRef = false;
let retryCountRef = 0;
let subscriberCount = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let cleanupTimer: ReturnType<typeof setTimeout> | null = null;
// 每次连接递增，用于区分新旧连接
let connectionGeneration = 0;

// 事件通知所有订阅者
type Listener = () => void;
const listeners = new Set<Listener>();
function notifyAll() {
  listeners.forEach((fn) => fn());
}

function cleanupShared() {
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  if (cleanupTimer) {
    clearTimeout(cleanupTimer);
    cleanupTimer = null;
  }
  if (sharedWS) {
    // 移除事件处理器，防止旧回调干扰新连接
    sharedWS.onclose = null;
    sharedWS.onerror = null;
    sharedWS.onmessage = null;
    sharedWS.close();
    sharedWS = null;
  }
  if (sharedPC) {
    sharedPC.ontrack = null;
    sharedPC.onicecandidate = null;
    sharedPC.onconnectionstatechange = null;
    sharedPC.close();
    sharedPC = null;
  }
  sharedRGBStream = null;
  sharedDepthStream = null;
  sharedCameraInfo = null;
  connectingRef = false;
}

/** 延迟清理：tab 切换时给新订阅者 500ms 的窗口，避免不必要的断连重连 */
function scheduleCleanup() {
  if (cleanupTimer) clearTimeout(cleanupTimer);
  cleanupTimer = setTimeout(() => {
    cleanupTimer = null;
    if (subscriberCount <= 0) {
      cleanupShared();
      notifyAll();
    }
  }, 500);
}

function connectShared(
  setCameraMode: (m: "webrtc" | "compressed" | "off") => void,
  setWebrtcConnected: (v: boolean) => void,
) {
  if (connectingRef || sharedPC) return;
  // 如果有延迟清理定时器，取消它（新的订阅者来了）
  if (cleanupTimer) {
    clearTimeout(cleanupTimer);
    cleanupTimer = null;
  }
  connectingRef = true;
  const gen = ++connectionGeneration;

  const loc = window.location;
  const wsProto = loc.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProto}//${loc.host}/webrtc`;

  console.log(`[DualStream] Connecting gen=${gen} to ${wsUrl}`);

  const ws = new WebSocket(wsUrl);
  sharedWS = ws;

  ws.onopen = async () => {
    // 检查是否已过时（被新连接取代）
    if (gen !== connectionGeneration) {
      ws.close();
      return;
    }

    const pc = new RTCPeerConnection({ iceServers: [] });
    sharedPC = pc;

    let trackCount = 0;
    let mutedCheckTimer: ReturnType<typeof setTimeout> | null = null;
    pc.ontrack = (event) => {
      if (gen !== connectionGeneration) return;
      trackCount++;
      const stream = event.streams[0] || new MediaStream([event.track]);
      if (trackCount === 1) {
        sharedRGBStream = stream;
      }
      if (trackCount === 2) {
        if (event.streams[0] && event.streams[0] !== sharedRGBStream) {
          sharedDepthStream = event.streams[0];
        } else {
          sharedDepthStream = stream;
        }
      }
      console.log(`[DualStream] Track #${trackCount}: id=${event.track.id.slice(0,8)} muted=${event.track.muted}`);

      // 监听 unmute — 如果 track 5 秒内没有 unmute，说明媒体流不通（如 cloudflared 隧道）
      const track = event.track;
      if (track.muted) {
        track.addEventListener("unmute", () => {
          console.log(`[DualStream] Track ${track.id.slice(0,8)} unmuted — media flowing`);
          if (mutedCheckTimer) { clearTimeout(mutedCheckTimer); mutedCheckTimer = null; }
        }, { once: true });

        // 只在第二个 track 到达后启动超时检测（等两个 track 都有机会 unmute）
        if (trackCount >= 2 && !mutedCheckTimer) {
          mutedCheckTimer = setTimeout(() => {
            if (gen !== connectionGeneration) return;
            // 检查是否所有 track 仍然 muted
            const allMuted = sharedRGBStream?.getVideoTracks().every(t => t.muted);
            if (allMuted) {
              console.warn("[DualStream] All tracks still muted after 5s — media not flowing, falling back");
              handleRetry(setCameraMode, setWebrtcConnected);
            }
          }, 5000);
        }
      }
      notifyAll();
    };

    pc.onicecandidate = (event) => {
      if (event.candidate && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({ type: "candidate", candidate: event.candidate }),
        );
      }
    };

    pc.onconnectionstatechange = () => {
      if (gen !== connectionGeneration) return;
      console.log(`[DualStream] PC state: ${pc.connectionState}`);
      if (pc.connectionState === "connected") {
        retryCountRef = 0;
        connectingRef = false;
        setCameraMode("webrtc");
        setWebrtcConnected(true);
        notifyAll();
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "get_camera_info" }));
        }
      }
      if (
        pc.connectionState === "failed" ||
        pc.connectionState === "disconnected"
      ) {
        setWebrtcConnected(false);
        handleRetry(setCameraMode, setWebrtcConnected);
      }
    };

    pc.addTransceiver("video", { direction: "recvonly" });
    pc.addTransceiver("video", { direction: "recvonly" });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    ws.send(JSON.stringify({ type: "offer", sdp: offer.sdp }));
  };

  ws.onmessage = async (event) => {
    if (gen !== connectionGeneration) return;
    const msg = JSON.parse(event.data);
    if (msg.type === "answer" && sharedPC) {
      await sharedPC.setRemoteDescription(
        new RTCSessionDescription({ type: "answer", sdp: msg.sdp }),
      );
    } else if (msg.type === "camera_info") {
      sharedCameraInfo = {
        fx: msg.fx,
        fy: msg.fy,
        cx: msg.cx,
        cy: msg.cy,
        width: msg.width,
        height: msg.height,
      };
      console.log(`[DualStream] Camera info received: fx=${msg.fx.toFixed(1)}`);
      notifyAll();
    } else if (msg.type === "candidate" && msg.candidate && sharedPC) {
      await sharedPC.addIceCandidate(new RTCIceCandidate(msg.candidate));
    }
  };

  ws.onerror = () => {
    if (gen !== connectionGeneration) return;
    handleRetry(setCameraMode, setWebrtcConnected);
  };
  ws.onclose = () => {
    if (gen !== connectionGeneration) return;
    if (subscriberCount > 0)
      handleRetry(setCameraMode, setWebrtcConnected);
  };
}

function handleRetry(
  setCameraMode: (m: "webrtc" | "compressed" | "off") => void,
  setWebrtcConnected: (v: boolean) => void,
) {
  cleanupShared();
  retryCountRef += 1;
  if (retryCountRef >= MAX_RETRIES) {
    console.warn(
      "[DualStream] WebRTC failed after",
      MAX_RETRIES,
      "retries, falling back to compressed",
    );
    setCameraMode("compressed");
    setWebrtcConnected(false);
    notifyAll();
  } else if (subscriberCount > 0) {
    retryTimer = setTimeout(
      () => connectShared(setCameraMode, setWebrtcConnected),
      2000,
    );
  }
}

// ── Hook ──

export function useWebRTCDualStream() {
  const setCameraMode = useVisionStore((s) => s.setCameraMode);
  const setWebrtcConnected = useVisionStore((s) => s.setWebrtcConnected);
  const cameraEnabled = useVisionStore((s) => s.cameraEnabled);
  const depthEnabled = useVisionStore((s) => s.depthEnabled);

  // 至少一个数据源需要 WebRTC
  const shouldConnect = cameraEnabled || depthEnabled;

  const [, forceUpdate] = useState(0);
  const rerender = useCallback(() => forceUpdate((n) => n + 1), []);

  useEffect(() => {
    if (!shouldConnect) return;

    subscriberCount++;
    listeners.add(rerender);

    if (!sharedPC && !connectingRef) {
      retryCountRef = 0;
      setCameraMode("webrtc");
      connectShared(setCameraMode, setWebrtcConnected);
    }

    return () => {
      subscriberCount--;
      listeners.delete(rerender);
      if (subscriberCount <= 0) {
        subscriberCount = 0;
        // 延迟清理：给 tab 切换时新组件 500ms 挂载窗口
        scheduleCleanup();
      }
    };
  }, [shouldConnect, setCameraMode, setWebrtcConnected, rerender]);

  return {
    rgbStream: sharedRGBStream,
    depthStream: sharedDepthStream,
    cameraInfo: sharedCameraInfo,
    connected: sharedPC?.connectionState === "connected",
  };
}
