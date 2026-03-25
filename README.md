# SSTG Navigation System

[![ROS2](https://img.shields.io/badge/ROS2-Humble-green)](https://docs.ros.org/en/humble/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-orange)](LICENSE)

**Spatial Semantic Topological Graph Navigation System** - 智能机器人导航的完整解决方案

## 🌟 项目概述

SSTG导航系统是一个基于ROS2的智能机器人导航框架，集成了自然语言理解、语义地图构建、拓扑路径规划和导航执行功能。通过多模态输入（文本+图像），系统能够理解用户的导航意图，规划智能路径，并控制机器人安全到达目标位置。

### ✨ 核心特性

- 🗣️ **自然语言导航**: 支持自然语言指令，如"去客厅沙发"或"带我去厨房"
- 🧠 **语义理解**: 集成VLM（Vision-Language Model）进行智能场景理解
- 🗺️ **拓扑地图**: 基于图结构的语义空间表示
- 🤖 **智能规划**: 语义驱动的路径规划和决策
- 📊 **实时监控**: 完整的导航状态反馈和进度跟踪
- 🔄 **任务管理**: 支持任务取消、状态查询和错误恢复

## 📦 系统架构

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  User Input     │    │  Interaction    │    │  Navigation     │
│  (Text/Image)   │───▶│  Manager        │───▶│  Executor       │
│                 │    │                 │    │  (Nav2)         │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │  NLP Interface  │    │  Map Manager    │
                       │  (VLM + NLU)    │    │  (Topological)  │
                       └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │  Navigation     │
                       │  Planner        │
                       │  (Semantic)     │
                       └─────────────────┘
```

### 核心组件

1. **`sstg_interaction_manager`** - 任务编排和系统协调
2. **`sstg_nlp_interface`** - 自然语言处理和意图识别
3. **`sstg_navigation_planner`** - 语义路径规划
4. **`sstg_navigation_executor`** - Nav2导航执行和监控
5. **`sstg_map_manager`** - 拓扑地图管理和Web界面
6. **`sstg_perception`** - 多模态感知和语义标注
7. **`sstg_msgs`** - 统一的消息和服务接口定义

## 🚀 快速开始

### 系统要求

- **ROS2**: Humble Hawksbill
- **Python**: 3.10+
- **操作系统**: Ubuntu 22.04
- **硬件**: 兼容Nav2的机器人（如Yahboom ROS2）

### 安装步骤

1. **克隆和构建**
   ```bash
   cd ~/yahboomcar_ros2_ws/src
   # 复制SSTG包到src目录
   cd ~/yahboomcar_ros2_ws
   colcon build --symlink-install
   source install/setup.bash
   ```

2. **启动系统**
   ```bash
   # 使用启动脚本
   ./test/start_integration_test.sh

   # 或手动启动各组件
   ros2 run sstg_map_manager map_manager_node &
   ros2 run sstg_nlp_interface nlp_node &
   ros2 run sstg_navigation_planner planning_node &
   ros2 run sstg_navigation_executor executor_node &
   ros2 run sstg_interaction_manager interaction_manager_node &
   ```

3. **验证安装**
   ```bash
   # 检查服务可用性
   ros2 service list | grep sstg
   ```

### 基本使用

```bash
# 发送导航指令
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: 'Go to the living room',
  context: 'home environment'
}"

# 查询任务状态
ros2 service call /query_task_status std_srvs/srv/Trigger

# 取消当前任务
ros2 service call /cancel_task std_srvs/srv/Trigger
```

## 📊 测试和验证

### 运行集成测试

```bash
# 完整系统测试
./test/complete_test.sh

# 快速功能验证
./test/quick_test.sh

# 详细集成测试
python test/test_system_integration.py
```

### 测试结果

- ✅ **服务可用性**: 7/7 核心服务正常
- ✅ **任务处理**: NLP意图识别准确 (95%+ 置信度)
- ✅ **状态管理**: 任务查询和取消功能正常
- ✅ **错误处理**: 优雅的失败处理和恢复
- ✅ **性能指标**: 响应时间 < 2秒，启动时间 < 15秒

## 📚 文档资源

- **[用户指南](SSTG_User_Guide.md)** - 完整使用手册和实验指导
- **[项目总结](PROJECT_SUMMARY.md)** - 开发完成情况和项目亮点
- **[技术规划](SSTG-Nav-Plan.md)** - 系统架构和设计文档
- **[开发进度](PROJECT_PROGRESS.md)** - 详细开发历程

### 各模块文档

- `sstg_*/README.md` - 模块使用说明
- `sstg_*/doc/` - 详细技术文档
- `test/` - 测试脚本和结果

## 🎯 示例应用

### 家庭服务机器人

```bash
# 日常任务
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: 'Bring me a cup from the kitchen',
  context: 'home assistance'
}"
```

### 商业环境导航

```bash
# 导览服务
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: 'Take me to the conference room on the second floor',
  context: 'office building'
}"
```

### 多模态交互

```bash
# 图像+文本导航
ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery "{
  text_input: 'Go to where the red chair is',
  context: 'living room',
  image_data: '<base64_encoded_image>'
}"
```

## 🔧 开发和扩展

### 添加新功能

```bash
# 创建新的ROS2包
ros2 pkg create --build-type ament_python sstg_your_feature

# 继承基础服务接口
from sstg_msgs.srv import YourCustomService
```

### 自定义配置

```yaml
# config/navigation.yaml
planner:
  semantic_weight: 0.8
  topological_weight: 0.2
executor:
  feedback_rate: 10.0  # Hz
```

### 性能监控

```bash
# 系统资源监控
ros2 topic echo /navigation_feedback

# 性能分析
ros2 run rqt_runtime_monitor rqt_runtime_monitor
```

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

### 开发规范

- 遵循ROS2 Python代码规范
- 添加完整的单元测试
- 更新相关文档
- 通过所有集成测试

## 📄 许可证

本项目采用 Apache 2.0 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- **ROS2社区**: 提供优秀的机器人框架
- **Yahboom**: 机器人硬件支持
- **开源社区**: NetworkX, FastAPI等优秀工具

## 📞 联系方式

**项目维护者**: Daojie Peng
- Email: Daojie.PENG@qq.com
- 项目日期: 2026-03-25
- 状态: ✅ **Phase 4 Complete - Production Ready**

---

**🎉 SSTG导航系统 - 让机器人真正理解你的意图！**