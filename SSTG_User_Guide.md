# SSTG Navigation System - User Guide

## 概述

SSTG (Spatial Semantic Topological Graph) 导航系统是一个**完整的机器人导航解决方案**，集成了自然语言理解、语义地图构建、拓扑规划和导航执行功能。该系统基于ROS2 Humble开发，支持多模态输入和智能任务规划，实现从自然语言指令到物理导航执行的完整端到端流程。

### 💡 核心特性

- ✅ **自然语言导航**: 用中文或英文指令导航，无需复杂坐标输入
- ✅ **语义地图管理**: 基于拓扑图的地图表示，支持房间、对象等高层次语义
- ✅ **多模态感知**: 集成视觉语言模型(VLM)进行语义理解
- ✅ **Nav2集成**: 与ROS2生态完全兼容
- ✅ **开源易用**: 完整文档、测试脚本、示例代码

### 核心组件

| 组件 | 功能 | 关键文件位置 |
|------|------|-----------|
| **Map Manager** (`sstg_map_manager`) | 拓扑地图管理、Web管理界面、节点查询 | `sstg_nav_ws/src/sstg_map_manager/` |
| **NLP Interface** (`sstg_nlp_interface`) | 自然语言处理、意图识别、LLM集成 | `sstg_nav_ws/src/sstg_nlp_interface/` |
| **Navigation Planner** (`sstg_navigation_planner`) | 语义路径规划、候选点生成、拓扑规划 | `sstg_nav_ws/src/sstg_navigation_planner/` |
| **Navigation Executor** (`sstg_navigation_executor`) | Nav2导航执行、进度监控、反馈发布 | `sstg_nav_ws/src/sstg_navigation_executor/` |
| **Interaction Manager** (`sstg_interaction_manager`) | 任务编排、系统协调、状态管理 | `sstg_nav_ws/src/sstg_interaction_manager/` |
| **Perception** (`sstg_perception`) | 多模态感知、语义标注、视觉处理 | `sstg_nav_ws/src/sstg_perception/` |
| **Messages** (`sstg_msgs`) | 统一接口定义(7消息+8服务) | `sstg_nav_ws/src/sstg_msgs/` |

## 系统要求

### 硬件和操作系统

- **操作系统**: Ubuntu 22.04 LTS
- **硬件**: 任何支持ROS2和Nav2的移动机器人（已验证支持Yahboom ROS2机器人）
- **处理器**: 双核以上（推荐四核或更高）
- **内存**: 2GB以上（推荐4GB+）

### 软件依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| **ROS2** | Humble Hawksbill | 核心中间件 |
| **Python** | 3.10+ | 节点实现 |
| **Nav2** | Humble版本 | 导航执行 |
| **NetworkX** | 3.0+ | 图算法 |
| **FastAPI** | 0.100+ | Web界面 |
| **Qwen-VLM** | (可选) | 视觉语言模型 |

### 前置检查

```bash
# 验证ROS2安装
ros2 --version

# 验证Python版本
python3 --version

# 验证Nav2可用
ros2 pkg list | grep nav2
```

## 安装和设置

### 第一步：环境预检查

```bash
# 验证系统环境
uname -a                    # 应输出 Linux
ros2 --version             # 应显示 ROS 2 Humble
python3 --version          # 应显示 3.10+
```

如果环境不完整，请参考 [INSTALLATION.md](sstg_nav_ws/INSTALLATION.md) 进行详细安装。

### 第二步：克隆或进入工作空间

```bash
# 如果已有工作空间，进入目录
cd ~/sstg_nav

# 确认目录结构（应该看到这两个工作空间）
ls -la | grep nav_ws
```

### 第三步：构建SSTG系统

```bash
# 进入SSTG独立工作空间
cd ~/sstg_nav/sstg_nav_ws

# 安装系统依赖（如果之前没有安装）
sudo apt-get install ros-humble-nav2 ros-humble-rclpy -y

# 构建所有包（第一次需要3-5分钟）
colcon build --symlink-install

# Source环境变量
source install/setup.bash
```

> **注意**: 如果构建失败，检查 [INSTALLATION.md](sstg_nav_ws/INSTALLATION.md) 中的常见问题。

### 第四步：验证安装

```bash
# 检查所有SSTG包是否成功构建
ros2 pkg list | grep sstg

# 应该看到7个包（如果看不全，继续看下面的验证）
# sstg_interaction_manager
# sstg_map_manager
# sstg_msgs
# sstg_navigation_executor
# sstg_navigation_planner
# sstg_nlp_interface
# sstg_perception

# 验证节点可执行性（检查是否能看到帮助信息）
ros2 run sstg_map_manager map_manager_node --help 2>&1 | head -5
```

如果看到节点帮助信息，说明安装成功！

## 基本使用方法

### 快速启动 (推荐方式)

**最简单的启动方式**：使用集成测试脚本，自动初始化地图并启动所有节点

```bash
# 进入项目根目录
cd ~/sstg_nav

# 运行启动脚本（自动处理所有事情）
./project_test/run_tests.sh
```

**脚本做的事情**:
1. ✅ 初始化测试拓扑地图（4个房间，16个导航节点）
2. ✅ 启动所有5个ROS2节点
3. ✅ 运行集成测试验证系统
4. ✅ 自动清理进程

**预期输出**: 参考 [TESTING.md](project_test/TESTING.md) 了解测试细节

### 手动启动各组件 (学习模式)

如果想逐步理解系统，可以手动启动各组件：

**终端 1 - 启动Map Manager（地图管理）**
```bash
cd ~/sstg_nav
source sstg_nav_ws/install/setup.bash

# 初始化测试地图
python3 project_test/init_test_map.py

# 启动地图管理节点
ros2 run sstg_map_manager map_manager_node
```

**终端 2 - 启动NLP Interface（自然语言处理）**
```bash
source ~/sstg_nav/sstg_nav_ws/install/setup.bash
ros2 run sstg_nlp_interface nlp_node
```

**终端 3 - 启动Navigation Planner（路径规划）**
```bash
source ~/sstg_nav/sstg_nav_ws/install/setup.bash
ros2 run sstg_navigation_planner planning_node
```

**终端 4 - 启动Navigation Executor（导航执行）**
```bash
source ~/sstg_nav/sstg_nav_ws/install/setup.bash
ros2 run sstg_navigation_executor executor_node
```

**终端 5 - 启动Interaction Manager（系统协调）**
```bash
source ~/sstg_nav/sstg_nav_ws/install/setup.bash
ros2 run sstg_interaction_manager interaction_manager_node
```

### 验证所有服务已就绪

启动后，检查所有关键服务是否可用：

```bash
# 列出所有SSTG服务
ros2 service list | grep -E '^/[a-z]' | head -20

# 应该看到这些核心服务：
# /start_task                  - 启动导航任务
# /cancel_task                 - 取消任务
# /query_task_status          - 查询任务状态
# /process_nlp_query          - 处理自然语言
# /plan_navigation            - 规划路径
# /execute_navigation         - 执行导航
# /get_node_pose              - 获取节点位置
```

### 执行导航任务

#### 方法1: 发送自然语言指令 (推荐！)

**最直接的方式** - 用自然语言指令机器人导航：

```bash
# 用中文发送任务
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: '去客厅',
  context: 'home'
}"

# 用英文发送任务
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: 'Go to the kitchen',
  context: 'home'
}"
```

**示例指令**:
- "去客厅" / "Go to living room"
- "导航到卧室" / "Navigate to bedroom"
- "去沙发" / "Go to the sofa"
- "带我去厨房" / "Take me to the kitchen"

#### 方法2: 分步调用各服务 (深入理解)

如果要手动控制各个步骤，可以逐个调用：

**步骤1: NLP处理 - 识别意图**
```bash
ros2 service call /process_nlp_query sstg_msgs/srv/ProcessNLPQuery "{
  text_input: '去客厅',
  context: 'home'
}"

# 预期输出示例:
# intent: navigate_to
# target_location: living_room  
# confidence: 0.95
```

**步骤2: 路径规划 - 生成路径**
```bash
ros2 service call /plan_navigation sstg_msgs/srv/PlanNavigation "{
  intent: 'navigate_to',
  target_location: 'living_room',
  context: 'home'
}"

# 预期输出示例:
# success: true
# candidate_poses: [pose1, pose2, pose3]  # 多个备选点
# path: [node1, node2, node3]             # 拓扑路径
```

**步骤3: 执行导航 - 控制机器人**
```bash
# 获取目标点的坐标
ros2 service call /get_node_pose sstg_msgs/srv/GetNodePose "{
  node_id: 'living_room_center'
}"

# 执行导航到目标点
ros2 service call /execute_navigation sstg_msgs/srv/ExecuteNavigation "{
  target_pose: {
    header: {frame_id: 'map'},
    pose: {
      position: {x: 2.5, y: 1.0, z: 0.0},
      orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}
    }
  }
}"
```

### 监控任务执行

```bash
# 查询当前任务状态
ros2 service call /query_task_status std_srvs/srv/Trigger

# 订阅导航反馈（实时监看机器人状态）
ros2 topic echo /navigation_feedback

# 订阅系统日志
ros2 topic echo /system_log

# 查看机器人当前位置（需要AMCL运行）
ros2 topic echo /amcl_pose
```

### 取消任务

```bash
# 立即停止当前导航任务
ros2 service call /cancel_task std_srvs/srv/Trigger

# 预期输出: success: true
```

## 高级功能

### 1. 地图管理

#### 查看和理解当前地图

```bash
# 查看地图中所有可用节点
ros2 service call /get_node_pose sstg_msgs/srv/GetNodePose "{
  node_id: 'all'
}"

# 查询特定节点的位置和信息
ros2 service call /get_node_pose sstg_msgs/srv/GetNodePose "{
  node_id: 'living_room_center'
}"
```

#### 使用Web管理界面添加/编辑节点 (高级)

```bash
# 启动Map Manager的Web服务
# 访问 http://localhost:8080 进行图形化管理
# - 可视化查看拓扑图
# - 点击添加新节点
# - 修改节点的语义标签
```

更多详情参考: [Map Manager文档](sstg_nav_ws/src/sstg_map_manager/doc/QUICK_START.md)

### 2. 自定义NLP命令

系统支持多种自然语言表达：

```bash
# 同义表达都被理解为相同意图
ros2 service call /process_nlp_query sstg_msgs/srv/ProcessNLPQuery "{
  text_input: '我想去厨房',
  context: 'home'
}"

# 在特定场景下的表达
ros2 service call /process_nlp_query sstg_msgs/srv/ProcessNLPQuery "{
  text_input: '返回客厅',
  context: 'home'
}"
```

### 3. 并发任务处理

系统支持任务队列和优先级：

```bash
# 当前任务执行时，新任务会被排队
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: '去卧室',
  context: 'home'
}"

# 查询当前任务和队列中的任务
ros2 service call /query_task_status std_srvs/srv/Trigger
```

### 4. 使用图像进行导航 (可选)

系统可集成视觉信息进行导航：

```bash
# 发送包含对象描述的导航任务
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: '去有红色沙发的地方',
  context: 'living room'
}"
```

## 配置和定制

### 修改系统参数

系统参数配置文件位置:

```bash
# 查看各个包的配置
ls -la ~/sstg_nav/sstg_nav_ws/src/*/config/

# 例如查看规划器参数
cat ~/sstg_nav/sstg_nav_ws/src/sstg_navigation_planner/config/planning_params.yaml
```

### 常用参数调整

| 参数 | 位置 | 作用 | 建议值 |
|------|------|------|--------|
| `semantic_match_threshold` | planner config | 语义匹配阈值 | 0.5-0.8 |
| `nlp_confidence_threshold` | nlp config | NLP置信度阈值 | 0.7+ |
| `max_task_queue_size` | manager config | 任务队列大小 | 5-10 |
| `task_timeout` | manager config | 任务超时时间 | 30-60s |

## 常见问题排查

### 1. 构建或启动失败

**问题**: `colcon build` 失败，或者启动时看到错误

**诊断步骤**:
```bash
# 检查依赖是否完整
rosdep check-rosdeps --all --from-paths src --rosdistro humble

# 清理重新构建
rm -rf build install log
colcon build --symlink-install 2>&1 | tee build.log

# 检查构建日志
tail -50 build.log | grep -i error
```

**常见原因和解决**:
- ❌ 缺少ROS2依赖 → 运行: `sudo apt-get install ros-humble-nav2 ros-humble-rclpy`
- ❌ Python依赖缺失 → 运行: `pip3 install networkx requests fastapi uvicorn`
- ❌ 权限问题 → 使用 `sudo` 或检查文件权限

### 2. 服务不可用或无响应

**问题**: `ros2 service call` 返回超时或连接错误

**诊断**:
```bash
# 检查节点是否正常运行
ps aux | grep -E "ros2|python" | grep -v grep

# 检查所有活跃服务
ros2 service list

# 检查特定服务
ros2 service type /start_task

# 查看节点日志
ros2 node list
ros2 node info /map_manager_node
```

**解决方案**:
```bash
# 方案1: 重启所有节点
pkill -f "ros2 run"
sleep 2
# 重新运行 ./project_test/run_tests.sh 或手动启动

# 方案2: 检查ROS2环信息
echo $ROS_DOMAIN_ID        # 应该为空或一致的值
echo $ROS_MIDDLEWARE_IMPL  # 应该显示rmw实现
```

### 3. NLP处理失败或置信度低

**问题**: 意图识别失败，或返回低置信度 (< 0.7)

**排查**:
```bash
# 测试NLP服务
ros2 service call /process_nlp_query sstg_msgs/srv/ProcessNLPQuery "{
  text_input: '去客厅',
  context: 'home'
}"

# 查看返回的置信度字段
# confidence: 0.0 表示完全失败
```

**原因和解决**:
- ❌ VLM API未连接 → 检查网络，确认VLM服务可用
- ❌ 输入格式错误 → 确保 `text_input` 不为空
- ❌ 上下文不匹配 → 尝试改变 `context` 参数 (如 'home' → 'office')

### 4. 导航规划失败

**问题**: `plan_navigation` 返回 "No candidate nodes found"

**排查步骤**:
```bash
# 检查地图是否正确加载
ros2 service call /get_node_pose sstg_msgs/srv/GetNodePose "{ node_id: 'all' }"

# 检查目标位置是否存在
ros2 service call /get_node_pose sstg_msgs/srv/GetNodePose "{ node_id: 'living_room_center' }"

# 查看规划器日志
ros2 topic echo /plan --once
```

**解决方案**:
```bash
# 重新初始化地图
python3 project_test/init_test_map.py

# 验证Map Manager节点运行正常
ros2 node list | grep map_manager

# 检查图结构完整性
# 理想情况下应该有4个房间，每个房间4个节点
```

### 5. Nav2集成问题

**问题**: 执行导航时失败，或执行器无响应

**诊断**:
```bash
# 检查Nav2服务
ros2 service list | grep nav2
ros2 service list | grep navigate_to_pose

# 检查执行器能否连接到Nav2
ps aux | grep -i nav2

# 查看Nav2日志
ros2 topic echo /goal_pose --once
```

**解决**:
```bash
# 确保Nav2栈已启动（可能需要手动启动）
ros2 launch nav2_bringup navigation_launch.py use_sim_time:=false

# 或者在模拟环境中
ros2 launch nav2_bringup navigation_launch.py use_sim_time:=true
```

### 6. 性能问题 - 系统响应缓慢

**问题**: 服务响应时间过长（> 5秒）

**优化方案**:
```bash
# 1. 监控CPU和内存使用
top -p $(pidof python3 | tr ' ' ',')
free -h

# 2. 检查各服务响应时间
time ros2 service call /process_nlp_query sstg_msgs/srv/ProcessNLPQuery "{ text_input: '去客厅', context: 'home' }"

# 3. 查看节点间通信延迟
ros2 topic hz /navigation_feedback
```

**改进方案**:
- 增加硬件资源（内存、CPU）
- 减小并发任务队列
- 调整语义匹配的灵敏度参数

### 7. 获取更多帮助

```bash
# 生成详细日志用于诊断
export ROS_LOG_LEVEL=debug
ros2 run sstg_interaction_manager interaction_manager_node

# 查看测试报告
cat ~/sstg_nav/project_test/integration_test_report.md

# 检查各包的详细文档
ls -la ~/sstg_nav/sstg_nav_ws/src/*/doc/
```

## 实验和示例

### 实验1: 验证基本导航流程

**目标**: 确保系统正常工作

**步骤**:
```bash
# 1. 启动系统
cd ~/sstg_nav
./project_test/run_tests.sh

# 2. 在新终端发送导航任务
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: '去客厅',
  context: 'home'
}"

# 3. 监听反馈
ros2 topic echo /navigation_feedback

# 4. 查询最终结果
ros2 service call /query_task_status std_srvs/srv/Trigger
```

**成功标志**:
- ✅ 返回成功状态
- ✅ `/navigation_feedback` 有消息更新
- ✅ 任务状态显示为 "completed"

### 实验2: 测试多语言支持

```bash
# 中文指令
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{ text_input: '导航到卧室', context: 'home' }"

# 英文指令
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{ text_input: 'Navigate to bedroom', context: 'home' }"

# 混合表达
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{ text_input: 'Take me to the kitchen', context: 'home' }"
```

### 实验3: 性能基准测试

```bash
# 计时：从请求到响应的完整流程
time ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{ text_input: '去客厅', context: 'home' }"

# 并发请求测试（需要改进系统设计）
for i in {1..5}; do
  ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{ text_input: '去客厅', context: 'home' }" &
done
wait
```

## 开发指南 (面向开发者)

### 项目结构理解

```
sstg_nav_ws/
├── src/
│   ├── sstg_msgs/                    # 消息和服务定义（接口层）
│   ├── sstg_map_manager/             # 地图管理（数据层）
│   ├── sstg_perception/              # 感知处理（输入层）
│   ├── sstg_nlp_interface/           # 自然语言处理（理解层）
│   ├── sstg_navigation_planner/      # 路径规划（规划层）
│   ├── sstg_navigation_executor/     # 导航执行（执行层）
│   └── sstg_interaction_manager/     # 任务编排（协调层）
├── build/                            # 编译输出
├── install/                          # 安装输出
└── log/                              # 运行日志
```

### 模块开发文档

| 模块 | 位置 | 文档 |
|------|------|------|
| Map Manager | `src/sstg_map_manager/` | doc/QUICK_START.md |
| NLP Interface | `src/sstg_nlp_interface/` | doc/ |
| Navigation Planner | `src/sstg_navigation_planner/` | doc/ |
| Navigation Executor | `src/sstg_navigation_executor/` | docs/ |
| Interaction Manager | `src/sstg_interaction_manager/` | docs/ |
| Perception | `src/sstg_perception/` | doc/ |

### 修改和扩展系统

#### 添加新导航命令

1. 编辑 `sstg_nlp_interface` 的意图识别规则
2. 修改 `sstg_navigation_planner` 的目标匹配逻辑
3. 添加测试用例验证

#### 自定义地图结构

编辑 `project_test/init_test_map.py` 修改初始地图，或使用Map Manager的Web界面。

#### 集成新的导航算法

在 `sstg_navigation_planner` 中扩展规划器，参考现有算法实现。

### 测试

```bash
# 运行完整集成测试
cd ~/sstg_nav
./project_test/run_tests.sh

# 查看测试结果
cat project_test/integration_test_report.md

# 单个包的测试
colcon test --packages-select sstg_map_manager
```

## 故障排除速查表

| 问题 | 快速诊断 | 解决方案 |
|------|--------|--------|
| 构建失败 | `colcon build --symlink-install` | 检查依赖，参考构建部分 |
| 服务无响应 | `ros2 service list` | 重启节点，检查日志 |
| NLP失败 | `ros2 service call /process_nlp_query` | 检查网络和置信度阈值 |
| 规划失败 | `ros2 service call /plan_navigation` | 验证地图，重新初始化 |
| Nav2连接失败 | `ros2 service list \| grep nav2` | 启动Nav2，检查坐标系 |

## 资源和文档

### 官方文档
- [ROS2官方](https://docs.ros.org/)
- [Nav2文档](https://navigation.ros.org/)
- [NetworkX文档](https://networkx.org/)

### 项目文档
- README.md - 了解项目整体状况
- PROJECT_SUMMARY.md - 完成情况统计
- WORKSPACE_MIGRATION_SUMMARY.md - 工作空间迁移信息和快速参考
- sstg_nav_ws/README.md - 工作空间特定信息
- sstg_nav_ws/INSTALLATION.md - 详细安装步骤
- project_test/TESTING.md - 测试框架说明

### 在线资源
- 本系统支持中英文双语导航
- 基于ROS2 Humble Hawksbill
- 支持所有ROS2兼容的导航栈

## 获取帮助

### 系统诊断工具

```bash
# 全面诊断
bash -c "
echo '=== System Info ==='; uname -a
echo '=== ROS2 Info ==='; ros2 --version
echo '=== Python ==='; python3 --version
echo '=== SSTG Packages ==='; ros2 pkg list | grep sstg
echo '=== Running Nodes ==='; ros2 node list
echo '=== Services ==='; ros2 service list | head -20
"
```

### 收集日志用于调试

```bash
# 启用详细日志并收集
export ROS_LOG_LEVEL=debug
cd ~/sstg_nav

# 后台运行，重定向日志
ros2 run sstg_interaction_manager interaction_manager_node > debug.log 2>&1 &

# 执行操作
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{ text_input: '去客厅', context: 'home' }"

# 查看日志
cat debug.log | tail -50
```

## 下一步

### 初级用户
1. 按照快速启动完成系统安装
2. 运行 `./project_test/run_tests.sh` 验证系统
3. 尝试发送简单的导航命令
4. 阅读各组件文档了解工作原理

### 中级用户
1. 自定义地图和导航点
2. 调整系统参数和阈值
3. 集成自己的应用
4. 扩展现有功能

### 高级用户
1. 修改和优化算法
2. 开发新的导航模式
3. 集成新的传感器和执行器
4. 跨平台和多机器人集成

## 许可和致谢

本系统基于ROS2生态开发，充分利用了开源社区的优秀工作。

---

**文档最后更新**: 2026-03-29
**系统版本**: SSTG Phase 4
**维护状态**: ✅ 活跃维护

---

## 快速开始命令速查

```bash
# 进入工作空间
cd ~/sstg_nav

# 一键启动所有系统
./project_test/run_tests.sh

# 源环境（如需手动启动）
source sstg_nav_ws/install/setup.bash

# 发送导航任务（在另一终端）
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: '去客厅',
  context: 'home'
}"

# 查询任务状态
ros2 service call /query_task_status std_srvs/srv/Trigger

# 监控反馈
ros2 topic echo /navigation_feedback

# 停止任务
ros2 service call /cancel_task std_srvs/srv/Trigger

# 清理进程（如需）
pkill -f "ros2 run"
```

**现在您已准备好使用SSTG导航系统！祝您使用愉快！** 🚀