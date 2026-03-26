# SSTG Perception Module - 使用指南

## 📋 概述

SSTG Perception 模块负责：
- RGB-D 图像采集（Gemini 336L 相机）
- 四方向全景图采集
- 调用阿里云百炼 VLM (qwen-vl-plus) 进行语义标注
- 结构化语义信息提取和存储

---

## 🚀 快速启动

### 前置条件

```bash
# 1. 安装依赖
pip install opencv-python numpy requests Pillow

# 2. 确保已构建包
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
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
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
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
cd ~/yahboomcar_ros2_ws/yahboomcar_ws/src/sstg_perception
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
全景图采集管理器

```python
from sstg_perception.panorama_capture import PanoramaCapture

# 初始化
capture = PanoramaCapture(storage_path='/tmp/sstg_perception')

# 采集单个方向
result = capture.capture_panorama(
    rgb_image,
    depth_image,
    node_id=0,
    pose={'x': 1.0, 'y': 2.0, 'theta': 0.0}
)

# 采集四个方向
panorama_data = capture.capture_four_directions(
    camera_subscriber,
    node_id=0,
    pose={'x': 1.0, 'y': 2.0, 'theta': 0.0},
    rotation_callback=None  # 可选的旋转回调
)

# 检查状态
if capture.is_panorama_complete():
    pano_data = capture.get_panorama_data()
    print(pano_data['images'])
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

**功能**：采集指定节点的四方向全景图（0°, 90°, 180°, 270°）

**调用示例**：
```bash
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {position: {x: 1.0, y: 2.0, z: 0.0}, orientation: {w: 1.0}}}"
```

**请求参数**:
- `node_id`: 拓扑节点 ID
- `pose`: 机器人位姿
  - `position`: {x, y, z}
  - `orientation`: {x, y, z, w} 四元数

**响应字段**:
- `success`: 布尔值，是否成功
- `image_paths`: JSON 字符串，包含四个方向的图像路径
  ```json
  {
    "0": "/tmp/sstg_perception/node_0/000deg_rgb.png",
    "90": "/tmp/sstg_perception/node_0/090deg_rgb.png",
    "180": "/tmp/sstg_perception/node_0/180deg_rgb.png",
    "270": "/tmp/sstg_perception/node_0/270deg_rgb.png"
  }
  ```
- `error_message`: 错误信息（失败时）

**成功响应示例**：
```
success: True
image_paths: '{"0": "/tmp/sstg_perception/node_0/000deg_rgb.png", ...}'
error_message: ''
```

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

### 快速测试（推荐）

使用一键测试脚本：

```bash
cd ~/yahboomcar_ros2_ws/yahboomcar_ws/src/sstg_perception
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
cd ~/yahboomcar_ros2_ws/yahboomcar_ws/src/sstg_perception/test
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
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
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

**测试全景采集**（需要相机）：
```bash
# 确保相机已启动
ros2 topic list | grep camera

# 调用服务
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {position: {x: 1.0, y: 2.0, z: 0.0}, orientation: {w: 1.0}}}"
```

### 性能测试

测试 VLM API 响应时间：

```bash
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
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
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
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
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
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
cd ~/yahboomcar_ros2_ws/yahboomcar_ws/src/sstg_perception
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
