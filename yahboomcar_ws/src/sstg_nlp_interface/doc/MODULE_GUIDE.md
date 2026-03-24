# SSTG NLP Interface - 使用指南

## 📖 概述

SSTG NLP Interface 是一个多模态自然语言理解模块，能够处理文本、音频、图片和混合模态输入，通过集成大语言模型进行语义理解，并构建结构化的查询。

## 🚀 快速开始

### 方式1：ROS2 节点启动

```bash
# 设置环境变量
export DASHSCOPE_API_KEY="your-api-key"
source /opt/ros/humble/setup.bash

# 启动 NLP 节点
ros2 run sstg_nlp_interface nlp_node
```

### 方式2：直接 Python 使用

```python
from sstg_nlp_interface.text_processor import TextProcessor
from sstg_nlp_interface.multimodal_input import MultimodalInputHandler
from sstg_nlp_interface.vlm_client import VLMClientWithRetry
from sstg_nlp_interface.query_builder import QueryBuilder

# 初始化处理器
text_processor = TextProcessor()
query_builder = QueryBuilder()

# 处理文本
text = "请带我去客厅"
text_query = text_processor.process(text)

# 构建查询
semantic_query = query_builder.build_query(
    intent=text_query.intent,
    entities=text_query.entities,
    original_text=text,
    confidence=text_query.confidence
)

print(semantic_query.to_json())
```

### 方式3：多模态处理

```python
from sstg_nlp_interface.multimodal_input import MultimodalInputHandler

handler = MultimodalInputHandler()

# 处理文本
text_input = handler.process_text("找椅子")

# 处理混合模态
mixed_input = handler.process_mixed(
    text="这里有什么？",
    image_path="/path/to/image.jpg"
)

# 验证输入
if handler.validate_input(mixed_input):
    print("Input is valid")
```

## 🏗️ 架构

### 核心组件

#### 1. TextProcessor（文本处理器）
- 文本清理和规范化
- 意图识别（navigate_to, locate_object, query_info, ask_direction）
- 实体提取（位置、物体、动作、方向）
- 置信度计算

**使用示例：**
```python
processor = TextProcessor()
query = processor.process("怎么走到卧室")

print(f"Intent: {query.intent}")          # navigate_to
print(f"Entities: {query.entities}")      # ['卧室']
print(f"Confidence: {query.confidence}")  # 0.8
```

#### 2. MultimodalInputHandler（多模态处理器）
- 支持文本、音频、图片输入
- 文件验证和编码
- 上下文管理
- 混合模态融合

**支持的格式：**
- 音频：.wav, .mp3, .ogg, .flac, .m4a
- 图片：.jpg, .jpeg, .png, .bmp, .gif, .webp

**使用示例：**
```python
handler = MultimodalInputHandler()

# 文本
text_input = handler.process_text("找灯")

# 图片
image_input = handler.process_image("/path/to/room.jpg")

# 混合
mixed = handler.process_mixed(
    text="这是什么",
    image_path="/path/to/object.jpg"
)
```

#### 3. VLMClient（VLM 客户端）
- 调用多模态大模型（Qwen-VL-Plus 等）
- 文本理解和意图识别
- 图片分析和描述
- 带重试机制的 VLMClientWithRetry 版本

**使用示例：**
```python
from sstg_nlp_interface.vlm_client import VLMClientWithRetry

client = VLMClientWithRetry(
    api_key="sk-xxx",
    model="qwen-vl-plus",
    max_retries=3
)

# 理解文本
response = client.understand_text("找客厅的椅子")
print(f"Intent: {response.intent}")
print(f"Entities: {response.entities}")

# 分析图片
image_response = client.analyze_image(image_base64)
print(f"Description: {image_response.content}")
```

#### 4. QueryBuilder（查询构建器）
- 将 NLP 理解结果转换为可执行查询
- 位置和物体分类
- 上下文管理
- 查询合并和验证

**使用示例：**
```python
builder = QueryBuilder()

query = builder.build_query(
    intent='navigate_to',
    entities=['客厅'],
    original_text='去客厅',
    confidence=0.85
)

print(query.to_json())
# {
#   "query_type": "navigation_query",
#   "intent": "navigate_to",
#   "target_locations": ["客厅"],
#   ...
# }
```

#### 5. QueryValidator（查询验证器）
- 验证查询有效性
- 检查必要字段
- 置信度检查

**使用示例：**
```python
validator = QueryValidator()
is_valid, errors = validator.validate(query)

if not is_valid:
    print(f"Validation errors: {errors}")
```

## 🔧 ROS2 服务

### ProcessNLPQuery 服务

处理自然语言查询并返回结构化结果。

**请求：**
```
string text_input     # 用户输入的文本
string context        # 可选的上下文信息（JSON 字符串）
```

**响应字段：**
```
bool success          # 处理是否成功
string query_json     # 结构化查询（JSON 字符串）
string intent         # 识别的意图
float32 confidence    # 置信度（0.0-1.0）
string error_message  # 错误消息（如有）
```

**调用示例：**
```bash
# 基本查询
ros2 service call /process_nlp_query sstg_msgs/srv/ProcessNLPQuery \
  '{text_input: "带我去厨房", context: ""}'

# 返回结果
# response:
# sstg_msgs.srv.ProcessNLPQuery_Response(
#   success=True,
#   query_json='{...}',
#   intent='navigate_to',
#   confidence=0.95,
#   error_message=''
# )
```

**完整响应示例：**
```json
{
  "success": true,
  "query_json": "{\n  \"query_type\": \"navigation_query\",\n  \"intent\": \"navigate_to\",\n  \"entities\": [\"厨房\"],\n  \"target_locations\": [\"厨房\"],\n  \"target_objects\": [],\n  \"context\": {},\n  \"confidence\": 0.95,\n  \"original_text\": \"带我去厨房\"\n}",
  "intent": "navigate_to",
  "confidence": 0.95,
  "error_message": ""
}
```

### semantic_queries 话题

发布处理后的语义查询。

**消息类型：** `sstg_msgs/SemanticData`

## ⚙️ 配置参数

在 ROS2 启动时可以配置以下参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `api_key` | 从环境变量 | DashScope API Key |
| `api_base_url` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | API 基础 URL |
| `vlm_model` | `qwen-vl-plus` | 使用的 VLM 模型 |
| `confidence_threshold` | `0.3` | 置信度阈值 |
| `max_retries` | `3` | 最大重试次数 |
| `language` | `zh` | 语言代码 |

## 📊 意图类型

支持以下意图类型：

| 意图类型 | 查询类型 | 说明 | 示例 |
|---------|---------|------|------|
| `navigate_to` | navigation_query | 导航到某个位置 | "去客厅" |
| `locate_object` | object_localization | 定位某个物体 | "找椅子" |
| `query_info` | information_query | 查询信息 | "这是什么" |
| `ask_direction` | direction_query | 询问方向 | "怎么走到厨房" |

## 🔄 处理流程

```
用户输入
   ↓
TextProcessor (文本处理)
   ↓ (意图识别 + 实体提取)
   ↓
VLMClient (可选，进一步理解)
   ↓ (基于大模型的理解)
   ↓
QueryBuilder (构建查询)
   ↓ (转为结构化查询)
   ↓
QueryValidator (验证查询)
   ↓
语义查询发布
   ↓
下游模块处理
```

## 🧪 测试

运行模块测试：

```bash
cd ~/yahboomcar_ws/src/sstg_nlp_interface
python3 test/test_nlp_interface.py
```

预期结果：**14/14 tests PASSED** ✅

## 🐛 故障排除

### 1. API Key 未配置
**症状：** VLM 功能不可用
**解决：** `export DASHSCOPE_API_KEY="your-key"`

### 2. 意图识别准确度低
**症状：** 置信度低于阈值
**解决方案：**
- 确保输入文本清晰完整
- 调整 `confidence_threshold` 参数
- 检查语言设置是否正确

### 3. 图片分析失败
**症状：** 图片处理返回错误
**解决：**
- 确保图片文件存在且格式支持
- 检查文件权限
- 查看日志了解具体错误

## 📚 API 参考

详见 `sstg_nlp_interface` 包中各模块的 docstring。

## 🔗 依赖关系

- rclpy (ROS2 Python 库)
- requests (HTTP 客户端)
- sstg_msgs (SSTG 消息定义)

## 📝 开发者注意事项

### 添加新的意图类型

1. 在 `TextProcessor.INTENT_PATTERNS` 中添加模式
2. 在 `QueryBuilder.INTENT_TO_QUERY_TYPE` 中添加映射
3. 在测试中验证

### 集成新的 VLM 模型

1. 创建新的客户端类继承 `VLMClient`
2. 实现 `_call_api()` 方法
3. 实现响应解析方法
4. 更新配置和文档

