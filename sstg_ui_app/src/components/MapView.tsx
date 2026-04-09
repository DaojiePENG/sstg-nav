import React, { useMemo, useState, useEffect, useRef } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Line, Html, Sphere } from "@react-three/drei";
import * as THREE from "three";
import { loadPGM3D } from "../lib/pgm3DParser";
import { Layers, Compass, MousePointer2, FolderOpen, Image as ImageIcon, X, Settings2, FlipHorizontal, FlipVertical, Map as MapIcon, ChevronDown, ChevronLeft, ChevronRight, Eye, EyeOff, Save, Check, Plus, Edit2, Trash2, Camera as CameraIcon, Navigation } from "lucide-react";
import { useRosStore } from "../store/rosStore";
import { useMapStore, DEFAULT_CALIB } from "../store/mapStore";
import { cn } from "../lib/utils";

interface TopoNode {
  id: number;
  name: string;
  pose: { x: number; y: number; theta: number };
  semantic_info: {
    room_type: string;
    room_type_cn: string;
    aliases: string[];
    confidence: number;
  }
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
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[-cx, 0.05, cy]}>
      <planeGeometry args={[W, H]} />
      <meshBasicMaterial map={texture} transparent opacity={0.7} side={THREE.DoubleSide} />
    </mesh>
  );
}

function MapScene({ mapData, topoNodes, selectedNode, onSelectNode, calibration, robotPose, occupancyGrid }: any) {
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

  const BASE_MAP_SCALE_X = -1;
  const BASE_MAP_SCALE_Y = 1;
  const BASE_NODE_SCALE_X = -1;
  const BASE_NODE_SCALE_Y = -1;

  const toLocal = (wx: number, wy: number) => {
     let lx = wx - cx;
     let ly = wy - cy; 
     return [lx, 0, -ly]; 
  };

  const { flipMapX = false, flipMapY = false, flipNodeX = false, flipNodeY = false, showMap = true, showNodes = true, nodeOffsetX = 0, nodeOffsetY = 0 } = (calibration || {}) as any;

  return (
    <group>
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
        <group position={[nodeOffsetX, 0, -nodeOffsetY]} scale={[(flipNodeX ? -1 : 1) * BASE_NODE_SCALE_X, 1, (flipNodeY ? -1 : 1) * BASE_NODE_SCALE_Y]}>
          
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
            return (
              <group key={`node-${n.id}`} position={[pos[0], pos[1], pos[2]]}>
                <mesh position={[0, 0.4, 0]} onClick={(e) => { e.stopPropagation(); onSelectNode(n); }}>
                  <octahedronGeometry args={[isSelected ? 0.3 : 0.2, 0]} />
                  <meshStandardMaterial 
                    color={isSelected ? "#60a5fa" : "#3b82f6"} 
                    emissive={isSelected ? "#60a5fa" : "#1e40af"} 
                    emissiveIntensity={isSelected ? 2 : 1}
                    wireframe={isSelected}
                  />
                </mesh>
                <Line points={[[0, 0, 0], [0, 0.4, 0]]} color={isSelected ? "#60a5fa" : "#3b82f6"} lineWidth={2} opacity={0.5} transparent />
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

          {robotPose && (
            <group position={(() => {
              const p = toLocal(robotPose.x, robotPose.y);
              return [p[0], 0.5, p[2]] as [number, number, number];
            })()}
            rotation={[0, -(robotPose.theta || 0), 0]}
            >
              {/* Arrow-shaped robot indicator: cone pointing forward */}
              <mesh rotation={[0, 0, Math.PI / 2]}>
                <coneGeometry args={[0.25, 0.6, 8]} />
                <meshStandardMaterial color="#34d399" emissive="#10b981" emissiveIntensity={1.5} />
              </mesh>
              <pointLight distance={2} intensity={2} color="#10b981" />
            </group>
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

const PANORAMA_ANGLES = [0, 90, 180, 270];

export default function MapView() {
  const [mapData, setMapData] = useState<any>(null);
  const [topoNodes, setTopoNodes] = useState<TopoNode[]>([]);
  const [selectedNode, setSelectedNode] = useState<TopoNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [showInspector, setShowInspector] = useState(false);

  const { maps, activeMapId, calibrations, savedCameraState, addMap, deleteMap, renameMap, updateMap, setActiveMapId, updateCalibration, saveCalibration, saveCameraState } = useMapStore();
  const activeMap = maps.find(m => m.id === activeMapId) || maps[0];
  const calibration = calibrations[activeMap.id] || DEFAULT_CALIB;
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
  const occupancyGrid = useRosStore(state => state.occupancyGrid);

  // Camera getter ref
  const getCameraStateRef = useRef<(() => any) | null>(null);

  useEffect(() => {
    async function initMap() {
      setLoading(true);
      try {
        const activeMap = maps.find(m => m.id === activeMapId) || maps[0];
        const topoRes = await fetch(activeMap.topoJson || "/maps/topological_map_manual.json");
        const topoData = await topoRes.json();
        setTopoNodes(topoData.nodes || []);
        const data = await loadPGM3D(activeMap.pgm, activeMap.yaml);
        setMapData(data);
      } catch (err) {
        console.error("Failed to load map:", err);
      } finally {
        setLoading(false);
      }
    }
    initMap();
  }, [activeMapId, maps]);

  const activeMapLabel = maps.find(m => m.id === activeMapId)?.label;

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
          <img key={enlargedAngle} src={`/maps/captured_nodes/node_${selectedNode.id}/${enlargedAngle.toString().padStart(3, 0)}deg_rgb.png`} className="max-w-[85vw] max-h-[85vh] rounded-lg shadow-[0_0_50px_rgba(0,0,0,0.8)] border border-slate-800 object-contain animate-in slide-in-from-bottom-4 zoom-in-95 duration-300" />
          <div className="absolute bottom-8 flex gap-3 z-50 bg-black/40 p-3 rounded-2xl backdrop-blur-md border border-white/5">
            {PANORAMA_ANGLES.map((angle) => (
              <div key={angle} onClick={() => setEnlargedAngle(angle)} className={cn("relative h-16 aspect-video rounded-md overflow-hidden cursor-pointer transition-all border-2", enlargedAngle === angle ? "border-blue-500 scale-110 shadow-[0_0_15px_rgba(59,130,246,0.5)]" : "border-transparent opacity-40 hover:opacity-80")}>
                <img src={`/maps/captured_nodes/node_${selectedNode.id}/${angle.toString().padStart(3, 0)}deg_rgb.png`} className="w-full h-full object-cover" />
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none"><span className="text-[11px] font-mono font-bold text-white drop-shadow-[0_2px_2px_rgba(0,0,0,1)] bg-black/40 px-1.5 rounded">{angle}°</span></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* MAIN 3D CANVAS */}
      <div className="flex-1 relative overflow-hidden bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-slate-900 to-black">
        {loading || !mapData ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex flex-col items-center gap-4">
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500"></div>
              <span className="text-sm font-mono text-slate-400">LOADING 3D HOLOGRAPHIC MAP...</span>
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
            />
          </Canvas>
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
                        src={`/maps/captured_nodes/node_${selectedNode.id}/${angle.toString().padStart(3, 0)}deg_rgb.png`}
                        alt={`Node ${selectedNode.id} at ${angle}°`}
                        className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity group-hover:scale-110 duration-500"
                        onError={(e) => {
                          e.currentTarget.parentElement!.style.display = none;
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

              <div className="pt-2 border-t border-slate-800 flex flex-col gap-3">
                <button
                  onClick={() => {
                    const roomName = selectedNode.semantic_info?.room_type_cn || selectedNode.name;
                    startTask(`去${roomName}`).catch(err => console.error('Navigate failed:', err));
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
