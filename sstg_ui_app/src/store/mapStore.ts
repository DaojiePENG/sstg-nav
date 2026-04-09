import { create } from "zustand";

export interface MapItem {
  id: string;
  label: string;
  pgm: string;
  yaml: string;
  topoJson: string;
}

export interface MapCalibration {
  flipMapX: boolean;
  flipMapY: boolean;
  flipNodeX: boolean;
  flipNodeY: boolean;
  nodeOffsetX: number;
  nodeOffsetY: number;
  showMap: boolean;
  showNodes: boolean;
}

export interface CameraState {
  position: [number, number, number];
  target: [number, number, number];
  zoom: number;
}

interface MapState {
  maps: MapItem[];
  activeMapId: string;
  calibrations: Record<string, MapCalibration>;
  savedCameraState: CameraState | null;
  addMap: (map: MapItem) => void;
  deleteMap: (id: string) => void;
  renameMap: (id: string, newLabel: string) => void;
  updateMap: (id: string, updates: Partial<MapItem>) => void;
  setActiveMapId: (id: string) => void;
  updateCalibration: (id: string, calib: Partial<MapCalibration>) => void;
  saveCameraState: (cameraState: CameraState) => void;
  saveCalibration: () => void;
}

export const DEFAULT_CALIB: MapCalibration = {
  flipMapX: false, flipMapY: false,
  flipNodeX: false, flipNodeY: false,
  nodeOffsetX: 0, nodeOffsetY: 0,
  showMap: true, showNodes: true
};

const DEFAULT_MAPS: MapItem[] = [
  { id: "20260402_083419", label: "家-探索完整版 (3D)", pgm: "/maps/20260402_083419.pgm", yaml: "/maps/20260402_083419.yaml", topoJson: "/maps/topological_map_manual.json" },
  { id: "map", label: "默认 2D 地图", pgm: "/maps/map.pgm", yaml: "/maps/map.yaml", topoJson: "/maps/topological_map_manual.json" },
  { id: "house", label: "模拟 House", pgm: "/maps/house.pgm", yaml: "/maps/house.yaml", topoJson: "/maps/topological_map_manual.json" },
  { id: "rrt_map", label: "RRT 基础图", pgm: "/maps/rrt_map.pgm", yaml: "/maps/rrt_map.yaml", topoJson: "/maps/topological_map_manual.json" },
  { id: "20260327_005229", label: "早期探索快照", pgm: "/maps/20260327_005229.pgm", yaml: "/maps/20260327_005229.yaml", topoJson: "/maps/topological_map_manual.json" }
];

const loadPersisted = () => {
  try {
    const stored = localStorage.getItem("sstg-map-store");
    if (stored) return JSON.parse(stored);
  } catch (e) {}
  return null;
};

const persisted = loadPersisted();

export const useMapStore = create<MapState>((set, get) => ({
  maps: persisted?.maps?.map((m: any) => ({...m, topoJson: m.topoJson || "/maps/topological_map_manual.json"})) || DEFAULT_MAPS,
  activeMapId: persisted?.activeMapId || DEFAULT_MAPS[0].id,
  calibrations: persisted?.calibrations || (persisted?.calibration ? { [persisted.activeMapId || DEFAULT_MAPS[0].id]: persisted.calibration } : {}),
  savedCameraState: persisted?.savedCameraState || null,

  addMap: (map) => set((state) => {
    const next = { maps: [...state.maps, map], activeMapId: map.id };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),

  deleteMap: (id) => set((state) => {
    const newMaps = state.maps.filter(m => m.id !== id);
    if (newMaps.length === 0) newMaps.push(DEFAULT_MAPS[0]);
    const next = { maps: newMaps, activeMapId: state.activeMapId === id ? newMaps[0].id : state.activeMapId };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),

  renameMap: (id, newLabel) => set((state) => {
    const next = { maps: state.maps.map(m => m.id === id ? { ...m, label: newLabel } : m) };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),

  updateMap: (id, updates) => set((state) => {
    const next = { maps: state.maps.map(m => m.id === id ? { ...m, ...updates } : m) };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),

  setActiveMapId: (id) => set((state) => {
    const next = { activeMapId: id };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),

  updateCalibration: (id, calib) => set((state) => {
    const oldCalib = state.calibrations[id] || DEFAULT_CALIB;
    const nextCalib = { ...oldCalib, ...calib };
    const next = { calibrations: { ...state.calibrations, [id]: nextCalib } };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),

  saveCameraState: (cameraState) => set((state) => {
    const next = { savedCameraState: cameraState };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),

  saveCalibration: () => {
    localStorage.setItem("sstg-map-store", JSON.stringify(get()));
  }
}));
