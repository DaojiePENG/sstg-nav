# SSTG Navigation System - 独立工作空间

**Spatial Semantic Topological Graph Navigation System - 独立导航工作空间**

这是SSTG导航系统的独立工作空间。本工作空间包含了完整的导航系统，与YahboomCar机器人控制系统分离，便于独立开发、测试和跨平台集成。

## 📦 包含的包

### 核心导航包

| 包名 | 功能描述 | 文档 |
|------|--------|------|
| `sstg_msgs` | 统一消息和服务接口定义（7消息+8服务） | [文档](src/sstg_msgs/README.md) |
| `sstg_map_manager` | 拓扑地图管理、Web管理界面、图形操作 | [文档](src/sstg_map_manager/doc/) |
| `sstg_perception` | 多模态感知、VLM集成、语义标注 | [文档](src/sstg_perception/doc/) |
| `sstg_nlp_interface` | 自然语言处理、意图识别、qwen-vl-plus集成 | [文档](src/sstg_nlp_interface/doc/) |
| `sstg_navigation_planner` | 语义路径规划、拓扑导航规划 | [文档](src/sstg_navigation_planner/doc/) |
| `sstg_navigation_executor` | Nav2集成、导航执行、进度监控 | [文档](src/sstg_navigation_executor/docs/) |
| `sstg_interaction_manager` | 任务编排、系统协调、状态管理 | [文档](src/sstg_interaction_manager/docs/) |

## 🚀 快速开始

### 前置要求

- **ROS2**: Humble Hawksbill
- **Python**: 3.10+
- **操作系统**: Ubuntu 22.04
- **依赖包**: fastapi, uvicorn, networkx（自动安装）

### 安装步骤

1. **构建工作空间**
   ```bash
   cd ~/sstg_nav/sstg_nav_ws
   
   # 安装依赖
   sudo apt-get install ros-humble-nav2 ros-humble-rclpy
   
   # 构建
   colcon build --symlink-install
   
   # Source环境
   source install/setup.bash
   ```

2. **验证安装**
   ```bash
   # 检查所有包
   ros2 pkg list | grep sstg
   
   # 应该看到7个sstg包
   ```

3. **启动系统**
   ```bash
   # 方式1：使用项目集成脚本（推荐）
   cd ~/sstg_nav
   ./project_test/run_tests.sh
   
   # 方式2：手动启动各节点
   ros2 run sstg_map_manager map_manager_node &
   ros2 run sstg_nlp_interface nlp_node &
   ros2 run sstg_navigation_planner planning_node &
   ros2 run sstg_navigation_executor executor_node &
   ros2 run sstg_interaction_manager interaction_manager_node &
   ```

## 📁 工作空间结构

```
sstg_nav_ws/
├── src/                               # 源代码
│   ├── sstg_interaction_manager/      # 任务编排
│   │   ├── doc/
│   │   ├── sstg_interaction_manager/
│   │   └── package.xml
│   ├── sstg_map_manager/              # 拓扑地图管理
│   │   ├── doc/
│   │   │   ├── QUICK_START.md
│   │   │   └── MODULE_GUIDE.md
│   │   ├── sstg_map_manager/
│   │   └── package.xml
│   ├── sstg_msgs/                     # 消息定义
│   ├── sstg_navigation_executor/      # 导航执行
│   ├── sstg_navigation_planner/       # 路径规划
│   ├── sstg_nlp_interface/            # 自然语言处理
│   └── sstg_perception/               # 感知处理
│
├── build/                             # 构建输出
├── install/                           # 安装输出
├── log/                               # 日志文件
└── README.md                          # 本文件
```

## 📚 文档导航

### 系统级文档
- **[系统架构](../README.md)** - 完整项目架构和两个工作空间的关系
- **[用户指南](../SSTG_User_Guide.md)** - 系统使用完整手册
- **[项目总结](../PROJECT_SUMMARY.md)** - 开发完成情况

### 工作空间文档
- **[安装指南](INSTALLATION.md)** - 详细安装步骤
- **[快速启动](src/sstg_map_manager/doc/QUICK_START.md)** - 快速开始
- **[API参考](src/sstg_msgs/README.md)** - 消息和服务接口

### 模块文档
- `sstg_map_manager/doc/MODULE_GUIDE.md` - 拓扑地图管理详解
- `sstg_perception/doc/` - 感知模块文档
- `sstg_nlp_interface/doc/` - NLP模块文档
- `sstg_navigation_planner/doc/` - 规划模块文档
- `sstg_navigation_executor/docs/` - 执行模块文档
- `sstg_interaction_manager/docs/` - 交互管理文档

## 🔧 开发工作流

### 构建特定包
```bash
source ~/sstg_nav/sstg_nav_ws/install/setup.bash

# 只构建某个包
colcon build --packages-select sstg_map_manager
```

### 运行测试
```bash
# 项目集成测试
cd ~/sstg_nav
./project_test/run_tests.sh

# 查看测试报告
cat project_test/integration_test_report.md
```

### 调试单个模块
```bash
# 启动Python调试
python3 -m pdb src/sstg_map_manager/sstg_map_manager/map_manager.py

# 或使用ROS2调试
ros2 run --prefix 'python3 -m pdb' sstg_map_manager map_manager_node
```

## 🌐 Web界面访问

构建和启动完成后，可以访问拓扑地图Web管理界面：

```bash
# 启动map_manager节点
ros2 run sstg_map_manager map_manager_node

# 在另一个终端启动WebUI
ros2 run sstg_map_manager map_webui

# 浏览器访问
http://localhost:8000
```

功能包括：
- 交互式拓扑图显示和编辑
- 节点创建、删除、属性编辑
- 边管理和权重调整
- 语义信息查看和更新
- 实时统计和导出

## 🔄 与YahboomCar工作空间的关系

这个工作空间是独立的，但在实际部署时可能需要与YahboomCar工作空间集成：

```bash
# 同时source两个工作空间的setup
source ~/sstg_nav/sstg_nav_ws/install/setup.bash
source ~/sstg_nav/yahboomcar_ws/install/setup.bash

# 这样就可以同时使用SSTG导航和Yahboom机器人控制节点
```

## 🆘 常见问题

### Q: 如何单独使用SSTG系统而不需要Yahboom机器人？
A: 这个工作空间就是为此设计的。你可以：
1. 只构建和运行此工作空间
2. 使用模拟机器人或其他兼容的机器人平台
3. 使用Nav2的仿真环境进行测试

### Q: 可以在其他机器人平台上使用SSTG吗？
A: 完全可以！SSTG系统只依赖ROS2和Nav2标准接口，与具体机器人硬件无关。
只需确保目标机器人：
- 运行ROS2 Humble
- 支持Nav2导航
- 有基础的移动控制接口

### Q: 如何贡献新的功能？
A: 参考[开发规范](../README.md#开发规范)部分。主要步骤：
1. Fork此项目
2. 创建功能分支
3. 在此工作空间中开发和测试
4. 提交Pull Request

## 📊 系统状态

- ✅ 所有7个核心包已完成
- ✅ 集成测试100%通过
- ✅ 文档完善
- ✅ 生产就绪

## 📞 支持

遇到问题？

1. 检查[文档](../README.md)
2. 查看[FAQ](../README.md#常见问题)
3. 运行诊断脚本：`./project_test/run_tests.sh`
4. 查看日志：`log/latest/`

## 📄 许可证

Apache 2.0 - 详见[LICENSE](../LICENSE)

---

**SSTG导航系统 - 让机器人真正理解你的意图！**

最后更新: 2026-03-29
