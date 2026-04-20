# SSTG 快速信息检索手册

> 版本：v0.1  
> 创建日期：2026-04-12  
> 文档定位：SSTG 项目的快速查阅手册  
> 使用方式：当你需要快速确认某个硬件、模块、入口地址、主控性能、传感器接口时，优先查这份文档。

## 前言

本文档用于集中记录 SSTG 项目的关键静态信息与工程速查信息，强调：

- 快速定位信息
- 避免重复翻代码
- 统一项目内部设备认知
- 为后续补充相机、雷达、底盘、网站、模块速览等内容提供统一入口

本文档当前已整理：

- MaxTang 主控信息
- 相机信息
- 激光雷达信息
- 底盘结构信息
- 网站与访问入口
- 模块速览
- 常用检查命令

后续可以继续补充：

- 各模块详细接口
- 相机/雷达实测频率
- 设备序列号
- 外参标定信息
- UI / rosbridge / Web 后端完整架构

## 目录

- [1. MaxTang](#1-maxtang)
- [2. 相机](#2-相机)
- [3. 激光雷达](#3-激光雷达)
- [4. 底盘结构](#4-底盘结构)
- [5. 网站与访问入口](#5-网站与访问入口)
- [6. 模块速览](#6-模块速览)
- [7. 常用检查命令](#7-常用检查命令)
- [8. 更新记录](#8-更新记录)

# 1. MaxTang

## 1.1 设备身份

| 项目 | 信息 |
|---|---|
| 主控品牌 | Maxtang |
| 设备型号 | FP750 |
| 主板厂商 | Maxtang |
| 主板型号 | FP750 |
| BIOS 厂商 | American Megatrends International, LLC. |
| BIOS 版本 | FP750D107 |

## 1.2 系统信息

| 项目 | 信息 |
|---|---|
| 操作系统 | Ubuntu 22.04.5 LTS |
| 内核 | Linux 6.8.0-107-generic |
| 架构 | x86_64 |

## 1.3 CPU / GPU / 内存 / 存储

| 项目 | 信息 |
|---|---|
| CPU | AMD Ryzen 5 6600H with Radeon Graphics |
| 核心线程 | 6 核 12 线程 |
| CPU 频率范围 | 400 MHz ～ 4.564 GHz |
| GPU | AMD Radeon 集显（Rembrandt） |
| 内存 | 12 GiB |
| Swap | 2 GiB |
| 系统盘 | SK hynix BC511 NVMe |
| 磁盘容量 | 238.5 GB |

## 1.4 网络接口

| 项目 | 信息 |
|---|---|
| 无线网卡 | Realtek RTL8822CE 802.11ac |
| 有线网卡 | Intel Ethernet Controller（PCI ID: 8086:125c） |

## 1.5 当前采样状态（2026-04-12）

| 项目 | 结果 |
|---|---|
| 系统负载 | 0.25 / 0.27 / 0.34 |
| 已用内存 | 约 2.8 GiB |
| 可用内存 | 约 8.4 GiB |
| 当前 CPU governor | `powersave` |
| 根分区使用率 | 约 19% |

## 1.6 性能判断

- 这台主控足以承担当前 SSTG 的核心 2D 导航链路：
  - `robot_localization`
  - `slam_toolbox`
  - `AMCL`
  - `Nav2`
  - 拓扑图管理
  - Web UI / rosbridge / 常规后端服务
- 当前瓶颈更可能来自：
  - 大模型 / VLM 本地推理
  - 相机链路负载
  - 参数与外参
  - CPU 仍处于 `powersave` 模式

## 1.7 本机可运行模型规模估算

> 基于 **Ryzen 5 6600H + 12 GiB RAM + 当前未验证 GPU/ROCm 推理链路** 的工程估算。

| 模型规模 | 判断 | 说明 |
|---|---|---|
| 0.5B ～ 1.5B | 适合本地运行 | 适合简单指令解析、规则补全、轻量问答 |
| 2B ～ 4B | 可运行 | 适合低并发、本地辅助推理 |
| 7B（4-bit 量化） | 勉强可用 | 可以跑，但延迟明显，不适合作为核心实时交互模型 |
| 13B / 14B 及以上 | 不推荐 | 内存与响应速度都不理想 |

## 1.8 对 SSTG 的建议

- **本地负责**：ROS2、定位、建图、导航、拓扑图、UI 后端
- **大模型/VLM**：
  - 优先云端 API
  - 或独立算力节点
  - 不建议将中大型 VLM 压在 MaxTang 主控上

# 2. 相机

## 2.1 当前识别结果

仓库内关于相机型号的记录当前有两种表述：

| 来源 | 记录结果 |
|---|---|
| `sstg_system_manager` | Gemini 336L |
| `orbbec_stable.launch.py` / Orbbec SDK launch | Gemini 330 系列 |

## 2.2 当前更可信的工程判断

综合当前仓库内容，**相机应为 Orbbec Gemini 330 系列设备，项目内部命名/记录中按 Gemini 336L 使用**。

当前手册先记录为：

| 项目 | 信息 |
|---|---|
| 相机品牌 | Orbbec |
| 当前项目命名 | Gemini 336L |
| 驱动系列 | Gemini 330 Series |
| 驱动包 | `orbbec_camera` |

## 2.3 启动方式

当前 SSTG 导航全栈中，相机通过以下 launch 接入：

- `sstg_rrt_explorer/launch/library/orbbec_stable.launch.py`
- `yahboomcar_nav/launch/camera_gemini_336l.launch.py`

## 2.4 稳定模式配置

SSTG 当前为了降低负载，采用了低负载稳定配置：

| 项目 | 当前配置 |
|---|---|
| camera_name | `camera` |
| 后端 | `v4l2` |
| RGB 分辨率 | 640 × 480 |
| RGB 帧率 | 15 FPS |
| 深度分辨率 | 640 × 480 |
| 深度帧率 | 15 FPS |
| 点云 | 关闭 |
| 彩色点云 | 关闭 |
| 左右 IR | 关闭 |
| 加速度计 | 关闭 |
| 陀螺仪 | 关闭 |
| 硬件降噪 | 开启 |

## 2.5 历史高质量配置

仓库中也保留了更高分辨率配置记录：

| 项目 | 历史配置 |
|---|---|
| RGB 分辨率 | 1280 × 800 |
| RGB 帧率 | 30 FPS |
| 深度分辨率 | 1280 × 800 |
| 深度帧率 | 30 FPS |
| IMU | 开启 |

## 2.6 ROS2 相关话题

| 话题 | 用途 |
|---|---|
| `/camera/color/image_raw` | RGB 图像 |
| `/camera/depth/image_raw` | 深度图像 |
| `/camera/color/camera_info` | 彩色相机内参 |

## 2.7 在 SSTG 中的用途

- `sstg_perception` 订阅 RGB / Depth 做语义采集
- 节点全景采集与目标点图像记录
- 后续支持 RTAB-Map / 视觉增强导航

## 2.8 当前结论

- 当前相机已经明确接入 SSTG 语义感知链路
- 当前主配置偏向 **稳定优先、低负载优先**
- 若后续要做更强的视觉语义建图，可再评估是否恢复到 1280×800@30

# 3. 激光雷达

## 3.1 型号记录

当前仓库内关于激光雷达存在两种记录：

| 来源 | 记录结果 |
|---|---|
| `sstg_system_manager` | RPLidar S2 |
| `hardware_bringup.launch.py` 注释 | RPLidar S2 |
| `sstg_rrt_explorer` 文档部分描述 | RPLidar A1 |

## 3.2 当前更可信的工程判断

从 **实际 launch 参数** 看，你现在的 SSTG 硬件启动配置更偏向：

| 项目 | 信息 |
|---|---|
| 雷达品牌 | SLAMTEC / RPLidar 系列 |
| 当前主配置推断 | **RPLidar S2** |
| ROS2 驱动 | `sllidar_ros2` |
| 节点名 | `sllidar_node` |

原因：

- 当前硬件启动里显式使用 `serial_baudrate = 1000000`
- 这与仓库内 `sllidar_s2_launch.py` 的默认配置一致
- 而 `A1` 的默认波特率是 `115200`

## 3.3 当前启动配置

| 项目 | 当前配置 |
|---|---|
| 驱动包 | `sllidar_ros2` |
| 可执行文件 | `sllidar_node` |
| 通信方式 | serial |
| 串口设备 | `/dev/rplidar` |
| 波特率 | 1000000 |
| frame_id | `laser` |
| inverted | false |
| angle_compensate | true |

## 3.4 ROS2 相关话题

| 话题 | 用途 |
|---|---|
| `/scan` | 激光扫描数据 |

## 3.5 在 SSTG 中的用途

- `slam_toolbox` 建图输入
- `AMCL` 定位输入
- `Nav2` 局部/全局代价地图障碍层输入
- RRT 探索时的环境覆盖与未知边界探索

## 3.6 当前结论

- 你的导航主链路强依赖 `/scan`
- 从启动参数判断，当前更像 **RPLidar S2**
- 文档里残留的 `A1` 说法建议后续统一清理

# 4. 底盘结构

## 4.1 底盘平台

| 项目 | 信息 |
|---|---|
| 平台 | Yahboom X3 |
| 运动学类型 | 麦克纳姆轮 / 全向底盘 |
| 轮子数量 | 4 |
| 电机布局 | 前右 / 前左 / 后右 / 后左 |

## 4.2 结构依据

从 `yahboomcar_X3.urdf.xacro` 可以确认：

- 存在 4 个轮关节：
  - `front_right_joint`
  - `front_left_joint`
  - `back_right_joint`
  - `back_left_joint`
- 使用 `mecanum` 相关 mesh 与结构描述

## 4.3 底盘相关节点

| 组件 | 节点/程序 |
|---|---|
| 底盘驱动 | `Mcnamu_driver_X3` |
| 底盘基础节点 | `base_node_X3` |
| IMU 滤波 | `imu_filter_madgwick_node` |
| 里程计融合 | `robot_localization/ekf_node` |

## 4.4 里程计链路

当前底盘定位相关链路是：

- `base_node_X3` 发布原始底盘里程计 / IMU 数据
- `imu_filter_madgwick` 处理 IMU
- `robot_localization` EKF 融合后输出 `/odom`

## 4.5 传感器安装位姿（来自 URDF / launch）

| 传感器 | 相对 `base_link` 位姿 |
|---|---|
| 激光雷达 | `x=0.0435, y≈0, z=0.11` |
| 相机 | `x=0.057105, y≈0, z=0.03755` |
| IMU | `x=-0.06, y=0.01, z=0.01` |

## 4.6 当前结论

- 你这台车是典型的 **全向麦轮平台**
- 对应 AMCL 中使用 `OmniMotionModel` 是合理的
- 底盘本体结构已经足够支撑室内语义导航实验

# 5. 网站与访问入口

## 5.1 本地 UI

| 项目 | 信息 |
|---|---|
| 本地访问地址 | `http://<MaxTang的IP>:5173` |
| UI 工程目录 | `sstg_ui_app/` |
| 启动命令 | `npm run dev` |

## 5.2 公网入口

| 项目 | 信息 |
|---|---|
| 公网地址 | `https://iadc.sstgnav.cc.cd` |
| 方式 | Cloudflare Tunnel |

## 5.3 当前作用

- 提供 SSTG 的 Web UI 操作界面
- 支持系统一键启动、状态查看、地图和导航交互

# 6. 模块速览

## 6.1 核心模块

| 模块 | 一句话说明 |
|---|---|
| `sstg_interaction_manager` | 任务编排与系统协调 |
| `sstg_nlp_interface` | 自然语言理解与意图提取 |
| `sstg_navigation_planner` | 语义目标匹配与路径规划 |
| `sstg_navigation_executor` | 调用 Nav2 执行导航 |
| `sstg_map_manager` | 拓扑地图存储、查询、可视化 |
| `sstg_perception` | 相机订阅、图像采集、语义标注 |
| `sstg_rrt_explorer` | 自主探索建图与拓扑节点建立 |
| `sstg_system_manager` | 硬件启停、模式切换、系统状态监控 |

## 6.2 当前系统主线

SSTG 当前主线可以概括为：

1. 底盘 + IMU + 激光雷达启动
2. EKF 输出 `/odom`
3. `slam_toolbox` 建图 / `AMCL` 定位
4. `Nav2` 执行几何导航
5. `sstg_map_manager` 管理拓扑图
6. `sstg_perception` 采集视觉语义
7. `sstg_nlp_interface` + `sstg_navigation_planner` 完成自然语言到导航目标的映射

# 7. 常用检查命令

## 7.1 主控信息

```bash
hostnamectl
cat /etc/os-release
lscpu
free -h
lsblk
lspci | grep -Ei 'vga|ethernet|network'
```

## 7.2 相机

```bash
ros2 topic list | grep camera
ros2 topic hz /camera/color/image_raw
ros2 topic echo /camera/color/image_raw --once
```

## 7.3 激光雷达

```bash
ls /dev/rplidar
ros2 topic hz /scan
ros2 topic echo /scan --once
```

## 7.4 CPU governor

```bash
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
```

# 8. 更新记录

| 日期 | 内容 |
|---|---|
| 2026-04-12 | 建立快速检索手册；补充 MaxTang、相机、激光雷达、底盘、网站与模块速览 |

