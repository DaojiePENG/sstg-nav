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
# 安装依赖
pip install opencv-python numpy requests Pillow

# 设置 API Key（环境变量方式）
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

# 确保已构建 sstg_msgs 和 sstg_perception
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
colcon build --symlink-install --packages-select sstg_msgs sstg_perception
```

### 启动方式 1: ROS2 启动文件（推荐）

```bash
# 源环境
source /opt/ros/humble/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

# 启动（包含相机和 perception 节点）
ros2 launch sstg_perception perception.launch.py

# 可选参数
ros2 launch sstg_perception perception.launch.py \
  color_width:=1280 \
  color_height:=800 \
  color_fps:=30 \
  panorama_storage_path:=/tmp/sstg_perception \
  confidence_threshold:=0.5
```

### 启动方式 2: 直接 Python 执行

```bash
source /opt/ros/humble/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

# 使用快速启动脚本
python3 /home/daojie/yahboomcar_ros2_ws/run_perception.py
```

### 启动方式 3: 独立模块测试

```bash
# 不需要 ROS2 环境
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

python3 << 'EOF'
from sstg_perception.panorama_capture import PanoramaCapture
from sstg_perception.semantic_extractor import SemanticExtractor
from sstg_perception.vlm_client import VLMClient

# 直接使用各组件
capture = PanoramaCapture()
extractor = SemanticExtractor()
vlm_client = VLMClient(api_key='sk-...')
EOF
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

### 服务 1: capture_panorama

采集指定节点的全景图

```bash
ros2 service call /perception_node/capture_panorama sstg_msgs/CaptureImage \
  "{node_id: 0, pose: {position: {x: 1.0, y: 2.0, z: 0.0}, orientation: {w: 1.0}}}"
```

**响应**:
- `success`: 布尔值
- `image_paths`: JSON 字符串，包含四个方向的图像路径
- `error_message`: 错误信息

### 服务 2: annotate_semantic

对图像进行语义标注

```bash
ros2 service call /perception_node/annotate_semantic sstg_msgs/AnnotateSemantic \
  "{image_path: '/tmp/image.jpg', node_id: 0}"
```

**响应**:
- `success`: 布尔值
- `room_type`: 房间类型
- `confidence`: 置信度
- `description`: 描述
- `objects`: 语义对象列表

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

运行测试套件：

```bash
cd ~/yahboomcar_ros2_ws/yahboomcar_ws/src/sstg_perception/test
python3 test_perception.py
```

**测试项目**:
- ✓ 全景图采集
- ✓ 语义提取（JSON 解析、置信度过滤、多视图合并）
- ✓ VLM 客户端配置
- ✓ 集成测试

---

## 🐛 故障排查

### 问题 1: 相机不响应

```bash
# 检查话题是否发布
ros2 topic list | grep camera

# 检查图像数据
ros2 topic echo /camera/color/image_raw --once
```

### 问题 2: API Key 未配置

```bash
# 检查环境变量
echo $DASHSCOPE_API_KEY

# 设置环境变量
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

# 添加到 ~/.bashrc（永久设置）
echo 'export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"' >> ~/.bashrc
source ~/.bashrc
```

### 问题 3: VLM API 错误

```
错误: "API Error: 401"
原因: API Key 无效
解决: 检查 API Key 和网络连接

错误: "Request timeout"
原因: API 响应过慢
解决: 增加 timeout 参数或增加重试次数
```

### 问题 4: JSON 解析失败

```
错误: "Failed to extract JSON"
原因: VLM 响应格式不正确
解决: 检查 VLM 输出，调整提示词
```

---

## 📖 API 参考

详见各模块源代码中的 docstring。

---

## 📝 更新历史

- **v0.1.0** (2026-03-24): 初始版本
  - RGB-D 图像采集
  - 四方向全景采集
  - VLM 语义标注集成
  - 语义信息提取和存储
  - Gemini 336L 相机支持
  - 环境变量 API Key 配置
