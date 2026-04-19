import { useEffect, useRef, useCallback } from "react";
import * as ROSLIB from "roslib";
import { useRosStore } from "../store/rosStore";

/**
 * useLaserScan — 订阅 /scan (sensor_msgs/LaserScan)
 * 使用 useRef 存储数据，避免高频 setState 导致 re-render
 */

export interface LaserScanData {
  ranges: number[];
  angleMin: number;
  angleMax: number;
  angleIncrement: number;
  rangeMin: number;
  rangeMax: number;
  timestamp: number;
  /** Pose snapshot at the time this scan was received */
  pose: { x: number; y: number; theta: number } | null;
}

export function useLaserScan(enabled: boolean) {
  const ros = useRosStore((s) => s.ros);
  const isConnected = useRosStore((s) => s.isConnected);
  const dataRef = useRef<LaserScanData | null>(null);
  const callbackRef = useRef<((data: LaserScanData) => void) | null>(null);

  /** 注册回调，每当有新数据时调用 */
  const onData = useCallback((cb: (data: LaserScanData) => void) => {
    callbackRef.current = cb;
  }, []);

  useEffect(() => {
    if (!enabled || !ros || !isConnected) return;

    const topic = new ROSLIB.Topic({
      ros,
      name: "/scan",
      messageType: "sensor_msgs/msg/LaserScan",
      throttle_rate: 120, // ~8fps, balance between smoothness and performance
    } as any);

    topic.subscribe((msg: any) => {
      const data: LaserScanData = {
        ranges: msg.ranges,
        angleMin: msg.angle_min,
        angleMax: msg.angle_max,
        angleIncrement: msg.angle_increment,
        rangeMin: msg.range_min,
        rangeMax: msg.range_max,
        timestamp: Date.now(),
        pose: useRosStore.getState().robotPose,
      };
      dataRef.current = data;
      callbackRef.current?.(data);
    });

    return () => {
      topic.unsubscribe();
    };
  }, [enabled, ros, isConnected]);

  return { dataRef, onData };
}
