import { create } from "zustand";

export type VisionTab = "camera" | "lidar" | "pointcloud" | "rgbd" | "teleop";

interface VisionState {
  /* ── PiP 窗口 ── */
  isPiPVisible: boolean;
  pipPosition: { x: number; y: number };
  pipSize: { width: number; height: number };
  /** 多选：同时显示的面板集合 */
  pipActivePanels: VisionTab[];
  pipMinimized: boolean;

  /* ── 相机 ── */
  cameraEnabled: boolean;
  cameraMode: "webrtc" | "compressed" | "off";
  webrtcConnected: boolean;

  /* ── LiDAR ── */
  lidarEnabled: boolean;

  /* ── 深度 ── */
  depthEnabled: boolean;

  /* ── 点云 ── */
  pointCloudLevel: 1 | 2 | 3;
  pointCloudEnabled: boolean;

  /* ── Actions ── */
  openPiP: (tab?: VisionTab) => void;
  closePiP: () => void;
  toggleMinimize: () => void;
  setPiPPosition: (pos: { x: number; y: number }) => void;
  setPiPSize: (size: { width: number; height: number }) => void;
  /** 切换某个面板的勾选状态 */
  togglePanel: (tab: VisionTab) => void;
  setCameraMode: (mode: "webrtc" | "compressed" | "off") => void;
  setWebrtcConnected: (v: boolean) => void;
  setCameraEnabled: (v: boolean) => void;
  setLidarEnabled: (v: boolean) => void;
  setPointCloudEnabled: (v: boolean) => void;
  setPointCloudLevel: (level: 1 | 2 | 3) => void;
  setDepthEnabled: (v: boolean) => void;

  /** @deprecated 兼容旧代码，等同于 pipActivePanels[0] */
  pipActiveTab: VisionTab;
  setActiveTab: (tab: VisionTab) => void;
}

const DEFAULT_SIZE = { width: 720, height: 400 };
const defaultPosition = () => ({
  x: Math.max(window.innerWidth - DEFAULT_SIZE.width - 24, 24),
  y: Math.max(window.innerHeight - DEFAULT_SIZE.height - 24, 24),
});

/** 根据激活面板集合，推导哪些数据源需要启用 */
function deriveDataSources(panels: VisionTab[], pointCloudLevel: number) {
  const has = (t: VisionTab) => panels.includes(t);
  return {
    cameraEnabled: has("camera") || has("rgbd"),
    lidarEnabled: has("lidar") || has("pointcloud"),
    pointCloudEnabled: has("pointcloud"),
    depthEnabled: has("rgbd") || (has("pointcloud") && pointCloudLevel < 3),
  };
}

export const useVisionStore = create<VisionState>((set, get) => ({
  isPiPVisible: false,
  pipPosition: defaultPosition(),
  pipSize: { ...DEFAULT_SIZE },
  pipActivePanels: [],
  pipMinimized: false,

  cameraEnabled: false,
  cameraMode: "off",
  webrtcConnected: false,

  lidarEnabled: false,
  depthEnabled: false,

  pointCloudLevel: 3,
  pointCloudEnabled: false,

  // 兼容旧代码
  pipActiveTab: "camera",

  openPiP: (tab) =>
    set((s) => {
      let panels = [...s.pipActivePanels];
      if (tab && !panels.includes(tab)) {
        panels.push(tab);
      }
      if (panels.length === 0) panels = ["camera"];
      return {
        isPiPVisible: true,
        pipMinimized: false,
        pipActivePanels: panels,
        pipActiveTab: tab ?? panels[0],
        ...deriveDataSources(panels, s.pointCloudLevel),
      };
    }),

  closePiP: () =>
    set({
      isPiPVisible: false,
      pipActivePanels: [],
      cameraEnabled: false,
      lidarEnabled: false,
      pointCloudEnabled: false,
      depthEnabled: false,
      cameraMode: "off",
      webrtcConnected: false,
    }),

  toggleMinimize: () => set((s) => ({ pipMinimized: !s.pipMinimized })),

  setPiPPosition: (pos) => set({ pipPosition: pos }),
  setPiPSize: (size) => set({ pipSize: size }),

  togglePanel: (tab) =>
    set((s) => {
      let panels = [...s.pipActivePanels];
      if (panels.includes(tab)) {
        panels = panels.filter((t) => t !== tab);
      } else {
        panels.push(tab);
      }
      // 如果全部取消勾选，关闭 PiP
      if (panels.length === 0) {
        return {
          isPiPVisible: false,
          pipActivePanels: [],
          cameraEnabled: false,
          lidarEnabled: false,
          pointCloudEnabled: false,
          depthEnabled: false,
          cameraMode: "off",
          webrtcConnected: false,
        };
      }
      return {
        isPiPVisible: true,
        pipActivePanels: panels,
        pipActiveTab: panels[0],
        ...deriveDataSources(panels, s.pointCloudLevel),
      };
    }),

  // 兼容旧 setActiveTab（单选行为：清空其他，只保留选中的）
  setActiveTab: (tab) =>
    set((s) => ({
      pipActiveTab: tab,
      pipActivePanels: [tab],
      ...deriveDataSources([tab], s.pointCloudLevel),
    })),

  setCameraMode: (mode) => set({ cameraMode: mode }),
  setWebrtcConnected: (v) => set({ webrtcConnected: v }),
  setCameraEnabled: (v) => set({ cameraEnabled: v }),
  setLidarEnabled: (v) => set({ lidarEnabled: v }),
  setPointCloudEnabled: (v) => set({ pointCloudEnabled: v }),
  setPointCloudLevel: (level) => set({ pointCloudLevel: level }),
  setDepthEnabled: (v) => set({ depthEnabled: v }),
}));
