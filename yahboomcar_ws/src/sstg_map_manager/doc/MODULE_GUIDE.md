# sstg_map_manager 模块开发完成

## 📋 模块概述

**sstg_map_manager** 是 SSTG 导航系统的拓扑图管理模块，负责构建、存储、查询和可视化机器人的拓扑地图。

## 🏗️ 模块架构

### 核心组件

1. **TopologicalNode** (`topological_node.py`)
   - 数据类，代表拓扑图中的单个节点
   - 属性：
     - `node_id`: 唯一标识符
     - `x, y, theta`: 位置和姿态信息
     - `panorama_paths`: 全景图存储路径字典（0°/90°/180°/270°）
     - `semantic_info`: 语义信息（房间类型、物品列表等）
     - `created_time, last_updated`: 时间戳
   - 方法：
     - `to_dict()`: 转换为字典（JSON序列化）
     - `from_dict()`: 从字典创建实例（JSON反序列化）

2. **TopologicalMap** (`topological_map.py`)
   - 使用 **NetworkX** 库管理拓扑图
   - 核心功能：
     - 节点管理：创建、删除、修改节点
     - 边管理：添加、删除边连接
     - 语义查询：按房间类型/物品名称/组合条件查询
     - 路径规划：求两点间最短路径
     - 持久化：JSON格式保存/加载
   - 图类型：支持有向图(DiGraph)和无向图(Graph)

3. **MapManagerNode** (`map_manager_node.py`)
   - ROS2 节点，暴露以下服务：
     - `create_node`: 创建新节点
     - `query_semantic`: 语义查询
     - `update_semantic`: 更新语义信息
     - `get_node_pose`: 获取节点位姿
   - 参数化配置（map_file、frame_id、graph_type）
   - 自动加载现有地图，正常关闭时保存

4. **MapWebUINode** (`map_webui.py`)
   - FastAPI Web服务器
   - 提供RESTful API：
     - `GET /api/graph`: 获取完整图数据
     - `GET /api/node/{node_id}`: 获取节点详情
     - `POST /api/node`: 创建节点
     - `DELETE /api/node/{node_id}`: 删除节点
     - `POST /api/edge`: 创建边
     - `DELETE /api/edge`: 删除边
     - `POST /api/save`: 保存地图
   - 内置HTML可视化界面
   - CORS支持，实时图表更新

## 📦 文件结构

```
sstg_map_manager/
├── package.xml                 # ROS2包定义
├── CMakeLists.txt             # CMake构建配置
├── setup.py                   # Python包配置
├── setup.cfg                  # setuptools配置
├── sstg_map_manager/
│   ├── __init__.py
│   ├── topological_node.py    # 节点数据类
│   ├── topological_map.py     # 拓扑图核心
│   ├── map_manager_node.py    # ROS2节点
│   ├── map_webui.py           # WebUI服务器
│   └── webui/                 # WebUI前端资源
├── launch/
│   └── map_manager.launch.py  # 启动脚本
├── config/
│   └── map_config.yaml        # 配置文件
└── test_map_manager.py        # 功能测试脚本
```

## 🚀 使用方法

### 1. 作为ROS2节点启动

```bash
# 直接启动
ros2 run sstg_map_manager map_manager_node

# 或使用launch文件
ros2 launch sstg_map_manager map_manager.launch.py
```

### 2. 调用ROS2服务

```bash
# 创建节点
ros2 service call /create_node sstg_msgs/srv/CreateNode \
  "{pose: {header: {frame_id: 'map'}, pose: {position: {x: 0.0, y: 0.0}}}}"

# 查询语义
ros2 service call /query_semantic sstg_msgs/srv/QuerySemantic \
  "{query: 'room_type:living_room'}"

# 更新语义
ros2 service call /update_semantic sstg_msgs/srv/UpdateSemantic \
  "{node_id: 0, semantic_data: {room_type: 'living_room', confidence: 0.95}}"

# 获取节点位姿
ros2 service call /get_node_pose sstg_msgs/srv/GetNodePose "{node_id: 0}"
```

### 3. 启动WebUI

```bash
# 启动WebUI服务器
ros2 run sstg_map_manager map_webui

# 在浏览器中打开：http://localhost:8000
```

### 4. Python脚本使用

```python
from sstg_map_manager.topological_map import TopologicalMap
from sstg_map_manager.topological_node import SemanticInfo, SemanticObject

# 创建地图
topo_map = TopologicalMap(map_file='/path/to/map.json')

# 创建节点
node = topo_map.create_node(x=0.0, y=0.0, theta=0.0)

# 添加语义信息
semantic = SemanticInfo(
    room_type='living_room',
    objects=[SemanticObject(name='sofa', position='center')]
)
topo_map.update_semantic(node.node_id, semantic)

# 查询
rooms = topo_map.query_by_room_type('living_room')

# 保存
topo_map.save_to_file('/path/to/map.json')
```

## ✅ 测试结果

所有功能已测试通过：

```
✓ 节点创建和管理
✓ 边的创建和删除
✓ 语义信息添加和更新
✓ 按房间类型查询
✓ 按物品名称查询
✓ 组合条件查询
✓ 最短路径查询
✓ 地图统计信息
✓ JSON序列化/反序列化
✓ 地图加载和保存
```

## 🔧 依赖

- rclpy - ROS2 Python客户端
- networkx >= 3.0 - 图论库
- fastapi >= 0.100 - Web框架
- uvicorn >= 0.23 - ASGI服务器
- geometry_msgs - ROS2标准几何消息

## 📝 JSON数据格式示例

```json
{
  "nodes": [
    {
      "id": 0,
      "pose": {
        "x": 0.0,
        "y": 0.0,
        "theta": 0.0
      },
      "panorama_paths": {
        "0°": "/path/to/image_0.png",
        "90°": "/path/to/image_90.png"
      },
      "semantic_info": {
        "room_type": "living_room",
        "confidence": 0.95,
        "objects": [
          {
            "name": "sofa",
            "position": "center",
            "quantity": 1,
            "confidence": 0.9
          }
        ],
        "description": "Living room with sofa"
      }
    }
  ],
  "edges": [
    {
      "from": 0,
      "to": 1,
      "weight": 5.0
    }
  ]
}
```

## 🎯 后续集成

此模块已准备好与以下模块集成：

1. **sstg_perception** - 获取语义标注，更新节点信息
2. **sstg_nlp_interface** - 接收自然语言查询，调用语义查询接口
3. **sstg_navigation_planner** - 使用拓扑图进行路径规划
4. **sstg_navigation_executor** - 获取节点位姿，执行导航

## 📊 下一步

- [ ] 集成sstg_perception模块进行语义标注
- [ ] 完善WebUI可视化（添加拖拽编辑、编辑器等功能）
- [ ] 添加多地图管理支持
- [ ] 实现地图版本控制和备份
