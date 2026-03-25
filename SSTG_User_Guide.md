# SSTG Navigation System - User Guide

## 概述

SSTG (Spatial Semantic Topological Graph) 导航系统是一个完整的机器人导航解决方案，集成了自然语言理解、语义地图构建、拓扑规划和导航执行功能。该系统基于ROS2 Humble开发，支持多模态输入和智能任务规划。

### 核心组件

1. **Map Manager** (`sstg_map_manager`): 拓扑地图管理和节点姿态查询
2. **NLP Interface** (`sstg_nlp_interface`): 自然语言处理和意图识别
3. **Navigation Planner** (`sstg_navigation_planner`): 语义路径规划和候选点生成
4. **Navigation Executor** (`sstg_navigation_executor`): Nav2导航执行和监控
5. **Interaction Manager** (`sstg_interaction_manager`): 任务编排和系统协调

## 系统要求

- **ROS2**: Humble Hawksbill
- **Python**: 3.10+
- **操作系统**: Ubuntu 22.04
- **硬件**: Yahboom ROS2机器人 (支持Nav2)
- **依赖**: Nav2, tf_transformations, NetworkX, requests

## 安装和设置

### 1. 工作空间准备

```bash
cd ~/yahboomcar_ros2_ws
source yahboomcar_ws/install/setup.bash
```

### 2. 构建所有包

```bash
colcon build --symlink-install
source install/setup.bash
```

### 3. 验证安装

```bash
# 检查所有包是否可用
ros2 pkg list | grep sstg

# 验证节点可执行性
ros2 run sstg_map_manager map_manager_node --help
ros2 run sstg_nlp_interface nlp_node --help
ros2 run sstg_navigation_planner planning_node --help
ros2 run sstg_navigation_executor executor_node --help
ros2 run sstg_interaction_manager interaction_manager_node --help
```

## 基本使用方法

### 启动完整系统

使用提供的启动脚本：

```bash
cd ~/yahboomcar_ros2_ws
./test/start_integration_test.sh
```

或者手动启动各组件：

```bash
# Terminal 1: Map Manager
ros2 run sstg_map_manager map_manager_node

# Terminal 2: NLP Interface
ros2 run sstg_nlp_interface nlp_node

# Terminal 3: Navigation Planner
ros2 run sstg_navigation_planner planning_node

# Terminal 4: Navigation Executor
ros2 run sstg_navigation_executor executor_node

# Terminal 5: Interaction Manager
ros2 run sstg_interaction_manager interaction_manager_node
```

### 验证服务可用性

```bash
# 检查所有SSTG服务
ros2 service list | grep -E '(start_task|cancel_task|query_task_status|get_node_pose|process_nlp_query|plan_navigation|execute_navigation)'
```

### 基本导航任务

#### 方法1: 使用交互管理器 (推荐)

```bash
# 发送自然语言导航指令
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: 'Go to the living room',
  context: 'home environment'
}"

# 查询任务状态
ros2 service call /query_task_status std_srvs/srv/Trigger

# 取消当前任务
ros2 service call /cancel_task std_srvs/srv/Trigger
```

#### 方法2: 直接调用各组件

```bash
# 1. NLP处理
ros2 service call /process_nlp_query sstg_msgs/srv/ProcessNLPQuery "{
  text_input: 'Take me to the kitchen',
  context: 'home'
}"

# 2. 路径规划
ros2 service call /plan_navigation sstg_msgs/srv/PlanNavigation "{
  intent: 'navigate_to',
  target_location: 'kitchen',
  context: 'home'
}"

# 3. 执行导航
ros2 service call /execute_navigation sstg_msgs/srv/ExecuteNavigation "{
  target_pose: {
    header: {frame_id: 'map'},
    pose: {
      position: {x: 2.0, y: 1.0, z: 0.0},
      orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}
    }
  }
}"
```

### 监控导航进度

```bash
# 订阅导航反馈
ros2 topic echo /navigation_feedback

# 查看机器人姿态
ros2 topic echo /amcl_pose

# 监控规划状态
ros2 topic echo /plan
```

## 高级功能

### 自定义地图管理

#### 添加地图节点

```python
# 使用Map Manager的Web界面 (如果启用)
# 访问 http://localhost:8080 添加语义节点
```

#### 查询节点信息

```bash
# 获取特定节点姿态
ros2 service call /get_node_pose sstg_msgs/srv/GetNodePose "{
  node_id: 'living_room_sofa'
}"
```

### 多模态输入

#### 图像+文本导航

```bash
# 发送包含图像描述的任务
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: 'Go to where the red chair is',
  context: 'living room',
  image_data: '<base64_encoded_image>'
}"
```

### 任务编排

#### 复杂任务序列

```bash
# 厨房取物任务
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: 'Go to kitchen, pick up the cup, then come back',
  context: 'home assistance'
}"
```

## 示例实验场景

### 实验1: 基础导航测试

**目标**: 验证基本导航功能

**步骤**:
1. 启动完整SSTG系统
2. 发送简单导航指令: "Go to living room"
3. 观察机器人导航行为
4. 验证到达目标位置

**预期结果**:
- NLP正确识别导航意图
- 规划器生成有效路径
- 执行器成功导航到目标
- 反馈系统报告任务完成

### 实验2: 并发任务处理

**目标**: 测试任务取消和并发处理

**步骤**:
1. 发送导航任务: "Go to kitchen"
2. 立即发送另一个任务: "Go to bedroom"
3. 观察系统如何处理并发请求
4. 测试任务取消功能

**预期结果**:
- 系统拒绝第二个并发任务
- 允许取消当前任务
- 状态查询正确反映任务状态

### 实验3: 语义理解测试

**目标**: 验证自然语言理解能力

**测试指令**:
- "Take me to the sofa in the living room"
- "Go to where I usually watch TV"
- "Navigate to the dining area"
- "Find the red chair"

**预期结果**:
- 高置信度识别导航意图
- 正确提取目标位置
- 处理模糊或上下文相关指令

### 实验4: 错误处理测试

**目标**: 验证系统鲁棒性

**测试场景**:
1. 发送无效位置: "Go to Mars"
2. 导航到不存在的地点: "Go to the moon"
3. 网络中断期间的任务
4. Nav2服务不可用时的行为

**预期结果**:
- 优雅的错误处理
- 有意义的错误消息
- 系统状态保持一致

### 实验5: 性能基准测试

**目标**: 评估系统性能

**测试指标**:
- NLP响应时间 (< 2秒)
- 规划计算时间 (< 5秒)
- 导航启动延迟 (< 1秒)
- 任务取消响应 (< 1秒)
- 系统启动时间 (< 30秒)

## 故障排除

### 常见问题

#### 1. 服务不可用

**症状**: `ros2 service list` 不显示SSTG服务

**解决**:
```bash
# 检查节点是否运行
ps aux | grep ros2

# 重启服务
./test/start_integration_test.sh

# 检查日志
tail -f ~/yahboomcar_ros2_ws/test/logs/*.log
```

#### 2. NLP处理失败

**症状**: 意图识别返回低置信度或错误

**解决**:
- 检查网络连接 (VLM API需要互联网)
- 验证输入格式
- 查看NLP接口日志

#### 3. 导航规划失败

**症状**: "No candidate nodes found"

**解决**:
- 检查拓扑地图是否正确加载
- 验证目标位置存在于地图中
- 确认语义匹配参数

#### 4. Nav2连接问题

**症状**: 执行器无法连接到Nav2

**解决**:
```bash
# 确保Nav2栈正在运行
ros2 launch nav2_bringup navigation_launch.py

# 检查Nav2服务
ros2 service list | grep nav2
```

### 日志分析

```bash
# 查看所有服务日志
tail -f ~/yahboomcar_ros2_ws/test/logs/*.log

# 过滤错误信息
grep -r "ERROR\|WARN" ~/yahboomcar_ros2_ws/test/logs/
```

### 调试模式

```bash
# 启用详细日志
export ROS_LOG_LEVEL=debug

# 运行单个组件进行调试
ros2 run sstg_interaction_manager interaction_manager_node --ros-args --log-level debug
```

## 性能优化

### 系统调优

1. **减少启动时间**: 预加载地图和模型
2. **优化响应时间**: 调整服务QoS设置
3. **内存管理**: 监控各组件内存使用

### 网络优化

1. **VLM缓存**: 本地缓存常用查询结果
2. **压缩传输**: 优化图像数据传输
3. **连接池**: 复用网络连接

## 扩展开发

### 添加新功能

1. **自定义NLP模型**: 修改 `sstg_nlp_interface`
2. **新规划算法**: 扩展 `sstg_navigation_planner`
3. **额外传感器**: 集成到感知管道

### 集成其他系统

1. **语音接口**: 添加语音到文本转换
2. **视觉SLAM**: 增强地图构建
3. **多机器人协调**: 扩展任务管理

## 总结

SSTG导航系统提供了一个完整的机器人导航解决方案，从自然语言输入到物理导航执行。通过本指南，您可以：

- ✅ 快速启动和配置系统
- ✅ 执行基本和高级导航任务
- ✅ 设计和运行各种实验场景
- ✅ 诊断和解决常见问题
- ✅ 扩展系统以满足特定需求

系统已通过完整集成测试，所有核心功能正常工作，准备进行实际机器人实验。