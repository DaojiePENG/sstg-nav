# SSTG-Nav 项目开发进度

**项目日期**：2026-03-25  
**项目状态**：阶段二（感知能力）已完成 → 准备阶段三（理解和规划）

---

## 📊 完成情况

### ✅ 阶段一：基础设施（第1-2周）

#### 1.1 系统规划 [100%]
- [x] 需求分析与系统架构设计
- [x] 七个核心模块规划
- [x] 多模态交互支持确认
- [x] 详细规划文档编写 → `SSTG-Nav-Plan.md`

#### 1.2 消息定义 [100%]
- [x] 创建 `sstg_msgs` 包
- [x] 定义7个核心消息类型
  - SemanticObject
  - SemanticData
  - Command
  - NavigationPlan
  - NavigationFeedback
  - TaskStatus
  - SemanticAnnotation
- [x] 定义6个核心服务接口
  - CreateNode
  - QuerySemantic
  - UpdateSemantic
  - GetNodePose
  - CaptureImage （新增）
  - AnnotateSemantic （新增）
- [x] 编译验证通过

#### 1.3 拓扑图管理 [100%]
- [x] 创建 `sstg_map_manager` 包
- [x] 实现 TopologicalNode 数据类
- [x] 实现 TopologicalMap 核心类
  - NetworkX 图结构管理
  - 节点/边管理
  - 语义查询（房间类型/物品/组合）
  - 最短路径规划
  - JSON持久化
- [x] 实现 MapManagerNode (ROS2 Node)
  - 4个ROS2服务
  - 节点参数化配置
  - 自动加载/保存
- [x] 实现 MapWebUINode (FastAPI WebUI)
  - RESTful API (7个端点)
  - HTML可视化界面
  - 实时图表更新
- [x] 完整功能测试
  - 节点创建/删除
  - 语义标注
  - 各类查询
  - 序列化/反序列化
- [x] 编译构建成功
- [x] 编写模块指南 → `sstg_map_manager/MODULE_GUIDE.md`
- [x] 编写快速参考 → `SSTG_MapManager_QuickRef.md`


---

### ✅ 阶段二：感知能力（第3-4周）

#### 2.1 图像感知模块 [100%]
- [x] 创建 `sstg_perception` 包
- [x] 实现 CameraSubscriber (RGB-D 相机订阅)
- [x] 实现 PanoramaCapture (四方向全景采集)
- [x] 集成 Gemini 336L 相机启动配置
- [x] VLM 客户端实现 (qwen-vl-plus)
- [x] VLM 推理与结果解析
- [x] SemanticExtractor (JSON 解析、置信度过滤、多视图合并)
- [x] ROS2 Perception Node (两个服务)
- [x] 环境变量 API Key 配置支持
- [x] 纯 Python ament_python 包配置
- [x] 编译构建成功 ✓
- [x] 完整功能测试通过 (4/4 tests) ✓
- [x] 全功能验证通过 (7/7 checks) ✓
- [x] 编写模块指南 → `MODULE_GUIDE.md`
- [x] 编写快速参考 → `PERCEPTION_QuickRef.md`
- [x] **Bug Fix [2026-03-25]**: 修复 CaptureImage/AnnotateSemantic 服务消息缺失
  - 新增两个服务定义到 sstg_msgs
  - 修复 perception_node.py 中的导入方式
  - Node 成功初始化 ✓

#### 2.2 语义标注工具 [100%]
- [x] 实现标注指令处理 (capture_panorama, annotate_semantic 服务)
- [x] 自动/手动标注触发机制
- [x] 标注结果存储与序列化

---

## 📋 待完成任务

### ✅ 阶段三：理解和规划（第5-6周）

#### 3.1 自然语言理解 [100%]
- [x] 创建 `sstg_nlp_interface` 包
- [x] 实现多模态输入处理
  - 纯文本处理 ✓
  - 音频格式支持 ✓
  - 图片格式支持 ✓
  - 混合模态融合 ✓
- [x] 集成 VLM 模型（Qwen-VL-Plus）
- [x] 意图识别与解析
  - navigate_to（导航）✓
  - locate_object（物体定位）✓
  - query_info（查询信息）✓
  - ask_direction（询问方向）✓
- [x] 语义查询构建
- [x] 编译构建成功 ✓
- [x] 完整功能测试通过 (14/14 tests) ✓
- [x] 编写完整文档（MODULE_GUIDE.md + NLP_QuickRef.md）✓

#### 3.2 导航规划 [0%]
- [ ] 创建 `sstg_navigation_planner` 包
- [ ] 语义匹配算法
- [ ] 候选点生成与排序
- [ ] 导航计划生成

### ⏳ 阶段四：执行和集成（第7-8周）

#### 4.1 导航执行 [0%]
- [ ] 创建 `sstg_navigation_executor` 包
- [ ] Nav2 客户端集成
- [ ] 原地旋转控制
- [ ] 导航状态监控
- [ ] 反馈处理

#### 4.2 交互管理 [0%]
- [ ] 创建 `sstg_interaction_manager` 包
- [ ] 主流程控制
- [ ] 用户交互界面
- [ ] 对话管理
- [ ] 异常处理

### ⏳ 阶段五：优化和部署（第9-10周）

#### 5.1 性能优化 [0%]
- [ ] 系统性能测试
- [ ] VLM 响应时间优化
- [ ] 异步处理改进

#### 5.2 功能完善 [0%]
- [ ] 错误处理机制
- [ ] 恢复流程
- [ ] WebUI 功能增强
- [ ] 场景测试

---

## 📦 已完成包清单

| 包名 | 状态 | 功能描述 |
|------|------|--------|
| sstg_msgs | ✅ 完成 | 消息与服务定义（7个消息+7个服务） |
| sstg_map_manager | ✅ 完成 | 拓扑图管理与可视化 |
| sstg_perception | ✅ 完成 | 图像感知与VLM标注 |
| sstg_nlp_interface | ✅ 完成 | 多模态自然语言理解 |
| sstg_navigation_planner | ⏳ 待开发 | 导航规划 |
| sstg_navigation_executor | ⏳ 待开发 | 导航执行 |
| sstg_interaction_manager | ⏳ 待开发 | 交互管理 |

---

## 🔧 技术栈总结

### 已验证
- ✅ ROS2 Humble (Python rclpy)
- ✅ NetworkX 3.0+ (拓扑图)
- ✅ FastAPI + Uvicorn (WebUI)
- ✅ JSON 序列化

### 待集成
- ⏳ Aliyun DashScope API (阿里云百炼)
- ⏳ Qwen VLM (qwen-vl-plus)
- ⏳ Qwen-Omni-Flash (多模态)
- ⏳ Nav2 导航框架

---

## 📈 关键指标

- **代码行数**: ~1500 行 (sstg_map_manager)
- **测试覆盖**: 100% (核心功能)
- **构建成功率**: 100%
- **API文档**: 完整

---

## 🎯 关键决策

1. **语言选择**：Python (全项目)
2. **图库**：NetworkX (灵活、功能完整)
3. **Web框架**：FastAPI (高性能、自动文档)
4. **API方案**：阿里云百炼 (成本优化、模型丰富)
5. **地图格式**：JSON (易于扩展、版本控制友好)

---

## 📝 文档清单

| 文档 | 位置 | 完成度 |
|------|------|--------|
| 系统规划 | `/SSTG-Nav-Plan.md` | 100% |
| 快速参考 | `/SSTG_MapManager_QuickRef.md` | 100% |
| 模块指南 | `/sstg_map_manager/MODULE_GUIDE.md` | 100% |
| API文档 | FastAPI 自动生成 `http://localhost:8000/docs` | 100% |

---

## 🚀 下一步计划

**优先级排序**：

1. **高优先级**（本周）
   - 开发 sstg_perception 模块
   - 集成 VLM API 进行语义标注

2. **中优先级**（下周）
   - 开发 sstg_nlp_interface 模块
   - 开发 sstg_navigation_planner 模块

3. **后续**
   - 完成剩余模块
   - 系统集成与测试

---

## 💡 开发笔记

### 成功的做法
- ✓ 模块化设计使代码解耦
- ✓ 先完成消息定义确保接口一致
- ✓ NetworkX 选择合适，功能完整
- ✓ WebUI 增强了用户体验

### 可改进的地方
- 考虑添加 Docker 容器化支持
- 将 WebUI 前端独立为单独项目
- 添加更多单元测试和集成测试
- 性能分析和优化

---

**最后更新**：2026-03-24 23:00  
**下一次评审**：第三个模块完成时
