import React, { useMemo, useState, useEffect, useRef, useCallback } from "react";
import { Canvas, useThree, useFrame } from "@react-three/fiber";
import { OrbitControls, Line, Html, Sphere } from "@react-three/drei";
import * as THREE from "three";
import { loadPGM3D } from "../lib/pgm3DParser";
import { useLaserScan, type LaserScanData } from "../hooks/useLaserScan";
import { Layers, Compass, MousePointer2, FolderOpen, Image as ImageIcon, X, Settings2, FlipHorizontal, FlipVertical, Map as MapIcon, ChevronDown, ChevronLeft, ChevronRight, Eye, EyeOff, Save, Check, Plus, Edit2, Trash2, Camera as CameraIcon, Navigation, Crosshair, Radar, Box, Gamepad2 } from "lucide-react";
import { useRosStore, type NavigationState, type ObjectSearchTrace } from "../store/rosStore";
import { useVisionStore, type VisionTab } from "../store/visionStore";

/** Pulsing beacon on target navigation node */
function TargetBeacon({ position }: { position: [number, number, number] }) {
  const ringRef = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (ringRef.current) {
      const s = 1 + 0.3 * Math.sin(clock.elapsedTime * 3);
      ringRef.current.scale.set(s, s, s);
      (ringRef.current.material as THREE.MeshBasicMaterial).opacity = 0.4 + 0.3 * Math.sin(clock.elapsedTime * 3);
    }
  });
  return (
    <mesh ref={ringRef} position={[position[0], 0.15, position[2]]} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[0.4, 0.55, 32]} />
      <meshBasicMaterial color="#f59e0b" transparent opacity={0.6} side={THREE.DoubleSide} />
    </mesh>
  );
}

/** Get node color based on search trace state */
function getNodeColor(nodeId: number, isSelected: boolean, trace: ObjectSearchTrace | null, navState: NavigationState | null): { color: string; emissive: string; emissiveIntensity: number } {
  const defaultColor = { color: isSelected ? "#60a5fa" : "#3b82f6", emissive: isSelected ? "#60a5fa" : "#1e40af", emissiveIntensity: isSelected ? 2 : 1 };
  // 导航中: 目标节点显示琥珀色
  if (navState?.isNavigating && navState.targetNodeId === nodeId) {
    return { color: "#fbbf24", emissive: "#f59e0b", emissiveIntensity: 2 };
  }
  if (!trace || trace.phase === '' || trace.phase === 'completed') {
    return defaultColor;
  }
  if (trace.found && trace.currentNodeId === nodeId) {
    return { color: "#10b981", emissive: "#10b981", emissiveIntensity: 2.5 };
  }
  if (trace.failedNodeIds.includes(nodeId)) {
    return { color: "#ef4444", emissive: "#ef4444", emissiveIntensity: 1.5 };
  }
  if (trace.visitedNodeIds.includes(nodeId)) {
    return { color: "#6b7280", emissive: "#4b5563", emissiveIntensity: 0.8 };
  }
  if (trace.candidateNodeIds.includes(nodeId)) {
    return { color: "#fbbf24", emissive: "#f59e0b", emissiveIntensity: 1.2 };
  }
  return defaultColor;
}

/** Laser scan point cloud rendered on the map */
function LaserScanCloud({ scanDataRef, poseOverride, robotPose, toLocal }: {
  scanDataRef: React.RefObject<LaserScanData | null>;
  poseOverride: { x: number; y: number; theta: number } | null;
  robotPose: { x: number; y: number; theta: number } | null;
  toLocal: (wx: number, wy: number) => number[];
}) {
  const pointsRef = useRef<THREE.Points>(null);
  const MAX_POINTS = 4096;

  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(MAX_POINTS * 3), 3));
    return geo;
  }, []);

  // Read pose directly from store to stay in sync with scan ref (both bypass React render cycle)
  const poseOverrideRef = useRef(poseOverride);
  poseOverrideRef.current = poseOverride;

  useFrame(() => {
    if (!pointsRef.current) return;
    const scan = scanDataRef.current;
    if (!scan) return;
    // Use the pose snapshot captured when this scan arrived (time-synced),
    // fall back to live pose only if snapshot is missing
    const pose = poseOverrideRef.current ?? scan.pose ?? useRosStore.getState().robotPose ?? { x: 0, y: 0, theta: 0 };
    const positions = geometry.attributes.position.array as Float32Array;
    const { ranges, angleMin, angleIncrement, rangeMax } = scan;
    let idx = 0;
    for (let i = 0; i < ranges.length && idx < MAX_POINTS; i++) {
      const r = ranges[i];
      if (r < 0.05 || r > rangeMax || !isFinite(r)) continue;
      // laser frame 相对 base_link 有 yaw=π（TF: base_link→laser），需补偿
      const angle = angleMin + i * angleIncrement + pose.theta + Math.PI;
      const wx = pose.x + r * Math.cos(angle);
      const wy = pose.y + r * Math.sin(angle);
      const p = toLocal(wx, wy);
      positions[idx * 3] = p[0];
      positions[idx * 3 + 1] = 0.2;
      positions[idx * 3 + 2] = p[2];
      idx++;
    }
    for (let i = idx; i < MAX_POINTS; i++) {
      positions[i * 3] = 0;
      positions[i * 3 + 1] = -10;
      positions[i * 3 + 2] = 0;
    }
    geometry.attributes.position.needsUpdate = true;
    geometry.setDrawRange(0, idx);
  });

  return (
    <points ref={pointsRef} geometry={geometry}>
      <pointsMaterial color="#22c55e" size={3} sizeAttenuation={false} transparent opacity={0.9} />
    </points>
  );
}

import { useMapStore, DEFAULT_CALIB } from "../store/mapStore";
import { cn } from "../lib/utils";

interface ViewpointInfo {
  angle: number;
  image_path: string;
  depth_path?: string;
  semantic_info?: {
    room_type: string;
    room_type_cn: string;
    confidence: number;
    objects: { name: string; name_cn: string; position: string; quantity: number; confidence: number }[];
    description: string;
  };
}

interface TopoNode {
  id: number;
  name: string;
  pose: { x: number; y: number; theta: number };
  viewpoints?: Record<string, ViewpointInfo>;
  semantic_info?: {
    room_type: string;
    room_type_cn: string;
    aliases: string[];
    confidence: number;
    objects?: { name: string; name_cn: string; position: string }[];
    description?: string;
  };
}

// Controller component to extract and set camera state
function CameraController({ savedCameraState, onSaveCameraState }: any) {
  const { camera } = useThree();
  const controlsRef = useRef<any>(null);

  // Restore camera state on mount if it exists
  useEffect(() => {
    if (savedCameraState && controlsRef.current) {
      camera.position.set(...savedCameraState.position);
      controlsRef.current.target.set(...savedCameraState.target);
      camera.zoom = savedCameraState.zoom;
      camera.updateProjectionMatrix();
      controlsRef.current.update();
    }
  }, []);

  // Expose save function to parent via ref or callback
  useEffect(() => {
    if (onSaveCameraState && controlsRef.current) {
      onSaveCameraState(() => {
        return {
          position: [camera.position.x, camera.position.y, camera.position.z],
          target: [controlsRef.current.target.x, controlsRef.current.target.y, controlsRef.current.target.z],
          zoom: camera.zoom
        };
      });
    }
  }, [camera, onSaveCameraState]);

  return (
    <OrbitControls 
      ref={controlsRef}
      makeDefault 
      minPolarAngle={0} 
      maxPolarAngle={Math.PI / 2 - 0.1} 
      enableDamping 
      dampingFactor={0.05} 
    />
  );
}

/**
 * LiveMapLayer - 实时渲染 OccupancyGrid (SLAM/探索过程中的地图)
 */
function LiveMapLayer({ grid }: { grid: { data: number[]; width: number; height: number; resolution: number; origin: [number, number] } }) {
  const texRef = useRef<THREE.CanvasTexture | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const texture = useMemo(() => {
    const canvas = document.createElement('canvas');
    canvas.width = grid.width;
    canvas.height = grid.height;
    canvasRef.current = canvas;
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    texRef.current = tex;
    return tex;
  }, [grid.width, grid.height]);

  // Update texture when grid data changes
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const imgData = ctx.createImageData(grid.width, grid.height);
    const pixels = imgData.data;

    for (let i = 0; i < grid.data.length; i++) {
      const val = grid.data[i];
      const idx = i * 4;
      if (val === -1 || val === 255) {
        // Unknown → transparent
        pixels[idx] = 0; pixels[idx + 1] = 0; pixels[idx + 2] = 0; pixels[idx + 3] = 0;
      } else if (val > 50) {
        // Occupied → cyan
        pixels[idx] = 56; pixels[idx + 1] = 189; pixels[idx + 2] = 248; pixels[idx + 3] = 200;
      } else {
        // Free → dark
        pixels[idx] = 15; pixels[idx + 1] = 23; pixels[idx + 2] = 42; pixels[idx + 3] = 120;
      }
    }

    ctx.putImageData(imgData, 0, 0);
    if (texRef.current) {
      texRef.current.needsUpdate = true;
    }
  }, [grid.data, grid.width, grid.height]);

  const W = grid.width * grid.resolution;
  const H = grid.height * grid.resolution;
  const cx = grid.origin[0] + W / 2;
  const cy = grid.origin[1] + H / 2;

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[cx, 0.05, -cy]}>
      <planeGeometry args={[W, H]} />
      <meshBasicMaterial map={texture} transparent opacity={0.7} side={THREE.DoubleSide} />
    </mesh>
  );
}

function MapScene({ mapData, topoNodes, selectedNode, onSelectNode, calibration, robotPose, occupancyGrid, navigationState, objectSearchTrace, setPoseMode, pendingPose, onGroundClick, onGroundMove, showScanCloud, scanDataRef, scanPoseOverride }: any) {
  const { colorCanvas, dispCanvas, width, height, config } = mapData;
  const W = width * config.resolution;
  const H = height * config.resolution;

  const colorTex = useMemo(() => {
    const tex = new THREE.CanvasTexture(colorCanvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }, [colorCanvas]);
  
  const dispTex = useMemo(() => new THREE.CanvasTexture(dispCanvas), [dispCanvas]);

  const cx = config.origin[0] + W/2;
  const cy = config.origin[1] + H/2;

  const BASE_MAP_SCALE_X = 1;
  const BASE_MAP_SCALE_Y = 1;

  const { flipMapX = false, flipMapY = false, flipNodeX = false, flipNodeY = false, showMap = true, showNodes = true, nodeOffsetX = 0, nodeOffsetY = 0 } = (calibration || {}) as any;

  // RViz 标准映射: scene.x = world.x, scene.z = -world.y
  // flipNode 在此基础上可选翻转
  const nfx = flipNodeX ? -1 : 1;   // 默认 +1（不翻转 X）
  const nfy = flipNodeY ? 1 : -1;   // 默认 -1（Y→-Z）

  // toLocal: ROS map frame → Three.js scene coords
  const toLocal = (wx: number, wy: number) => {
     return [nfx * (wx - cx), 0, nfy * (wy - cy)];
  };

  // Reverse: Three.js scene → ROS map frame
  const toWorld = (lx: number, lz: number) => {
    return { x: lx / nfx + cx, y: lz / nfy + cy };
  };

  const { camera, raycaster, pointer } = useThree();

  // Handle click on ground plane for set-pose mode
  // e.point is in toLocal coords (no group scale), toWorld directly
  const groundRef = useRef<THREE.Mesh>(null);
  const handleGroundClick = (e: any) => {
    if (!setPoseMode || !onGroundClick) return;
    e.stopPropagation();
    const point = e.point;
    // group scale 已去掉，point 就是 toLocal 坐标，直接 toWorld
    const world = toWorld(point.x, point.z);
    onGroundClick(world.x, world.y);
  };

  const handleGroundMove = (e: any) => {
    if (!setPoseMode || !pendingPose || !onGroundMove) return;
    const point = e.point;
    const world = toWorld(point.x, point.z);
    const dx = world.x - pendingPose.x;
    const dy = world.y - pendingPose.y;
    if (Math.abs(dx) > 0.01 || Math.abs(dy) > 0.01) {
      onGroundMove(Math.atan2(dy, dx));
    }
  };

  return (
    <group>
      {/* NOTE: ground plane for set-pose moved inside node group below */}

      {/* Pending pose marker — rendered at top level, outside node group */}

      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 20, 10]} intensity={1.5} color="#bae6fd" />
      <pointLight position={[0, 5, 0]} intensity={2} color="#3b82f6" />
      <pointLight position={[-5, 2, -5]} intensity={1} color="#8b5cf6" />

      <gridHelper args={[W * 1.5, 40, "#1e293b", "#0f172a"]} position={[0, -0.01, 0]} />

      {/* Live OccupancyGrid overlay */}
      {occupancyGrid && <LiveMapLayer grid={occupancyGrid} />}

      {showMap && (
        <group scale={[(flipMapX ? -1 : 1) * BASE_MAP_SCALE_X, 1, (flipMapY ? -1 : 1) * BASE_MAP_SCALE_Y]}>
          <mesh rotation={[-Math.PI/2, 0, 0]} receiveShadow castShadow>
            <planeGeometry args={[W, H, Math.min(width, 256), Math.min(height, 256)]} />
            <meshStandardMaterial
              map={colorTex}
              displacementMap={dispTex}
              displacementScale={0.5} 
              transparent={true}
              roughness={0.7}
              metalness={0.3}
            />
          </mesh>
        </group>
      )}

      {showNodes && (
        <group position={[nodeOffsetX, 0, nodeOffsetY]}>

          {/* Ground plane for set-pose click detection — inside node group for consistent coords */}
          {setPoseMode && (
            <mesh ref={groundRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]} onClick={handleGroundClick} onPointerMove={handleGroundMove}>
              <planeGeometry args={[W * 2, H * 2]} />
              <meshBasicMaterial color="#3b82f6" transparent opacity={0.08} side={THREE.DoubleSide} />
            </mesh>
          )}

          {/* Pending pose marker (blue pin) */}
          {setPoseMode && pendingPose && (() => {
            const p = toLocal(pendingPose.x, pendingPose.y);
            return (
              <group position={[p[0], 0, p[2]]} raycast={() => null}>
                <mesh position={[0, 0.6, 0]} raycast={() => null}>
                  <sphereGeometry args={[0.2, 16, 16]} />
                  <meshStandardMaterial color="#3b82f6" emissive="#3b82f6" emissiveIntensity={2} />
                </mesh>
                <mesh position={[0, 0.3, 0]} raycast={() => null}>
                  <cylinderGeometry args={[0.05, 0.05, 0.6, 8]} />
                  <meshStandardMaterial color="#3b82f6" emissive="#1e40af" emissiveIntensity={1} />
                </mesh>
                <mesh position={[0.5 * Math.cos(pendingPose.yaw || 0), 0.15, 0.5 * Math.sin(pendingPose.yaw || 0)]} rotation={[0, pendingPose.yaw || 0, 0]} raycast={() => null}>
                  <coneGeometry args={[0.15, 0.4, 8]} />
                  <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={2} />
                </mesh>
              </group>
            );
          })()}

          {topoNodes.map((n: TopoNode, i: number) => {
            if (i === 0) return null;
            const p0 = toLocal(topoNodes[i-1].pose.x, topoNodes[i-1].pose.y);
            const p1 = toLocal(n.pose.x, n.pose.y);
            return (
              <Line key={`edge-${i}`} points={[[p0[0], 0.2, p0[2]], [p1[0], 0.2, p1[2]]]} color="#38bdf8" lineWidth={2} transparent opacity={0.6} />
            );
          })}

          {topoNodes.map((n: TopoNode) => {
            const pos = toLocal(n.pose.x, n.pose.y);
            const isSelected = selectedNode?.id === n.id;
            const nodeColors = getNodeColor(n.id, isSelected, objectSearchTrace, navigationState);
            const isTarget = (navigationState?.isNavigating && navigationState.targetNodeId === n.id)
              || (objectSearchTrace?.currentNodeId === n.id && objectSearchTrace?.phase !== 'completed');
            return (
              <group key={`node-${n.id}`} position={[pos[0], pos[1], pos[2]]}>
                <mesh position={[0, 0.4, 0]} onClick={(e) => { e.stopPropagation(); onSelectNode(n); }}>
                  <octahedronGeometry args={[isSelected ? 0.3 : 0.2, 0]} />
                  <meshStandardMaterial
                    color={nodeColors.color}
                    emissive={nodeColors.emissive}
                    emissiveIntensity={nodeColors.emissiveIntensity}
                    wireframe={isSelected}
                  />
                </mesh>
                {isTarget && <TargetBeacon position={[0, 0, 0]} />}
                <Line points={[[0, 0, 0], [0, 0.4, 0]]} color={nodeColors.color} lineWidth={2} opacity={0.5} transparent />
                <Html position={[0, 0.8, 0]} center zIndexRange={[100, 0]} className="pointer-events-none">
                  <div className={cn(
                    "text-[10px] font-mono px-1.5 py-0.5 rounded backdrop-blur-md border whitespace-nowrap shadow-lg transition-all",
                    isSelected ? "bg-blue-900/80 text-blue-200 border-blue-500/50 scale-110" : "bg-slate-900/60 text-slate-400 border-slate-700/50"
                  )}>
                    {n.name}
                  </div>
                </Html>
              </group>
            )
          })}

          {/* Pose trail */}
          {navigationState?.poseTrail && navigationState.poseTrail.length > 1 && (
            <Line
              points={navigationState.poseTrail.map((p: { x: number; y: number }) => {
                const lp = toLocal(p.x, p.y);
                return [lp[0], 0.15, lp[2]] as [number, number, number];
              })}
              color="#34d399"
              lineWidth={3}
              transparent
              opacity={0.7}
            />
          )}

          {robotPose && (
            <group position={(() => {
              const p = toLocal(robotPose.x, robotPose.y);
              return [p[0], 0.5, p[2]] as [number, number, number];
            })()}
            rotation={[0, robotPose.theta || 0, 0]}
            >
              {/* cone 默认朝+Y，绕Z转-π/2使其朝+X（scene +X = world +X = 机器人前方） */}
              <mesh rotation={[0, 0, -Math.PI / 2]}>
                <coneGeometry args={[0.25, 0.6, 8]} />
                <meshStandardMaterial color="#34d399" emissive="#10b981" emissiveIntensity={1.5} />
              </mesh>
              <pointLight distance={2} intensity={2} color="#10b981" />
            </group>
          )}

          {/* Laser scan — inside node group so it shares the same scale/offset transform */}
          {showScanCloud && (
            <LaserScanCloud
              scanDataRef={scanDataRef}
              poseOverride={scanPoseOverride}
              robotPose={robotPose}
              toLocal={toLocal}
            />
          )}
        </group>
      )}
    </group>
  );
}

function getConfidenceColor(str: string, baseConf: number) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  const rand = Math.abs(hash) / 2147483648; 
  const val = Math.min(0.99, Math.max(0.3, baseConf * 0.7 + rand * 0.5));
  
  if (val > 0.85) return { val, bg: "bg-emerald-500/20", border: "border-emerald-500/30", text: "text-emerald-400" };
  if (val > 0.60) return { val, bg: "bg-blue-500/20", border: "border-blue-500/30", text: "text-blue-400" };
  return { val, bg: "bg-orange-500/20", border: "border-orange-500/30", text: "text-orange-400" };
}

const VISION_BUTTONS: { icon: React.ElementType; label: string; tab: VisionTab }[] = [
  { icon: CameraIcon, label: "相机", tab: "camera" },
  { icon: Layers,     label: "深度", tab: "rgbd" },
  { icon: Radar,      label: "LiDAR", tab: "lidar" },
  { icon: Box,        label: "伪3D", tab: "pointcloud" },
  { icon: Gamepad2,   label: "遥控", tab: "teleop" },
];

function VisionQuickBar() {
  const togglePanel = useVisionStore(s => s.togglePanel);
  const pipActivePanels = useVisionStore(s => s.pipActivePanels);
  const isPiPVisible = useVisionStore(s => s.isPiPVisible);
  const openPiP = useVisionStore(s => s.openPiP);

  return (
    <div className="absolute top-6 left-[21rem] z-50 flex items-center gap-1.5 bg-slate-900/70 backdrop-blur-md border border-slate-700/50 rounded-xl px-2 py-1.5 shadow-xl">
      {VISION_BUTTONS.map(({ icon: Icon, label, tab }) => {
        const isActive = isPiPVisible && pipActivePanels.includes(tab);
        return (
          <button
            key={tab}
            onClick={() => isPiPVisible ? togglePanel(tab) : openPiP(tab)}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[11px] font-medium transition-all",
              isActive
                ? "bg-blue-500/15 border-blue-500/30 text-blue-400"
                : "border-transparent text-slate-500 hover:text-slate-300 hover:bg-slate-800/60"
            )}
            title={label}
          >
            <Icon size={14} />
            <span className="hidden sm:inline">{label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** 纯置信度判色，无 hash 扰动 —— 用于 viewpoint 方向语义 */
function confidenceColor(conf: number) {
  if (conf >= 0.85) return { bg: "bg-emerald-500/20", border: "border-emerald-500/30", text: "text-emerald-400" };
  if (conf >= 0.60) return { bg: "bg-blue-500/20", border: "border-blue-500/30", text: "text-blue-400" };
  return { bg: "bg-orange-500/20", border: "border-orange-500/30", text: "text-orange-400" };
}

const PANORAMA_ANGLES = [0, 90, 180, 270];

/** 获取节点方向图片 URL。session 地图用 viewpoints 里的相对路径，legacy 用旧路径
 * R8++: URL 带两段 buster：
 *   - v={capture_time}  —— 后端 update_semantic 成功会 bump，保证"真有新数据"时 URL 变化
 *   - t={topoLoadNonce} —— 每次 topology re-fetch 时 bump，用来绕过浏览器"负缓存"
 *       （早期 middleware 不剥 query 时 ?v= URL 全部返 404，浏览器把这些精确 URL 记死了，
 *         即使现在服务端 200，浏览器也不会再发请求。加 t 改变 URL 形状即可绕开）。
 */
function getNodeImageUrl(node: TopoNode, angle: number, activeMap: any, topoNonce: number): string {
  const vp = node.viewpoints?.[String(angle)];
  const ct = vp && (vp as any).capture_time ? Math.floor(Number((vp as any).capture_time)) : 0;
  const q = `?v=${ct}&t=${topoNonce}`;
  if (vp?.image_path && activeMap?.source === 'session') {
    const sessionId = activeMap.id.replace('session:', '');
    return `/map-sessions/${sessionId}/${vp.image_path}${q}`;
  }
  // legacy fallback
  return `/maps/captured_nodes/node_${node.id}/${angle.toString().padStart(3, '0')}deg_rgb.png${q}`;
}

export default function MapView() {
  const [mapData, setMapData] = useState<any>(null);
  const [topoNodes, setTopoNodes] = useState<TopoNode[]>([]);
  // R8++: 每次 setTopoNodes 时 bump 这个值 → 作为 img URL 的 ?t= 绕过浏览器负缓存
  const [topoNonce, setTopoNonce] = useState<number>(() => Date.now());
  // R8++: 用 id 而非对象引用做 selectedNode 指针；panel 渲染时从最新 topoNodes 派生，
  //       保证 setTopoNodes 后 selectedNode 自动拿到新 viewpoints（含新 capture_time）
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const selectedNode = useMemo<TopoNode | null>(
    () => (selectedNodeId == null ? null : topoNodes.find(n => n.id === selectedNodeId) ?? null),
    [topoNodes, selectedNodeId]
  );
  const setSelectedNode = (n: TopoNode | null) => setSelectedNodeId(n?.id ?? null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showInspector, setShowInspector] = useState(false);

  const { maps, activeMapId, calibrations, savedCameraState, showScanOverlay, addMap, deleteMap, renameMap, updateMap, setActiveMapId, updateCalibration, saveCalibration, saveCameraState, setShowScanOverlay, discoverSessions } = useMapStore();

  // Auto-discover map sessions on mount
  useEffect(() => { discoverSessions(); }, []);
  const activeMap = maps.find(m => m.id === activeMapId) || maps[0];
  const activeMapLabel = activeMap?.label;
  const calibration = calibrations[activeMap?.id] || DEFAULT_CALIB;
  const [showMapSelector, setShowMapSelector] = useState(false);

  const [showAlignMenu, setShowAlignMenu] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveCamSuccess, setSaveCamSuccess] = useState(false);

  // Map Editor State
  const [editingMapId, setEditingMapId] = useState<string | null>(null);
  const [editMapText, setEditMapText] = useState("");

  // Add Map Modal State
  const [showAddMap, setShowAddMap] = useState(false);
  const [newMap, setNewMap] = useState({ id: "", label: "", pgm: "", yaml: "" });

  const [enlargedAngle, setEnlargedAngle] = useState<number | null>(null);
  const robotPose = useRosStore(state => state.robotPose);
  const startTask = useRosStore(state => state.startTask);
  const cancelTask = useRosStore(state => state.cancelTask);
  const executeNavigation = useRosStore(state => state.executeNavigation);
  const clearPoseTrail = useRosStore(state => state.clearPoseTrail);
  const clearSearchTrace = useRosStore(state => state.clearSearchTrace);
  const occupancyGrid = useRosStore(state => state.occupancyGrid);
  const navigationState = useRosStore(state => state.navigationState);
  const objectSearchTrace = useRosStore(state => state.objectSearchTrace);
  const taskStatus = useRosStore(state => state.taskStatus);
  const localizationQuality = useRosStore(state => state.localizationQuality);
  const setInitialPose = useRosStore(state => state.setInitialPose);

  // Set Pose mode state: step1=pick position, step2=preview yaw via mouse, confirm click
  const [setPoseMode, setSetPoseMode] = useState(false);
  const [pendingPose, setPendingPose] = useState<{ x: number; y: number } | null>(null);
  const [pendingYaw, setPendingYaw] = useState<number>(0);

  // Navigation failure toast
  const [navError, setNavError] = useState<string | null>(null);
  const prevNavStatusRef = useRef<string>('');
  useEffect(() => {
    const status = navigationState?.status || '';
    const prev = prevNavStatusRef.current;
    prevNavStatusRef.current = status;
    if (status === 'failed' && prev !== 'failed' && navigationState?.errorMessage) {
      setNavError(navigationState.errorMessage);
      const timer = setTimeout(() => setNavError(null), 8000);
      return () => clearTimeout(timer);
    }
  }, [navigationState?.status, navigationState?.errorMessage]);

  // Laser scan — show when in set-pose mode OR scan overlay toggled on
  const showScanCloud = setPoseMode || showScanOverlay;
  const { dataRef: scanDataRef } = useLaserScan(showScanCloud);

  // Arrow keys to adjust pendingPose position (0.05m per press)
  useEffect(() => {
    if (!setPoseMode || !pendingPose) return;
    const STEP = 0.05;
    const handler = (e: KeyboardEvent) => {
      let dx = 0, dy = 0;
      // RViz 标准: world+X=屏幕右, world+Y=屏幕上(远离相机)
      if (e.key === 'ArrowUp') dy = STEP;
      else if (e.key === 'ArrowDown') dy = -STEP;
      else if (e.key === 'ArrowLeft') dx = -STEP;
      else if (e.key === 'ArrowRight') dx = STEP;
      else if (e.key === 'Enter') {
        // Confirm pose
        setInitialPose(pendingPose.x, pendingPose.y, pendingYaw);
        setPendingPose(null);
        setPendingYaw(0);
        setSetPoseMode(false);
        return;
      } else if (e.key === 'Escape') {
        setPendingPose(null);
        setPendingYaw(0);
        setSetPoseMode(false);
        return;
      } else return;
      e.preventDefault();
      setPendingPose(prev => prev ? { x: prev.x + dx, y: prev.y + dy } : null);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [setPoseMode, pendingPose, pendingYaw, setInitialPose]);

  // Camera getter ref
  const getCameraStateRef = useRef<(() => any) | null>(null);

  useEffect(() => {
    async function initMap() {
      setLoading(true);
      setLoadError(null);
      try {
        const activeMap = maps.find(m => m.id === activeMapId) || maps[0];
        if (!activeMap) { setLoadError('没有可用的地图'); return; }

        // Load topo nodes
        if (activeMap.topoJson) {
          try {
            const topoRes = await fetch(activeMap.topoJson + `?t=${Date.now()}`);
            if (topoRes.ok) {
              const topoData = await topoRes.json();
              setTopoNodes(topoData.nodes || []);
              setTopoNonce(Date.now());  // R8++: bump 图片 URL ?t= buster
            } else {
              console.warn('Topo JSON not found:', activeMap.topoJson);
              setTopoNodes([]);
            }
          } catch { setTopoNodes([]); }
        }

        // Load PGM grid map (optional — session maps may not have one)
        if (activeMap.pgm) {
          try {
            const data = await loadPGM3D(activeMap.pgm, activeMap.yaml);
            setMapData(data);
          } catch (err: any) {
            console.warn('PGM load failed (using topo-only mode):', err?.message || err);
            setMapData(null);
          }
        } else {
          setMapData(null);
        }
      } catch (err: any) {
        console.error("Failed to load map:", err);
        setLoadError(err?.message || '地图加载失败');
      } finally {
        setLoading(false);
      }
    }
    initMap();
  }, [activeMapId, maps]);

  // R8++: ROS 端每个 viewpoint 的 update_semantic 落盘后，会 publish event_type='semantic_update_done'。
  // 同一次搜索会连发 4 条（四个角度），dep 用 currentNodeId + visitedNodeIds.length + eventType 确保能重复触发。
  // 兜底：也监听 taskStatus 变化（任务结束时再拉一次全量）。
  const refetchTopoTimer = useRef<number | null>(null);
  const refetchTopology = useCallback(async () => {
    const am = maps.find(m => m.id === activeMapId) || maps[0];
    if (!am?.topoJson) return;
    try {
      const res = await fetch(am.topoJson + `?t=${Date.now()}`);
      if (!res.ok) return;
      const data = await res.json();
      setTopoNodes(data.nodes || []);
      setTopoNonce(Date.now());  // 关键：bump nonce 让所有 <img> URL 形状变化，绕负缓存
    } catch {}
  }, [activeMapId, maps]);

  useEffect(() => {
    const ev = objectSearchTrace?.eventType;
    if (ev !== 'semantic_update_done') return;
    if (refetchTopoTimer.current !== null) window.clearTimeout(refetchTopoTimer.current);
    refetchTopoTimer.current = window.setTimeout(() => { refetchTopology(); }, 350) as unknown as number;
    return () => {
      if (refetchTopoTimer.current !== null) window.clearTimeout(refetchTopoTimer.current);
    };
  }, [objectSearchTrace?.eventType, objectSearchTrace?.currentNodeId,
      objectSearchTrace?.currentAngleDeg, objectSearchTrace?.visitedNodeIds?.length,
      refetchTopology]);

  // 任务结束时再保险拉一次（有些角度 update_done 可能在任务结束后才落盘）
  useEffect(() => {
    const s = taskStatus?.state;
    if (s === 'completed' || s === 'success' || s === 'failed' || s === 'cancelled') {
      const t = window.setTimeout(() => { refetchTopology(); }, 800);
      return () => window.clearTimeout(t);
    }
  }, [taskStatus?.state, taskStatus?.taskId, refetchTopology]);


  useEffect(() => {
    if (enlargedAngle === null) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setEnlargedAngle(null);
      if (e.key === "ArrowLeft") handlePrevImage();
      if (e.key === "ArrowRight") handleNextImage();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [enlargedAngle]);

  const handlePrevImage = () => {
    if (enlargedAngle === null) return;
    const currentIndex = PANORAMA_ANGLES.indexOf(enlargedAngle);
    const prevIndex = (currentIndex - 1 + PANORAMA_ANGLES.length) % PANORAMA_ANGLES.length;
    setEnlargedAngle(PANORAMA_ANGLES[prevIndex]);
  };
  const handleNextImage = () => {
    if (enlargedAngle === null) return;
    const currentIndex = PANORAMA_ANGLES.indexOf(enlargedAngle);
    const nextIndex = (currentIndex + 1) % PANORAMA_ANGLES.length;
    setEnlargedAngle(PANORAMA_ANGLES[nextIndex]);
  };

  const handleSaveCalibration = () => {
    saveCalibration();
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 2000);
  };

  const handleSaveCameraView = () => {
    if (getCameraStateRef.current) {
      const camState = getCameraStateRef.current();
      saveCameraState(camState);
      setSaveCamSuccess(true);
      setTimeout(() => setSaveCamSuccess(false), 2000);
    }
  };

  const handleAddMapSubmit = () => {
    if (!newMap.id || !newMap.label || !newMap.pgm || !newMap.yaml) return;
    addMap(newMap);
    setShowAddMap(false);
    setNewMap({ id: "", label: "", pgm: "", yaml: "" });
  };

  return (
    <div className="flex h-full w-full bg-slate-950 text-slate-200">
      
      {showAddMap && (
        <div className="fixed inset-0 z-[200] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 w-full max-w-md rounded-2xl shadow-2xl flex flex-col animate-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between p-5 border-b border-slate-800 bg-slate-950/50">
              <span className="font-bold text-slate-200">导入新环境地图</span>
              <button onClick={() => setShowAddMap(false)} className="text-slate-500 hover:text-white"><X size={18}/></button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">地图 ID (英文/数字)</label>
                <input className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-sm" placeholder="e.g. office_1" value={newMap.id} onChange={e=>setNewMap({...newMap, id: e.target.value})} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">地图显示名称 (备注)</label>
                <input className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-sm" placeholder="e.g. 办公室一楼" value={newMap.label} onChange={e=>setNewMap({...newMap, label: e.target.value})} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">PGM 路径</label>
                <input className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-sm" placeholder="/maps/your_map.pgm" value={newMap.pgm} onChange={e=>setNewMap({...newMap, pgm: e.target.value})} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">YAML 路径</label>
                <input className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-sm" placeholder="/maps/your_map.yaml" value={newMap.yaml} onChange={e=>setNewMap({...newMap, yaml: e.target.value})} />
              </div>
            </div>
            <div className="p-5 border-t border-slate-800 bg-slate-950/50 flex justify-end">
              <button onClick={handleAddMapSubmit} className="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg">保存导入</button>
            </div>
          </div>
        </div>
      )}

      {enlargedAngle !== null && selectedNode && (
        <div className="fixed inset-0 z-[100] bg-black/95 backdrop-blur-md flex flex-col items-center justify-center select-none animate-in fade-in duration-200">
          <div className="absolute top-0 left-0 right-0 h-20 bg-gradient-to-b from-black/80 to-transparent flex items-center justify-between px-8 z-50">
            <div className="flex flex-col">
              <span className="text-white font-bold text-lg tracking-wide">{selectedNode.semantic_info?.room_type_cn || selectedNode.name}</span>
              <span className="text-slate-400 font-mono text-xs">NODE_{selectedNode.id} | {enlargedAngle}° 视角</span>
            </div>
            <button className="p-2.5 bg-white/10 hover:bg-white/20 text-white rounded-full transition-colors backdrop-blur-md" onClick={() => setEnlargedAngle(null)}><X size={20} /></button>
          </div>
          <button onClick={handlePrevImage} className="absolute left-8 top-1/2 -translate-y-1/2 p-4 bg-white/5 hover:bg-white/20 text-white rounded-full transition-all hover:scale-110 backdrop-blur-md border border-white/10 z-50 shadow-[0_0_20px_rgba(0,0,0,0.5)]"><ChevronLeft size={32} /></button>
          <button onClick={handleNextImage} className="absolute right-8 top-1/2 -translate-y-1/2 p-4 bg-white/5 hover:bg-white/20 text-white rounded-full transition-all hover:scale-110 backdrop-blur-md border border-white/10 z-50 shadow-[0_0_20px_rgba(0,0,0,0.5)]"><ChevronRight size={32} /></button>
          <img key={`${enlargedAngle}-${topoNonce}`} src={getNodeImageUrl(selectedNode, enlargedAngle, activeMap, topoNonce)} className="max-w-[85vw] max-h-[85vh] rounded-lg shadow-[0_0_50px_rgba(0,0,0,0.8)] border border-slate-800 object-contain animate-in slide-in-from-bottom-4 zoom-in-95 duration-300" />
          <div className="absolute bottom-8 flex gap-3 z-50 bg-black/40 p-3 rounded-2xl backdrop-blur-md border border-white/5">
            {PANORAMA_ANGLES.map((angle) => (
              <div key={angle} onClick={() => setEnlargedAngle(angle)} className={cn("relative h-16 aspect-video rounded-md overflow-hidden cursor-pointer transition-all border-2", enlargedAngle === angle ? "border-blue-500 scale-110 shadow-[0_0_15px_rgba(59,130,246,0.5)]" : "border-transparent opacity-40 hover:opacity-80")}>
                <img key={`thumb-${angle}-${topoNonce}`} src={getNodeImageUrl(selectedNode, angle, activeMap, topoNonce)} className="w-full h-full object-cover" />
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none"><span className="text-[11px] font-mono font-bold text-white drop-shadow-[0_2px_2px_rgba(0,0,0,1)] bg-black/40 px-1.5 rounded">{angle}°</span></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* MAIN 3D CANVAS */}
      <div className="flex-1 relative overflow-hidden bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-slate-900 to-black">
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex flex-col items-center gap-4">
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500"></div>
              <span className="text-sm font-mono text-slate-400">LOADING 3D HOLOGRAPHIC MAP...</span>
            </div>
          </div>
        ) : loadError ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-center px-8">
              <span className="text-red-400 text-lg">地图加载失败</span>
              <span className="text-sm text-slate-500 font-mono max-w-md">{loadError}</span>
              <span className="text-xs text-slate-600 mt-2">请在左侧切换其他地图，或检查地图文件是否存在</span>
            </div>
          </div>
        ) : (
          <Canvas camera={{ position: [0, 10, 10], fov: 45 }} gl={{ antialias: true, alpha: false }}>
            <CameraController 
              savedCameraState={savedCameraState} 
              onSaveCameraState={(getter: any) => { getCameraStateRef.current = getter; }}
            />
            <MapScene
              mapData={mapData}
              topoNodes={topoNodes}
              selectedNode={selectedNode}
              onSelectNode={setSelectedNode}
              calibration={calibration}
              robotPose={robotPose}
              occupancyGrid={occupancyGrid}
              navigationState={navigationState}
              objectSearchTrace={objectSearchTrace}
              setPoseMode={setPoseMode}
              pendingPose={pendingPose ? { ...pendingPose, yaw: pendingYaw } : null}
              showScanCloud={showScanCloud}
              scanDataRef={scanDataRef}
              scanPoseOverride={pendingPose ? { x: pendingPose.x, y: pendingPose.y, theta: pendingYaw } : null}
              onGroundClick={(x: number, y: number) => {
                if (!pendingPose) {
                  // Step 1: set position
                  setPendingPose({ x, y });
                  setPendingYaw(0);
                } else {
                  // Step 2: confirm with current yaw
                  setInitialPose(pendingPose.x, pendingPose.y, pendingYaw);
                  setPendingPose(null);
                  setPendingYaw(0);
                  setSetPoseMode(false);
                }
              }}
              onGroundMove={(yaw: number) => {
                if (pendingPose) setPendingYaw(yaw);
              }}
            />
          </Canvas>
        )}

        {/* Localization Quality Indicator + Set Pose Button */}
        <div className="absolute top-6 right-52 z-50 flex items-center gap-2">
          {localizationQuality === 'poor' && !setPoseMode && (
            <div className="bg-amber-500/15 backdrop-blur-md border border-amber-500/30 px-3 py-2 rounded-xl text-amber-400 text-[11px] font-medium animate-pulse">
              定位不确定，建议设定初始位置
            </div>
          )}
          {/* Independent scan overlay toggle */}
          <button
            onClick={() => setShowScanOverlay(!showScanOverlay)}
            className={cn(
              "backdrop-blur-md border px-3 py-2.5 rounded-xl shadow-lg flex items-center gap-2 transition-colors text-xs font-medium",
              showScanOverlay
                ? "bg-green-500/20 border-green-500/50 text-green-400"
                : "bg-slate-900/80 border-slate-700/50 text-slate-400 hover:text-white hover:bg-slate-800"
            )}
            title="在地图上显示/隐藏激光点云"
          >
            <Layers size={16} />
            点云
          </button>
          <button
            onClick={() => { setSetPoseMode(!setPoseMode); setPendingPose(null); setPendingYaw(0); }}
            className={cn(
              "backdrop-blur-md border px-4 py-2.5 rounded-xl shadow-lg flex items-center gap-2 transition-colors text-xs font-medium",
              setPoseMode
                ? "bg-blue-500/20 border-blue-500/50 text-blue-400"
                : "bg-slate-900/80 border-slate-700/50 text-slate-400 hover:text-white hover:bg-slate-800"
            )}
          >
            <Crosshair size={16} />
            {setPoseMode
              ? (pendingPose ? "移动鼠标调整朝向，点击确认" : "点击地图选择位置...")
              : "设定位置"}
          </button>
        </div>

        {/* Set Pose Coordinate Panel */}
        {setPoseMode && pendingPose && (
          <div className="absolute bottom-6 right-6 z-50 bg-slate-900/90 backdrop-blur-md border border-blue-500/30 rounded-xl p-4 shadow-2xl min-w-[220px]">
            <div className="text-[10px] text-blue-400 uppercase tracking-wider font-bold mb-2">设定位置</div>
            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between">
                <span className="text-[11px] text-slate-400">X</span>
                <span className="text-[11px] text-white font-mono">{pendingPose.x.toFixed(3)} m</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[11px] text-slate-400">Y</span>
                <span className="text-[11px] text-white font-mono">{pendingPose.y.toFixed(3)} m</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[11px] text-slate-400">Yaw</span>
                <span className="text-[11px] text-amber-400 font-mono">{(pendingYaw * 180 / Math.PI).toFixed(1)}°</span>
              </div>
              <div className="mt-2 pt-2 border-t border-slate-700/50 text-[10px] text-slate-500 leading-relaxed">
                方向键微调位置 (0.05m/次)<br/>
                鼠标移动预览朝向<br/>
                点击确认 / Enter 确认 / Esc 取消
              </div>
              <button
                onClick={() => {
                  setInitialPose(pendingPose.x, pendingPose.y, pendingYaw);
                  setPendingPose(null); setPendingYaw(0); setSetPoseMode(false);
                }}
                className="mt-2 w-full py-1.5 rounded-lg bg-blue-500/20 border border-blue-500/30 text-blue-400 text-[11px] font-medium hover:bg-blue-500/30 transition-colors"
              >
                确认设定
              </button>
            </div>
          </div>
        )}

        {/* Robot Pose Display — always visible */}
        {robotPose && !navigationState?.isNavigating && !(setPoseMode && pendingPose) && (
          <div className="absolute bottom-6 right-6 z-40 flex flex-col items-end gap-2">
            {objectSearchTrace && (
              <button
                onClick={clearSearchTrace}
                className="bg-blue-500/15 backdrop-blur-md border border-blue-500/40 text-blue-400 hover:bg-blue-500/25 transition-colors rounded-xl px-4 py-2 text-xs font-medium shadow-lg"
              >
                重置节点状态
              </button>
            )}
            {navigationState?.poseTrail && navigationState.poseTrail.length > 0 && (
              <button
                onClick={clearPoseTrail}
                className="bg-red-500/15 backdrop-blur-md border border-red-500/40 text-red-400 hover:bg-red-500/25 transition-colors rounded-xl px-4 py-2 text-xs font-medium shadow-lg"
              >
                清除轨迹
              </button>
            )}
            <div className="bg-slate-900/80 backdrop-blur-md border border-slate-700/50 rounded-xl px-3 py-2 shadow-lg">
              <div className="text-[9px] text-emerald-400 uppercase tracking-wider font-bold mb-1">Robot Pose</div>
              <div className="flex gap-3 text-[11px] font-mono">
                <span className="text-slate-400">X <span className="text-white">{robotPose.x.toFixed(2)}</span></span>
                <span className="text-slate-400">Y <span className="text-white">{robotPose.y.toFixed(2)}</span></span>
                <span className="text-slate-400">{(robotPose.theta * 180 / Math.PI).toFixed(0)}°</span>
              </div>
            </div>
          </div>
        )}

        {/* Navigation Failure Toast */}
        {navError && (
          <div className="absolute bottom-6 right-6 z-50 max-w-sm animate-in slide-in-from-bottom-4 bg-red-500/15 backdrop-blur-md border border-red-500/40 rounded-xl p-4 shadow-2xl">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-red-500/20 flex items-center justify-center shrink-0 mt-0.5">
                <X size={16} className="text-red-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] text-red-400 font-bold uppercase tracking-wider mb-1">导航失败</div>
                <div className="text-[12px] text-red-300/90 leading-relaxed">{navError}</div>
              </div>
              <button onClick={() => setNavError(null)} className="text-red-400/60 hover:text-red-300 shrink-0">
                <X size={14} />
              </button>
            </div>
          </div>
        )}

        {/* Navigation HUD */}
        {navigationState?.isNavigating && (
          <div className="absolute bottom-6 right-6 z-50 bg-slate-900/90 backdrop-blur-md border border-slate-700/50 rounded-xl p-4 shadow-2xl min-w-[200px]">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold mb-2">
              {objectSearchTrace?.phase && objectSearchTrace.phase !== 'completed' ? '搜索导航' : '导航'}
            </div>
            <div className="flex flex-col gap-1.5">
              {objectSearchTrace?.targetObject && objectSearchTrace.phase !== 'completed' && (
                <div className="flex justify-between">
                  <span className="text-[11px] text-slate-400">目标</span>
                  <span className="text-[11px] text-amber-400 font-medium">{objectSearchTrace.targetObject}</span>
                </div>
              )}
              {objectSearchTrace?.phase && objectSearchTrace.phase !== 'completed' && (
                <div className="flex justify-between">
                  <span className="text-[11px] text-slate-400">候选</span>
                  <span className="text-[11px] text-white font-mono">{objectSearchTrace.currentCandidateIndex + 1} / {objectSearchTrace.totalCandidates}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-[11px] text-slate-400">节点</span>
                <span className="text-[11px] text-emerald-400 font-mono">Node {navigationState.targetNodeId}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[11px] text-slate-400">距离</span>
                <span className="text-[11px] text-white font-mono">{navigationState.distanceToTarget.toFixed(2)}m</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[11px] text-slate-400">ETA</span>
                <span className="text-[11px] text-white font-mono">{navigationState.estimatedTimeRemaining.toFixed(0)}s</span>
              </div>
              <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden mt-1">
                <div className="h-full bg-emerald-500 rounded-full transition-all duration-300" style={{ width: `${(taskStatus?.progress ?? 0) * 100}%` }} />
              </div>
              <button
                onClick={() => cancelTask().catch(err => console.error('[NAV] cancel error:', err))}
                className="mt-2 w-full py-2 bg-red-500/20 border border-red-500/30 text-red-400 rounded-lg text-[11px] font-medium hover:bg-red-500/30 transition-colors"
              >
                取消导航
              </button>
            </div>
          </div>
        )}

        {/* OVERLAYS: Top Left Map Selector */}
        <div className="absolute top-6 left-6 z-50">
          <div className="relative">
            <button onClick={() => setShowMapSelector(!showMapSelector)} className="bg-slate-900/80 backdrop-blur-md border border-slate-700/50 px-4 py-2.5 rounded-xl shadow-xl flex items-center gap-3 hover:bg-slate-800 transition-colors">
              <div className="w-6 h-6 rounded bg-indigo-500/20 text-indigo-400 flex items-center justify-center"><MapIcon size={14} /></div>
              <div className="flex flex-col items-start">
                <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider leading-none mb-1">当前数字地图</span>
                <span className="text-sm text-slate-200 font-medium leading-none">{activeMapLabel || "Loading..."}</span>
              </div>
              <ChevronDown size={16} className="text-slate-500 ml-2" />
            </button>

            {showMapSelector && (
              <div className="absolute top-full left-0 mt-2 w-80 bg-slate-900/95 backdrop-blur-xl border border-slate-700/50 rounded-xl shadow-2xl overflow-hidden animate-in slide-in-from-top-2 flex flex-col">
                <div className="px-4 py-3 border-b border-slate-800 bg-slate-950/50 flex justify-between items-center">
                  <span className="text-xs font-semibold text-slate-400">管理与选择地图集</span>
                  <button onClick={() => setShowAddMap(true)} className="text-blue-400 hover:text-blue-300 text-xs flex items-center gap-1"><Plus size={14}/> 导入</button>
                </div>
                <div className="flex flex-col p-1.5 max-h-[40vh] overflow-y-auto">
                  {maps.map(m => (
                    <div key={m.id} className={cn("group flex items-center justify-between px-3 py-2 rounded-lg transition-colors border border-transparent", activeMapId === m.id ? "bg-indigo-600/10 border-indigo-500/20" : "hover:bg-slate-800")}>
                      <button onClick={() => { setActiveMapId(m.id); setShowMapSelector(false); setSelectedNode(null); }} className="flex items-center gap-3 flex-1 text-left">
                        <MapIcon size={14} className={activeMapId === m.id ? "text-indigo-400" : "text-slate-500"} />
                        <div className="flex flex-col">
                          {editingMapId === m.id ? (
                            <input autoFocus className="bg-slate-950 text-white text-sm border border-slate-600 rounded px-1 outline-none w-32" value={editMapText} onChange={e=>setEditMapText(e.target.value)} onBlur={() => { renameMap(m.id, editMapText || m.label); setEditingMapId(null); }} onKeyDown={e => { if (e.key===Enter) { renameMap(m.id, editMapText || m.label); setEditingMapId(null); }}} />
                          ) : (
                            <span className={cn("text-sm font-medium", activeMapId === m.id ? "text-indigo-300" : "text-slate-300")}>{m.label}</span>
                          )}
                          <span className="text-[10px] text-slate-500 font-mono mt-0.5">{m.id}</span>
                        </div>
                      </button>
                      {editingMapId !== m.id && (
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button onClick={(e) => { e.stopPropagation(); setEditMapText(m.label); setEditingMapId(m.id); }} className="p-1.5 text-slate-500 hover:text-blue-400"><Edit2 size={14}/></button>
                          <button onClick={(e) => { e.stopPropagation(); deleteMap(m.id); }} className="p-1.5 text-slate-500 hover:text-red-400"><Trash2 size={14}/></button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* OVERLAYS: Top Right Custom Camera Actions */}
        <div className="absolute top-6 right-6 z-50">
          <button 
            className="bg-slate-900/80 backdrop-blur-md border border-slate-700/50 px-4 py-2.5 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition-colors shadow-lg flex items-center gap-2 group"
            onClick={handleSaveCameraView}
            title="保存当前的缩放、旋转和平移视角，下次刷新自动恢复"
          >
            {saveCamSuccess ? <Check size={16} className="text-green-400"/> : <CameraIcon size={16} className="group-hover:text-blue-400 transition-colors" />}
            <span className={cn("text-xs font-medium pr-1", saveCamSuccess ? "text-green-400" : "")}>
              {saveCamSuccess ? "视角已设为默认" : "锁定当前视角"}
            </span>
          </button>
        </div>

        {/* OVERLAYS: Top Center Vision Quick Buttons */}
        <VisionQuickBar />

        {/* OVERLAYS: Bottom Left Alignment Menu */}
        <div className="absolute bottom-6 left-6 z-50">
          {!showAlignMenu ? (
            <button 
              className="bg-slate-900/80 backdrop-blur-md border border-slate-700/50 p-3 rounded-full text-slate-400 hover:text-white hover:bg-slate-800 transition-colors shadow-lg flex items-center gap-2"
              onClick={() => setShowAlignMenu(true)}
              title="地图与节点对齐校准"
            >
              <Settings2 size={20} />
              <span className="text-xs font-medium pr-1">3D 图层调校</span>
            </button>
          ) : (
            <div className="bg-slate-900/90 backdrop-blur-md border border-slate-700/50 p-4 rounded-2xl shadow-2xl flex flex-col gap-5 min-w-[280px] animate-in slide-in-from-bottom-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                <span className="text-sm font-bold text-slate-200">图层对齐校准 (叠加调整)</span>
                <div className="flex items-center gap-3">
                  <button onClick={handleSaveCalibration} className="text-blue-400 hover:text-blue-300 flex items-center gap-1 text-xs transition-colors">
                    {saveSuccess ? <Check size={14} className="text-green-400"/> : <Save size={14}/>} {saveSuccess ? "已保存" : "保存坐标偏移"}
                  </button>
                  <button onClick={() => setShowAlignMenu(false)} className="text-slate-500 hover:text-white"><X size={16}/></button>
                </div>
              </div>
              
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-slate-500 uppercase">2.5D 挤出图层 (Map)</span>
                  <button onClick={() => updateCalibration(activeMap.id, { showMap: !calibration.showMap })} className={cn("text-xs flex items-center gap-1", calibration.showMap ? "text-blue-400" : "text-slate-500")}>{calibration.showMap ? <Eye size={14}/> : <EyeOff size={14}/>}</button>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => updateCalibration(activeMap.id, { flipMapX: !calibration.flipMapX })} className={cn("flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium transition-colors", calibration.flipMapX ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700")}><FlipHorizontal size={14} /> 水平翻转</button>
                  <button onClick={() => updateCalibration(activeMap.id, { flipMapY: !calibration.flipMapY })} className={cn("flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium transition-colors", calibration.flipMapY ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700")}><FlipVertical size={14} /> 上下翻转</button>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-slate-500 uppercase">全息节点图层 (Nodes)</span>
                  <button onClick={() => updateCalibration(activeMap.id, { showNodes: !calibration.showNodes })} className={cn("text-xs flex items-center gap-1", calibration.showNodes ? "text-green-400" : "text-slate-500")}>{calibration.showNodes ? <Eye size={14}/> : <EyeOff size={14}/>}</button>
                </div>
                
                {/* Node File Path Editor */}
                <div className="mb-3 flex flex-col gap-1.5">
                  <div className="flex relative">
                    <input 
                      type="text" 
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-2 pr-9 py-2 text-[10px] text-slate-300 font-mono focus:outline-none focus:border-indigo-500 transition-colors"
                      placeholder="/maps/topological_map_manual.json"
                      value={activeMap.topoJson || ""}
                      onChange={(e) => updateMap(activeMapId, { topoJson: e.target.value })}
                      title="自定义当前地图关联的拓扑节点 JSON 文件路径"
                    />
                    <label 
                      className="absolute right-1 top-1/2 -translate-y-1/2 p-1.5 bg-slate-900 hover:bg-indigo-600 text-slate-400 hover:text-white rounded-md cursor-pointer transition-colors shadow-sm"
                      title="从本地计算机选择 JSON 文件"
                    >
                      <FolderOpen size={12} />
                      <input 
                        type="file" 
                        accept=".json"
                        className="hidden"
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) {
                            // In a real Desktop App (Tauri/Electron), we would get the absolute path.
                            // For Web, we can read the file content directly and create an ObjectURL, 
                            // or just set a mock path. Since you are building a Linux App, 
                            // we will assume we eventually need the path. 
                            // For now, we set the mock path so the UI feels right.
                            updateMap(activeMapId, { topoJson: `/maps/${file.name}` });
                          }
                        }}
                      />
                    </label>
                  </div>
                  <span className="text-[9px] text-slate-500 leading-tight">
                    * 由于 Web 安全限制，目前点击左侧文件夹图标选中文件后，会自动映射到 <code className="bg-slate-900 px-1 rounded">/maps/你的文件名.json</code>。后续打包为 Tauri 桌面应用后，将直接读取本地绝对路径。
                  </span>
                </div>

                <div className="flex gap-2 mb-3">
                  <button onClick={() => updateCalibration(activeMap.id, { flipNodeX: !calibration.flipNodeX })} className={cn("flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium transition-colors", calibration.flipNodeX ? "bg-green-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700")}><FlipHorizontal size={14} /> 水平翻转</button>
                  <button onClick={() => updateCalibration(activeMap.id, { flipNodeY: !calibration.flipNodeY })} className={cn("flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium transition-colors", calibration.flipNodeY ? "bg-green-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700")}><FlipVertical size={14} /> 上下翻转</button>
                </div>
                
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 space-y-3">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-500 w-12">X 平移</span>
                    <input type="range" min="-10" max="10" step="0.1" value={calibration.nodeOffsetX} onChange={(e) => updateCalibration(activeMap.id, { nodeOffsetX: parseFloat(e.target.value) })} className="flex-1 accent-blue-500" />
                    <span className="text-xs text-slate-400 font-mono w-8 text-right">{calibration.nodeOffsetX.toFixed(1)}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-500 w-12">Y 平移</span>
                    <input type="range" min="-10" max="10" step="0.1" value={calibration.nodeOffsetY} onChange={(e) => updateCalibration(activeMap.id, { nodeOffsetY: parseFloat(e.target.value) })} className="flex-1 accent-blue-500" />
                    <span className="text-xs text-slate-400 font-mono w-8 text-right">{calibration.nodeOffsetY.toFixed(1)}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* RIGHT: Node Inspector Panel */}
      <div className={cn(
        "w-64 lg:w-80 border-l border-slate-800 bg-slate-900/50 flex flex-col z-10 shadow-[-10px_0_30px_rgba(0,0,0,0.5)] shrink-0"
      )}>
        <div className="h-16 flex items-center px-5 border-b border-slate-800 bg-slate-950 shrink-0">
          <h2 className="font-medium text-sm text-slate-300 flex items-center gap-2">
            <Layers size={16} className="text-blue-500" />
            <span className="hidden lg:inline">3D 语义详情侦测</span>
            <span className="lg:hidden">语义详情</span>
          </h2>
        </div>
        
        <div className="p-5 flex-1 overflow-y-auto">
          {!selectedNode ? (
            <div className="h-full flex flex-col items-center justify-center text-center opacity-50">
              <div className="w-16 h-16 bg-slate-800 rounded-full flex items-center justify-center mb-4 shadow-inner">
                <MousePointer2 size={24} className="text-slate-400" />
              </div>
              <p className="text-sm text-slate-400">在全息地图中点击立体晶体<br/>查看空间语义特征与实景</p>
            </div>
          ) : (
            <div className="space-y-5 animate-in fade-in slide-in-from-right-4 duration-300 pb-8">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.8)]"></div>
                  <span className="text-xs text-slate-500 font-mono">NODE_{selectedNode.id}</span>
                </div>
                <h3 className="text-2xl font-bold text-slate-100">{selectedNode.semantic_info?.room_type_cn || selectedNode.name}</h3>
              </div>

              {/* Panorama Gallery Thumbnail Grid */}
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-2">
                  <ImageIcon size={14} /> 节点实景快照 (360°)
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                  {[0, 90, 180, 270].map((angle) => (
                    <div 
                      key={angle} 
                      className="relative group aspect-video bg-slate-950 rounded-lg overflow-hidden border border-slate-800/80 cursor-pointer hover:border-blue-500/50 transition-colors shadow-inner"
                      onClick={() => setEnlargedAngle(angle)}
                    >
                      <img
                        key={`${selectedNode.id}-${angle}-${topoNonce}`}
                        src={getNodeImageUrl(selectedNode, angle, activeMap, topoNonce)}
                        alt={`Node ${selectedNode.id} at ${angle}°`}
                        className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity group-hover:scale-110 duration-500"
                        onError={(e) => {
                          // R8+: 记录失败 URL 便于排查；不再把父元素隐藏（之前 `none` 是未声明标识符，运行时抛 ReferenceError）
                          console.warn('[MapView] node image load failed:', (e.currentTarget as HTMLImageElement).src);
                        }}
                      />
                      <div className="absolute bottom-1 right-1 bg-black/70 px-1.5 py-0.5 rounded text-[9px] text-white font-mono border border-white/10 backdrop-blur-sm">
                        {angle}°
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Advanced Semantic Objects with Confidence */}
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-wider mb-3 flex justify-between items-center">
                  <span>空间包含语义</span>
                  <span className="text-slate-500 font-mono bg-slate-900 px-2 py-0.5 rounded text-[10px] border border-slate-800">
                    总体 {(selectedNode.semantic_info?.confidence * 100).toFixed(0)}% Conf
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {selectedNode.semantic_info?.aliases?.map((alias, idx) => {
                    const confColor = getConfidenceColor(alias, selectedNode.semantic_info.confidence);
                    return (
                      <div 
                        key={idx} 
                        className={cn("px-2.5 py-1.5 rounded-md border flex flex-col gap-0.5 shadow-sm group relative cursor-help transition-all hover:scale-105", confColor.bg, confColor.border)}
                      >
                        <span className={cn("text-xs font-medium", confColor.text)}>{alias}</span>
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-slate-900 border border-slate-700 rounded text-[10px] text-slate-300 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-50">
                          单体置信度: {(confColor.val * 100).toFixed(1)}%
                          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-slate-700"></div>
                        </div>
                      </div>
                    )
                  })}
                  {(!selectedNode.semantic_info?.aliases || selectedNode.semantic_info.aliases.length === 0) && (
                    <span className="text-sm text-slate-600 italic">暂无语义标注数据</span>
                  )}
                </div>
              </div>

              {/* Per-viewpoint semantic details */}
              {selectedNode.viewpoints && Object.keys(selectedNode.viewpoints).length > 0 && (
                <div>
                  <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">方向语义</div>
                  <div className="space-y-1.5">
                    {PANORAMA_ANGLES.map(angle => {
                      const vp = selectedNode.viewpoints?.[String(angle)];
                      const sem = vp?.semantic_info;
                      if (!sem) return null;
                      const roomColor = confidenceColor(sem.confidence);
                      return (
                        <div key={angle} className={cn("text-xs rounded px-2 py-1.5 border", roomColor.bg, roomColor.border)}>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-mono text-blue-400 w-8 shrink-0">{angle}°</span>
                            <span className={cn("font-medium", roomColor.text)}>{sem.room_type_cn || sem.room_type}</span>
                            <span className={cn("ml-auto text-[10px]", roomColor.text)}>{Math.round(sem.confidence * 100)}%</span>
                          </div>
                          {sem.objects && sem.objects.length > 0 && (
                            <div className="flex flex-wrap gap-1 ml-10">
                              {sem.objects.slice(0, 6).map((o, i) => {
                                const objColor = confidenceColor(o.confidence);
                                return (
                                  <span key={i} className={cn("inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border", objColor.bg, objColor.border)}>
                                    <span className={objColor.text}>{o.name_cn || o.name}</span>
                                    <span className="text-[10px] text-slate-500">{Math.round(o.confidence * 100)}%</span>
                                  </span>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="pt-2 border-t border-slate-800 flex flex-col gap-3">
                <button
                  onClick={() => {
                    const { id, pose } = selectedNode;
                    console.log('[NAV] executeNavigation:', `node_${id}`, pose);
                    executeNavigation(id, pose.x, pose.y, pose.theta || 0)
                      .then(res => console.log('[NAV] response:', res))
                      .catch(err => console.error('[NAV] error:', err));
                  }}
                  className="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-medium transition-colors flex items-center justify-center gap-2 shadow-lg shadow-blue-900/30"
                >
                  <Navigation size={18} /> 导航前往
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
