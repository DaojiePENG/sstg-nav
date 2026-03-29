# 全景图采集管理器调试总结

**日期**: 2026-03-27
**版本**: v0.1.2

## 🎯 调试目标

1. 确认相机和Nav2服务正常运行
2. 调试全景图采集管理器功能
3. 修复发现的bug
4. 完善技术文档

## ✅ 完成的工作

### 1. 系统状态确认

- ✅ Gemini 336L相机正常运行
  - 节点: `/camera/camera`
  - RGB话题: `/camera/color/image_raw` (1280x800)
  - 深度话题: `/camera/depth/image_raw` (1280x800)

- ✅ Nav2导航服务正常运行
  - AMCL定位、路径规划、控制器等所有节点在线

### 2. 发现并修复的Bug

#### Bug #1: PoseStamped访问错误
**位置**: `perception_node.py:129-130`

**问题**: 错误访问 `request.pose.position.x`，但 `pose` 是 `PoseStamped` 类型
```python
# 错误代码
pose = {
    'x': float(request.pose.position.x),  # ✗ PoseStamped没有直接的position属性
    'y': float(request.pose.position.y),
}
```

**修复**: 使用正确的嵌套访问路径
```python
# 正确代码
pose = {
    'x': float(request.pose.pose.position.x),  # ✓ 正确访问路径
    'y': float(request.pose.pose.position.y),
}
```

#### Bug #2: 服务响应格式不匹配
**位置**: `perception_node.py:160`

**问题**: 服务定义要求 `string[]` 数组，但返回JSON字符串
```python
# 错误代码
response.image_paths = json.dumps(panorama_data['images'])  # ✗ 返回JSON字符串
```

**修复**: 转换为字符串数组，格式为 "angle:path"
```python
# 正确代码
images_dict = panorama_data['images']
response.image_paths = [f"{angle}:{path}" for angle, path in sorted(images_dict.items())]
```

#### Bug #3: 全景采集缺少验证
**位置**: `panorama_capture.py:104-156`

**问题**:
1. 没有检查相机就绪状态
2. 没有验证图像有效性
3. 缺少详细的日志输出
4. 旋转后等待时间固定不可配置

**修复**:
```python
def capture_four_directions(self, camera_subscriber,
                           node_id: int,
                           pose: Dict,
                           rotation_callback=None,
                           wait_after_rotation: float = 1.5) -> Dict:  # ✓ 新增参数

    # ✓ 1. 检查相机就绪
    if not camera_subscriber.is_ready():
        self.get_logger_func('✗ Camera not ready before panorama capture')
        return None

    for idx, angle in enumerate(self.panorama_angles):
        # ✓ 2. 改进日志输出
        self.get_logger_func(f'📸 Capturing direction {idx+1}/4: {angle}°')

        if rotation_callback is not None:
            # ✓ 3. 可配置等待时间
            time.sleep(wait_after_rotation)

        rgb, depth = camera_subscriber.get_latest_pair()

        # ✓ 4. 验证图像有效性
        if rgb is None:
            self.get_logger_func(f'✗ Failed to get RGB image at {angle}°')
            return None

        if rgb.size == 0:
            self.get_logger_func(f'✗ Empty RGB image at {angle}°')
            return None
```

### 3. 代码改进

#### 改进 #1: 清理未使用的导入
- `panorama_capture.py`: 移除 `List`, `Tuple`
- `perception_node.py`: 移除 `Image`, `PoseStamped`, `json`, `Optional`, `SemanticObject`

#### 改进 #2: 增强日志可读性
使用表情符号标记不同的日志级别：
- 📸 采集进行中
- 🔄 旋转操作
- ⏳ 等待中
- ✓ 成功
- ✗ 失败
- ✅ 完全成功
- ⚠️ 警告

### 4. 测试验证

#### 测试环境
- 相机: Gemini 336L (1280x800 @ 30fps)
- 节点: perception_node v0.1.2
- 模式: 手动模式（无自动旋转）

#### 测试结果
✅ **全部通过！**

**服务调用**:
```bash
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {header: {frame_id: 'map'}, pose: {position: {x: 1.0, y: 2.0, z: 0.0}, orientation: {w: 1.0}}}}"
```

**输出结果**:
```
success: true
image_paths:
  - '0:/tmp/sstg_perception/node_0/000deg_rgb.png'
  - '90:/tmp/sstg_perception/node_0/090deg_rgb.png'
  - '180:/tmp/sstg_perception/node_0/180deg_rgb.png'
  - '270:/tmp/sstg_perception/node_0/270deg_rgb.png'
```

**保存的文件**:
```
node_0/
├── 000deg_rgb.png    (1280x800, RGB, 872KB)
├── 000deg_depth.png  (1280x800, 16-bit, 413KB)
├── 090deg_rgb.png
├── 090deg_depth.png
├── 180deg_rgb.png
├── 180deg_depth.png
├── 270deg_rgb.png
├── 270deg_depth.png
└── panorama_metadata.json
```

**元数据示例**:
```json
{
  "node_id": 0,
  "pose": {"x": 1.0, "y": 2.0, "theta": 0.0},
  "timestamp": "2026-03-27T14:32:28.743120",
  "images": {
    "0": "/tmp/sstg_perception/node_0/000deg_rgb.png",
    "90": "/tmp/sstg_perception/node_0/090deg_rgb.png",
    "180": "/tmp/sstg_perception/node_0/180deg_rgb.png",
    "270": "/tmp/sstg_perception/node_0/270deg_rgb.png"
  },
  "complete": true
}
```

### 5. 文档更新

更新了 `MODULE_GUIDE.md`，包括：
- ✅ v0.1.2版本改进说明
- ✅ PanoramaCapture API更新（新参数、工作模式）
- ✅ 正确的服务调用格式（PoseStamped）
- ✅ 完整的Python客户端示例
- ✅ 实际测试结果和输出示例
- ✅ 重要使用注意事项

## 🎓 经验教训

### 1. ROS2消息类型要仔细
- `Pose` vs `PoseStamped` - 结构完全不同
- 使用 `ros2 interface show` 确认消息结构
- 嵌套访问路径要正确：`pose.pose.position.x`

### 2. 服务定义要严格遵守
- srv文件定义 `string[]` 就必须返回字符串数组
- 不能用JSON字符串替代（即使更灵活）
- 可以在数组元素中编码额外信息（如 "angle:path"）

### 3. 图像采集需要验证
- 检查相机就绪状态
- 验证返回的图像不是None
- 验证图像不是空的（size > 0）
- 在旋转后留足够时间让图像稳定

### 4. 日志对调试至关重要
- 使用清晰的日志标记
- 表情符号能快速识别状态
- 记录关键参数和路径

## 📋 后续建议

### 短期改进
1. 实现自动旋转功能
   - 集成Nav2旋转控制
   - 实现 rotation_callback
   - 测试自动模式

2. 增加采集验证
   - 检测图像模糊度
   - 验证相邻图像差异
   - 重试机制

### 长期优化
1. 支持更多采集角度（如8个方向）
2. 支持点云拼接生成真正的全景
3. 集成到拓扑地图构建流程
4. 添加采集进度回调

## 🔧 快速使用

启动系统：
```bash
# 1. 启动相机和导航（如果未运行）
# 2. 启动perception节点
cd ~/sstg_nav/yahboomcar_ws
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
ros2 run sstg_perception perception_node

# 3. 测试采集
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {header: {frame_id: 'map'}, pose: {position: {x: 0.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}"
```

## ✨ 总结

全景图采集管理器已经完成调试并正常工作！主要成果：
- ✅ 修复3个关键bug
- ✅ 增强验证和错误处理
- ✅ 改进日志输出
- ✅ 完善技术文档
- ✅ 测试验证通过

系统现在可以稳定地采集RGB-D全景图像，为后续的VLM语义标注和拓扑地图构建提供基础。
