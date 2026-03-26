# 在 Jupyter Notebook 中使用 SSTG Perception

## 问题原因

在 Jupyter Notebook 中导入 `sstg_perception` 时出现 `ModuleNotFoundError`，通常由以下原因导致：

1. **包未编译或编译失败**：`colcon build` 没有正确安装 Python 模块到 `install/` 目录
2. **环境未加载**：Jupyter kernel 没有加载 ROS2 工作空间环境
3. **Python 路径问题**：包的安装路径不在 Jupyter 的 `sys.path` 中

## 解决方案

### 方法 1：启动 Jupyter 前设置环境（推荐）⭐

这是最可靠的方法，确保 Jupyter 在正确的环境中启动。

```bash
# 1. 切换到工作空间
cd ~/yahboomcar_ros2_ws/yahboomcar_ws

# 2. 编译包（如果未编译或有更新）
colcon build --packages-select sstg_perception

# 3. 加载环境
source /opt/ros/humble/setup.bash
source install/setup.bash

# 4. 设置 API Key（如果需要 VLM 功能）
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"

# 5. 启动 Jupyter
jupyter notebook
# 或
jupyter lab
```

**优点**：
- ✓ 完整的 ROS2 环境
- ✓ 所有依赖都正确加载
- ✓ 环境变量正确设置

---

### 方法 2：在 Notebook 中添加路径

如果 Jupyter 已经启动，可以在第一个 cell 中动态添加路径。

```python
# 第一个 Cell：设置环境
import sys
import os

# 添加 sstg_perception 包路径
PERCEPTION_PATH = '/home/daojie/yahboomcar_ros2_ws/yahboomcar_ws/install/sstg_perception/lib/python3.10/site-packages'
if PERCEPTION_PATH not in sys.path:
    sys.path.insert(0, PERCEPTION_PATH)

# 设置 API Key（如果需要）
os.environ['DASHSCOPE_API_KEY'] = 'sk-942e8661f10f492280744a26fe7b953b'

# 验证导入
try:
    import sstg_perception
    print("✓ sstg_perception 导入成功")
    from sstg_perception.camera_subscriber import CameraSubscriber
    print("✓ CameraSubscriber 导入成功")
except ModuleNotFoundError as e:
    print(f"✗ 导入失败: {e}")
```

**优点**：
- ✓ 无需重启 Jupyter
- ✓ 适合快速测试

**缺点**：
- ✗ 每个 notebook 都需要添加
- ✗ ROS2 环境可能不完整

---

### 方法 3：使用环境设置脚本

创建一个便捷脚本来设置环境。

```bash
# 使用已创建的脚本
source ~/yahboomcar_ros2_ws/yahboomcar_ws/setup_perception_env.sh

# 然后启动 Jupyter
jupyter notebook
```

---

## 完整使用示例

### 示例 1：使用 CameraSubscriber 获取图像

**前提条件**：
- ROS2 环境已加载（使用方法 1 或 3）
- 相机节点正在运行

```python
import rclpy
from sstg_perception.camera_subscriber import CameraSubscriber
import cv2
from IPython.display import Image, display
import matplotlib.pyplot as plt

# ✓ 关键步骤 1：初始化 ROS2
rclpy.init()

try:
    # ✓ 关键步骤 2：创建相机订阅器
    camera = CameraSubscriber(
        rgb_topic='/camera/color/image_raw',
        depth_topic='/camera/depth/image_raw'
    )

    print("等待相机图像...")

    # ✓ 关键步骤 3：等待图像（会自动处理消息）
    if camera.wait_for_images(timeout=5):
        rgb, depth = camera.get_latest_pair()
        print(f"✓ 成功接收图像!")
        print(f"  RGB shape: {rgb.shape}")
        print(f"  Depth shape: {depth.shape}")

        # 显示 RGB 图像
        plt.figure(figsize=(12, 4))

        plt.subplot(1, 2, 1)
        plt.imshow(cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB))
        plt.title('RGB Image')
        plt.axis('off')

        plt.subplot(1, 2, 2)
        plt.imshow(depth, cmap='gray')
        plt.title('Depth Image')
        plt.axis('off')

        plt.show()
    else:
        print("✗ 超时：未接收到图像")

finally:
    # ✓ 关键步骤 4：清理资源
    camera.destroy_node()
    rclpy.shutdown()
    print("✓ 清理完成")
```

---

### 示例 2：使用 VLM 进行语义标注

```python
import os
from sstg_perception.vlm_client import VLMClient
from sstg_perception.semantic_extractor import SemanticExtractor
from IPython.display import Image, display

# 设置 API Key
api_key = os.getenv('DASHSCOPE_API_KEY')
if not api_key:
    api_key = 'sk-942e8661f10f492280744a26fe7b953b'
    os.environ['DASHSCOPE_API_KEY'] = api_key

# 创建客户端
vlm_client = VLMClient(api_key=api_key, model='qwen-vl-plus')
extractor = SemanticExtractor(confidence_threshold=0.5)

# 测试图像路径
test_image = '/home/daojie/Pictures/kitchen.png'

# 显示图像
print("测试图像:")
display(Image(filename=test_image, width=400))

# 调用 VLM
print("\n调用 VLM API...")
response = vlm_client.call_semantic_annotation(test_image)

if response.success:
    print(f"✓ VLM 调用成功")
    print(f"  Tokens: {response.tokens_used}")
    print(f"\nVLM 输出:\n{response.content}\n")

    # 提取语义信息
    success, semantic_info, error = extractor.extract_semantic_info(response.content)

    if success:
        print("✓ 语义提取成功")
        print(f"\n房间类型: {semantic_info.room_type}")
        print(f"置信度: {semantic_info.confidence:.2f}")
        print(f"\n检测到的物体 ({len(semantic_info.objects)} 个):")

        for obj in semantic_info.objects:
            print(f"  - {obj.name}: 位置={obj.position}, 数量={obj.quantity}, 置信度={obj.confidence:.2f}")

        print(f"\n场景描述:\n{semantic_info.description}")
    else:
        print(f"✗ 语义提取失败: {error}")
else:
    print(f"✗ VLM 调用失败: {response.error}")
```

---

### 示例 3：全景图采集

```python
import rclpy
from sstg_perception.camera_subscriber import CameraSubscriber
from sstg_perception.panorama_capture import PanoramaCapture
import matplotlib.pyplot as plt
import cv2

# 初始化
rclpy.init()

try:
    # 创建组件
    camera = CameraSubscriber(
        rgb_topic='/camera/color/image_raw',
        depth_topic='/camera/depth/image_raw'
    )
    capture = PanoramaCapture(storage_path='/tmp/sstg_perception')

    # 等待图像
    if camera.wait_for_images(timeout=5):
        print("✓ 相机就绪")

        # 采集 4 个方向（模拟）
        angles = [0, 90, 180, 270]
        images = []

        for angle in angles:
            rgb, depth = camera.get_latest_pair()

            result = capture.capture_panorama(
                rgb,
                depth,
                node_id=0,
                pose={'x': 1.0, 'y': 2.0, 'theta': angle}
            )

            print(f"✓ 采集 {angle}° 完成: {result['rgb_path']}")
            images.append(cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB))

        # 显示全景图
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        for i, (img, angle) in enumerate(zip(images, angles)):
            ax = axes[i // 2, i % 2]
            ax.imshow(img)
            ax.set_title(f'{angle}°')
            ax.axis('off')

        plt.tight_layout()
        plt.show()

        # 检查状态
        if capture.is_panorama_complete():
            print("✓ 全景图采集完成")
            pano_data = capture.get_panorama_data()
            print(f"图像路径: {pano_data['images']}")

finally:
    camera.destroy_node()
    rclpy.shutdown()
```

---

## 验证安装

运行此代码检查 `sstg_perception` 是否正确安装：

```python
import sys

print("Python 路径检查:")
print("-" * 50)

# 检查 sstg_perception 路径
perception_paths = [p for p in sys.path if 'sstg_perception' in p]
if perception_paths:
    print("✓ 找到 sstg_perception 路径:")
    for p in perception_paths:
        print(f"  {p}")
else:
    print("✗ 未找到 sstg_perception 路径")
    print("\n可能需要:")
    print("1. 编译包: colcon build --packages-select sstg_perception")
    print("2. 添加路径: sys.path.insert(0, '/home/daojie/yahboomcar_ros2_ws/yahboomcar_ws/install/sstg_perception/lib/python3.10/site-packages')")

print("\n" + "-" * 50)
print("模块导入测试:")
print("-" * 50)

# 尝试导入
modules = [
    ('sstg_perception', 'sstg_perception'),
    ('camera_subscriber', 'sstg_perception.camera_subscriber'),
    ('vlm_client', 'sstg_perception.vlm_client'),
    ('semantic_extractor', 'sstg_perception.semantic_extractor'),
    ('panorama_capture', 'sstg_perception.panorama_capture'),
]

for name, module_path in modules:
    try:
        __import__(module_path)
        print(f"✓ {name}: 导入成功")
    except ModuleNotFoundError as e:
        print(f"✗ {name}: 导入失败 - {e}")
```

---

## 重新编译包

如果模块导入失败，需要重新编译：

```bash
# 在终端中运行
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
rm -rf build/sstg_perception install/sstg_perception
colcon build --packages-select sstg_perception
```

**验证编译成功**：
```bash
# 检查安装的文件
ls install/sstg_perception/lib/python3.10/site-packages/sstg_perception/

# 应该看到:
#   camera_subscriber.py
#   vlm_client.py
#   semantic_extractor.py
#   panorama_capture.py
#   perception_node.py
```

---

## 关键要点

### ✓ 必须做的事
1. **编译包**：`colcon build --packages-select sstg_perception`
2. **Source 环境**：`source install/setup.bash`（在启动 Jupyter 前）
3. **初始化 ROS2**：`rclpy.init()`（在使用 ROS2 节点前）
4. **清理资源**：`destroy_node()` 和 `rclpy.shutdown()`（使用完后）

### ✓ 推荐做法
- 使用方法 1 启动 Jupyter（在正确环境中）
- 将常用导入放在第一个 cell
- 使用 `try-finally` 确保资源清理
- 设置环境变量 `DASHSCOPE_API_KEY`

### ✗ 常见错误
- ❌ 忘记 `rclpy.init()`
- ❌ 没有 source 环境就启动 Jupyter
- ❌ 包未编译或编译失败
- ❌ 使用错误的 Python 路径

---

## 相关文档

- [MODULE_GUIDE.md](MODULE_GUIDE.md) - 完整模块使用指南
- [PERCEPTION_QuickRef.md](PERCEPTION_QuickRef.md) - 快速参考卡
- [scripts/README.md](../scripts/README.md) - 测试脚本说明

---

**版本**: v0.1.1
**最后更新**: 2026-03-26
