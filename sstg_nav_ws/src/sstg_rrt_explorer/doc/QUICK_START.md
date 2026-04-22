# sstg_rrt_explorer 快速启动指南

## 验证状态

- 构建验证：`colcon build --packages-select sstg_msgs sstg_rrt_explorer` 通过
- auto_node_placer 在线模式：ROS2 节点，订阅代价地图 + RViz 可视化
- auto_node_placer 离线测试：在示例地图上成功生成 19 个节点

---

## 完整工作流

整个流程分两次启动：

### 第一次启动 — RRT 探索建图

每个终端都需要先 source 环境（可写入 `~/.bashrc` 简化）：

```bash
source /opt/ros/humble/setup.bash
source ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash
source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
```

#### 快速启动（推荐）

只需 **2 个终端**：

```bash
# Terminal 1: 一键启动（硬件 + SLAM + Nav2 + RRT 自动分阶段延时启动）
source /opt/ros/humble/setup.bash
source ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash
source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
ros2 launch sstg_rrt_explorer rrt_exploration_full.launch.py

# Terminal 2: RViz 可视化（需要在有显示器的桌面终端启动）
source /opt/ros/humble/setup.bash
source ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash
source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
bash ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/launch_rviz_true_map.sh
```

启动时序：
| 时间 | 启动内容 |
|------|----------|
| 0s   | 硬件层（底盘驱动、雷达、IMU、EKF、TF） |
| 3s   | SLAM Toolbox（异步建图） |
| 6s   | Nav2 导航（路径规划 + 局部避障） |
| 10s  | RRT 探索节点（全局/局部检测器 + 过滤器 + 分配器） |

一个 `Ctrl+C` 全部停掉。

#### 分步启动（调试用）

需要 **5 个终端**，适合需要单独查看各模块日志的场景：

```bash
# Terminal 1: 硬件驱动（Yahboom X3 底盘 + RPLidar A1 + IMU + EKF）
ros2 launch sstg_rrt_explorer hardware_bringup.launch.py

# Terminal 2: SLAM 建图
ros2 launch sstg_rrt_explorer slam_toolbox.launch.py

# Terminal 3: Nav2 导航
ros2 launch nav2_bringup navigation_launch.py \
  params_file:=$(ros2 pkg prefix sstg_rrt_explorer)/share/sstg_rrt_explorer/param/common/nav2_params.yaml \
  use_sim_time:=false

# Terminal 4: RRT 探索（内部延迟 8 秒等 SLAM + Nav2 就绪）
ros2 launch sstg_rrt_explorer rrt_exploration_ros2.launch.py

# Terminal 5: RViz（需要在有显示器的桌面终端启动）
bash ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/launch_rviz_true_map.sh
```

**在 RViz 中启动探索：**

1. 工具栏选择 **Publish Point**
2. 在机器人附近的自由空间点击 **1 个点**（种子点）
3. RRT 自动开始探索，搜索范围随 SLAM 地图自动扩大，机器人会自主移动
4. （可选）探索过程中可再次点击 Publish Point 引导探索方向（会在自由空间边界植入新种子）

**探索完成后保存（3 步）：**

```bash
# 1. 保存 RRT 轨迹 + PGM 地图
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ros2 service call /save_rrt_session sstg_msgs/srv/SaveRrtSession \
  "{requested_prefix: '${TIMESTAMP}'}"

# 2. 保存 PGM 地图（slam_toolbox 版本）
MAPS_DIR=~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/maps
ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap \
  "{name: {data: '${MAPS_DIR}/${TIMESTAMP}'}}"

# 3. 序列化地图（第二阶段 localization 模式必需！）
ros2 service call /slam_toolbox/serialize_map slam_toolbox/srv/SerializePoseGraph \
  "{filename: '${MAPS_DIR}/${TIMESTAMP}_serialized'}"

# 输出文件：
#   ${TIMESTAMP}.pgm + .yaml        — 栅格地图
#   ${TIMESTAMP}.trace.json          — RRT 探索轨迹
#   ${TIMESTAMP}_serialized.posegraph + .data — slam_toolbox 序列化地图
```

### 第二次启动 — 拓扑节点建立 + 语义采集 + 导航

> **前提**：已完成第一次启动（RRT 探索建图），且已保存：
> - PGM 栅格地图（`.pgm` + `.yaml`）
> - slam_toolbox 序列化地图（`_serialized.posegraph` + `_serialized.data`）
>
> **定位方案**：使用 slam_toolbox localization 模式（scan matching 定位，精度远高于 AMCL）
> 参考 Yahboom 官方 `localization_imu_odom.launch.py`（Cartographer localization + 序列化地图）
>
> **串口说明**：`hardware_bringup.launch.py` 启动时自动切换到 ROS2 模式，无需手动处理。

每个终端都需要先 source 环境：

```bash
source /opt/ros/humble/setup.bash
source ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash
source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=28
export DASHSCOPE_API_KEY=sk-942e8661f10f492280744a26fe7b953b
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
```

#### Step 1: 硬件 + 相机

```bash
# Terminal 1: 底盘 + 雷达 + IMU + EKF（自动切换 ROS2 模式）
ros2 launch sstg_rrt_explorer hardware_bringup.launch.py

# Terminal 2: Orbbec 相机（低负载稳定模式）
ros2 launch sstg_rrt_explorer orbbec_stable.launch.py
```

验证：
```bash
# IMU z 轴应 ≈ -9.8（重力加速度），不能为 0
ros2 topic echo /imu/data_raw --field linear_acceleration.z --once
# 相机应有发布者
ros2 topic info /camera/color/image_raw
```

#### Step 2: slam_toolbox 定位 + map_server + Nav2

```bash
# Terminal 3: slam_toolbox localization（加载序列化地图定位）+ map_server（加载 PGM 地图）
# 默认加载 maps/20260402_083419 系列地图，可通过参数指定其他地图
ros2 launch sstg_rrt_explorer slam_toolbox_localization.launch.py

# 如需指定其他地图：
# ros2 launch sstg_rrt_explorer slam_toolbox_localization.launch.py \
#   map_yaml:=/path/to/map.yaml \
#   serialized_map:=/path/to/serialized_map_name_without_extension

# Terminal 4: Nav2 导航（路径规划 + 局部避障，robot_radius=0.22, inflation_radius=0.55）
NAV_PARAMS=$(ros2 pkg prefix sstg_rrt_explorer)/share/sstg_rrt_explorer/param/common/nav2_params.yaml
ros2 launch nav2_bringup navigation_launch.py \
  params_file:=$NAV_PARAMS \
  use_sim_time:=false
```

> **注意**：这里用 `navigation_launch.py`（不是 `bringup_launch.py`），
> 因为 slam_toolbox 已经提供了 `map→odom` TF 和 `/map`（通过 map_server），不需要 AMCL。

#### Step 3: 拓扑管理 + 感知 + 采集脚本

```bash
# Terminal 5: 拓扑地图管理
ros2 run sstg_map_manager map_manager_node

# Terminal 6: 感知节点（相机订阅 + VLM 语义标注）
# DASHSCOPE_API_KEY 必须已 export，否则 VLM 标注会失败
ros2 run sstg_perception perception_node

# Terminal 7: RViz 点选采集（需在桌面终端启动）
MAPS_DIR=~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/maps
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/click_and_capture.py \
  --report-file $MAPS_DIR/manual_capture_report.json \
  --map-file $MAPS_DIR/topological_map_manual.json
```

#### Step 4: RViz（需在桌面终端启动）

```bash
# Terminal 8: RViz（桌面终端）
export DISPLAY=:0
export XAUTHORITY=/run/user/1000/gdm/Xauthority
bash ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/launch_rviz_true_map.sh
```

#### 启动后操作 — 拓扑节点采集

1. 在 RViz 中确认地图已加载（`/map` 话题），激光点云与地图对齐
2. 如果点云有偏移，slam_toolbox 会在几秒内自动校正（不需要手动设 2D Pose Estimate）
3. 工具栏选择 **Publish Point**，点击地图上希望采集的位置
4. `click_and_capture` 自动执行全链路：

```
clicked_point → create_node（写入 topological_map_manual.json）
             → Nav2 导航到目标点
             → capture_panorama（原地旋转拍 4 方向 RGB）
             → annotate_semantic（每张图 VLM 标注）
             → update_semantic（合并语义写入 topological_map_manual.json）
```

5. 采集完成后，`topological_map_manual.json` 中该节点自动包含：
   - 位姿 (pose)
   - 4 张照片路径 (panorama_paths)
   - 语义信息：房间类型 + 物体列表 + 描述 (semantic_info)

**RViz 节点状态颜色：**
| 颜色 | 状态 |
|------|------|
| 黄色 | pending（排队中） |
| 绿色 | captured（拍照完成） |
| 蓝色 | semantic（语义标注完成） |
| 橙色 | partial（部分拍照） |
| 红色 | failed（失败） |

#### Step 5: 自然语言查找物体 + 导航

采集完成后，可以用自然语言查找物体并自动导航到对应节点：

```bash
# 自然语言查找（推荐，通过 LLM 语义匹配，支持近义词/口语化表达）
# 例如用户说"书包"，LLM 能匹配到拓扑图中的"背包"
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --query "我要找我的书包"

# 精确匹配物体名称（不调 LLM）
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --object 背包

# 直接指定节点 ID 导航
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --node-id 3

# 查看所有节点及语义信息（不导航）
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --list

# 只搜索不导航
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --query "书包" --no-nav
```

> **注意**：`--query` 模式需要 `DASHSCOPE_API_KEY` 环境变量（调用 qwen-plus LLM）。

#### 补跑语义标注（已拍照但未标注的节点）

```bash
# 对已有照片的节点补跑 VLM 标注（无需机器人移动）
# 需要 map_manager + perception 运行中
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/batch_semantic_annotate.py \
  --nodes 0 1 2 3 4
```

#### 数据文件说明

| 文件 | 作用 | 自动更新 |
|------|------|----------|
| `maps/topological_map_manual.json` | 拓扑图（节点位姿 + 语义） | click_and_capture 采集后自动写入 |
| `maps/manual_capture_report.json` | 采集报告（每次采集的状态记录） | click_and_capture 自动更新 |
| `captured_nodes/node_X/` | 每个节点的 4 方向 RGB 照片 | capture_panorama 自动保存 |

#### 启动后验证清单

```bash
# IMU 正常（z ≈ -9.8，不能为 0）
ros2 topic echo /imu/data_raw --field linear_acceleration.z --once

# odom 有值（车没动时接近 0，但不能一直是 0.000）
ros2 topic echo /odom --field pose.pose.position --once

# 地图已发布（map_server 发布预建地图）
ros2 topic info /map  # Publisher count: 1

# slam_toolbox 定位地图（内部使用，不影响 Nav2）
ros2 topic info /slam_map  # Publisher count: 1

# 关键服务就绪
ros2 service list | grep -E "create_node|capture_panorama|annotate_semantic|update_semantic"

# 确认拓扑图文件位置（map_manager 默认读写此文件）
ros2 param get /map_manager_node map_file
```

---

### 第三次启动 — 在已有地图+拓扑节点上直接导航

> **前提**：已完成前两次启动，拥有：
> - PGM 栅格地图 + slam_toolbox 序列化地图
> - `topological_map_manual.json`（已含语义标注的拓扑节点）
>
> **目的**：快速启动全栈，在 RViz 中显示地图+拓扑节点+激光+摄像头，然后在终端输入自然语言指令导航到目标物体。

每个终端都需要先 source 环境：

```bash
source /opt/ros/humble/setup.bash
source ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash
source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=28
export DASHSCOPE_API_KEY=sk-942e8661f10f492280744a26fe7b953b
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
```

#### 快速启动（推荐）

只需 **2 个终端**：

```bash
# Terminal 1: 一键启动全栈（硬件 + 定位 + Nav2 + 相机 + 拓扑管理，自动分阶段延时启动）
ros2 launch sstg_rrt_explorer navigation_full.launch.py

# Terminal 2: RViz 可视化（需要在有显示器的桌面终端启动）
rviz2 -d ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/rviz/rrt_ros2.rviz
```

启动时序：
| 时间 | 启动内容 |
|------|----------|
| 0s   | 硬件层（底盘驱动、雷达、IMU、EKF、TF） |
| 3s   | SLAM Toolbox 定位（加载序列化地图）+ map_server + Orbbec 相机 |
| 6s   | Nav2 导航（路径规划 + 局部避障） |
| 8s   | 拓扑管理（map_manager_node + topo_node_viz） |

一个 `Ctrl+C` 全部停掉。

#### 分步启动（调试用）

```bash
# Terminal 1: 底盘 + 雷达 + IMU + EKF
ros2 launch sstg_rrt_explorer hardware_bringup.launch.py

# Terminal 2: slam_toolbox 定位 + map_server
ros2 launch sstg_rrt_explorer slam_toolbox_localization.launch.py

# Terminal 3: Nav2 导航
NAV_PARAMS=$(ros2 pkg prefix sstg_rrt_explorer)/share/sstg_rrt_explorer/param/common/nav2_params.yaml
ros2 launch nav2_bringup navigation_launch.py \
  params_file:=$NAV_PARAMS \
  use_sim_time:=false

# Terminal 4: Orbbec 相机（稳定配置，推荐）
ros2 launch sstg_rrt_explorer orbbec_stable.launch.py
```

#### Step 2: 拓扑节点可视化 + RViz

```bash
# Terminal 5: 拓扑地图管理 + 节点可视化
ros2 run sstg_map_manager map_manager_node &
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/topo_node_viz.py &

# Terminal 6: RViz（桌面终端）
export DISPLAY=:0
export XAUTHORITY=/run/user/1000/gdm/Xauthority
bash ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/launch_rviz_true_map.sh
```

RViz 中应显示：地图（灰色栅格）、激光点云（白色）、小车模型、6 个蓝色拓扑节点（含物体标签）、摄像头画面。

#### Step 3: 自然语言导航（在新终端中输入）

```bash
# 自然语言查找物体并导航（推荐）
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --query "我要找我的书包"

# 查看所有节点和物体（不导航）
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py --list

# 精确匹配物体名
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py --object 背包

# 直接导航到指定节点
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py --node-id 3

# 只搜索不导航
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --query "书包" --no-nav
```

#### 启动后快速验证

```bash
# TF 链完整（应输出 Translation + Rotation）
timeout 5 ros2 run tf2_ros tf2_echo map base_footprint

# Nav2 就绪
ros2 action list | grep navigate_to_pose

# 相机正常
ros2 topic info /camera/color/image_raw  # Publisher count: 1

# 拓扑节点可视化正常
ros2 topic info /topo_node_markers  # Publisher count: 1
```

---

## 分步操作

### Step 1: 自动布点

#### 在线模式（推荐，需要 AMCL + Nav2 运行）

```bash
# 前提: AMCL 定位 + Nav2（含 global_costmap）已启动

# 基本用法 — 订阅代价地图，在 RViz 中可视化节点
ros2 run sstg_rrt_explorer auto_node_placer.py --spacing 2.0

# 调整参数
ros2 run sstg_rrt_explorer auto_node_placer.py \
  --spacing 1.5 \
  --wall-clearance 0.4 \
  --cost-threshold 40

# 启用路径可达性验证（用 Nav2 ComputePathToPose 检查每个节点）
ros2 run sstg_rrt_explorer auto_node_placer.py \
  --spacing 2.0 \
  --verify-paths

# 指定输出路径
ros2 run sstg_rrt_explorer auto_node_placer.py \
  --spacing 2.0 \
  --output /home/jetson/my_nodes.json
```

**RViz 可视化：**
- 话题: `/topo_node_placement` (MarkerArray)
- 绿色球 = 可达节点，红色球 = 不可达节点，黄色球 = 待验证
- 每个节点上方显示编号

#### 离线模式（不需要 ROS 环境）

```bash
# 纯离线计算，直接读取 PGM 文件
cd ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer

python3 scripts/auto_node_placer.py --offline \
  --map /path/to/my_map.yaml \
  --spacing 2.0

# 输出: node_positions.json（与 map.yaml 同目录）
```

**参数调整建议：**

| 场景 | spacing | wall-clearance |
|------|---------|----------------|
| 大房间，希望多采集 | 1.5m | 0.3m |
| 默认 | 2.0m | 0.3m |
| 走廊/小空间 | 2.5m | 0.2m |
| 快速粗采集 | 3.0m | 0.3m |

### Step 2: 语义采集

```bash
# 前提: Nav2 + map_manager + perception 已启动

# 完整采集（导航 + 拍照 + VLM 标注）
ros2 run sstg_rrt_explorer node_semantic_collector.py \
  --nodes /path/to/node_positions.json

# 跳过语义（只注册节点坐标 + 验证导航可达性）
ros2 run sstg_rrt_explorer node_semantic_collector.py \
  --nodes /path/to/node_positions.json \
  --skip-semantic

# 从第 5 个节点开始（中断后继续）
ros2 run sstg_rrt_explorer node_semantic_collector.py \
  --nodes /path/to/node_positions.json \
  --start-index 5

# 指定拓扑图输出路径
ros2 run sstg_rrt_explorer node_semantic_collector.py \
  --nodes /path/to/node_positions.json \
  --map-file /home/jetson/my_topo_map.json
```

### Step 3: 查找物体 + 导航

```bash
# 查看所有节点及语义信息
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --list

# 自然语言查找（推荐，通过 LLM 语义匹配近义词）
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --query "我要找我的书包"

# 精确匹配物体名称搜索并导航
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --object 背包

# 直接指定节点 ID 导航
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --node-id 3

# 只搜索不导航
python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \
  --query "书包" --no-nav
```

---

## 关键文件位置

```
~/wbt_ws/sstg-nav/sstg_nav_ws/
├── src/
│   ├── sstg_rrt_explorer/
│   │   ├── scripts/
│   │   │   ├── auto_node_placer.py           # 地图 → 节点位置（在线/离线）
│   │   │   ├── node_semantic_collector.py     # 逐节点采集
│   │   │   ├── find_and_navigate.py           # 自然语言查找 + 导航（LLM 语义匹配）
│   │   │   ├── click_and_capture.py           # RViz 点选 → 导航 → 拍照 → VLM → 写入拓扑图
│   │   │   ├── batch_semantic_annotate.py     # 对已有照片批量补跑 VLM 标注
│   │   │   ├── assigner_ros2.py               # RRT 目标分配
│   │   │   ├── filter_ros2.py                 # 前沿过滤
│   │   │   └── rrt_trace_manager.py           # 轨迹记录
│   │   ├── launch/
│   │   │   ├── rrt_exploration_full.launch.py       # 一键全流程启动（推荐）
│   │   │   ├── rrt_exploration_ros2.launch.py       # RRT 探索节点（单独启动用）
│   │   │   └── library/
│   │   │       ├── hardware_bringup.launch.py       # Yahboom X3 硬件
│   │   │       ├── slam_toolbox.launch.py           # SLAM 建图（第一阶段）
│   │   │       ├── slam_toolbox_localization.launch.py  # slam_toolbox 定位 + map_server（第二阶段）
│   │   │       └── orbbec_stable.launch.py          # Orbbec 相机（低负载稳定模式）
│   │   ├── maps/
│   │   │   ├── topological_map_manual.json    # 拓扑图（节点 + 语义，map_manager 默认读写）
│   │   │   ├── manual_capture_report.json     # 采集报告
│   │   │   ├── 20260402_083419.yaml/.pgm      # PGM 栅格地图
│   │   │   └── 20260402_083419_serialized.*   # slam_toolbox 序列化地图
│   │   └── captured_nodes/                    # 每个节点的 4 方向 RGB 照片
│   ├── sstg_map_manager/                      # 拓扑图管理（create_node / update_semantic）
│   ├── sstg_perception/                       # 感知 + VLM（capture_panorama / annotate_semantic）
│   └── sstg_msgs/                             # 消息定义
└── install/
```

---

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| 雷达无数据 (`/scan` 无输出) | 检查 USB 连接：`ls /dev/rplidar`；无设备则检查 udev 规则或用 `/dev/ttyUSB0` |
| 底盘不动 | 检查 `Mcnamu_driver_X3` 是否报错；确认串口权限 `sudo chmod 666 /dev/ttyACM0` |
| SLAM 报 TF 错误 | 确认硬件 bringup 已启动（提供 base_link→laser TF） |
| Nav2 启动后报 `Timed out waiting for transform` | SLAM 还没就绪，等 `/map` 有数据后重启 Nav2 |
| auto_node_placer 生成 0 个节点 | 减小 `--spacing` 或 `--wall-clearance`；在线模式下增大 `--cost-threshold`；检查地图是否有足够自由空间 |
| auto_node_placer 在线模式无反应 | 确认 Nav2 global_costmap 已发布：`ros2 topic echo /global_costmap/costmap --once` |
| RViz 看不到节点标记 | 添加 MarkerArray 显示，话题设为 `/topo_node_placement` |
| `Nav2 action server not available` | 确认 Nav2 已启动：`ros2 action list` 应包含 `/navigate_to_pose` |
| `create_node service not available` | 确认 map_manager 已启动：`ros2 service list` 应包含 `/create_node` |
| 导航频繁失败 | 检查 slam_toolbox 定位是否准确（RViz 中激光与地图对齐）；确认代价地图合理 |
| VLM 标注失败 | 检查 `DASHSCOPE_API_KEY` 环境变量已 export；确认 perception_node 启动时加载了 key |
| LLM 查找失败 | 检查 `DASHSCOPE_API_KEY`；网络是否可达 `dashscope.aliyuncs.com` |
| 语义未写入 topological_map_manual.json | 确认 map_manager_node 已启动且默认路径正确：`ros2 param get /map_manager_node map_file` |
| 中途中断想继续 | 使用 `--start-index N` 从第 N 个节点继续采集 |
| PGM 读取失败 | 确认 map.yaml 中 `image` 路径正确（相对路径基于 yaml 所在目录）|

---

## 依赖检查

```bash
# 检查 Python 依赖
python3 -c "import cv2; print('cv2:', cv2.__version__)"
python3 -c "import numpy; print('numpy:', numpy.__version__)"
python3 -c "import yaml; print('pyyaml: OK')"

# 检查 ROS2 包
ros2 pkg list | grep sstg
# 应包含: sstg_msgs, sstg_rrt_explorer, sstg_map_manager, sstg_perception

# 检查硬件驱动包（来自 yahboomcar_ws）
# 需要 source:
#   ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash
ros2 pkg list | grep -E "yahboomcar|sllidar"
# 应包含: yahboomcar_bringup, yahboomcar_base_node, sllidar_ros2

# 检查 Nav2
ros2 pkg list | grep nav2

# 检查硬件连接
ls /dev/rplidar    # 雷达 USB
ls /dev/ttyACM0    # 底盘串口（具体设备名视情况）
```

---

**最后更新**：2026-04-02
**状态**：构建通过，硬件启动验证通过（Yahboom X3 + RPLidar A1），支持一键启动全流程
