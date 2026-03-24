# SSTG-Nav 快速启动指南

## ✅ 验证状态

所有SSTG模块已成功编译和验证：
- ✅ sstg_msgs - 消息定义
- ✅ sstg_map_manager - 拓扑图管理
- ✅ 所有dependencies已安装

---

## 🚀 启动方式

### 方式一：使用Python直接运行（推荐用于测试）

```bash
# 1. 启动拓扑图管理节点
source /opt/ros/humble/setup.bash
python3 /home/daojie/yahboomcar_ros2_ws/run_map_manager.py

# 2. 在另一个终端启动WebUI
source /opt/ros/humble/setup.bash
python3 -c "from sstg_map_manager.map_webui import main; main()"

# 3. 打开浏览器访问
# http://localhost:8000
```

### 方式二：ROS2标准命令

```bash
# 完整sourcing后尝试
source /opt/ros/humble/setup.bash
source /home/daojie/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash

# 这些命令可能需要调整ROS_PACKAGE_PATH
ros2 run sstg_map_manager map_manager_node
```


---

## 🔧 依赖检查

已安装的Python包：
- fastapi >= 0.100
- uvicorn >= 0.23
- networkx >= 3.0
- rclpy (via ROS2 Humble)

如需手动安装：
```bash
python3 -m pip install fastapi uvicorn networkx
```

---

## 📁 关键文件位置

```
/home/daojie/yahboomcar_ros2_ws/
└── yahboomcar_ws/
    ├── src/
    │   ├── sstg_msgs/              # 消息定义包
    │   └── sstg_map_manager/        # 拓扑图管理包
    └── install/
        ├── sstg_msgs/
        └── sstg_map_manager/
```

---

## 🌐 WebUI 访问

```bash
# 完整sourcing后尝试
source /opt/ros/humble/setup.bash
source /home/daojie/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash

ros2 run sstg_map_manager map_webui

# 或者直接使用launch脚本启动 map_manager_node 和 map_webui 两个节点
ros2 launch sstg_map_manager map_manager.launch.py

```

启动WebUI后访问：
```
http://localhost:8000
```

功能：
- 交互式拓扑图显示
- 节点创建/删除
- 边管理
- 语义信息查看
- 实时统计

---

## 🔍 服务接口（ROS2）

如果ROS2包发现工作，可使用以下服务：

```bash
# 创建节点
ros2 service call /create_node sstg_msgs/srv/CreateNode \
  "{pose: {header: {frame_id: 'map'}, pose: {position: {x: 0.0, y: 0.0}}}}"

# 查询语义
ros2 service call /query_semantic sstg_msgs/srv/QuerySemantic \
  "{query: 'room_type:living_room'}"

# 更新语义
ros2 service call /update_semantic sstg_msgs/srv/UpdateSemantic \
  "{node_id: 0, semantic_data: {room_type: 'test'}}"

# 获取节点位姿
ros2 service call /get_node_pose sstg_msgs/srv/GetNodePose \
  "{node_id: 0}"
```

---

## 📝 Python API 示例

```python
from sstg_map_manager.topological_map import TopologicalMap
from sstg_map_manager.topological_node import SemanticInfo, SemanticObject

# 创建地图
topo_map = TopologicalMap('/path/to/map.json')

# 创建节点
node = topo_map.create_node(x=0.0, y=0.0, theta=0.0)

# 添加语义信息
semantic = SemanticInfo(
    room_type='living_room',
    objects=[
        SemanticObject(name='sofa', position='center', confidence=0.95)
    ]
)
topo_map.update_semantic(node.node_id, semantic)

# 查询
rooms = topo_map.query_by_room_type('living_room')

# 保存
topo_map.save_to_file()
```

---

## ✅ 下一步

第一阶段基础设施已完成，准备进入第二阶段：

- [ ] 开发 sstg_perception 模块（图像采集 + VLM 标注）
- [ ] 开发 sstg_nlp_interface 模块（自然语言理解）
- [ ] 开发 sstg_navigation_planner 模块（导航规划）
- [ ] 完成其他模块并进行系统集成测试

---

## 📞 故障排除

| 问题 | 解决方案 |
|------|--------|
| `ModuleNotFoundError: No module named 'fastapi'` | 运行 `python3 -m pip install fastapi uvicorn networkx` |
| `Package 'sstg_map_manager' not found` | 使用 Python 直接导入，或重新source setup |
| WebUI 无响应 | 检查端口 8000 是否被占用，或使用其他端口 |
| 节点启动失败 | 确保ROS2 Humble已安装并souced |

---

**最后更新**：2026-03-24  
**状态**：✅ 验证通过，可投入使用
