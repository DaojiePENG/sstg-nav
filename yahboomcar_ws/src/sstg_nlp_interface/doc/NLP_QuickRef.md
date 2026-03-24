# SSTG NLP Interface - 快速参考卡

## ⚡ 一行启动

```bash
export DASHSCOPE_API_KEY="your-key" && ros2 run sstg_nlp_interface nlp_node
```

## 🎯 常用 ROS2 命令

### 查看话题
```bash
ros2 topic list | grep nlp
ros2 topic echo /semantic_queries
```

### 查看服务
```bash
ros2 service list | grep nlp
```

### 调用服务
```bash
# 基本查询
ros2 service call /process_nlp_query sstg_msgs/srv/ProcessNLPQuery \
  '{text_input: "带我去客厅", context: ""}'

# 带上下文
ros2 service call /process_nlp_query sstg_msgs/srv/ProcessNLPQuery \
  '{text_input: "找椅子", context: "{\"current_room\": \"living_room\"}"}'
```

## 🐍 Python 使用示例

### 示例 1：文本处理
```python
from sstg_nlp_interface.text_processor import TextProcessor

processor = TextProcessor()
query = processor.process("怎么走到卧室")
print(f"Intent: {query.intent}")
print(f"Entities: {query.entities}")
```

### 示例 2：多模态处理
```python
from sstg_nlp_interface.multimodal_input import MultimodalInputHandler

handler = MultimodalInputHandler()
text_input = handler.process_text("这是什么")
image_input = handler.process_image("image.jpg")
mixed = handler.process_mixed(text="看看这是什么", image_path="image.jpg")
```

### 示例 3：完整流程
```python
from sstg_nlp_interface.text_processor import TextProcessor
from sstg_nlp_interface.query_builder import QueryBuilder, QueryValidator

# 处理文本
processor = TextProcessor()
text_query = processor.process("去客厅")

# 构建查询
builder = QueryBuilder()
query = builder.build_query(
    intent=text_query.intent,
    entities=text_query.entities,
    original_text="去客厅"
)

# 验证
validator = QueryValidator()
is_valid, errors = validator.validate(query)

if is_valid:
    print(query.to_json())
```

### 示例 4：VLM 理解
```python
from sstg_nlp_interface.vlm_client import VLMClientWithRetry

client = VLMClientWithRetry(
    api_key="sk-xxx",
    max_retries=3
)

response = client.understand_text("我想找一个椅子")
print(f"Intent: {response.intent}")
```

## 📁 目录结构

```
sstg_nlp_interface/
├── sstg_nlp_interface/
│   ├── __init__.py                 # 包初始化
│   ├── text_processor.py           # 文本处理（意图识别、实体提取）
│   ├── multimodal_input.py         # 多模态输入处理
│   ├── vlm_client.py               # VLM 客户端
│   ├── query_builder.py            # 查询构建和验证
│   └── nlp_node.py                 # ROS2 节点
├── test/
│   └── test_nlp_interface.py       # 完整的功能测试
├── doc/
│   ├── MODULE_GUIDE.md             # 完整使用指南
│   └── NLP_QuickRef.md             # 快速参考（本文件）
├── setup.py                         # Python 包配置
├── package.xml                      # ROS2 包定义
└── resource/sstg_nlp_interface     # 包索引文件
```

## 🔧 参数配置

### 通过环境变量
```bash
export DASHSCOPE_API_KEY="your-key"
export NLP_CONFIDENCE_THRESHOLD="0.3"
export NLP_MAX_RETRIES="3"
```

### 通过 ROS2 参数
```bash
ros2 run sstg_nlp_interface nlp_node \
  --ros-args -p api_key:="sk-xxx" \
  -p confidence_threshold:=0.5 \
  -p vlm_model:="qwen-vl-max"
```

## 🎨 意图类型速查

| 用户输入 | 识别意图 | 查询类型 |
|---------|---------|---------|
| "去客厅" | navigate_to | navigation_query |
| "找椅子" | locate_object | object_localization |
| "这是什么" | query_info | information_query |
| "怎么走到厨房" | ask_direction | direction_query |

## 📊 消息结构

### ProcessNLPQuery 服务

**请求：**
```
text_input: string     # 用户输入的文本
context: string        # 上下文信息（JSON 字符串，可为空）
```

**响应：**
```
success: bool          # 处理是否成功
query_json: string     # 结构化查询（JSON 字符串）
intent: string         # 识别的意图
confidence: float32    # 置信度 (0.0-1.0)
error_message: string  # 错误消息（如有）
```

**响应示例：**
```json
{
  "success": true,
  "query_json": "{\n  \"query_type\": \"navigation_query\",\n  \"intent\": \"navigate_to\",\n  \"entities\": [\"客厅\"],\n  \"target_locations\": [\"客厅\"],\n  \"target_objects\": [],\n  \"context\": {},\n  \"confidence\": 0.95,\n  \"original_text\": \"带我去客厅\"\n}",
  "intent": "navigate_to",
  "confidence": 0.95,
  "error_message": ""
}
```

### SemanticData （发布消息）
```
room_type: string              # 房间类型 (room/context/navigation)
confidence: float32            # 置信度
objects: SemanticObject[]      # 提取的物体列表
  - name: string               # 物体名称
  - position: string           # 物体位置
  - quantity: int32            # 物体数量
  - confidence: float32        # 物体置信度
description: string            # 查询描述
```

### ProcessNLPQuery 服务

**请求：**
```
text_input: string      # 用户输入文本
context: string        # 上下文（JSON）
```

**响应：**
```
success: bool          # 成功标志
query_json: string     # 查询 JSON
intent: string         # 意图
confidence: float32    # 置信度
error_message: string  # 错误信息
```

## 🧪 快速测试

```bash
# 运行所有测试
cd ~/yahboomcar_ws/src/sstg_nlp_interface
python3 test/test_nlp_interface.py

# 运行特定测试
python3 -m pytest test/test_nlp_interface.py::TestTextProcessor -v
```

## 🔍 调试技巧

### 1. 启用详细日志
```python
from sstg_nlp_interface.text_processor import TextProcessor

processor = TextProcessor()
processor.set_logger(print)  # 输出所有日志
```

### 2. 检查处理结果
```python
query = processor.process("找椅子")
print(f"Text: {query.text}")
print(f"Intent: {query.intent}")
print(f"Entities: {query.entities}")
print(f"Confidence: {query.confidence}")
```

### 3. JSON 验证
```python
import json

semantic_query = builder.build_query(...)
data = json.loads(semantic_query.to_json())
print(json.dumps(data, indent=2, ensure_ascii=False))
```

## 📝 常见问题

**Q: 如何添加新意图类型？**
A: 在 `TextProcessor.INTENT_PATTERNS` 中添加正则表达式模式

**Q: VLM 调用失败怎么办？**
A: 检查 API Key、网络连接、模型名称是否正确

**Q: 如何支持多语言？**
A: 设置 `language` 参数，更新 `TextProcessor.INTENT_PATTERNS`

**Q: 查询验证失败？**
A: 检查 intent 和 entities 是否为空，confidence 是否过低

## 🚀 性能优化

- 使用缓存减少 VLM 调用
- 批量处理多个查询
- 调整置信度阈值以平衡准确度和响应速度
- 使用异步处理提高吞吐量

## 🔗 相关文档

- 完整指南：`MODULE_GUIDE.md`
- 测试用例：`test/test_nlp_interface.py`
- sstg_msgs：消息定义文档

## ✅ 验证清单

- [ ] API Key 已配置
- [ ] 所有依赖已安装
- [ ] 包已成功构建
- [ ] 测试全部通过
- [ ] 节点可正常启动
- [ ] 服务可调用

