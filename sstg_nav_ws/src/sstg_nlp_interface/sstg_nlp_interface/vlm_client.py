"""
VLM Client - 视觉语言模型客户端
集成Qwen-Omni-Flash/Qwen-VL等大模型进行多模态理解
"""

import os
import json
import time
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class VLMResponse:
    """VLM 响应数据类"""
    success: bool
    content: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None
    intent: Optional[str] = None
    entities: Optional[List[str]] = None
    confidence: float = 0.0
    response: Optional[str] = None  # 小拓的自然语言回复
    error_message: Optional[str] = None


class VLMClient:
    """
    VLM 客户端 - 基础版本
    
    功能：
    - 调用多模态大模型
    - 文本理解和意图识别
    - 图片分析
    - 音频转录
    """
    
    def __init__(self, api_key: str, base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                 model: str = 'qwen-vl-plus', logger_func=None):
        """
        初始化 VLM 客户端
        
        Args:
            api_key: API Key
            base_url: API 基础 URL
            model: 模型名称
            logger_func: 日志函数
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.logger = logger_func if logger_func else print
        self.session = self._create_session()
        self.logger(f"✓ VLMClient initialized with model: {model}")
    
    def _create_session(self) -> requests.Session:
        """创建带重试机制的会话"""
        session = requests.Session()
        retry_strategy = Retry(
            total=1,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def understand_text(self, text: str, context: Optional[Dict] = None,
                        map_context: str = '',
                        chat_history: Optional[List[Dict[str, str]]] = None,
                        sender_name: str = '') -> VLMResponse:
        """
        理解纯文本（标准多轮对话格式）

        Args:
            text: 输入文本
            context: 可选上下文
            map_context: 地图环境摘要
            chat_history: 标准多轮历史 [{"role": "user"/"assistant", "content": "..."}]
            sender_name: 发送者昵称

        Returns:
            VLMResponse: 理解结果
        """
        if not text:
            return VLMResponse(success=False, error_message="Empty text input")

        messages = self._build_messages(text, context, map_context, chat_history, sender_name)

        try:
            response = self._call_api_messages(messages)
            if response['success']:
                return self._parse_text_response(response['content'], text)
            else:
                return VLMResponse(success=False, error_message=response.get('error', 'API call failed'))
        except Exception as e:
            return VLMResponse(success=False, error_message=str(e))
    
    def analyze_image(self, image_base64: str, question: str = '') -> VLMResponse:
        """
        分析图片
        
        Args:
            image_base64: 图片 base64 编码
            question: 关于图片的问题
            
        Returns:
            VLMResponse: 分析结果
        """
        if not image_base64:
            return VLMResponse(success=False, error_message="Empty image input")
        
        prompt = question if question else "请分析这张图片中的内容，特别是其中的位置、物体和语义信息。"
        
        try:
            response = self._call_api(prompt, [{'image_base64': image_base64}])
            if response['success']:
                return self._parse_image_response(response['content'])
            else:
                return VLMResponse(success=False, error_message=response.get('error', 'API call failed'))
        except Exception as e:
            return VLMResponse(success=False, error_message=str(e))
    
    def _needs_array_content(self) -> bool:
        """判断当前模型是否需要 user content 为数组格式（qwen-vl 系列）"""
        model_lower = self.model.lower()
        return 'qwen-vl' in model_lower or 'qwen-omni' in model_lower

    def _call_api_messages(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        调用 API（标准多轮 messages 格式）

        Args:
            messages: 完整的 messages 数组 [{"role": ..., "content": ...}, ...]

        Returns:
            Dict: API 响应
        """
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        # qwen-vl 系列模型要求 user content 为数组格式，其他模型保持字符串
        use_array = self._needs_array_content()
        formatted = []
        for msg in messages:
            if use_array and msg['role'] == 'user' and isinstance(msg['content'], str):
                formatted.append({
                    'role': 'user',
                    'content': [{'type': 'text', 'text': msg['content']}]
                })
            else:
                formatted.append(msg)

        payload = {
            'model': self.model,
            'messages': formatted,
            'temperature': 0.3,
            'top_p': 0.8,
            'max_tokens': 1024,
        }

        try:
            response = self.session.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=payload,
                timeout=15
            )
            response.raise_for_status()
            result = response.json()

            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content']
                return {'success': True, 'content': content}
            else:
                return {'success': False, 'error': 'Invalid API response'}

        except requests.exceptions.RequestException as e:
            return {'success': False, 'error': str(e)}

    def _call_api(self, prompt: str, images: List[Dict] = None,
                  system_prompt: str = '') -> Dict[str, Any]:
        """
        调用 API

        Args:
            prompt: 提示文本
            images: 图片列表
            system_prompt: 系统提示（角色定义）

        Returns:
            Dict: API 响应
        """
        if images is None:
            images = []

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        # 构建消息
        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})

        content = [{'type': 'text', 'text': prompt}]
        for img in images:
            if 'image_base64' in img:
                content.append({
                    'type': 'image',
                    'image': f"data:image/jpeg;base64,{img['image_base64']}"
                })
        messages.append({'role': 'user', 'content': content})
        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': 0.3,
            'top_p': 0.8,
            'max_tokens': 1024,
        }
        
        try:
            response = self.session.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=payload,
                timeout=15
            )
            response.raise_for_status()
            result = response.json()
            
            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content']
                return {'success': True, 'content': content}
            else:
                return {'success': False, 'error': 'Invalid API response'}
        
        except requests.exceptions.RequestException as e:
            return {'success': False, 'error': str(e)}
    
    def _build_messages(self, text: str, context: Optional[Dict] = None,
                         map_context: str = '',
                         chat_history: Optional[List[Dict[str, str]]] = None,
                         sender_name: str = '') -> List[Dict[str, Any]]:
        """构建标准多轮 messages 数组"""
        system_prompt = """你是小拓，SSTG-Nav 空间语义拓扑导航机器人的智能助手。
性格：友好、热心、像一个熟悉这个空间的好伙伴。
能力：带用户去指定位置、帮忙找东西、探索新环境、描述周围场景、回答环境问题。
说话风格：亲切自然，适当用语气词，简洁但有温度。不要用markdown格式。
当用户有名字时，回复时可以自然地称呼对方。"""

        if map_context:
            system_prompt += f"\n\n当前环境地图：\n{map_context}"

        messages = [{'role': 'system', 'content': system_prompt}]

        # 注入真正的多轮对话历史
        if chat_history:
            for msg in chat_history:
                messages.append({'role': msg['role'], 'content': msg['content']})

        # 当前用户输入 + 指令
        sender_label = f"{sender_name} 对你说" if sender_name else "用户输入"
        user_prompt = f"""{sender_label}：{text}

请以JSON格式返回：
{{
  "intent": "用户意图，从以下选择：navigate_to（去某个具体地点）/locate_object（去寻找某个具体物体）/explore_new_home（探索新环境）/describe_scene（看看周围、描述场景、拍照看看）/stop_task（停止、取消、别走了、不要去了）/conversation（闲聊、问候、提问、询问信息等所有对话类）",
  "entities": ["提取的关键实体列表。只能是具体的地点名或物体名（如'客厅'、'书包'），绝不能是动词、句子片段或抽象概念。conversation/describe_scene/stop_task 意图的 entities 必须为空数组 []"],
  "confidence": 0.0-1.0的置信度,
  "response": "用小拓的语气友好回复用户（必填）"
}}

意图判断规则（严格按优先级判断）：
1. 用户要求停止、取消、别走了、不要去了、算了 → stop_task
2. 用户要求看看周围、描述场景、拍照看看、前面有什么 → describe_scene
3. 用户明确要求"去XX"、"带我去XX"、"到XX" → navigate_to
4. 用户明确要求"帮我找XX"、"去找XX"、"搜索XX" → locate_object
5. 用户说"探索"、"看看新家"、"建图" → explore_new_home
6. 其他所有情况（打招呼、闲聊、提问、询问信息）→ conversation

关键区分规则：
- navigate_to 和 locate_object 必须是用户明确要求机器人"去做"某事（祈使句），如"去客厅"、"帮我找书包"
- 所有疑问句（"...吗？"、"...哪个？"、"知道...吗"、"有没有..."）一律归为 conversation
- 关于机器人自身状态的提问（"你知道...吗"、"你在哪"、"你能...吗"）一律归为 conversation
- "有XX吗"、"XX在哪里"、"知道哪个地图吗" 这类提问归为 conversation
- 只有用户明确用祈使语气要求你去寻找时才用 locate_object

重要：不要被对话历史中的意图影响当前判断。每条消息独立判断意图。

只返回JSON，不要其他文本。"""

        if context:
            user_prompt += f"\n\n额外上下文：{json.dumps(context, ensure_ascii=False)}"

        messages.append({'role': 'user', 'content': user_prompt})
        return messages
    
    def _build_image_prompt(self, question: str) -> str:
        """构建图片分析提示"""
        prompt = f"""请分析这张图片。用户的问题是：{question}

请以JSON格式返回：
{{
  "description": "对图片内容的详细描述",
  "locations": ["检测到的位置列表"],
  "objects": ["检测到的物体列表"],
  "semantic_info": "语义理解和含义"
}}

只返回JSON，不要其他文本。"""
        
        return prompt
    
    def _parse_text_response(self, response_text: str, original_text: str) -> VLMResponse:
        """解析文本理解响应"""
        try:
            # 尝试从 response_text 中提取 JSON
            json_str = response_text
            
            # 处理 Markdown 代码块
            if '```' in json_str:
                json_str = json_str.split('```')[1]
                if json_str.startswith('json'):
                    json_str = json_str[4:]
            
            data = json.loads(json_str.strip())
            
            return VLMResponse(
                success=True,
                content=response_text,
                structured_data=data,
                intent=data.get('intent'),
                entities=data.get('entities', []),
                confidence=data.get('confidence', 0.7),
                response=data.get('response', ''),
            )
        except json.JSONDecodeError:
            return VLMResponse(
                success=True,
                content=response_text,
                confidence=0.5
            )
    
    def _parse_image_response(self, response_text: str) -> VLMResponse:
        """解析图片分析响应"""
        try:
            json_str = response_text
            
            if '```' in json_str:
                json_str = json_str.split('```')[1]
                if json_str.startswith('json'):
                    json_str = json_str[4:]
            
            data = json.loads(json_str.strip())
            
            return VLMResponse(
                success=True,
                content=response_text,
                structured_data=data,
                entities=data.get('objects', []),
                confidence=0.8
            )
        except json.JSONDecodeError:
            return VLMResponse(
                success=True,
                content=response_text,
                confidence=0.5
            )
    
    def set_logger(self, logger_func):
        """设置日志函数"""
        self.logger = logger_func

    # ── 流式 API ──────────────────────────────────────

    def _call_api_messages_stream(self, messages: List[Dict[str, Any]]):
        """
        流式调用 API，逐 token yield。

        Yields:
            str: 每次产出一个 token 片段
        """
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        use_array = self._needs_array_content()
        formatted = []
        for msg in messages:
            if use_array and msg['role'] == 'user' and isinstance(msg['content'], str):
                formatted.append({
                    'role': 'user',
                    'content': [{'type': 'text', 'text': msg['content']}]
                })
            else:
                formatted.append(msg)

        payload = {
            'model': self.model,
            'messages': formatted,
            'temperature': 0.3,
            'top_p': 0.8,
            'max_tokens': 1024,
            'stream': True,
        }

        response = self.session.post(
            f'{self.base_url}/chat/completions',
            headers=headers,
            json=payload,
            timeout=30,
            stream=True,
        )
        response.raise_for_status()

        for line in response.iter_lines():
            if not line:
                continue
            decoded = line.decode('utf-8')
            if not decoded.startswith('data: '):
                continue
            data = decoded[6:]
            if data.strip() == '[DONE]':
                break
            try:
                chunk = json.loads(data)
                token = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
                if token:
                    yield token
            except (json.JSONDecodeError, IndexError, KeyError):
                continue

    def understand_text_stream(self, text: str, context=None,
                                map_context: str = '',
                                chat_history=None,
                                sender_name: str = ''):
        """
        流式文本理解 — 逐 token yield，用于纯聊天场景。

        Yields:
            str: 每个 token 片段
        """
        messages = self._build_messages(text, context, map_context, chat_history, sender_name)
        yield from self._call_api_messages_stream(messages)


class VLMClientWithRetry(VLMClient):
    """
    带重试机制的 VLM 客户端
    """
    
    def __init__(self, api_key: str, base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                 model: str = 'qwen-vl-plus', max_retries: int = 2, logger_func=None):
        """
        初始化带重试的 VLM 客户端
        
        Args:
            api_key: API Key
            base_url: API 基础 URL
            model: 模型名称
            max_retries: 最大重试次数
            logger_func: 日志函数
        """
        super().__init__(api_key, base_url, model, logger_func)
        self.max_retries = max_retries
        self.logger(f"✓ VLMClientWithRetry initialized (max_retries: {max_retries})")
    
    def understand_text(self, text: str, context: Optional[Dict] = None,
                        map_context: str = '',
                        chat_history: Optional[List[Dict[str, str]]] = None,
                        sender_name: str = '') -> VLMResponse:
        """带重试的文本理解"""
        for attempt in range(self.max_retries):
            try:
                return super().understand_text(text, context, map_context, chat_history, sender_name)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    self.logger(f"Retry attempt {attempt + 1}/{self.max_retries} after {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    return VLMResponse(
                        success=False,
                        error_message=f"Failed after {self.max_retries} retries: {str(e)}"
                    )
        
        return VLMResponse(success=False, error_message="Unknown error")
    
    def analyze_image(self, image_base64: str, question: str = '') -> VLMResponse:
        """带重试的图片分析"""
        for attempt in range(self.max_retries):
            try:
                return super().analyze_image(image_base64, question)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    self.logger(f"Retry attempt {attempt + 1}/{self.max_retries} after {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    return VLMResponse(
                        success=False,
                        error_message=f"Failed after {self.max_retries} retries: {str(e)}"
                    )
        
        return VLMResponse(success=False, error_message="Unknown error")
