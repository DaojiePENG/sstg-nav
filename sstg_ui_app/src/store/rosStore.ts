import { create } from "zustand";
import * as ROSLIB from "roslib";

interface SystemStatus {
  mode: string;
  cpu: number;
  memory: number;
  devices: { name: string; path: string; ok: boolean }[];
  nodeCount: number;
  activeNodes: string[];
}

export interface NavigationState {
  isNavigating: boolean;
  targetNodeId: number;
  distanceToTarget: number;
  estimatedTimeRemaining: number;
  status: string;
  errorMessage: string;
  poseTrail: { x: number; y: number }[];
}

export interface ObjectSearchTrace {
  taskId: string;
  targetObject: string;
  phase: string;
  eventType: string;
  currentNodeId: number;
  candidateNodeIds: number[];
  visitedNodeIds: number[];
  failedNodeIds: number[];
  currentCandidateIndex: number;
  totalCandidates: number;
  found: boolean;
  confidence: number;
}

interface RosState {
  ros: ROSLIB.Ros | null;
  isConnected: boolean;
  robotPose: { x: number; y: number; theta: number } | null;
  localizationQuality: 'good' | 'poor' | 'unknown';
  taskStatus: { state: string; message: string; progress: number; taskId: string } | null;
  systemStatus: SystemStatus | null;
  systemLogs: string[];
  occupancyGrid: {
    data: number[];
    width: number;
    height: number;
    resolution: number;
    origin: [number, number];
  } | null;
  navigationState: NavigationState | null;
  objectSearchTrace: ObjectSearchTrace | null;
  connect: (url?: string) => void;
  disconnect: () => void;
  startTask: (text: string, context?: string, sessionId?: string, senderName?: string) => Promise<any>;
  cancelTask: () => Promise<boolean>;
  deleteChatSession: (sessionId: string) => Promise<any>;
  launchMode: (mode: string) => Promise<any>;
  getSystemStatus: () => Promise<any>;
  restartNode: (nodeName: string, killDuplicates: boolean) => Promise<any>;
  updateLLMConfig: (baseUrl: string, apiKey: string, model: string) => Promise<any>;
  executeNavigation: (nodeId: number, x: number, y: number, theta: number) => Promise<any>;
  setInitialPose: (x: number, y: number, yaw: number) => void;
  clearPoseTrail: () => void;
}

const MAX_LOGS = 200;

/** 四元数 → yaw (弧度) */
function quaternionToYaw(q: { x: number; y: number; z: number; w: number }): number {
  const siny = 2.0 * (q.w * q.z + q.x * q.y);
  const cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z);
  return Math.atan2(siny, cosy);
}

/** 解析设备状态字符串 "OK:底盘 CH340:/dev/ttyUSB1" */
function parseDeviceStatus(raw: string[]): { name: string; path: string; ok: boolean }[] {
  return raw.map(s => {
    const parts = s.split(':');
    return {
      ok: parts[0] === 'OK',
      name: parts[1] || 'Unknown',
      path: parts[2] || '',
    };
  });
}

export const useRosStore = create<RosState>((set, get) => ({
  ros: null,
  isConnected: false,
  robotPose: null,
  localizationQuality: 'unknown' as const,
  taskStatus: null,
  systemStatus: null,
  systemLogs: [],
  occupancyGrid: null,
  navigationState: null,
  objectSearchTrace: null,

  connect: (url?: string) => {
    if (get().ros) return;

    // 自动检测 WebSocket 地址：
    // 本地开发 → ws://localhost:9090
    // 公网访问（Tailscale Funnel / Cloudflare Tunnel）→ 走 /rosbridge 代理
    if (!url) {
      const loc = window.location;
      const isLocal = loc.hostname === 'localhost' || loc.hostname === '127.0.0.1';
      if (isLocal) {
        url = 'ws://localhost:9090';
      } else {
        const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
        url = `${wsProto}//${loc.host}/rosbridge`;
      }
    }

    const tryConnect = () => {
      const ros = new ROSLIB.Ros({ url });

      ros.on("connection", () => {
        console.log("Connected to websocket server.");
        set({ isConnected: true, ros });

      // ── /amcl_pose: 始终可用的机器人位姿（空闲+导航） ──
      const amclPoseSub = new ROSLIB.Topic({
        ros,
        name: "/amcl_pose",
        messageType: "geometry_msgs/msg/PoseWithCovarianceStamped",
        throttle_rate: 100,
      } as any);
      amclPoseSub.subscribe((message: any) => {
        const pose = message.pose?.pose;
        if (!pose) return;
        const theta = quaternionToYaw(pose.orientation || { x: 0, y: 0, z: 0, w: 1 });
        set({ robotPose: { x: pose.position.x, y: pose.position.y, theta } });

        // 协方差判断定位质量: covariance[0]=xx, [7]=yy, [35]=yaw-yaw
        const cov = message.pose?.covariance;
        if (cov && cov.length >= 36) {
          const posVar = cov[0] + cov[7];  // x + y 方差之和
          const quality = posVar > 0.5 ? 'poor' : 'good';
          set({ localizationQuality: quality as 'good' | 'poor' });
        }
      });

      // ── /navigation_feedback: 机器人位姿 + 导航状态 ──
      const feedbackSub = new ROSLIB.Topic({
        ros,
        name: "/navigation_feedback",
        messageType: "sstg_msgs/msg/NavigationFeedback"
      });
      feedbackSub.subscribe((message: any) => {
        const pose = message.current_pose;
        let theta = 0;
        if (pose?.orientation) {
          theta = quaternionToYaw(pose.orientation);
        }
        const newX = pose?.position?.x || 0;
        const newY = pose?.position?.y || 0;
        set({ robotPose: { x: newX, y: newY, theta } });

        const status = message.status || '';
        const isNavigating = status === 'starting' || status === 'in_progress';
        const prevNav = get().navigationState;
        const prevTrail = prevNav?.poseTrail || [];

        let trail = prevTrail;
        if (isNavigating) {
          const last = prevTrail[prevTrail.length - 1];
          const dx = last ? newX - last.x : 1;
          const dy = last ? newY - last.y : 1;
          if (!last || Math.sqrt(dx * dx + dy * dy) > 0.05) {
            trail = [...prevTrail, { x: newX, y: newY }].slice(-500);
          }
        }

        set({
          navigationState: {
            isNavigating,
            targetNodeId: message.node_id ?? 0,
            distanceToTarget: message.distance_to_target ?? 0,
            estimatedTimeRemaining: message.estimated_time_remaining ?? 0,
            status,
            errorMessage: message.error_message || '',
            poseTrail: trail,
          }
        });
      });

      // ── /object_search_trace: 搜索追踪 ──
      const searchTraceSub = new ROSLIB.Topic({
        ros,
        name: "/object_search_trace",
        messageType: "sstg_msgs/msg/ObjectSearchTrace"
      });
      searchTraceSub.subscribe((message: any) => {
        const prevTrace = get().objectSearchTrace;
        // 新任务时清空轨迹
        if (prevTrace && prevTrace.taskId !== message.task_id) {
          set({ navigationState: { ...get().navigationState!, poseTrail: [] } });
        }
        set({
          objectSearchTrace: {
            taskId: message.task_id || '',
            targetObject: message.target_object || '',
            phase: message.phase || '',
            eventType: message.event_type || '',
            currentNodeId: message.current_node_id ?? -1,
            candidateNodeIds: message.candidate_node_ids || [],
            visitedNodeIds: message.visited_node_ids || [],
            failedNodeIds: message.failed_node_ids || [],
            currentCandidateIndex: message.current_candidate_index ?? 0,
            totalCandidates: message.total_candidates ?? 0,
            found: message.found ?? false,
            confidence: message.confidence ?? 0,
          }
        });
      });

      // ── /task_status: 任务状态 ──
      const taskStatusSub = new ROSLIB.Topic({
        ros,
        name: "/task_status",
        messageType: "sstg_msgs/msg/TaskStatus"
      });
      taskStatusSub.subscribe((message: any) => {
        set({
          taskStatus: {
            state: message.state,
            message: message.current_message,
            progress: message.progress,
            taskId: message.task_id || '',
          }
        });
      });

      // ── /system/status: 系统状态 (CPU/内存/设备) ──
      const systemStatusSub = new ROSLIB.Topic({
        ros,
        name: "/system/status",
        messageType: "sstg_msgs/msg/SystemStatus"
      });
      systemStatusSub.subscribe((message: any) => {
        set(state => ({
          systemStatus: {
            mode: message.mode || 'idle',
            cpu: message.cpu_percent ?? 0,
            memory: message.memory_percent ?? 0,
            devices: parseDeviceStatus(message.device_status || []),
            nodeCount: message.active_node_count ?? 0,
            activeNodes: state.systemStatus?.activeNodes || [],
          }
        }));
      });

      // ── /system/log: 系统日志 ──
      const systemLogSub = new ROSLIB.Topic({
        ros,
        name: "/system/log",
        messageType: "std_msgs/msg/String"
      });
      systemLogSub.subscribe((message: any) => {
        set(state => ({
          systemLogs: [...state.systemLogs.slice(-(MAX_LOGS - 1)), message.data],
        }));
      });

      // ── /map: 实时 OccupancyGrid ──
      const mapSub = new ROSLIB.Topic({
        ros,
        name: "/map",
        messageType: "nav_msgs/msg/OccupancyGrid",
        throttle_rate: 2000,
      } as any);
      mapSub.subscribe((message: any) => {
        set({
          occupancyGrid: {
            data: message.data,
            width: message.info.width,
            height: message.info.height,
            resolution: message.info.resolution,
            origin: [
              message.info.origin.position.x,
              message.info.origin.position.y,
            ],
          }
        });
      });

      // ── 重连后主动拉取一次当前状态（不依赖 topic 被动推送）──
      const queryTaskStatus = new ROSLIB.Service({
        ros,
        name: "/query_task_status",
        serviceType: "std_srvs/srv/Trigger"
      });
      queryTaskStatus.callService({}, (result: any) => {
        if (result?.success) {
          set({
            taskStatus: {
              state: result.message || 'idle',
              message: '',
              progress: result.message === 'completed' ? 1.0 : 0,
              taskId: '',
            }
          });
        }
      }, () => {});

      const querySystemStatus = new ROSLIB.Service({
        ros,
        name: "/system/get_status",
        serviceType: "sstg_msgs/srv/GetSystemStatus"
      });
      querySystemStatus.callService({}, (result: any) => {
        if (result) {
          set({
            systemStatus: {
              mode: result.mode || 'idle',
              cpu: result.cpu_percent ?? 0,
              memory: result.memory_percent ?? 0,
              devices: parseDeviceStatus(result.device_status || []),
              nodeCount: result.active_node_count ?? 0,
              activeNodes: result.active_nodes || [],
            }
          });
        }
      }, () => {});
    });

    ros.on("error", (error) => {
      console.error("Error connecting to websocket server: ", error);
    });

    ros.on("close", () => {
      console.log("Connection to websocket server closed. Reconnecting in 3s...");
      set({ isConnected: false, ros: null, systemStatus: null, systemLogs: [], taskStatus: null });
      setTimeout(() => {
        if (!get().ros) tryConnect();
      }, 3000);
    });
    };

    tryConnect();
  },

  disconnect: () => {
    const { ros } = get();
    if (ros) {
      ros.close();
    }
  },

  startTask: (text: string, context = "home", sessionId = "", senderName = "") => {
    return new Promise((resolve, reject) => {
      const { ros, isConnected } = get();
      if (!ros || !isConnected) return reject("ROS not connected");

      const startTaskClient = new ROSLIB.Service({
        ros,
        name: "/start_task",
        serviceType: "sstg_msgs/srv/ProcessNLPQuery"
      });

      startTaskClient.callService(
        { text_input: text, context, session_id: sessionId, sender_name: senderName },
        (result: any) => resolve(result),
        (error: any) => reject(error),
      );
    });
  },

  deleteChatSession: (sessionId: string) => {
    return new Promise((resolve, reject) => {
      const { ros, isConnected } = get();
      if (!ros || !isConnected) return resolve(false);

      const client = new ROSLIB.Service({
        ros,
        name: "/nlp/delete_session",
        serviceType: "sstg_msgs/srv/DeleteChatSession"
      });

      client.callService(
        { session_id: sessionId },
        (result: any) => resolve(result?.success ?? false),
        () => resolve(false),
      );
    });
  },

  cancelTask: () => {
    return new Promise((resolve, reject) => {
      const { ros, isConnected } = get();
      if (!ros || !isConnected) return reject("ROS not connected");

      const cancelClient = new ROSLIB.Service({
        ros,
        name: "/cancel_task",
        serviceType: "std_srvs/srv/Trigger"
      });

      cancelClient.callService(
        {},
        (result: any) => resolve(result.success),
        (error: any) => reject(error),
      );
    });
  },

  launchMode: (mode: string) => {
    return new Promise((resolve, reject) => {
      const { ros, isConnected } = get();
      if (!ros || !isConnected) return reject("ROS not connected");

      const client = new ROSLIB.Service({
        ros,
        name: "/system/launch_mode",
        serviceType: "sstg_msgs/srv/LaunchMode"
      });

      client.callService(
        { mode },
        (result: any) => resolve(result),
        (error: any) => reject(error),
      );
    });
  },

  getSystemStatus: () => {
    return new Promise((resolve, reject) => {
      const { ros, isConnected } = get();
      if (!ros || !isConnected) return reject("ROS not connected");

      const client = new ROSLIB.Service({
        ros,
        name: "/system/get_status",
        serviceType: "sstg_msgs/srv/GetSystemStatus"
      });

      client.callService(
        {},
        (result: any) => {
          set(state => ({
            systemStatus: {
              // 保留已有的 cpu/memory/devices/nodeCount（来自 topic 推送）
              mode: 'idle',
              cpu: 0,
              memory: 0,
              devices: [],
              nodeCount: 0,
              activeNodes: [],
              ...state.systemStatus,
              // 用 service 返回的数据覆盖 activeNodes 和 mode
              activeNodes: result.active_nodes || [],
              mode: result.mode || state.systemStatus?.mode || 'idle',
            },
          }));
          resolve(result);
        },
        (error: any) => reject(error),
      );
    });
  },

  restartNode: (nodeName: string, killDuplicates: boolean) => {
    return new Promise((resolve, reject) => {
      const { ros, isConnected } = get();
      if (!ros || !isConnected) return reject("ROS not connected");

      const client = new ROSLIB.Service({
        ros,
        name: "/system/restart_node",
        serviceType: "sstg_msgs/srv/RestartNode"
      });

      client.callService(
        { node_name: nodeName, kill_duplicates: killDuplicates },
        (result: any) => resolve(result),
        (error: any) => reject(error),
      );
    });
  },

  updateLLMConfig: (baseUrl: string, apiKey: string, model: string) => {
    return new Promise((resolve, reject) => {
      const { ros, isConnected } = get();
      if (!ros || !isConnected) return reject("ROS not connected");

      const client = new ROSLIB.Service({
        ros,
        name: "/nlp/update_llm_config",
        serviceType: "sstg_msgs/srv/UpdateLLMConfig"
      });

      client.callService(
        { base_url: baseUrl, api_key: apiKey, model },
        (result: any) => resolve(result),
        (error: any) => reject(error),
      );
    });
  },

  executeNavigation: (nodeId: number, x: number, y: number, theta: number) => {
    return new Promise((resolve, reject) => {
      const { ros, isConnected } = get();
      if (!ros || !isConnected) return reject("ROS not connected");

      const client = new ROSLIB.Service({
        ros,
        name: "/execute_navigation",
        serviceType: "sstg_msgs/srv/ExecuteNavigation"
      });

      client.callService(
        {
          node_id: nodeId,
          target_pose: {
            header: { frame_id: "map" },
            pose: {
              position: { x, y, z: 0.0 },
              orientation: {
                x: 0.0, y: 0.0,
                z: Math.sin(theta / 2.0),
                w: Math.cos(theta / 2.0),
              },
            },
          },
        },
        (result: any) => resolve(result),
        (error: any) => reject(error),
      );
    });
  },

  setInitialPose: (x: number, y: number, yaw: number) => {
    const { ros, isConnected } = get();
    if (!ros || !isConnected) return;

    const initialPosePub = new ROSLIB.Topic({
      ros,
      name: "/initialpose",
      messageType: "geometry_msgs/msg/PoseWithCovarianceStamped",
    });

    initialPosePub.publish({
      header: { frame_id: "map" },
      pose: {
        pose: {
          position: { x, y, z: 0.0 },
          orientation: {
            x: 0.0, y: 0.0,
            z: Math.sin(yaw / 2.0),
            w: Math.cos(yaw / 2.0),
          },
        },
        covariance: [
          0.25, 0, 0, 0, 0, 0,
          0, 0.25, 0, 0, 0, 0,
          0, 0, 0, 0, 0, 0,
          0, 0, 0, 0, 0, 0,
          0, 0, 0, 0, 0, 0,
          0, 0, 0, 0, 0, 0.07,
        ],
      },
    });

    set({ localizationQuality: 'poor' as const });
  },

  clearPoseTrail: () => {
    const nav = get().navigationState;
    if (nav) {
      set({ navigationState: { ...nav, poseTrail: [] } });
    }
  },
}));
