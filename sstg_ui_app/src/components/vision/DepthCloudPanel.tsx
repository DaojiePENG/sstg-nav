import { useRef, useMemo, useCallback, useEffect, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Grid } from "@react-three/drei";
import * as THREE from "three";
import { useVisionStore } from "../../store/visionStore";
import { useLaserScan, type LaserScanData } from "../../hooks/useLaserScan";
import { useWebRTCDualStream } from "../../hooks/useWebRTCDualStream";
import {
  useDepthToPointCloud,
  type PointCloudData,
} from "../../hooks/useDepthToPointCloud";

/**
 * 3D 点云面板 — 三级降级
 *
 * Level 1/2: 真 RGB-D 彩色点云 (WebRTC 深度 + RGB 双轨道)
 * Level 3 (默认): 2D LaserScan 在 Three.js 中伪 3D 展示
 */

// ── Level 3: 伪 3D (LaserScan) ──

function LaserScan3DScene() {
  const pointCloudEnabled = useVisionStore((s) => s.pointCloudEnabled);
  const { onData } = useLaserScan(pointCloudEnabled);

  const pointsRef = useRef<THREE.Points>(null);
  const linesRef = useRef<THREE.LineSegments>(null);

  const maxPoints = 1440;
  const positions = useMemo(() => new Float32Array(maxPoints * 3), []);
  const colors = useMemo(() => new Float32Array(maxPoints * 3), []);
  const linePositions = useMemo(() => new Float32Array(maxPoints * 2 * 3), []);

  const updateGeometry = useCallback(
    (data: LaserScanData) => {
      const { ranges, angleMin, angleIncrement, rangeMin, rangeMax } = data;
      let idx = 0;
      let lineIdx = 0;

      for (let i = 0; i < ranges.length; i++) {
        const r = ranges[i];
        if (r < rangeMin || r > rangeMax || !isFinite(r)) continue;

        const angle = angleMin + i * angleIncrement;
        // 激光雷达安装旋转 180°：scan angle=π 是车头
        // 修正：加 π 偏移，使 Three.js +X 方向 = 车头前方
        const corrected = angle + Math.PI;
        const x = r * Math.cos(corrected);
        const y = r * Math.sin(corrected);
        const z = 0;

        // Three.js: X=前方(车头), Y=上, Z=右
        positions[idx * 3] = x;
        positions[idx * 3 + 1] = z;
        positions[idx * 3 + 2] = -y;

        const t = Math.min(r / rangeMax, 1);
        colors[idx * 3] = t * 0.3;
        colors[idx * 3 + 1] = 0.4 + (1 - t) * 0.6;
        colors[idx * 3 + 2] = t * 0.2;

        linePositions[lineIdx++] = 0;
        linePositions[lineIdx++] = 0;
        linePositions[lineIdx++] = 0;
        linePositions[lineIdx++] = x;
        linePositions[lineIdx++] = z;
        linePositions[lineIdx++] = -y;

        idx++;
      }

      if (pointsRef.current) {
        const geom = pointsRef.current.geometry;
        geom.setAttribute(
          "position",
          new THREE.BufferAttribute(positions.slice(0, idx * 3), 3),
        );
        geom.setAttribute(
          "color",
          new THREE.BufferAttribute(colors.slice(0, idx * 3), 3),
        );
        geom.attributes.position.needsUpdate = true;
        geom.attributes.color.needsUpdate = true;
        geom.setDrawRange(0, idx);
      }

      if (linesRef.current) {
        const geom = linesRef.current.geometry;
        geom.setAttribute(
          "position",
          new THREE.BufferAttribute(linePositions.slice(0, lineIdx), 3),
        );
        geom.attributes.position.needsUpdate = true;
        geom.setDrawRange(0, lineIdx / 3);
      }
    },
    [positions, colors, linePositions],
  );

  useEffect(() => {
    onData(updateGeometry);
  }, [onData, updateGeometry]);

  return (
    <>
      <points ref={pointsRef}>
        <bufferGeometry />
        <pointsMaterial size={3} vertexColors sizeAttenuation={false} />
      </points>
      <lineSegments ref={linesRef}>
        <bufferGeometry />
        <lineBasicMaterial color="#22c55e" opacity={0.1} transparent />
      </lineSegments>
      {/* 三棱锥指向 +X = 车头前方 */}
      <mesh position={[0.2, 0.05, 0]} rotation={[0, 0, -Math.PI / 2]}>
        <coneGeometry args={[0.12, 0.3, 3]} />
        <meshBasicMaterial color="#3b82f6" />
      </mesh>
      {/* 车头方向标注线 */}
      <line>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[new Float32Array([0, 0.06, 0, 0.6, 0.06, 0]), 3]}
          />
        </bufferGeometry>
        <lineBasicMaterial color="#60a5fa" opacity={0.6} transparent />
      </line>
    </>
  );
}

// ── Level 1/2: 真 RGB-D 彩色点云 ──

function RGBDPointCloudScene() {
  const pointCloudEnabled = useVisionStore((s) => s.pointCloudEnabled);
  const setDepthEnabled = useVisionStore((s) => s.setDepthEnabled);
  const setCameraEnabled = useVisionStore((s) => s.setCameraEnabled);

  // 确保 depth + camera 双流启用
  useEffect(() => {
    if (pointCloudEnabled) {
      setDepthEnabled(true);
      setCameraEnabled(true);
    }
    return () => {
      setDepthEnabled(false);
    };
  }, [pointCloudEnabled, setDepthEnabled, setCameraEnabled]);

  const { depthStream, rgbStream, cameraInfo, connected } =
    useWebRTCDualStream();
  const { onData } = useDepthToPointCloud(
    depthStream,
    rgbStream,
    cameraInfo,
    pointCloudEnabled,
  );

  const pointsRef = useRef<THREE.Points>(null);
  const MAX_POINTS = 20000;
  const posBuffer = useMemo(() => new Float32Array(MAX_POINTS * 3), []);
  const colBuffer = useMemo(() => new Float32Array(MAX_POINTS * 3), []);

  const updatePointCloud = useCallback(
    (data: PointCloudData) => {
      if (!pointsRef.current) return;
      const geom = pointsRef.current.geometry;
      const n = Math.min(data.count, MAX_POINTS);

      // ROS 坐标 → Three.js 坐标:  Three.x = ROS.x, Three.y = ROS.z, Three.z = -ROS.y
      for (let i = 0; i < n; i++) {
        const rosX = data.positions[i * 3];
        const rosY = data.positions[i * 3 + 1];
        const rosZ = data.positions[i * 3 + 2];
        posBuffer[i * 3] = rosX;
        posBuffer[i * 3 + 1] = rosZ; // Three Y = ROS Z (上)
        posBuffer[i * 3 + 2] = -rosY; // Three Z = -ROS Y
      }

      // 颜色直接复制
      colBuffer.set(data.colors.subarray(0, n * 3));

      geom.setAttribute(
        "position",
        new THREE.BufferAttribute(posBuffer.slice(0, n * 3), 3),
      );
      geom.setAttribute(
        "color",
        new THREE.BufferAttribute(colBuffer.slice(0, n * 3), 3),
      );
      geom.attributes.position.needsUpdate = true;
      geom.attributes.color.needsUpdate = true;
      geom.setDrawRange(0, n);
      geom.computeBoundingSphere();
    },
    [posBuffer, colBuffer],
  );

  useEffect(() => {
    onData(updatePointCloud);
  }, [onData, updatePointCloud]);

  return (
    <>
      <points ref={pointsRef}>
        <bufferGeometry />
        <pointsMaterial size={2} vertexColors sizeAttenuation />
      </points>
      {/* 等待数据提示 */}
      {!connected && (
        <mesh position={[0, 1, 0]}>
          <boxGeometry args={[0.3, 0.3, 0.3]} />
          <meshBasicMaterial color="#f59e0b" wireframe />
        </mesh>
      )}
      {/* 相机位置标记 */}
      <mesh position={[0, 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.1, 0.2, 4]} />
        <meshBasicMaterial color="#3b82f6" />
      </mesh>
    </>
  );
}

// ── 旋转扫描平面 (仅 Level 3) ──

function ScanPlane() {
  const meshRef = useRef<THREE.Mesh>(null);
  useFrame((_, delta) => {
    if (meshRef.current) meshRef.current.rotation.y += delta * 0.5;
  });

  return (
    <mesh
      ref={meshRef}
      position={[0, 0.01, 0]}
      rotation={[-Math.PI / 2, 0, 0]}
    >
      <ringGeometry args={[0.05, 6, 64, 1, 0, Math.PI / 6]} />
      <meshBasicMaterial
        color="#22c55e"
        opacity={0.05}
        transparent
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

// ── Level 切换 UI ──

function LevelSelector() {
  const level = useVisionStore((s) => s.pointCloudLevel);
  const setLevel = useVisionStore((s) => s.setPointCloudLevel);

  return (
    <div className="absolute top-2 right-2 flex gap-1 bg-black/70 rounded-lg p-1">
      {([
        [3, "伪3D"],
        [1, "真3D"],
      ] as [1 | 2 | 3, string][]).map(([lv, label]) => (
        <button
          key={lv}
          onClick={() => setLevel(lv)}
          className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
            level === lv
              ? "bg-blue-600 text-white"
              : "text-slate-400 hover:text-white hover:bg-slate-700"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

// ── 主组件 ──

export default function DepthCloudPanel() {
  const enabled = useVisionStore((s) => s.pointCloudEnabled);
  const level = useVisionStore((s) => s.pointCloudLevel);

  if (!enabled) {
    return (
      <div className="w-full h-full flex items-center justify-center text-slate-500 text-sm">
        点云未启用
      </div>
    );
  }

  return (
    <div className="w-full h-full bg-black relative">
      <Canvas
        camera={{ position: [3, 3, 3], fov: 60, near: 0.1, far: 100 }}
        gl={{ antialias: true, alpha: false }}
        style={{ background: "#0a0a0a" }}
      >
        <ambientLight intensity={0.3} />

        <Grid
          args={[20, 20]}
          cellSize={1}
          cellThickness={0.5}
          cellColor="#1a2a1a"
          sectionSize={5}
          sectionThickness={1}
          sectionColor="#334155"
          fadeDistance={15}
          position={[0, -0.01, 0]}
        />

        {level === 3 && <ScanPlane />}
        {level === 3 && <LaserScan3DScene />}
        {level < 3 && <RGBDPointCloudScene />}

        <OrbitControls
          enableDamping
          dampingFactor={0.1}
          minDistance={0.5}
          maxDistance={20}
          maxPolarAngle={Math.PI * 0.85}
        />
      </Canvas>

      {/* Level 切换 */}
      <LevelSelector />

      {/* 状态标注 */}
      <div className="absolute top-2 left-2 flex items-center gap-1.5 text-xs bg-black/60 px-2 py-1 rounded">
        <span className="w-2 h-2 rounded-full bg-green-500" />
        <span className="text-slate-300">
          {level === 3
            ? "伪3D (LaserScan)"
            : "RGB-D 彩色点云 (WebRTC)"}
        </span>
      </div>
      <div className="absolute bottom-2 right-2 text-xs text-slate-500 bg-black/60 px-2 py-0.5 rounded">
        拖拽旋转 / 滚轮缩放 / 蓝色锥体 = 车头
      </div>
    </div>
  );
}
