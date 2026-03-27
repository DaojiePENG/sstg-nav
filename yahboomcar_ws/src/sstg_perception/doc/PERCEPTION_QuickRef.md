# SSTG Perception Module - 快速参考卡 v0.2.0

## ⚡ 完整系统启动

```bash
# 终端1: 启动相机
ros2 launch yahboomcar_nav camera_gemini_336l.launch.py

# 终端2: 启动雷达
ros2 launch yahboomcar_nav laser_bringup_launch.py

# 终端3: 启动导航（DWA）
ros2 launch yahboomcar_nav navigation_dwa_launch.py

# 终端4: 启动可视化（可选）
ros2 launch yahboomcar_nav display_nav_launch.py

# 终端5: 启动perception节点
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
ros2 run sstg_perception perception_node
```

## ✅ 验证系统就绪

```bash
# 检查关键节点
ros2 node list | grep -E "(camera|amcl|bt_navigator|perception)"

# 检查相机（应该有数据）
ros2 topic hz /camera/color/image_raw

# 检查定位（机器人已定位）
ros2 topic echo /amcl_pose --once

# 检查服务
ros2 service list | grep capture_panorama
```

---

## 🎯 核心功能

**自动导航并采集全景图**：给定目标位姿 → 自动导航 → 自动旋转4个方向 → 采集RGB-D图像

---

## 🔧 快速测试

### 1. 准备工作
```bash
# 确保相机运行
ros2 topic hz /camera/color/image_raw

# 确保Nav2运行且机器人已定位
ros2 topic echo /amcl_pose --once
```

### 2. 调用采集服务
```bash
# 导航到(2.0, 1.5)并自动采集
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {header: {frame_id: 'map'}, pose: {position: {x: 2.0, y: 1.5, z: 0.0}, orientation: {w: 1.0}}}}"

# 查看结果
ls -lh /tmp/sstg_perception/node_0/
```

---

## 🔧 常用命令

### 启动 Perception 节点（推荐）
```bash
# 方法 1: 前台运行（可查看日志）
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
ros2 run sstg_perception perception_node

# 方法 2: 后台运行
ros2 run sstg_perception perception_node > /tmp/perception_node.log 2>&1 &
# 查看日志: tail -f /tmp/perception_node.log
```

### 使用 Launch 文件启动（包含相机）
```bash
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
ros2 launch sstg_perception perception.launch.py
```

### 仅启动相机（用于测试）
```bash
ros2 launch orbbec_camera gemini_330_series.launch.py
```

### 查看相机话题
```bash
ros2 topic list | grep camera
```

### 查看相机图像
```bash
ros2 topic echo /camera/rgb/image_raw --once
ros2 run image_view image_view image:=/camera/rgb/image_raw
```

### 运行测试
```bash
cd /home/daojie/yahboomcar_ros2_ws/yahboomcar_ws/src/sstg_perception/test
python3 test_perception.py
```

### 构建包
```bash
cd /home/daojie/yahboomcar_ros2_ws/yahboomcar_ws
colcon build --symlink-install --packages-select sstg_perception
```

---

## 📡 ROS2 服务调用

### 全景图采集（主要功能）

**前置条件**：
- ✅ perception_node运行
- ✅ 相机运行
- ✅ Nav2运行且机器人已定位

**调用示例**：
```bash
# 基本调用：导航到原点并采集
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {header: {frame_id: 'map'}, pose: {position: {x: 0.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}"

# 导航到指定位置
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 1, pose: {header: {frame_id: 'map'}, pose: {position: {x: 2.5, y: 1.3, z: 0.0}, orientation: {w: 1.0}}}}"

# 带初始朝向（90度）
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 2, pose: {header: {frame_id: 'map'}, pose: {position: {x: 1.0, y: 1.0, z: 0.0}, orientation: {z: 0.707, w: 0.707}}}}"
```

**响应格式**：
```yaml
success: true
image_paths:
  - '0:/tmp/sstg_perception/node_0/000deg_rgb.png'
  - '90:/tmp/sstg_perception/node_0/090deg_rgb.png'
  - '180:/tmp/sstg_perception/node_0/180deg_rgb.png'
  - '270:/tmp/sstg_perception/node_0/270deg_rgb.png'
error_message: ''
```

**工作流程**：
```
1. 🚗 Nav2导航到目标位置 (x, y)
2. 🔄 旋转到0°并拍照
3. 🔄 旋转到90°并拍照
4. 🔄 旋转到180°并拍照
5. 🔄 旋转到270°并拍照
6. 💾 保存图像和元数据
7. ✅ 返回成功
```

### 语义标注（辅助功能）

```bash
ros2 service call /annotate_semantic sstg_msgs/srv/AnnotateSemantic \
  "{image_path: '/home/daojie/Pictures/kitchen.png', node_id: 0}"
```

**成功响应示例**：
```
success: True
image_paths: '{"0": "/tmp/sstg_perception/node_0/000deg_rgb.png", "90": "...", ...}'
error_message: ''
```

### 订阅标注结果
```bash
ros2 topic echo /semantic_annotations
```

---

## 🐍 Python API 快速示例

### 使用相机订阅器（获取 RGB-D 图像）
```python
import rclpy
from sstg_perception.camera_subscriber import CameraSubscriber

# ✓ 关键：必须先初始化 ROS2
rclpy.init()

try:
    # 创建相机订阅器
    camera = CameraSubscriber(
        rgb_topic='/camera/color/image_raw',
        depth_topic='/camera/depth/image_raw'
    )

    # 等待图像（会自动处理消息）
    if camera.wait_for_images(timeout=5):
        rgb, depth = camera.get_latest_pair()
        print(f"RGB: {rgb.shape}, Depth: {depth.shape}")
finally:
    # ✓ 关键：清理资源
    camera.destroy_node()
    rclpy.shutdown()
```

### 创建全景图
```python
from sstg_perception.panorama_capture import PanoramaCapture
import cv2

capture = PanoramaCapture(storage_path='/tmp/sstg_perception')
rgb_image = cv2.imread('image.jpg')
depth_image = cv2.imread('depth.png', cv2.IMREAD_UNCHANGED)

# 采集单个方向
result = capture.capture_panorama(
    rgb_image,
    depth_image,
    node_id=0,
    pose={'x': 1.0, 'y': 2.0, 'theta': 0.0}
)
print(f"Saved: {result['rgb_path']}")
```

### 提取语义信息
```python
from sstg_perception.semantic_extractor import SemanticExtractor

extractor = SemanticExtractor(confidence_threshold=0.5)

json_str = '''{
    "room_type": "living_room",
    "confidence": 0.95,
    "objects": [{"name": "sofa", "position": "left", "quantity": 1, "confidence": 0.9}],
    "description": "Living room"
}'''

success, info, error = extractor.extract_semantic_info(json_str)
if success:
    print(f"Room: {info.room_type}, Objects: {len(info.objects)}")
```

### 调用 VLM
```python
from sstg_perception.vlm_client import VLMClient
import os

api_key = os.getenv('DASHSCOPE_API_KEY')
client = VLMClient(api_key=api_key, model='qwen-vl-plus')

response = client.call_semantic_annotation('/tmp/image.jpg')
print(response.content)
```

---

## 📁 目录结构

```
sstg_perception/
├── sstg_perception/              # 核心模块
│   ├── __init__.py
│   ├── camera_subscriber.py      # 相机订阅器
│   ├── panorama_capture.py       # 全景图采集
│   ├── vlm_client.py             # VLM 客户端
│   ├── semantic_extractor.py     # 语义提取
│   └── perception_node.py        # ROS2 节点
├── launch/                        # 启动文件
│   └── perception.launch.py      # 集成相机和感知
├── config/                        # 配置文件
│   └── perception_config.yaml
├── scripts/                       # 工具脚本
│   └── test_perception_services.sh  # 服务测试脚本
├── test/                          # 测试脚本
│   ├── test_perception.py        # 单元测试
│   └── test_camera_subscriber.py # 相机测试
├── doc/                           # 文档
│   ├── MODULE_GUIDE.md           # 详细指南
│   ├── PERCEPTION_QuickRef.md    # 快速参考
│   └── JUPYTER_USAGE.md          # Jupyter 使用
├── package.xml                    # ROS2 包配置
├── CMakeLists.txt                 # CMake 配置
├── setup.py                       # Python 包配置
└── setup.cfg
```

---

## 🔌 消息和服务定义

### 服务: capture_panorama
- 请求: node_id, pose
- 响应: success, image_paths (JSON), error_message

### 服务: annotate_semantic
- 请求: image_path, node_id
- 响应: success, room_type, confidence, description, objects

### 话题: semantic_annotations (发布)
- 消息类型: sstg_msgs/SemanticAnnotation

---

## 🎯 数据流

```
相机 (Gemini 336L)
  ↓
CameraSubscriber (RGB-D)
  ↓
PanoramaCapture (4 directions)
  ↓
VLMClient (qwen-vl-plus)
  ↓
SemanticExtractor (JSON 解析)
  ↓
PerceptionNode (ROS2 服务/话题)
  ↓
其他模块 (sstg_map_manager, ...)
```

---

## 📊 参数配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| api_base_url | https://dashscope.aliyuncs.com/compatible-mode/v1 | API 基础 URL |
| vlm_model | qwen-vl-plus | VLM 模型名称 |
| panorama_storage_path | /tmp/sstg_perception | 图像存储路径 |
| rgb_topic | /camera/rgb/image_raw | RGB 图像话题 |
| depth_topic | /camera/depth/image_raw | 深度图话题 |
| confidence_threshold | 0.5 | 置信度阈值 |
| max_retries | 3 | API 最大重试次数 |
| color_width | 1280 | RGB 分辨率宽 |
| color_height | 800 | RGB 分辨率高 |
| color_fps | 30 | RGB 帧率 |
| depth_width | 1280 | 深度分辨率宽 |
| depth_height | 800 | 深度分辨率高 |
| depth_fps | 30 | 深度帧率 |

---

## 🔑 环境变量

```bash
# API Key（必须设置）
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

# ROS2 设置
source /opt/ros/humble/setup.bash

# 工作空间设置
source ~/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash
```

---

## 📝 日志和调试

```bash
# 查看节点日志
ros2 run sstg_perception perception_node

# 查看所有 ROS2 节点
ros2 node list

# 查看所有话题
ros2 topic list

# 查看所有服务
ros2 service list

# 监听话题
ros2 topic echo /semantic_annotations
```

---

## 💡 常见用法

### 场景 1: 远程建图和语义标注
1. 启动相机和感知节点
2. 操纵机器人到目标位置
3. 调用 capture_panorama 采集全景
4. 调用 annotate_semantic 进行标注
5. 结果通过 semantic_annotations 话题发布

### 场景 2: 批量标注历史图像
```python
from sstg_perception.vlm_client import VLMClientWithRetry
import os

client = VLMClientWithRetry(
    api_key=os.getenv('DASHSCOPE_API_KEY'),
    max_retries=3
)

image_files = ['/tmp/img1.jpg', '/tmp/img2.jpg']
responses = client.batch_annotate(image_files, delay_between_calls=1.0)

for resp in responses:
    print(resp.content)
```

### 场景 3: 多视图信息融合
```python
from sstg_perception.semantic_extractor import SemanticExtractor

extractor = SemanticExtractor()

# 合并 4 个方向的语义信息
merged = extractor.merge_semantic_infos(
    [info_0deg, info_90deg, info_180deg, info_270deg],
    strategy='average'
)

print(f"Merged room: {merged.room_type}")
print(f"All objects: {len(merged.objects)}")
```

---

## 🚨 故障快速排查

| 问题 | 症状 | 解决方案 |
|------|------|--------|
| 服务调用超时 | `waiting for service to become available...` | ① 检查节点是否运行: `ros2 node list` <br> ② 启动节点: `ros2 run sstg_perception perception_node` |
| 服务名称错误 | 找不到服务 | 使用 `/annotate_semantic` (不是 `/perception_node/annotate_semantic`) |
| 模块导入失败 | `ModuleNotFoundError` | ① 重新编译: `colcon build --packages-select sstg_perception` <br> ② Source 环境: `source install/setup.bash` |
| 相机无图像 | `Timeout waiting for images` | ① 检查相机连接: `lsusb` <br> ② 检查话题: `ros2 topic list \| grep camera` <br> ③ 查看话题数据: `ros2 topic echo /camera/color/image_raw --once` |
| API Key 错误 | 401 Unauthorized | 检查环境变量: `echo $DASHSCOPE_API_KEY` |
| VLM 超时 | Request timeout | ① 检查网络连接 <br> ② 增加 timeout 参数 |
| JSON 解析失败 | 无对象提取 | 检查 VLM 输出格式，调整提示词 |

### 完整测试流程（推荐）

```bash
# 步骤 1: 编译（如果修改了代码）
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
colcon build --packages-select sstg_perception

# 步骤 2: Source 环境
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

# 步骤 3: 启动节点
ros2 run sstg_perception perception_node &
sleep 3

# 步骤 4: 验证节点和服务
ros2 node list | grep perception_node
ros2 service list | grep -E "(annotate|capture)"

# 步骤 5: 测试服务
ros2 service call /annotate_semantic sstg_msgs/srv/AnnotateSemantic \
  "{image_path: '/home/daojie/Pictures/kitchen.png', node_id: 0}"
```

### 快速测试脚本

```bash
# 运行一键测试脚本
cd ~/yahboomcar_ros2_ws/yahboomcar_ws/src/sstg_perception
bash scripts/test_perception_services.sh
```

---

**版本**: v0.1.1
**最后更新**: 2026-03-26
**维护者**: SSTG-Nav Team

**更新日志**:
- v0.1.1 (2026-03-26):
  - ✓ 修复 CameraSubscriber 消息处理问题
  - ✓ 优化 QoS 配置
  - ✓ 修正服务名称说明
  - ✓ 添加完整测试脚本
  - ✓ 完善文档和故障排查指南
- v0.1.0 (2026-03-24): 初始版本
