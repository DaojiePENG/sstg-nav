import { useEffect, useRef, useCallback } from "react";
import * as ROSLIB from "roslib";
import { useRosStore } from "../store/rosStore";

/**
 * useDepthImage — 订阅 /camera/depth/image_raw (16UC1)
 * 通过 rosbridge 传输，解码为 Uint16Array
 * 然后渲染 JET 伪彩色到 Canvas
 */

export interface DepthImageData {
  /** 原始 16bit 深度值 (mm) */
  depth: Uint16Array;
  width: number;
  height: number;
  timestamp: number;
}

export function useDepthImage(enabled: boolean) {
  const ros = useRosStore((s) => s.ros);
  const isConnected = useRosStore((s) => s.isConnected);
  const callbackRef = useRef<((data: DepthImageData) => void) | null>(null);

  const onData = useCallback((cb: (data: DepthImageData) => void) => {
    callbackRef.current = cb;
  }, []);

  useEffect(() => {
    if (!enabled || !ros || !isConnected) return;

    const topic = new ROSLIB.Topic({
      ros,
      name: "/camera/depth/image_raw",
      messageType: "sensor_msgs/msg/Image",
      throttle_rate: 200, // ~5fps, 深度图数据量大
    } as any);

    topic.subscribe((msg: any) => {
      const w: number = msg.width;
      const h: number = msg.height;
      const encoding: string = msg.encoding;

      let depth: Uint16Array;

      if (encoding === "16UC1") {
        // base64 → Uint8Array → Uint16Array
        const raw = Uint8Array.from(atob(msg.data), (c) => c.charCodeAt(0));
        depth = new Uint16Array(raw.buffer);
      } else if (encoding === "32FC1") {
        const raw = Uint8Array.from(atob(msg.data), (c) => c.charCodeAt(0));
        const floats = new Float32Array(raw.buffer);
        depth = new Uint16Array(floats.length);
        for (let i = 0; i < floats.length; i++) {
          depth[i] = Math.round(floats[i] * 1000);
        }
      } else {
        return; // 不支持的编码
      }

      callbackRef.current?.({ depth, width: w, height: h, timestamp: Date.now() });
    });

    return () => {
      topic.unsubscribe();
    };
  }, [enabled, ros, isConnected]);

  return { onData };
}
