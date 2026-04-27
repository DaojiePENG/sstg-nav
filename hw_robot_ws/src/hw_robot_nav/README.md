# hw_robot_nav

`hw_robot_nav` 为当前 hw_robot 底盘提供这些启动入口：

- `hardware.launch.py`：启动 S2 激光雷达、`cmd_control` 底盘串口控制、`base_footprint -> laser` 静态 TF。
- `gmapping.launch.py`：启动硬件和 `slam_gmapping`，用于 2D 建图。
- `navigation_dwa_launch.py`：启动硬件、AMCL 和 Nav2 DWB/DWA，用预先建立的地图导航。
- `navigation.launch.py`：启动硬件、AMCL 和 Nav2，用已保存地图导航。
- `gmapping_nav2.launch.py`：启动 gmapping 和 Nav2 navigation server，用于边建图边做简单导航调试。
- `ekf.launch.py`：启动 `robot_localization` 的 EKF 滤波器。
- `gmapping_ekf.launch.py` / `navigation_ekf.launch.py`：硬件原始里程计 + EKF + 建图/导航的推荐入口。

## 当前接口约定

| 接口 | 默认值 | 说明 |
| --- | --- | --- |
| 激光 | `/scan` | 来自 `sllidar_ros2/sllidar_s2_launch.py` |
| gmapping 激光 | `/scan_gmapping` | 由 `scan_downsampler` 从 `/scan` 降采样得到 |
| 速度控制 | `/cmd_vel` | Nav2 输出，`cmd_control` 订阅后发到底盘串口 |
| 里程计 | `/odom` / `/odom_raw` | 默认直接发布；EKF 入口会把 `/odom_raw` 滤成 `/odom` |
| IMU | `/imu` | 来自 `mqtt_bridge_pkg` |
| 坐标系 | `map -> odom -> base_footprint -> laser` | gmapping/Nav2 都依赖这条 TF 链 |

`cmd_control` 只订阅 `/cmd_vel` 并写串口。默认模式下 `/odom` 和 `odom -> base_footprint` 由 `mqtt_bridge_pkg` 发布；EKF 模式下桥接层改发 `/odom_raw`，再由 `robot_localization` 输出 `/odom`。

## 构建

```bash
cd /home/nx/SSTG_WS/sstg-nav/hw_robot_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select \
  cmd_control mqtt_bridge_pkg hw_robot_nav
source install/setup.bash
```

## 调试步骤

### 1. 只启动硬件

```bash
ros2 launch hw_robot_nav hardware.launch.py
```

另开终端检查：

```bash
source /opt/ros/humble/setup.bash
source /home/nx/SSTG_WS/sstg-nav/hw_robot_ws/install/setup.bash
ros2 topic echo --once /scan
ros2 topic echo --once /odom
ros2 topic echo --once /imu
ros2 topic list | grep -E '/scan|/cmd_vel|/odom'
ros2 run tf2_ros tf2_echo base_footprint laser
ros2 run tf2_ros tf2_echo odom base_footprint
```

当前 S2 雷达按“出线/安装方向与底盘前进方向相反”处理，默认 `laser_yaw:=3.1415926`。在 RViz 中把 Fixed Frame 切到 `base_footprint` 时，机器人正前方的障碍物应该落在 +X 方向；如果显示到后方，把启动参数改回：

```bash
ros2 launch hw_robot_nav hardware.launch.py laser_yaw:=0.0
```

如果雷达或底盘串口设备名不同：

```bash
ros2 launch hw_robot_nav hardware.launch.py \
  lidar_serial_port:=/dev/rplidar \
  base_serial_port:=/dev/ttyTHS1 \
  mqtt_broker_ip:=192.168.0.6 \
  mqtt_topic:=wifi/car_status
```

华为当前 MQTT 状态包使用 `line_v`、`Yaw`、`w`、`acc_x`、`X`、`Y` 这些字段；桥接层已经兼容这些名字，并默认把 `Yaw` 按角度处理，`line_v` 按厘米/秒缩放到米/秒。

如果你的上位机改回了弧度制，再启动时加：

```bash
ros2 launch hw_robot_nav hardware.launch.py mqtt_yaw_in_degrees:=true
```

如果发现前进/转向方向相反，可以先用缩放参数修正符号：

```bash
ros2 launch hw_robot_nav hardware.launch.py \
  mqtt_linear_velocity_scale:=-0.01 \
  mqtt_angular_velocity_scale:=-1.0
```

### 2. 运行接口检查

硬件启动后执行：

```bash
ros2 run hw_robot_nav check_system
```

全部通过后再进入 gmapping 或 Nav2。若缺少 `topic /odom` 或 `tf odom -> base_footprint`，先不要调 Nav2 参数，应先补齐底盘里程计。若准备启用 EKF，再确认 `/odom_raw` 和 `/imu` 都在。

EKF 模式下硬件桥接层会把原始里程计发到 `/odom_raw`，并关闭桥接层的 `odom -> base_footprint` TF，由 `robot_localization` 统一输出 `/odom` 和 TF：

```bash
ros2 launch hw_robot_nav hardware.launch.py \
  odom_topic:=/odom_raw \
  publish_odom_tf:=false
```

### 3. gmapping 建图

```bash
ros2 launch hw_robot_nav gmapping.launch.py

# 键盘控制机器人
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

S2 的 `DenseBoost` 一帧点数会超过 gmapping 的 2048 束上限，所以该 launch 默认启动 `scan_downsampler`，把 `/scan` 降采样为 `/scan_gmapping` 给 gmapping 使用。需要调整时：

```bash
ros2 launch hw_robot_nav gmapping.launch.py max_scan_beams:=1200
```

低速移动机器人，确认 RViz 中 `/map` 持续更新。`gmapping.launch.py` 使用单独的 RViz 配置，`/map` 的 QoS 是 Volatile；如果你手动添加 Map display，也要把 Durability 设为 Volatile。

`gmapping.launch.py` 不会启动 Nav2，所以这个阶段没有 local/global costmap。需要调 costmap 时使用 `gmapping_nav2.launch.py` 或保存地图后使用 `navigation_dwa_launch.py`。

如果想把 EKF 一起带上，改用：

```bash
ros2 launch hw_robot_nav gmapping_ekf.launch.py
```

保存地图：

```bash
ros2 run nav2_map_server map_saver_cli \
  -f /home/nx/SSTG_WS/sstg-nav/hw_robot_ws/src/hw_robot_nav/maps/hw_robot_map
```

### 4. 用 Nav2 导航

```bash
# 用默认的预先构建地图
ros2 launch hw_robot_nav navigation_dwa_launch.py

# 显式指定地图
ros2 launch hw_robot_nav navigation_dwa_launch.py \
  map:=/home/nx/Documents/HUWEI_Lab_Plus_20260424/grid_map.yaml

```

`navigation_dwa_launch.py` 默认使用 `config/dwa_nav_params.yaml`，会同时带起硬件、MQTT 里程计、S2 雷达、AMCL、Nav2 和 RViz。若硬件节点已经单独启动，可加 `include_hardware:=false`；若不需要 RViz，可加 `use_rviz:=false`。

在 RViz 里先用 `2D Pose Estimate` 给 AMCL 初始位姿，再用 `Nav2 Goal` 发送目标点。初次调试建议把机器人架空或保持急停可用，确认 `/cmd_vel` 速度方向和角速度方向正确后再落地。

如果想让导航直接走 EKF 链路，改用：

```bash
ros2 launch hw_robot_nav navigation_ekf.launch.py \
  map:=/home/nx/SSTG_WS/sstg-nav/hw_robot_ws/src/hw_robot_nav/maps/hw_robot_map.yaml
```

如果定位收敛慢，先让机器人在原地或小范围内低速旋转/平移几秒，让 AMCL 粒子云收敛后再发布目标点。当前 Nav2 参数已经偏向“更快使用激光修正定位、降低原地旋转激进程度”；如果仍然绕圈，优先检查里程计方向和 yaw 单位：

```bash
ros2 topic echo /odom
ros2 topic echo /odom_raw
ros2 run tf2_ros tf2_echo odom base_footprint
```

机器人前进时，`odom -> base_footprint` 的 x 应持续增加；原地逆时针旋转时 yaw 应按 ROS 坐标系正方向增加。如果 yaw 明显跳变或角度单位不对，用：

```bash
ros2 launch hw_robot_nav navigation.launch.py \
  map:=/home/nx/SSTG_WS/sstg-nav/hw_robot_ws/src/hw_robot_nav/maps/hw_robot_map.yaml \
  mqtt_yaw_in_degrees:=true
```

如果雷达点云已经正确，但 Nav2 中机器人箭头/odom 朝向仍整体反 180 度，再给 MQTT yaw 加偏置：

```bash
ros2 launch hw_robot_nav navigation_ekf.launch.py \
  map:=/home/nx/SSTG_WS/sstg-nav/hw_robot_ws/src/hw_robot_nav/maps/hw_robot_map.yaml \
  mqtt_yaw_offset:=3.1415926
```

如果前进或转向速度符号反了，调整：

```bash
mqtt_linear_velocity_scale:=-0.01
mqtt_angular_velocity_scale:=-1.0
```

如果 MQTT 状态发布频率较低，保持默认 `mqtt_data_timeout_sec:=2.0`。如果状态频率很高但断连后希望更快刹停，可以再把它调小。

### 5. 边建图边调 Nav2

```bash
ros2 launch hw_robot_nav gmapping_nav2.launch.py
```

这个模式不启动 AMCL 和 map server，由 gmapping 发布 `map -> odom` 和 `/map`，Nav2 navigation server 直接使用当前地图。它适合调控制链路和局部避障，不建议作为最终导航流程。

注意：当前默认 `config/nav2_params.yaml` 优先保证“保存地图后导航”的稳定性，global costmap 按 map server 的 transient local 地图 QoS 配置。边建图边导航如果 costmap 不显示，需要单独使用 gmapping 专用 Nav2 参数。

## 常用参数

```bash
# 雷达相对 base_footprint 的安装位置，单位 m/rad；默认 laser_yaw 为 pi
ros2 launch hw_robot_nav gmapping.launch.py \
  laser_x:=0.10 laser_y:=0.0 laser_z:=0.18 laser_yaw:=3.1415926

# 如果底盘 odom 使用 base_footprint
ros2 launch hw_robot_nav gmapping.launch.py base_frame:=base_footprint
```

当前默认已经统一使用 `base_footprint`。如果后续底盘改为直接发布别的底盘基准，再把 Nav2 和桥接参数一起切过去即可。
