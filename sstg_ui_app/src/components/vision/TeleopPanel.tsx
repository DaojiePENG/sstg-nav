import { useEffect, useRef, useCallback, useState, memo } from "react";
import * as ROSLIB from "roslib";
import { useRosStore } from "../../store/rosStore";

// ── 速度限制范围 ──
const LINEAR_MIN = 0.05;
const LINEAR_MAX = 0.5;
const LINEAR_STEP = 0.05;
const LINEAR_DEFAULT = 0.25;

const ANGULAR_MIN = 0.1;
const ANGULAR_MAX = 2.0;
const ANGULAR_STEP = 0.1;
const ANGULAR_DEFAULT = 1.0;

const PUBLISH_HZ = 10; // 发布频率

// ── 按键映射 ──
type DirKey = "w" | "a" | "s" | "d" | "q" | "e";
const DIR_KEYS = new Set<DirKey>(["w", "a", "s", "d", "q", "e"]);

function isDirKey(k: string): k is DirKey {
  return DIR_KEYS.has(k as DirKey);
}

// ── 按钮样式定义 ──
interface BtnDef {
  label: string;
  sub: string;
  color: string;
  hoverColor: string;
  action: string;
}

const MOVE_BTN = (label: string, sub: string, action: string): BtnDef => ({
  label, sub, color: "bg-blue-600", hoverColor: "hover:bg-blue-500", action,
});
const ROT_BTN = (label: string, sub: string, action: string): BtnDef => ({
  label, sub, color: "bg-purple-600", hoverColor: "hover:bg-purple-500", action,
});
const ANG_BTN = (label: string, sub: string, action: string): BtnDef => ({
  label, sub, color: "bg-purple-500", hoverColor: "hover:bg-purple-400", action,
});
const LIN_BTN = (label: string, sub: string, action: string): BtnDef => ({
  label, sub, color: "bg-sky-500", hoverColor: "hover:bg-sky-400", action,
});

// 第一行: Q W E   R T
const ROW1: (BtnDef | null)[] = [
  ROT_BTN("↺", "Q", "q"),
  MOVE_BTN("▲", "W", "w"),
  ROT_BTN("↻", "E", "e"),
  null, // gap
  ANG_BTN("⟳+", "R", "angular+"),
  ANG_BTN("⟳−", "T", "angular-"),
];

// 第二行: A S D   F G
const ROW2: (BtnDef | null)[] = [
  MOVE_BTN("◀", "A", "a"),
  MOVE_BTN("▼", "S", "s"),
  MOVE_BTN("▶", "D", "d"),
  null, // gap
  LIN_BTN("»", "F", "linear+"),
  LIN_BTN("«", "G", "linear-"),
];

function TeleopPanel() {
  const ros = useRosStore((s) => s.ros);
  const isConnected = useRosStore((s) => s.isConnected);

  const [linearLimit, setLinearLimit] = useState(LINEAR_DEFAULT);
  const [angularLimit, setAngularLimit] = useState(ANGULAR_DEFAULT);

  // 用 ref 追踪按下的方向键集合，避免 re-render
  const pressedRef = useRef(new Set<DirKey>());
  const publisherRef = useRef<ROSLIB.Topic | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const linearRef = useRef(LINEAR_DEFAULT);
  const angularRef = useRef(ANGULAR_DEFAULT);

  // 同步 state → ref
  useEffect(() => { linearRef.current = linearLimit; }, [linearLimit]);
  useEffect(() => { angularRef.current = angularLimit; }, [angularLimit]);

  // 创建 publisher
  useEffect(() => {
    if (!ros) { publisherRef.current = null; return; }
    const topic = new ROSLIB.Topic({
      ros,
      name: "/cmd_vel",
      messageType: "geometry_msgs/msg/Twist",
    });
    publisherRef.current = topic;
    return () => { publisherRef.current = null; };
  }, [ros]);

  // 发布 Twist
  const publishTwist = useCallback((lx: number, ly: number, az: number) => {
    if (!publisherRef.current) return;
    publisherRef.current.publish({
      linear: { x: lx, y: ly, z: 0 },
      angular: { x: 0, y: 0, z: az },
    });
  }, []);

  // 从按下的键集合计算速度并发布
  const publishFromKeys = useCallback(() => {
    const keys = pressedRef.current;
    let lx = 0, ly = 0, az = 0;
    const sl = linearRef.current;
    const sa = angularRef.current;

    if (keys.has("w")) lx += sl;
    if (keys.has("s")) lx -= sl;
    if (keys.has("a")) ly += sl;
    if (keys.has("d")) ly -= sl;
    if (keys.has("q")) az += sa;
    if (keys.has("e")) az -= sa;

    publishTwist(lx, ly, az);
  }, [publishTwist]);

  // 停止
  const stopAll = useCallback(() => {
    pressedRef.current.clear();
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    publishTwist(0, 0, 0);
  }, [publishTwist]);

  // 启动定时器
  const ensureTimer = useCallback(() => {
    if (timerRef.current) return;
    timerRef.current = setInterval(publishFromKeys, 1000 / PUBLISH_HZ);
  }, [publishFromKeys]);

  // 键盘事件
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 忽略输入框中的按键
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      const k = e.key.toLowerCase();

      if (k === " ") {
        e.preventDefault();
        stopAll();
        return;
      }

      if (isDirKey(k)) {
        e.preventDefault();
        pressedRef.current.add(k);
        ensureTimer();
        publishFromKeys(); // 立即发一帧
        return;
      }

      // 变速键
      if (k === "r") {
        setAngularLimit((v) => Math.min(ANGULAR_MAX, +(v + ANGULAR_STEP).toFixed(2)));
      } else if (k === "t") {
        setAngularLimit((v) => Math.max(ANGULAR_MIN, +(v - ANGULAR_STEP).toFixed(2)));
      } else if (k === "f") {
        setLinearLimit((v) => Math.min(LINEAR_MAX, +(v + LINEAR_STEP).toFixed(2)));
      } else if (k === "g") {
        setLinearLimit((v) => Math.max(LINEAR_MIN, +(v - LINEAR_STEP).toFixed(2)));
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (isDirKey(k)) {
        pressedRef.current.delete(k);
        if (pressedRef.current.size === 0) {
          stopAll();
        }
      }
    };

    const handleBlur = () => stopAll();

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    window.addEventListener("blur", handleBlur);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      window.removeEventListener("blur", handleBlur);
      // 卸载时安全停车
      stopAll();
    };
  }, [stopAll, ensureTimer, publishFromKeys]);

  // 按钮点击处理（按下 / 松开）
  const handleBtnDown = useCallback(
    (action: string) => {
      if (isDirKey(action)) {
        pressedRef.current.add(action);
        ensureTimer();
        publishFromKeys();
      } else if (action === "angular+") {
        setAngularLimit((v) => Math.min(ANGULAR_MAX, +(v + ANGULAR_STEP).toFixed(2)));
      } else if (action === "angular-") {
        setAngularLimit((v) => Math.max(ANGULAR_MIN, +(v - ANGULAR_STEP).toFixed(2)));
      } else if (action === "linear+") {
        setLinearLimit((v) => Math.min(LINEAR_MAX, +(v + LINEAR_STEP).toFixed(2)));
      } else if (action === "linear-") {
        setLinearLimit((v) => Math.max(LINEAR_MIN, +(v - LINEAR_STEP).toFixed(2)));
      } else if (action === "stop") {
        stopAll();
      }
    },
    [ensureTimer, publishFromKeys, stopAll],
  );

  const handleBtnUp = useCallback(
    (action: string) => {
      if (isDirKey(action)) {
        pressedRef.current.delete(action);
        if (pressedRef.current.size === 0) stopAll();
      }
    },
    [stopAll],
  );

  const renderBtn = (def: BtnDef) => (
    <button
      key={def.action}
      onMouseDown={() => handleBtnDown(def.action)}
      onMouseUp={() => handleBtnUp(def.action)}
      onMouseLeave={() => handleBtnUp(def.action)}
      onTouchStart={(e) => { e.preventDefault(); handleBtnDown(def.action); }}
      onTouchEnd={(e) => { e.preventDefault(); handleBtnUp(def.action); }}
      className={`w-[42px] h-[42px] ${def.color} ${def.hoverColor} rounded-lg flex flex-col items-center justify-center text-white select-none active:scale-95 transition-all shadow-md cursor-pointer`}
    >
      <span className="text-[14px] leading-none">{def.label}</span>
      <span className="text-[8px] opacity-60 leading-none mt-0.5">{def.sub}</span>
    </button>
  );

  const renderRow = (row: (BtnDef | null)[]) => (
    <div className="flex gap-[3px] items-center">
      {row.map((def, i) =>
        def === null ? <div key={`gap-${i}`} className="w-[8px]" /> : renderBtn(def),
      )}
    </div>
  );

  return (
    <div className="w-full h-full bg-slate-950 flex flex-col items-center justify-center p-3 select-none">
      {/* 连接状态 */}
      {!isConnected && (
        <div className="text-[10px] text-red-400 mb-2">ROS2 未连接</div>
      )}

      {/* 上部: 实时速度信息 */}
      <div className="flex justify-center gap-4 text-[11px] mb-3">
        <span className="text-slate-400">
          线速{" "}
          <span className="text-blue-400 font-semibold text-[13px]">
            {linearLimit.toFixed(2)}
          </span>{" "}
          <span className="text-slate-600 text-[9px]">m/s</span>
        </span>
        <span className="text-slate-400">
          角速{" "}
          <span className="text-purple-400 font-semibold text-[13px]">
            {angularLimit.toFixed(2)}
          </span>{" "}
          <span className="text-slate-600 text-[9px]">rad/s</span>
        </span>
      </div>

      {/* 中部: 键盘按键区 */}
      <div className="flex flex-col gap-[3px] items-center">
        {renderRow(ROW1)}
        {renderRow(ROW2)}

        {/* 急停 */}
        <div className="flex gap-[3px] mt-[3px]">
          <button
            onMouseDown={() => handleBtnDown("stop")}
            onTouchStart={(e) => { e.preventDefault(); handleBtnDown("stop"); }}
            className="w-[134px] h-[36px] bg-red-600 hover:bg-red-500 rounded-lg flex items-center justify-center text-white text-[11px] font-bold select-none active:scale-95 transition-all shadow-md cursor-pointer gap-1.5"
          >
            ⏹ 急停
            <span className="text-[9px] opacity-60">Space</span>
          </button>
        </div>
      </div>

      {/* 下部: 按键说明 */}
      <div className="mt-3 text-center text-[9px] text-slate-600 leading-relaxed">
        <span className="text-blue-500">WASD</span> 移动{" · "}
        <span className="text-purple-500">QE</span> 旋转{" · "}
        <span className="text-purple-400">RT</span> 角速{" · "}
        <span className="text-sky-400">FG</span> 线速{" · "}
        <span className="text-red-500">Space</span> 停
      </div>
    </div>
  );
}

export default memo(TeleopPanel);
