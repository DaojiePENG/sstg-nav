# sstg_rrt_explorer 模块指南

## 模块概述

**sstg_rrt_explorer** 是 SSTG 导航系统的自主探索模块，负责在未知环境中自主探索建图，并在探索完成的地图上自动布局拓扑节点、采集语义信息。

本模块包含两层功能：

1. **RRT 前沿探索**：基于 RRT（快速随机树）算法检测未知区域边界，驱动机器人自主覆盖环境
2. **拓扑节点建立**：在已建地图上自动布局节点、逐点导航采集语义、支持按物体查询导航

## 模块架构

### 硬件层

**hardware_bringup** (`launch/library/hardware_bringup.launch.py`)
   - Yahboom X3 麦轮车硬件统一启动文件
   - 启动内容：底盘驱动 (`Mcnamu_driver_X3`) + 里程计 (`base_node_X3`) + IMU 滤波 (`imu_filter_madgwick`) + EKF 融合 (`robot_localization`) + 雷达 (`sllidar_node`, RPLidar A1) + URDF TF 树 + base_link→laser 静态 TF
   - 依赖包来源：`~/yahboomcar_ros2_ws/`（已编译）
   - 环境变量：`ROBOT_TYPE=x3`, `RPLIDAR_TYPE=a1`

### 核心组件 — RRT 探索层

1. **global_rrt_detector** (`src/global_rrt_detector_ros2.cpp`)
   - C++ 节点，全局 RRT 前沿检测器
   - 只需 1 个 Publish Point 种子点即可启动，搜索范围从地图范围自动推导并随 SLAM 地图扩大自动增长
   - 当树的边从已知空间穿越到未知空间时，发布该点为前沿候选
   - 启动后可再次点击 Publish Point 引导探索方向（在自由空间边界植入新种子）
   - 发布话题：`/detected_points` (PointStamped)
   - 需要：`/map` 话题 + `/clicked_point` 初始化（1 个种子点）

2. **local_rrt_detector** (`src/local_rrt_detector_ros2.cpp`)
   - C++ 节点，局部 RRT 前沿检测器
   - 在机器人周围 `range`（默认 8m）范围内采样，搜索范围随地图自动增长
   - 跟随机器人移动，自动重置树
   - 发布话题：`/detected_points` (PointStamped)

3. **filter** (`scripts/filter_ros2.py`)
   - Python 节点，前沿聚类过滤器
   - 收集 `/detected_points` 上的原始前沿点
   - 使用 MeanShift 聚类（bandwidth 0.45m）合并临近点
   - 过滤掉代价地图中的高代价区域和低信息增益区域
   - 发布话题：`/filtered_points` (PointArray)

4. **assigner** (`scripts/assigner_ros2.py`)
   - Python 节点，目标分配器
   - 订阅 `/filtered_points`，为每个前沿计算收益（信息增益 × 倍率 - 代价）
   - 选择最高收益前沿，发送 Nav2 `NavigateToPose` 目标
   - 发布 `GoalTraceEvent`（assigned/reached/failed/canceled）到 `/rrt_goal_event`
   - 关键参数：`info_radius`、`info_multiplier`、`hysteresis_gain`、`goal_tolerance`

5. **rrt_trace_manager** (`scripts/rrt_trace_manager.py`)
   - Python 节点，轨迹记录与状态管理
   - 通过 TF 以 5Hz 采样机器人轨迹
   - 记录目标生命周期事件（assigned/reached/failed）
   - 评估探索状态：waiting → running → settling → completed
   - 提供 `save_rrt_session` 服务，保存栅格地图 + 轨迹 JSON
   - 发布 RViz 可视化 MarkerArray 到 `/rrt_trace_markers`

6. **trace_replay** (`scripts/trace_replay.py`)
   - Python 节点，安全回放 reached 路径
   - 预规划检查、代价地图碰撞检测、连续失败保护

### 核心组件 — 拓扑节点建立层

7. **auto_node_placer** (`scripts/auto_node_placer.py`)
   - 支持**在线模式**（默认）和**离线模式**（`--offline`）
   - **在线模式**：ROS2 节点，订阅 Nav2 代价地图（`/global_costmap/costmap`），
     基于真实代价值计算安全区域，在 RViz 中实时可视化节点位置（`/topo_node_placement`），
     可选调用 `ComputePathToPose` 验证每个节点可达性
   - **离线模式**：直接读取 PGM 文件做几何分析（不需要 ROS 环境）
   - 在安全自由空间上等间距网格采样，生成节点位置
   - 输出 `node_positions.json`

8. **node_semantic_collector** (`scripts/node_semantic_collector.py`)
   - ROS2 节点，逐个到达拓扑节点并采集语义
   - 流程：注册节点(create_node) → Nav2导航 → 拍照(capture_panorama) → VLM标注(annotate_semantic) → 更新语义(update_semantic)
   - 支持 `--skip-semantic` 跳过语义采集、`--start-index` 断点续做

9. **find_and_navigate** (`scripts/find_and_navigate.py`)
   - ROS2 节点，按物体名称或节点 ID 查找并导航
   - 直接读取 `topological_map.json`，搜索匹配物体
   - 使用 Nav2 导航到目标节点

## 文件结构

```
sstg_rrt_explorer/
├── CMakeLists.txt                           # 构建配置
├── package.xml                              # ROS2 包定义
├── src/                                     # C++ RRT 检测器
│   ├── global_rrt_detector_ros2.cpp
│   ├── local_rrt_detector_ros2.cpp
│   ├── functions.cpp
│   └── mtrand.cpp
├── include/                                 # C++ 头文件
├── scripts/                                 # Python 节点和脚本
│   ├── filter_ros2.py                       # 前沿聚类过滤
│   ├── assigner_ros2.py                     # 目标分配 → Nav2
│   ├── functions_ros2.py                    # robot 类、信息增益计算
│   ├── rrt_trace_manager.py                 # 轨迹记录 + 会话保存
│   ├── trace_replay.py                      # 安全回放
│   ├── auto_node_placer.py                  # 地图 → 节点位置 JSON
│   ├── node_semantic_collector.py           # 逐节点导航 + 语义采集
│   └── find_and_navigate.py                 # 按物体查找 + 导航
├── launch/
│   ├── rrt_exploration_full.launch.py   # 一键全流程启动（硬件+SLAM+Nav2+RRT）
│   ├── rrt_exploration_ros2.launch.py   # RRT 探索节点（单独启动用）
│   ├── trace_replay.launch.py               # 回放启动文件
│   └── library/
│       ├── hardware_bringup.launch.py       # Yahboom X3 硬件启动
│       ├── nav2.launch.py                   # Nav2 启动
│       └── slam_toolbox.launch.py           # SLAM 启动
├── param/common/
│   └── nav2_params.yaml                     # Nav2 参数配置
├── rviz/                                    # RViz 配置
├── maps/                                    # 示例地图
└── doc/                                     # 文档
    ├── MODULE_GUIDE.md                      # 本文件
    └── QUICK_START.md                       # 快速启动指南
```

## 数据流

### RRT 探索阶段

```
hardware_bringup (底盘+雷达+IMU+EKF)
       │
       ├── /scan ──→ slam_toolbox ──→ /map
       │
       └── /odom ──→ Nav2 (controller + planner + bt_navigator)
                          │
/clicked_point (1 个种子点启动，后续点击引导探索方向)
       │
       ├──→ global_rrt_detector ──→ /detected_points
       │     (搜索范围随地图自动扩大)
       │
       └──→ local_rrt_detector  ──→ /detected_points
              (机器人周围 range 范围)
                                        │
                                   filter (MeanShift + 代价地图过滤)
                                        │
                                   /filtered_points (PointArray)
                                        │
                              ┌─────────┴──────────┐
                              │                    │
                         assigner              rrt_trace_manager
                      (选最优前沿)            (记录轨迹+目标事件)
                              │                    │
                    Nav2 NavigateToPose      /rrt_exploration_status
                              │              /rrt_trace_markers
                    /rrt_goal_event          save_rrt_session 服务
                  (reached/failed)
```

### 拓扑节点建立阶段

```
map.yaml + map.pgm (RRT 探索产物)
       │
       ├── 离线模式: auto_node_placer.py --offline
       │
       └── 在线模式 (推荐):
           AMCL + Nav2 (global_costmap)
                │
           auto_node_placer.py
                │
                ├── 订阅 /global_costmap/costmap
                ├── 计算安全区域 + 网格采样
                ├── 发布 /topo_node_placement (RViz 可视化)
                └── 可选: ComputePathToPose 验证可达性
                │
           node_positions.json
       │
  node_semantic_collector.py
       │
       ├── create_node 服务 ──→ sstg_map_manager
       ├── Nav2 导航到达
       ├── capture_panorama 服务 ──→ sstg_perception
       ├── annotate_semantic 服务 ──→ sstg_perception
       └── update_semantic 服务 ──→ sstg_map_manager
       │
  topological_map.json
       │
  find_and_navigate.py
       │
  读取 JSON → 匹配物体 → Nav2 导航
```

## ROS2 话题和服务

### 发布的话题

| 话题 | 类型 | 发布者 |
|------|------|--------|
| `/detected_points` | `PointStamped` | global/local_rrt_detector |
| `/filtered_points` | `sstg_msgs/PointArray` | filter |
| `/rrt_goal_event` | `sstg_msgs/GoalTraceEvent` | assigner |
| `/rrt_trace_markers` | `MarkerArray` | rrt_trace_manager |
| `/rrt_exploration_status` | `String` | rrt_trace_manager |
| `/assigned_goal_marker` | `Marker` | assigner |
| `/topo_node_placement` | `MarkerArray` | auto_node_placer（在线模式）|

### 提供的服务

| 服务 | 类型 | 提供者 |
|------|------|--------|
| `save_rrt_session` | `sstg_msgs/SaveRrtSession` | rrt_trace_manager |

### 依赖的外部服务

| 服务 | 类型 | 来源 | 使用者 |
|------|------|------|--------|
| `navigate_to_pose` | Nav2 Action | Nav2 | assigner, node_semantic_collector, find_and_navigate |
| `create_node` | `CreateNode` | sstg_map_manager | node_semantic_collector |
| `update_semantic` | `UpdateSemantic` | sstg_map_manager | node_semantic_collector |
| `capture_panorama` | `CaptureImage` | sstg_perception | node_semantic_collector |
| `annotate_semantic` | `AnnotateSemantic` | sstg_perception | node_semantic_collector |

## 关键参数

### RRT 探索参数（launch 文件配置）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `global_eta` | 4.0 | 全局 RRT 步长 |
| `local_eta` | 1.5 | 局部 RRT 步长 |
| `local_range` | 8.0 | 局部检测范围 (m) |
| `info_radius` | 1.5 | 信息增益计算半径 (m) |
| `filter_cluster_bandwidth` | 0.45 | MeanShift 聚类带宽 (m) |
| `assignment_period` | 0.2 | 目标分配周期 (s) |
| `completion_patience` | 10.0 | 无前沿多久判定为探索完成 (s) |

### 自动布点参数（命令行参数）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--spacing` | 2.0 | 节点间距 (m) |
| `--wall-clearance` | 0.3 | 距墙安全距离 (m) |
| `--costmap-topic` | `/global_costmap/costmap` | [在线模式] 代价地图话题 |
| `--cost-threshold` | 50 | [在线模式] 安全代价阈值 (0-252) |
| `--verify-paths` | false | [在线模式] 用 Nav2 ComputePathToPose 验证可达性 |
| `--offline` | false | 启用离线模式（读取 PGM 文件） |
| `--map` | - | [离线模式] 地图 YAML 文件路径 |

## 依赖

### ROS2 包依赖
- rclcpp / rclpy — ROS2 客户端库
- nav2_msgs — Nav2 导航动作
- tf2_ros — 坐标变换
- sstg_msgs — SSTG 自定义消息/服务
- slam_toolbox — SLAM 建图

### 硬件驱动依赖（来自 `~/yahboomcar_ros2_ws/`）
- yahboomcar_bringup — Yahboom X3 底盘电机驱动
- yahboomcar_base_node — 里程计 + IMU 原始数据
- yahboomcar_description — URDF 模型
- sllidar_ros2 — RPLidar A1 雷达驱动
- robot_localization — EKF 融合里程计 + IMU
- imu_filter_madgwick — IMU 滤波（ROS2 humble 系统自带）

### Python 依赖
- numpy — 数值计算
- opencv-python (cv2) — 图像处理
- pyyaml — YAML 解析
- scikit-learn — MeanShift 聚类（filter 使用）

## 输出数据格式

### node_positions.json（auto_node_placer 输出）

```json
{
  "map_yaml": "/path/to/map.yaml",
  "spacing": 2.0,
  "wall_clearance": 0.3,
  "node_count": 19,
  "nodes": [
    {"x": 1.5, "y": 2.3},
    {"x": 3.5, "y": 2.3}
  ]
}
```

### .trace.json（save_rrt_session 输出）

```json
{
  "session_id": "20260401_143022",
  "goals": [
    {
      "id": 0,
      "x": 1.2, "y": 3.4,
      "status": "reached",
      "assigned_at": "2026-04-01 14:30:25 CST",
      "reached_at": "2026-04-01 14:31:02 CST"
    }
  ],
  "trajectory": [
    {"x": 0.0, "y": 0.0, "t": "2026-04-01 14:30:22 CST"}
  ]
}
```
