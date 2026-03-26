# SSTG Perception 模块文档索引

## 📚 文档列表

### 1. [MODULE_GUIDE.md](MODULE_GUIDE.md) - 完整模块指南 ⭐
**适用场景**：首次使用、深入学习、完整参考

**包含内容**：
- ✓ 详细的快速启动指南（3种启动方式）
- ✓ 核心组件 API 参考（CameraSubscriber, PanoramaCapture, VLMClient, SemanticExtractor）
- ✓ ROS2 服务接口详细说明（请求/响应格式）
- ✓ 数据存储结构和元数据格式
- ✓ 配置参数说明
- ✓ 相机参数（Gemini 336L）
- ✓ 完整测试指南
- ✓ 详细故障排查（6个常见问题）
- ✓ 更新历史

**推荐阅读顺序**：
1. 快速启动 → 2. ROS2 服务接口 → 3. 核心组件 → 4. 故障排查

---

### 2. [PERCEPTION_QuickRef.md](PERCEPTION_QuickRef.md) - 快速参考卡 ⚡
**适用场景**：日常使用、快速查找命令

**包含内容**：
- ✓ 一句话启动命令
- ✓ 常用命令速查（启动、测试、构建）
- ✓ ROS2 服务调用示例
- ✓ Python API 快速示例
- ✓ 目录结构
- ✓ 数据流图
- ✓ 参数配置表
- ✓ 常见用法场景
- ✓ 故障快速排查表

**特点**：紧凑、命令导向、适合打印

---

### 3. [JUPYTER_USAGE.md](JUPYTER_USAGE.md) - Jupyter 使用指南 📓
**适用场景**：在 Jupyter Notebook 中使用 sstg_perception

**包含内容**：
- ✓ 问题原因说明（ModuleNotFoundError）
- ✓ 3种解决方案（环境设置）
- ✓ 完整示例代码（CameraSubscriber 使用）
- ✓ 验证安装方法
- ✓ 关键要点总结

**适用人群**：数据科学家、研究人员、交互式开发者

---

### 4. [scripts/README.md](../scripts/README.md) - 测试脚本说明 🧪
**适用场景**：运行自动化测试

**包含内容**：
- ✓ test_perception_services.sh 详细说明
- ✓ 脚本执行流程
- ✓ 输出示例
- ✓ 日志位置
- ✓ 常见问题
- ✓ 手动测试命令

**特点**：专注于测试脚本的使用和排错

---

## 🎯 快速导航

### 我该看哪个文档？

| 我想... | 推荐文档 | 章节 |
|--------|---------|------|
| 快速启动 perception 节点 | PERCEPTION_QuickRef.md | "⚡ 一句话启动" |
| 学习如何使用模块 | MODULE_GUIDE.md | "🚀 快速启动" |
| 调用 ROS2 服务 | MODULE_GUIDE.md | "🔌 ROS2 服务接口" |
| 在 Jupyter 中使用 | JUPYTER_USAGE.md | 全文 |
| 运行测试 | scripts/README.md | "test_perception_services.sh" |
| 解决导入错误 | JUPYTER_USAGE.md | "解决方案" |
| 排查服务超时 | MODULE_GUIDE.md | "🐛 故障排查 - 问题 1" |
| 查看 API 参考 | MODULE_GUIDE.md | "📦 模块架构" |
| 找启动命令 | PERCEPTION_QuickRef.md | "🔧 常用命令" |
| 了解数据格式 | MODULE_GUIDE.md | "💾 数据存储" |

---

## 📖 完整学习路径

### 入门路径（30分钟）
1. 阅读 PERCEPTION_QuickRef.md 的"一句话启动"
2. 运行 `bash scripts/test_perception_services.sh`
3. 查看 PERCEPTION_QuickRef.md 的"ROS2 服务调用"
4. 尝试手动调用一次服务

### 进阶路径（2小时）
1. 通读 MODULE_GUIDE.md 的"快速启动"和"核心组件"
2. 阅读各个 Python API 示例
3. 在 Python 中使用 CameraSubscriber 和 VLMClient
4. 学习 MODULE_GUIDE.md 的"故障排查"

### 开发路径（持续）
1. 熟悉所有文档
2. 修改代码时参考 API 文档
3. 遇到问题查看故障排查
4. 在 Jupyter 中进行实验（参考 JUPYTER_USAGE.md）

---

## 🔍 关键概念速查

### ROS2 服务名称（重要！）
- ✅ 正确：`/annotate_semantic`, `/capture_panorama`
- ❌ 错误：`/perception_node/annotate_semantic`

### 必须的环境变量
```bash
export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
```

### 启动节点的最简命令
```bash
ros2 run sstg_perception perception_node
```

### CameraSubscriber 关键步骤
```python
rclpy.init()                    # 1. 初始化
camera = CameraSubscriber()     # 2. 创建
camera.wait_for_images()        # 3. 等待（自动 spin）
camera.destroy_node()           # 4. 清理
rclpy.shutdown()
```

---

## 📞 获取帮助

### 常见问题先查这里
1. MODULE_GUIDE.md "🐛 故障排查" 章节
2. PERCEPTION_QuickRef.md "🚨 故障快速排查" 表格

### 日志位置
- 节点日志: `/tmp/perception_node_test.log`
- 编译日志: `/tmp/colcon_build.log`

### 调试命令
```bash
# 检查节点
ros2 node list

# 检查服务
ros2 service list | grep -E "(annotate|capture)"

# 查看话题
ros2 topic list | grep camera

# 测试接收图像
ros2 topic echo /camera/color/image_raw --once
```

---

## 📌 版本信息

- **当前版本**: v0.1.1
- **最后更新**: 2026-03-26
- **维护团队**: SSTG-Nav Team

### v0.1.1 主要更新
- ✓ 修复 CameraSubscriber 消息处理问题
- ✓ 优化 QoS 配置
- ✓ 修正服务名称说明
- ✓ 添加完整测试脚本
- ✓ 完善文档体系

---

**提示**：建议将 PERCEPTION_QuickRef.md 打印或保存为 PDF，放在手边作为日常参考！
