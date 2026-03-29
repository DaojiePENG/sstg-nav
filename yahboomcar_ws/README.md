# YahboomCar 机器人控制工作空间

**YahboomCar ROS2 Control System - 机器人硬件控制系统**

这是YahboomCar机器人的硬件控制系统工作空间，专门用于YahboomCar机器人的底层驱动、传感器接口和基础控制。

> **⚠️ 重要提示**: 从Phase 3.1开始，SSTG导航系统已独立迁移到 `sstg_nav_ws` 工作空间。此工作空间现在**仅包含**YahboomCar机器人相关的包。

## 📂 工作空间结构

```
yahboomcar_ws/
├── src/                       # 源代码
│   ├── yahboomcar_base_node/      # 机器人基础控制
│   ├── yahboomcar_bringup/        # 机器人启动
│   ├── yahboomcar_ctrl/           # 运动控制
│   ├── yahboomcar_description/    # 机器人描述
│   ├── yahboomcar_laser/          # 激光传感器驱动
│   ├── yahboomcar_astra/          # 深度摄像头驱动
│   ├── yahboomcar_slam/           # SLAM功能
│   ├── yahboomcar_nav/            # Nav2基础导航
│   └── 其他模块...
│
├── build/                     # 构建输出
├── install/                   # 安装输出
├── log/                       # 日志文件
└── README.md                  # 本文件
```

## 🚀 快速开始

### 前置要求

- **ROS2**: Humble Hawksbill
- **Python**: 3.10+
- **操作系统**: Ubuntu 22.04

### 安装步骤

```bash
# 1. 进入工作空间
cd ~/sstg_nav/yahboomcar_ws

# 2. 安装依赖
sudo apt-get install ros-humble-nav2 ros-humble-rclpy

# 3. 构建
colcon build --symlink-install

# 4. Source环境
source install/setup.bash

# 5. 添加到bashrc（可选）
echo "source ~/sstg_nav/yahboomcar_ws/install/setup.bash" >> ~/.bashrc
```

## 🤖 YahboomCar 机器人包

| 包名 | 功能 |
|------|------|
| `yahboomcar_base_node` | 机器人基础节点和初始化 |
| `yahboomcar_bringup` | 机器人启动launch文件 |
| `yahboomcar_ctrl` | 运动控制和速度命令处理 |
| `yahboomcar_description` | URDF机器人描述文件 |
| `yahboomcar_laser` | 激光雷达驱动和接口 |
| `yahboomcar_astra` | 深度摄像头(Astra)驱动 |
| `yahboomcar_slam` | SLAM和地图构建 |
| `yahboomcar_nav` | Nav2导航基础设置 |
| 其他模块 | 各种功能扩展 |

## 📚 文档

### 关键文档位置

- **[主项目README](../README.md)** - 完整项目架构说明
- **[SSTG独立工作空间](../sstg_nav_ws/README.md)** - SSTG导航系统文档
- **[SSTG用户指南](../SSTG_User_Guide.md)** - 系统完整使用手册

### 工作空间文档

各个包的README和文档位于对应包的目录下。

## 🔄 与SSTG导航系统的集成

### 单独使用YahboomCar

如果只想使用YahboomCar机器人的基础功能（不需要SSTG导航）：

```bash
# 只Source YahboomCar工作空间
source ~/sstg_nav/yahboomcar_ws/install/setup.bash

# 启动机器人
ros2 launch yahboomcar_bringup bringup.launch.py
```

### 同时使用YahboomCar和SSTG导航系统

如果需要完整的SSTG导航系统和YahboomCar控制的集成：

```bash
# Source两个工作空间
source ~/sstg_nav/sstg_nav_ws/install/setup.bash
source ~/sstg_nav/yahboomcar_ws/install/setup.bash

# 启动YahboomCar机器人
ros2 launch yahboomcar_bringup bringup.launch.py &

# 启动SSTG导航系统
cd ~/sstg_nav
./project_test/run_tests.sh
```

### 使用其他机器人平台

如果想在其他机器人平台上使用SSTG导航系统：

```bash
# 只需要SSTG工作空间，不需要YahboomCar工作空间
source ~/sstg_nav/sstg_nav_ws/install/setup.bash

# 确保目标机器人支持：
# - ROS2 Humble
# - Nav2导航框架
# - 基础移动控制接口

# 启动SSTG导航系统
cd ~/sstg_nav
./project_test/run_tests.sh
```

## ⚙️ 硬件配置

### 启动YahboomCar机器人

```bash
# 确保已source此工作空间
source ~/sstg_nav/yahboomcar_ws/install/setup.bash

# 启动所有硬件驱动和基础节点
ros2 launch yahboomcar_bringup bringup.launch.py
```

### 检查机器人连接

```bash
# 列出所有节点
ros2 node list

# 列出所有话题
ros2 topic list

# 查看传感器数据
ros2 topic echo /scan        # 激光雷达扫描
ros2 topic echo /color/image_raw  # 摄像头图像
```

## 🔧 开发工作流

### 构建特定包

```bash
source ~/sstg_nav/yahboomcar_ws/install/setup.bash

# 只构建某个包
colcon build --packages-select yahboomcar_ctrl
```

### 调试

```bash
# 启用详细日志
ROS_LOG_DIR=~/sstg_nav/yahboomcar_ws/log ros2 launch yahboomcar_bringup bringup.launch.py

# 使用rqt监控节点
rqt_graph

# 使用rviz可视化
rviz2
```

## 📊 系统要求

- **硬件**: YahboomCar机器人
- **处理器**: 支持ROS2（建议ARM处理器如树莓派4B或更高）
- **传感器**: 激光雷达，深度摄像头，IMU，电机编码器
- **网络**: 有线或无线网络连接

## 🆘 故障排除

### 无法连接到机器人

**症状**: 节点无法启动或连接超时

**检查项**:
```bash
# 1. 检查网络连接
ping <robot_ip>

# 2. 检查ROS_DOMAIN_ID
echo $ROS_DOMAIN_ID

# 3. 检查中间件配置
ros2 doctor
```

### 传感器驱动问题

**症状**: 无法读取传感器数据

**解决**:
```bash
# 1. 检查USB设备
lsusb

# 2. 检查权限
sudo usermod -a -G dialout $USER

# 3. 重新启动驱动
ros2 launch yahboomcar_bringup bringup.launch.py --log-level debug
```

## 📝 架构变化说明

### Phase 3.1 之前
- SSTG导航和YahboomCar控制在同一工作空间混合
- 不便于版本管理和跨平台集成

### Phase 3.1 之后 (当前)
- ✅ SSTG系统独立到 `sstg_nav_ws`
- ✅ YahboomCar工作空间专注于机器人控制
- ✅ 两个系统可独立开发、版本管理和部署
- ✅ 便于将SSTG系统集成到其他机器人平台

## 📄 许可证

Apache 2.0 - 详见[LICENSE](../LICENSE)

---

**YahboomCar 工作空间文档**

最后更新: 2026-03-29

> **相关链接**:
> - [主项目README](../README.md)
> - [SSTG独立工作空间](../sstg_nav_ws/README.md)
> - [项目总结](../PROJECT_SUMMARY.md)
