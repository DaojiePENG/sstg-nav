# SSTG Perception Module - 使用指南

## 📋 概述

SSTG Perception 模块负责：
- **自主全景图采集**：导航到目标位姿并自动旋转采集四方向图像
- RGB-D 图像采集（Gemini 336L 相机）
- 调用阿里云百炼 VLM (qwen-vl-plus) 进行语义标注
- 结构化语义信息提取和存储

**核心特性**：
- ✅ **一键采集**：给定目标位姿，自动完成导航、旋转、采集全流程
- ✅ **Nav2集成**：使用Nav2进行自主导航和原地旋转
- ✅ **智能重试**：自动处理导航失败和图像采集失败
- ✅ **完整元数据**：保存位姿、时间戳、图像路径等信息

---

## 🚀 快速启动

### 完整系统启动流程

**步骤1: 启动相机**（终端1）
```bash
ros2 launch yahboomcar_nav camera_gemini_336l.launch.py
```

**步骤2: 启动雷达和导航**（终端2）
```bash
# 启动雷达
ros2 launch yahboomcar_nav laser_bringup_launch.py
```

**步骤3: 启动可视化（可选）**（终端4）
```bash
ros2 launch yahboomcar_nav display_nav_launch.py
```

**步骤4: 启动导航模块**（终端3）
```bash
# 使用DWA导航
ros2 launch yahboomcar_nav navigation_dwa_launch.py
```


**步骤5: 启动Perception节点**（终端5）
```bash
cd ~/sstg_nav/yahboomcar_ws
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
ros2 run sstg_perception perception_node
```

### 验证系统就绪

```bash
# 检查所有关键节点
ros2 node list | grep -E "(camera|amcl|bt_navigator|perception)"

# 检查相机话题
ros2 topic hz /camera/color/image_raw

# 检查机器人定位
ros2 topic echo /amcl_pose --once

# 检查perception服务
ros2 service list | grep capture_panorama
```

### 前置条件

```bash
# 1. 安装依赖
pip install opencv-python numpy requests Pillow

# 2. 确保已构建包
cd ~/sstg_nav/yahboomcar_ws
colcon build --packages-select sstg_msgs sstg_perception

# 3. Source 环境
source install/setup.bash

# 4. 设置 API Key（必须！）
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
```

### 启动方式 1: 仅启动 Perception 节点（推荐）

**适用场景**：相机已启动，只需要感知服务

```bash
# 前台运行（可查看实时日志）
cd ~/sstg_nav/yahboomcar_ws
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
ros2 run sstg_perception perception_node

# 或后台运行
ros2 run sstg_perception perception_node > /tmp/perception_node.log 2>&1 &
```

**验证节点启动成功**：
```bash
# 检查节点
ros2 node list | grep perception_node
# 应输出: /perception_node

# 检查服务
ros2 service list | grep -E "(annotate|capture)"
# 应输出:
#   /annotate_semantic
#   /capture_panorama
```

### 启动方式 2: Launch 文件（相机 + 感知）

**适用场景**：同时启动相机和感知节点

```bash
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

# 基本启动
ros2 launch sstg_perception perception.launch.py

# 带参数启动
ros2 launch sstg_perception perception.launch.py \
  color_width:=1280 \
  color_height:=800 \
  color_fps:=30 \
  panorama_storage_path:=/tmp/sstg_perception \
  confidence_threshold:=0.5
```

### 启动方式 3: 快速测试脚本

```bash
# 一键启动并测试所有功能
cd ~/sstg_nav/yahboomcar_ws/src/sstg_perception
bash scripts/test_perception_services.sh
```

---

## 📦 模块架构

### 核心组件

#### 1. CameraSubscriber
RGB-D 相机订阅器

```python
import rclpy
from sstg_perception.camera_subscriber import CameraSubscriber

# ✓ 核心修复：必须先初始化 ROS2
rclpy.init()

# 创建订阅器
camera = CameraSubscriber(
    rgb_topic='/camera/color/image_raw',
    depth_topic='/camera/depth/image_raw'
)

# 等待图像（会自动处理 ROS2 消息）
if camera.wait_for_images(timeout=5):
    rgb, depth = camera.get_latest_pair()
    print(f"RGB shape: {rgb.shape}, Depth shape: {depth.shape}")

# 清理
camera.destroy_node()
rclpy.shutdown()
```

**关键要点**：
1. ✓ 必须先调用 `rclpy.init()` 初始化 ROS2
2. ✓ `wait_for_images()` 会自动调用 `spin_once()` 处理消息
3. ✓ 使用完毕后调用 `destroy_node()` 和 `rclpy.shutdown()`
4. ✓ QoS 配置已优化为 RELIABLE 模式以匹配相机发布者

#### 2. PanoramaCapture
全景图采集管理器（**重新设计 v0.2.0**）

**新架构设计**：集成Nav2导航，给定位姿即可自主完成采集

```python
import rclpy
from sstg_perception.camera_subscriber import CameraSubscriber
from sstg_perception.panorama_capture import PanoramaCapture

# 初始化ROS2
rclpy.init()

# 创建相机订阅器
camera = CameraSubscriber(
    rgb_topic='/camera/color/image_raw',
    depth_topic='/camera/depth/image_raw'
)

# 等待相机就绪
camera.wait_for_images(timeout=5)

# 创建全景采集器（传入相机订阅器）
capture = PanoramaCapture(
    camera_subscriber=camera,
    storage_path='/tmp/sstg_perception',
    enable_navigation=True  # 启用自动导航（需要Nav2运行）
)

# 🎯 一键采集：给定目标位姿，自动完成所有工作
result = capture.capture_at_pose(
    node_id=0,
    pose={'x': 2.0, 'y': 1.5, 'theta': 0.0},
    frame_id='map',
    navigate=True,  # 自动导航到目标点
    wait_after_rotation=2.0  # 旋转后等待时间
)

if result:
    print(f"✅ Success! Images: {result['images']}")
else:
    print("❌ Failed")

# 清理
capture.shutdown()
camera.destroy_node()
rclpy.shutdown()
```

**工作流程**：
1. **导航阶段**：使用Nav2自动导航到目标位姿 (x, y, theta)
2. **旋转采集**：原地旋转到4个方向（0°, 90°, 180°, 270°）
3. **图像采集**：每个方向采集RGB + 深度图
4. **保存数据**：自动保存图像和元数据

**关键改进**：
- ✅ **不再需要**手动传入camera_subscriber到每个方法
- ✅ **不再需要**手动实现旋转回调
- ✅ **不再需要**手动管理采集状态
- ✅ **自动导航**到目标点（Nav2）
- ✅ **自动旋转**到每个角度（Nav2）
- ✅ **智能等待**相机稳定和图像更新

**API参考**：

```python
# 主方法：在指定位姿采集全景图
result = capture.capture_at_pose(
    node_id: int,           # 拓扑节点ID
    pose: Dict,             # {'x': float, 'y': float, 'theta': float}
    frame_id: str = 'map',  # 坐标系
    navigate: bool = True,  # 是否导航（False则原地采集）
    wait_after_rotation: float = 2.0  # 旋转后等待时间（秒）
) -> Optional[Dict]

# 返回值（成功）
{
    'node_id': 0,
    'pose': {'x': 2.0, 'y': 1.5, 'theta': 0.0},
    'timestamp': '2026-03-27T15:30:45.123456',
    'images': {
        0: '/tmp/sstg_perception/node_0/000deg_rgb.png',
        90: '/tmp/sstg_perception/node_0/090deg_rgb.png',
        180: '/tmp/sstg_perception/node_0/180deg_rgb.png',
        270: '/tmp/sstg_perception/node_0/270deg_rgb.png'
    },
    'complete': True
}

# 返回值（失败）
None
```

**两种工作模式**：

1. **自动模式**（推荐）：
```python
capture = PanoramaCapture(
    camera_subscriber=camera,
    enable_navigation=True  # Nav2必须运行
)

# 自动导航 + 自动旋转 + 自动采集
result = capture.capture_at_pose(
    node_id=0,
    pose={'x': 2.0, 'y': 1.5, 'theta': 0.0},
    navigate=True
)
```

2. **手动模式**（调试用）：
```python
capture = PanoramaCapture(
    camera_subscriber=camera,
    enable_navigation=False  # 不使用Nav2
)

# 在当前位置连续采集4次（不旋转）
result = capture.capture_at_pose(
    node_id=0,
    pose={'x': 0.0, 'y': 0.0, 'theta': 0.0},
    navigate=False
)
```

#### 3. VLMClient
VLM API 客户端

```python
from sstg_perception.vlm_client import VLMClient, VLMClientWithRetry

# 基础客户端
client = VLMClient(
    api_key='sk-942e8661f10f492280744a26fe7b953b',
    model='qwen-vl-plus',
    timeout=30.0
)

# 带重试的客户端
client = VLMClientWithRetry(
    api_key='sk-942e8661f10f492280744a26fe7b953b',
    max_retries=3,
    retry_delay=2.0
)

# 调用 VLM
response = client.call_semantic_annotation(
    image_path='/tmp/image.jpg',
    prompt=None  # 使用默认提示词
)

if response.success:
    print(response.content)
    print(f"Tokens: {response.tokens_used}")
else:
    print(f"Error: {response.error}")

# 批量标注
responses = client.batch_annotate(
    image_paths=['/tmp/img1.jpg', '/tmp/img2.jpg'],
    delay_between_calls=1.0
)
```

#### 4. SemanticExtractor
语义信息提取器

```python
from sstg_perception.semantic_extractor import SemanticExtractor

extractor = SemanticExtractor(confidence_threshold=0.5)

vlm_output = '''{
    "room_type": "living_room",
    "confidence": 0.95,
    "objects": [
        {"name": "sofa", "position": "left", "quantity": 1, "confidence": 0.9}
    ],
    "description": "Cozy living room"
}'''

success, semantic_info, error = extractor.extract_semantic_info(vlm_output)

if success:
    print(f"Room: {semantic_info.room_type}")
    print(f"Objects: {[obj.name for obj in semantic_info.objects]}")
    print(f"Confidence: {semantic_info.confidence}")
else:
    print(f"Error: {error}")

# 合并多视图信息
merged = extractor.merge_semantic_infos(
    [info1, info2, info3, info4],
    strategy='average'  # 或 'union', 'intersection'
)
```

---

## 🔌 ROS2 服务接口

**重要提示**：
- ✓ 服务名称是 `/annotate_semantic` 和 `/capture_panorama`（不带 `/perception_node` 前缀）
- ✓ 必须先启动 `perception_node`，服务才可用
- ✓ 必须设置环境变量 `DASHSCOPE_API_KEY`

### 验证服务可用性

```bash
# 检查节点是否运行
ros2 node list | grep perception_node

# 检查服务是否存在
ros2 service list | grep -E "(annotate|capture)"

# 查看服务详细信息
ros2 service type /annotate_semantic
ros2 service type /capture_panorama
```

### 服务 1: annotate_semantic（语义标注）

**功能**：对单张图像进行 VLM 语义标注

**调用示例**：
```bash
ros2 service call /annotate_semantic sstg_msgs/srv/AnnotateSemantic \
  "{image_path: '/home/daojie/Pictures/kitchen.png', node_id: 0}"
```

**请求参数**:
- `image_path`: 图像文件路径（必须存在）
- `node_id`: 拓扑节点 ID

**响应字段**:
- `success`: 布尔值，是否成功
- `room_type`: 房间类型（如 "餐厅", "客厅"）
- `confidence`: 置信度 (0.0-1.0)
- `description`: 场景描述文本
- `objects`: 语义对象列表，每个对象包含：
  - `name`: 物体名称
  - `position`: 位置描述
  - `quantity`: 数量
  - `confidence`: 置信度
- `error_message`: 错误信息（失败时）

**成功响应示例**：
```
success: True
room_type: '餐厅'
confidence: 0.95
objects: [
  {name: '餐桌', position: '中心', quantity: 1, confidence: 0.95},
  {name: '餐椅', position: '周围', quantity: 5, confidence: 0.95},
  ...
]
description: '这是一个现代风格的餐厅，配有白色大理石餐桌...'
error_message: ''
```

### 服务 2: capture_panorama（全景采集）

**功能**：自动导航到目标位姿并采集四方向全景图（0°, 90°, 180°, 270°）

**⭐ 新特性（v0.2.0）**：
- ✅ **自动导航**：使用Nav2导航到目标位置
- ✅ **自动旋转**：原地旋转到4个方向
- ✅ **无需手动干预**：完全自主完成采集

**调用示例**：
```bash
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {header: {frame_id: 'map'}, pose: {position: {x: 2.0, y: 1.5, z: 0.0}, orientation: {w: 1.0}}}}"
```

**请求参数**:
- `node_id`: 拓扑节点 ID
- `pose`: geometry_msgs/PoseStamped 类型
  - `header.frame_id`: 坐标系（'map' 或 'odom'）
  - `pose.position`: {x, y, z} - 目标位置（米）
  - `pose.orientation`: {x, y, z, w} - 目标朝向（四元数）

**响应字段**:
- `success`: 布尔值，是否成功
- `image_paths`: 字符串数组，格式为 `["angle:path", ...]`
- `error_message`: 错误信息（失败时）

**成功示例**：
```bash
# 导航到 (2.0, 1.5)，朝向0度
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 1, pose: {header: {frame_id: 'map'}, pose: {position: {x: 2.0, y: 1.5, z: 0.0}, orientation: {w: 1.0}}}}"

# 预期输出：
response:
  success: true
  image_paths:
    - '0:/tmp/sstg_perception/node_1/000deg_rgb.png'
    - '90:/tmp/sstg_perception/node_1/090deg_rgb.png'
    - '180:/tmp/sstg_perception/node_1/180deg_rgb.png'
    - '270:/tmp/sstg_perception/node_1/270deg_rgb.png'
  error_message: ''
```

**完整工作流程**：
```
1. 收到服务请求
   ↓
2. 🚗 Nav2导航到目标位置 (x, y)
   ├─ 避障
   ├─ 路径规划
   └─ 到达目标
   ↓
3. 🔄 逐个旋转到4个方向
   ├─ 0° → 拍照
   ├─ 90° → 拍照
   ├─ 180° → 拍照
   └─ 270° → 拍照
   ↓
4. 💾 保存图像和元数据
   └─ 返回成功响应
```

**四元数朝向参考**：
```bash
# 0度（正东）
orientation: {x: 0, y: 0, z: 0, w: 1}

# 90度（正北）
orientation: {x: 0, y: 0, z: 0.707, w: 0.707}

# 180度（正西）
orientation: {x: 0, y: 0, z: 1, w: 0}

# 270度（正南）
orientation: {x: 0, y: 0, z: -0.707, w: 0.707}
```

**前置条件**：
- ✅ 相机节点运行
- ✅ Nav2导航栈运行
- ✅ 机器人已定位（AMCL）
- ✅ 地图已加载

**故障处理**：
- 导航失败 → 返回错误 "Navigation failed"
- 旋转失败 → 返回错误 "Rotation to X° failed"
- 相机无响应 → 返回错误 "Camera not responding"
- 图像无效 → 返回错误 "Invalid RGB image"

### 话题: semantic_annotations

订阅语义标注结果

```bash
ros2 topic echo /semantic_annotations
```

---

## 💾 数据存储

### 目录结构

```
/tmp/sstg_perception/
├── node_0/
│   ├── 000deg_rgb.png         # 0° RGB 图像
│   ├── 000deg_depth.png       # 0° 深度图
│   ├── 090deg_rgb.png
│   ├── 090deg_depth.png
│   ├── 180deg_rgb.png
│   ├── 180deg_depth.png
│   ├── 270deg_rgb.png
│   ├── 270deg_depth.png
│   └── panorama_metadata.json # 元数据
├── node_1/
│   └── ...
└── temp/
    └── (临时图像)
```

### 元数据格式

```json
{
  "node_id": 0,
  "timestamp": "2026-03-24T10:30:45.123456",
  "pose": {
    "x": 1.0,
    "y": 2.0,
    "theta": 0.0
  },
  "images": {
    "0": "/tmp/sstg_perception/node_0/000deg_rgb.png",
    "90": "/tmp/sstg_perception/node_0/090deg_rgb.png",
    "180": "/tmp/sstg_perception/node_0/180deg_rgb.png",
    "270": "/tmp/sstg_perception/node_0/270deg_rgb.png"
  },
  "complete": true
}
```

---

## ⚙️ 配置说明

编辑 `config/perception_config.yaml`:

```yaml
# API 配置（从环境变量读取，无需配置文件）
api_base_url: "https://dashscope.aliyuncs.com/..."        # API 基础 URL
vlm_model: "qwen-vl-plus"                                 # VLM 模型

# 相机话题
rgb_topic: "/camera/color/image_raw"                        # RGB 话题
depth_topic: "/camera/depth/image_raw"                    # 深度话题

# 存储配置
panorama_storage_path: "/tmp/sstg_perception"             # 存储路径
image_format: "png"                                        # 图像格式

# VLM 配置
confidence_threshold: 0.5                                  # 置信度阈值
max_retries: 3                                             # 最大重试次数
vlm_timeout: 30.0                                          # 超时时间（秒）
```

---

## 📸 相机参数（Gemini 336L）

启动文件中的相机参数：

```bash
# RGB 分辨率和帧率
color_width: 1280
color_height: 800
color_fps: 30

# 深度分辨率和帧率
depth_width: 1280
depth_height: 800
depth_fps: 30

# 传感器
enable_accel: true    # 加速度计
enable_gyro: true     # 陀螺仪
```

---

## 🧪 测试

### 完整测试流程

**步骤1: 启动所有必需服务**（按顺序）

```bash
# 终端1: 相机
ros2 launch yahboomcar_nav camera_gemini_336l.launch.py

# 终端2: 雷达
ros2 launch yahboomcar_nav laser_bringup_launch.py

# 终端3: 导航
ros2 launch yahboomcar_nav navigation_dwa_launch.py

# 终端4: 可视化（可选，用于监控）
ros2 launch yahboomcar_nav display_nav_launch.py

# 终端5: Perception节点
cd ~/sstg_nav/yahboomcar_ws
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
ros2 run sstg_perception perception_node
```

**步骤2: 验证系统就绪**

```bash
# 检查所有关键节点运行
ros2 node list | grep -E "(camera|amcl|bt_navigator|perception)"
# 应该看到:
#   /camera/camera
#   /amcl
#   /bt_navigator
#   /perception_node

# 检查相机有数据
ros2 topic hz /camera/color/image_raw
# 应该显示 ~30Hz

# 检查机器人已定位
ros2 topic echo /amcl_pose --once
# 应该有位姿输出

# 检查perception服务可用
ros2 service list | grep capture_panorama
# 应该显示: /capture_panorama
```

**步骤3: 测试全景采集**

```bash
# 测试1: 在当前位置附近采集（近距离）
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {header: {frame_id: 'map'}, pose: {position: {x: 0.5, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}"

# 等待完成（大约1-2分钟）
# 在RViz中应该看到机器人导航到目标点并旋转

# 测试2: 远距离导航测试
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 1, pose: {header: {frame_id: 'map'}, pose: {position: {x: 2.0, y: 1.5, z: 0.0}, orientation: {w: 1.0}}}}"
```

**步骤4: 验证结果**

```bash
# 查看保存的图像
ls -lh /tmp/sstg_perception/node_0/
# 应该看到:
#   000deg_rgb.png (约800KB)
#   000deg_depth.png (约400KB)
#   090deg_rgb.png
#   090deg_depth.png
#   180deg_rgb.png
#   180deg_depth.png
#   270deg_rgb.png
#   270deg_depth.png
#   panorama_metadata.json

# 查看元数据
cat /tmp/sstg_perception/node_0/panorama_metadata.json

# 验证图像完整性
file /tmp/sstg_perception/node_0/*.png
# 应该都显示为 PNG image data, 1280 x 800
```

### 快速测试（推荐）

使用一键测试脚本：

```bash
cd ~/sstg_nav/yahboomcar_ws/src/sstg_perception
bash scripts/test_perception_services.sh
```

**脚本功能**：
1. ✓ 自动编译包
2. ✓ 启动 perception_node
3. ✓ 验证节点和服务
4. ✓ 测试服务调用（语义标注、全景采集）
5. ✓ 显示详细结果和日志
6. ✓ 提供手动测试命令

### 单元测试

运行 Python 单元测试：

```bash
cd ~/sstg_nav/yahboomcar_ws/src/sstg_perception/test
python3 test_perception.py
```

**测试项目**:
- ✓ 全景图采集
- ✓ 语义提取（JSON 解析、置信度过滤、多视图合并）
- ✓ VLM 客户端配置
- ✓ 集成测试

### 相机订阅测试

测试相机图像接收：

```bash
cd ~/sstg_nav/yahboomcar_ws
source install/setup.bash
python3 src/sstg_perception/test/test_camera_subscriber.py
```

**预期输出**：
```
[INFO] [XXX] [camera_subscriber]: Waiting for subscriptions to establish...
[INFO] [XXX] [camera_subscriber]: Images received!
✓ 成功接收图像!
  RGB shape: (800, 1280, 3)
  Depth shape: (800, 1280)
```

### 手动服务测试

**测试语义标注**：
```bash
# 准备测试图像
TEST_IMAGE="/home/daojie/Pictures/kitchen.png"

# 启动节点（如果未运行）
ros2 run sstg_perception perception_node &
sleep 3

# 调用服务
ros2 service call /annotate_semantic sstg_msgs/srv/AnnotateSemantic \
  "{image_path: '$TEST_IMAGE', node_id: 0}"
```

**测试全景采集**（需要相机和Nav2）：
```bash
# 1. 确保相机已启动
ros2 topic list | grep camera

# 2. 确保Nav2已启动并且机器人已定位
ros2 topic echo /amcl_pose --once

# 3. 调用服务：导航到目标点并采集
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {header: {frame_id: 'map'}, pose: {position: {x: 1.0, y: 1.0, z: 0.0}, orientation: {w: 1.0}}}}"

# 4. 查看采集进度（perception_node日志）
# 应该看到：
#   🚗 Navigating to target pose...
#   🔄 Rotating to 0°...
#   📸 Capturing...
#   ✓ Captured: 000deg_rgb.png
#   ... (重复4次)
#   ✅ Panorama capture complete!

# 5. 验证保存的图像
ls -lh /tmp/sstg_perception/node_0/
cat /tmp/sstg_perception/node_0/panorama_metadata.json
```

**使用Python客户端测试**：
```python
#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sstg_msgs.srv import CaptureImage
from geometry_msgs.msg import PoseStamped

rclpy.init()
node = Node('test_client')
client = node.create_client(CaptureImage, '/capture_panorama')

if client.wait_for_service(timeout_sec=5.0):
    # 创建请求
    request = CaptureImage.Request()
    request.node_id = 0
    request.pose = PoseStamped()
    request.pose.header.frame_id = 'map'
    request.pose.pose.position.x = 2.0
    request.pose.pose.position.y = 1.5
    request.pose.pose.orientation.w = 1.0

    print('📍 Requesting panorama at (2.0, 1.5)')

    # 异步调用（可能需要较长时间）
    future = client.call_async(request)
    rclpy.spin_until_future_complete(node, future, timeout_sec=120.0)  # 2分钟超时

    if future.done():
        response = future.result()
        if response.success:
            print('✅ Success!')
            for img_path in response.image_paths:
                angle, path = img_path.split(':', 1)
                print(f'  {angle:>3}°: {path}')
        else:
            print(f'❌ Failed: {response.error_message}')
    else:
        print('⏱️  Timeout')

node.destroy_node()
rclpy.shutdown()
```

### 性能测试

测试 VLM API 响应时间：

```bash
cd ~/sstg_nav/yahboomcar_ws
source install/setup.bash

python3 << 'EOF'
import time
import os
from sstg_perception.vlm_client import VLMClient

api_key = os.getenv('DASHSCOPE_API_KEY')
client = VLMClient(api_key=api_key)

# 测试单次调用
start = time.time()
response = client.call_semantic_annotation('/home/daojie/Pictures/kitchen.png')
elapsed = time.time() - start

print(f"响应时间: {elapsed:.2f}s")
print(f"Tokens: {response.tokens_used}")
print(f"成功: {response.success}")
EOF
```

---

## 🐛 故障排查

### 问题 1: 服务调用超时 "waiting for service to become available..."

**原因**：perception_node 未启动或服务名称错误

**解决方案**：
```bash
# 步骤 1: 检查节点是否运行
ros2 node list | grep perception_node

# 如果没有输出，启动节点
cd ~/sstg_nav/yahboomcar_ws
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
ros2 run sstg_perception perception_node &

# 等待 3 秒让节点启动
sleep 3

# 步骤 2: 验证服务存在
ros2 service list | grep -E "(annotate|capture)"

# 步骤 3: 使用正确的服务名称
# ✓ 正确: /annotate_semantic
# ✗ 错误: /perception_node/annotate_semantic
ros2 service call /annotate_semantic sstg_msgs/srv/AnnotateSemantic \
  "{image_path: '/path/to/image.jpg', node_id: 0}"
```

### 问题 2: 相机无图像 "Timeout waiting for images"

**症状**：CameraSubscriber 等待超时，无法接收图像

**解决方案**：
```bash
# 步骤 1: 检查相机硬件连接
lsusb | grep -i orbbec
# 应显示: Bus XXX Device XXX: ID 2bc5:XXXX ORBBEC

# 步骤 2: 检查相机话题是否发布
ros2 topic list | grep camera

# 应显示:
#   /camera/color/image_raw
#   /camera/depth/image_raw

# 步骤 3: 测试接收一帧图像
ros2 topic echo /camera/color/image_raw --once

# 如果没有输出，启动相机
ros2 launch orbbec_camera gemini_330_series.launch.py
```

### 问题 3: 模块导入失败 "ModuleNotFoundError: No module named 'sstg_perception'"

**原因**：包未正确编译或环境未 source

**解决方案**：
```bash
# 步骤 1: 清理并重新编译
cd ~/sstg_nav/yahboomcar_ws
rm -rf build/sstg_perception install/sstg_perception
colcon build --packages-select sstg_perception

# 检查编译输出，确保成功:
# Summary: 1 package finished

# 步骤 2: Source 环境
source install/setup.bash

# 步骤 3: 验证模块可导入
python3 -c "import sstg_perception; print('✓ 导入成功')"

# 步骤 4: 检查安装位置
ls install/sstg_perception/lib/python3.10/site-packages/sstg_perception/
# 应显示: camera_subscriber.py, vlm_client.py, etc.
```

### 问题 4: API Key 错误 "401 Unauthorized"

**原因**：API Key 未设置或错误

**解决方案**：
```bash
# 检查环境变量
echo $DASHSCOPE_API_KEY

# 如果为空或错误，重新设置
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

# 永久设置（添加到 ~/.bashrc）
echo 'export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"' >> ~/.bashrc
source ~/.bashrc

# 重启 perception_node 使环境变量生效
pkill -f perception_node
ros2 run sstg_perception perception_node &
```

### 问题 5: VLM API 超时或失败

**症状**：
```
错误: "Request timeout"
错误: "API Error: 429 Too Many Requests"
```

**解决方案**：
```bash
# 1. 检查网络连接
ping -c 3 dashscope.aliyuncs.com

# 2. 增加超时时间（修改代码或配置）
# 在 vlm_client.py 中设置 timeout=60.0

# 3. 如果是频率限制，增加重试延迟
# 使用 VLMClientWithRetry 并设置 retry_delay=5.0
```

### 问题 6: JSON 解析失败

**症状**：
```
错误: "Failed to extract JSON from VLM response"
```

**解决方案**：
```bash
# 1. 查看 VLM 原始输出
# 在 perception_node 日志中查找响应内容

# 2. 检查提示词是否正确
# VLM 需要明确要求返回 JSON 格式

# 3. 调整 SemanticExtractor 的解析逻辑
# 如果 VLM 输出格式改变，需要相应调整
```

### 快速诊断脚本

运行完整诊断：
```bash
cd ~/sstg_nav/yahboomcar_ws/src/sstg_perception
bash scripts/test_perception_services.sh
```

这个脚本会自动：
1. 编译包
2. 启动节点
3. 验证服务
4. 运行测试调用
5. 显示结果和日志

---

## 📖 API 参考

详见各模块源代码中的 docstring。

---

## 📝 更新历史

- **v0.2.0** (2026-03-27): 🎯 **架构重构 - 自主导航采集**
  - 🚀 **重大改进**：PanoramaCapture完全重新设计
  - ✓ 集成Nav2导航：自动导航到目标位姿
  - ✓ 自动旋转控制：原地旋转到4个方向（0°/90°/180°/270°）
  - ✓ 一键采集：`capture_at_pose()` 完成所有工作
  - ✓ 智能等待：旋转后自动等待图像稳定
  - ✓ 改进的错误处理和日志输出
  - ✓ 支持两种模式：自动模式（Nav2）和手动模式（调试）
  - ✓ 更新perception_node服务接口
  - ✓ 完善文档和使用示例
  - **突破性变更**：
    - `capture_four_directions()` 已废弃
    - 新API：`capture_at_pose(node_id, pose, frame_id, navigate)`
    - 构造函数需要传入 `camera_subscriber`

- **v0.1.2** (2026-03-27): 全景采集管理器调试和功能增强
  - ✓ 修复 PoseStamped 访问错误（pose.pose.position 而非 pose.position）
  - ✓ 修复 capture_panorama 服务响应格式（使用字符串数组而非JSON）
  - ✓ 增强 capture_four_directions 方法：
    - 添加相机就绪状态检查
    - 增加图像有效性验证（None检查和空图像检查）
    - 添加可配置的稳定等待时间参数
    - 改进日志输出（使用表情符号标记）
  - ✓ 完善错误处理和用户提示
  - ✓ 测试验证：成功采集4个方向的RGB+深度图（1280x800）
  - ✓ 更新文档：添加实际测试示例和重要注意事项

- **v0.1.1** (2026-03-26): 功能修复和文档完善
  - ✓ 修复 CameraSubscriber 消息处理问题（添加 rclpy.spin_once）
  - ✓ 优化 QoS 配置为 RELIABLE 模式
  - ✓ 修正 ROS2 服务名称（移除 /perception_node 前缀）
  - ✓ 添加完整测试脚本 (test_perception_services.sh)
  - ✓ 完善故障排查指南
  - ✓ 添加 Jupyter 使用文档
  - ✓ 更新所有代码示例

- **v0.1.0** (2026-03-24): 初始版本
  - RGB-D 图像采集
  - 四方向全景采集
  - VLM 语义标注集成
  - 语义信息提取和存储
  - Gemini 336L 相机支持
  - 环境变量 API Key 配置
