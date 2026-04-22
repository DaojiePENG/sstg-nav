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
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def understand_text(self, text: str, context: Optional[Dict] = None) -> VLMResponse:
        """
        理解纯文本
        
        Args:
            text: 输入文本
            context: 可选上下文
            
        Returns:
            VLMResponse: 理解结果
        """
        if not text:
            return VLMResponse(success=False, error_message="Empty text input")
        
        prompt = self._build_text_prompt(text, context)
        
        try:
            response = self._call_api(prompt, [])
            if response['success']:
                return self._parse_text_response(response['content'], text)
            else:
                return response
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
                return response
        except Exception as e:
            return VLMResponse(success=False, error_message=str(e))
    
    def _call_api(self, prompt: str, images: List[Dict] = None) -> Dict[str, Any]:
        """
        调用 API
        
        Args:
            prompt: 提示文本
            images: 图片列表
            
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
        content = [{'type': 'text', 'text': prompt}]
        
        for img in images:
            if 'image_base64' in img:
                content.append({
                    'type': 'image',
                    'image': f"data:image/jpeg;base64,{img['image_base64']}"
                })
        
        payload = {
            'model': self.model,
            'messages': [{'role': 'user', 'content': content}],
            'temperature': 0.7,
            'top_p': 0.9,
            'max_tokens': 1024,
        }
        
        try:
            response = self.session.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=payload,
                timeout=30
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
    
    def _build_text_prompt(self, text: str, context: Optional[Dict] = None) -> str:
        """构建文本理解提示"""
        prompt = f"""请分析以下用户输入，并提供结构化的理解结果。

用户输入：{text}

请以JSON格式返回以下信息：
{{
  "intent": "用户的主要意图（navigate_to/locate_object/query_info/ask_direction等）",
  "entities": ["提取的关键实体列表"],
  "confidence": 0.0-1.0的置信度,
  "clarification": "如果需要，请提出澄清问题"
}}

只返回JSON，不要其他文本。"""
        
        if context:
            prompt += f"\n\n上下文信息：{json.dumps(context, ensure_ascii=False)}"
        
        return prompt
    
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
                confidence=data.get('confidence', 0.7)
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


class VLMClientWithRetry(VLMClient):
    """
    带重试机制的 VLM 客户端
    """
    
    def __init__(self, api_key: str, base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                 model: str = 'qwen-vl-plus', max_retries: int = 3, logger_func=None):
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
    
    def understand_text(self, text: str, context: Optional[Dict] = None) -> VLMResponse:
        """带重试的文本理解"""
        for attempt in range(self.max_retries):
            try:
                return super().understand_text(text, context)
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
