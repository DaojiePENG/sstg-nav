import { create } from "zustand";

export interface MapItem {
  id: string;
  label: string;
  pgm: string;
  yaml: string;
  topoJson: string;
  /** 来源: 'legacy' = public/maps 旧地图, 'session' = map_manager/maps 新地图 */
  source?: 'legacy' | 'session';
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
  /** 从后端自动发现 map sessions */
  discoverSessions: () => Promise<void>;
}

export const DEFAULT_CALIB: MapCalibration = {
  flipMapX: false, flipMapY: false,
  flipNodeX: false, flipNodeY: false,
  nodeOffsetX: 0, nodeOffsetY: 0,
  showMap: true, showNodes: true
};

const LEGACY_MAPS: MapItem[] = [
  { id: "20260402_083419", label: "家-探索完整版 (3D)", pgm: "/maps/20260402_083419.pgm", yaml: "/maps/20260402_083419.yaml", topoJson: "/maps/topological_map_manual.json", source: 'legacy' },
  { id: "map", label: "默认 2D 地图", pgm: "/maps/map.pgm", yaml: "/maps/map.yaml", topoJson: "/maps/topological_map_manual.json", source: 'legacy' },
  { id: "house", label: "模拟 House", pgm: "/maps/house.pgm", yaml: "/maps/house.yaml", topoJson: "/maps/topological_map_manual.json", source: 'legacy' },
  { id: "rrt_map", label: "RRT 基础图", pgm: "/maps/rrt_map.pgm", yaml: "/maps/rrt_map.yaml", topoJson: "/maps/topological_map_manual.json", source: 'legacy' },
  { id: "20260327_005229", label: "早期探索快照", pgm: "/maps/20260327_005229.pgm", yaml: "/maps/20260327_005229.yaml", topoJson: "/maps/topological_map_manual.json", source: 'legacy' },
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
  maps: persisted?.maps || LEGACY_MAPS,
  activeMapId: persisted?.activeMapId || LEGACY_MAPS[0].id,
  calibrations: persisted?.calibrations || {},
  savedCameraState: persisted?.savedCameraState || null,

  addMap: (map) => set((s) => {
    const next = { maps: [...s.maps, map], activeMapId: map.id };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),
  deleteMap: (id) => set((s) => {
    const newMaps = s.maps.filter(m => m.id !== id);
    if (!newMaps.length) newMaps.push(LEGACY_MAPS[0]);
    const next = { maps: newMaps, activeMapId: s.activeMapId === id ? newMaps[0].id : s.activeMapId };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),
  renameMap: (id, newLabel) => set((s) => {
    const next = { maps: s.maps.map(m => m.id === id ? { ...m, label: newLabel } : m) };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),
  updateMap: (id, updates) => set((s) => {
    const next = { maps: s.maps.map(m => m.id === id ? { ...m, ...updates } : m) };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),
  setActiveMapId: (id) => set(() => {
    const next = { activeMapId: id };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),
  updateCalibration: (id, calib) => set((s) => {
    const old = s.calibrations[id] || DEFAULT_CALIB;
    const next = { calibrations: { ...s.calibrations, [id]: { ...old, ...calib } } };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),
  saveCameraState: (cameraState) => set(() => {
    const next = { savedCameraState: cameraState };
    localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
    return next;
  }),
  saveCalibration: () => { localStorage.setItem("sstg-map-store", JSON.stringify(get())); },

  discoverSessions: async () => {
    try {
      const res = await fetch('/api/map-sessions');
      const sessions: any[] = await res.json();
      const sessionMaps: MapItem[] = sessions
        .filter((s: any) => s.hasTopo)
        .map((s: any) => ({
          id: `session:${s.id}`,
          label: s.id,
          pgm: s.hasPgm ? `/map-sessions/${s.id}/${s.pgm}` : '',
          yaml: s.yaml ? `/map-sessions/${s.id}/${s.yaml}` : '',
          topoJson: `/map-sessions/${s.id}/topological_map.json`,
          source: 'session' as const,
        }));
      set((state) => {
        const legacy = state.maps.filter(m => m.source !== 'session');
        const allMaps = [...sessionMaps, ...legacy];
        const allIds = allMaps.map(m => m.id);
        const activeMapId = allIds.includes(state.activeMapId) ? state.activeMapId : allMaps[0]?.id || '';
        const next = { maps: allMaps, activeMapId };
        localStorage.setItem("sstg-map-store", JSON.stringify({ ...get(), ...next }));
        return next;
      });
    } catch (e) {
      console.warn('Failed to discover map sessions:', e);
    }
  },
}));
