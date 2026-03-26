# SSTG Perception 测试脚本

## 脚本列表

### test_perception_services.sh

**功能**：完整的服务测试脚本，自动化测试 perception 模块的所有服务

**使用方法**：
```bash
cd ~/yahboomcar_ros2_ws/yahboomcar_ws/src/sstg_perception
bash scripts/test_perception_services.sh
```

**脚本执行流程**：
1. ✓ 切换到工作空间目录
2. ✓ 编译 sstg_perception 包
3. ✓ 加载 ROS2 环境
4. ✓ 启动 perception_node（后台）
5. ✓ 验证节点和服务
6. ✓ 测试语义标注服务
7. ✓ 测试全景采集服务（如果相机可用）
8. ✓ 显示测试结果和有用命令

**输出示例**：
```
==============================================================
    SSTG Perception 服务测试
==============================================================

[INFO] 步骤 1/6: 切换到工作空间目录...
[SUCCESS] 当前目录: /home/daojie/yahboomcar_ros2_ws/yahboomcar_ws

[INFO] 步骤 2/6: 编译 sstg_perception 包...
[SUCCESS] 编译成功

[INFO] 步骤 3/6: 加载环境...
[SUCCESS] DASHSCOPE_API_KEY 已设置

[INFO] 步骤 4/6: 启动 perception_node...
[SUCCESS] Perception Node 已启动 (PID: 12345)

[INFO] 步骤 5/6: 验证节点和服务...
/perception_node
/camera_subscriber
[SUCCESS] 节点正常运行

/annotate_semantic
/capture_panorama
[SUCCESS] 服务已就绪

[INFO] 步骤 6/6: 测试服务调用...
[INFO] 测试 1: 语义标注服务
[SUCCESS] ✓ 语义标注服务调用成功

[INFO] 测试 2: 全景采集服务
[SUCCESS] ✓ 全景采集服务调用成功

==============================================================
    测试完成
==============================================================
```

**日志位置**：
- 节点日志: `/tmp/perception_node_test.log`
- 编译日志: `/tmp/colcon_build.log`
- 标注结果: `/tmp/annotate_result.log`
- 采集结果: `/tmp/capture_result.log`

**交互选项**：
脚本结束时会询问是否保持节点运行：
- 选择 `Y`：节点继续在后台运行
- 选择 `n`：自动停止节点

**常见问题**：

1. **编译失败**
   - 检查日志: `cat /tmp/colcon_build.log`
   - 确保依赖已安装: `rosdep install --from-paths src --ignore-src -r -y`

2. **节点启动失败**
   - 查看日志: `cat /tmp/perception_node_test.log`
   - 检查环境变量: `echo $DASHSCOPE_API_KEY`

3. **服务调用超时**
   - 确认节点运行: `ros2 node list | grep perception`
   - 确认服务存在: `ros2 service list | grep annotate`

4. **测试图像不存在**
   - 脚本会自动查找其他图像
   - 或手动指定: 编辑脚本中的 `TEST_IMAGE` 变量

## 手动测试命令

如果需要手动测试单个功能：

### 1. 启动节点
```bash
cd ~/yahboomcar_ros2_ws/yahboomcar_ws
source install/setup.bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
ros2 run sstg_perception perception_node
```

### 2. 测试语义标注
```bash
ros2 service call /annotate_semantic sstg_msgs/srv/AnnotateSemantic \
  "{image_path: '/home/daojie/Pictures/kitchen.png', node_id: 0}"
```

### 3. 测试全景采集
```bash
ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 0, pose: {position: {x: 1.0, y: 2.0, z: 0.0}, orientation: {w: 1.0}}}"
```

### 4. 查看实时日志
```bash
tail -f /tmp/perception_node_test.log
```

### 5. 停止节点
```bash
# 如果知道 PID
kill <PID>

# 或强制停止所有
pkill -f "ros2 run sstg_perception"
```

## 参考文档

- [MODULE_GUIDE.md](../doc/MODULE_GUIDE.md) - 详细模块使用指南
- [PERCEPTION_QuickRef.md](../doc/PERCEPTION_QuickRef.md) - 快速参考卡
- [JUPYTER_USAGE.md](../doc/JUPYTER_USAGE.md) - Jupyter 环境使用
