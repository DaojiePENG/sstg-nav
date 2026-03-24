"""
Multimodal Input Handler - 多模态输入处理
处理文本、音频、图片和混合模态输入
"""

import os
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, Union
from enum import Enum
import base64
import logging


class InputModality(Enum):
    """输入模态类型"""
    TEXT = 'text'
    AUDIO = 'audio'
    IMAGE = 'image'
    MIXED = 'mixed'


@dataclass
class MultimodalInput:
    """多模态输入数据类"""
    modality: InputModality
    text: Optional[str] = None
    audio_path: Optional[str] = None
    image_path: Optional[str] = None
    audio_base64: Optional[str] = None
    image_base64: Optional[str] = None
    language: str = 'zh'
    context: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    
    def to_dict(self):
        """转换为字典"""
        d = asdict(self)
        d['modality'] = self.modality.value
        return d


class MultimodalInputHandler:
    """
    多模态输入处理器
    
    功能：
    - 接收多种格式的输入（文本、音频、图片）
    - 统一处理和验证
    - 音频转录 (可选)
    - 图片识别 (可选)
    - 混合模态融合
    """
    
    # 支持的音频格式
    AUDIO_FORMATS = {'.wav', '.mp3', '.ogg', '.flac', '.m4a'}
    # 支持的图片格式
    IMAGE_FORMATS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}
    
    def __init__(self, logger_func=None):
        """初始化处理器"""
        self.logger = logger_func if logger_func else print
        self.logger(f"✓ MultimodalInputHandler initialized")
    
    def process_text(self, text: str, context: Optional[Dict] = None) -> MultimodalInput:
        """
        处理纯文本输入
        
        Args:
            text: 输入文本
            context: 可选上下文
            
        Returns:
            MultimodalInput: 多模态输入对象
        """
        return MultimodalInput(
            modality=InputModality.TEXT,
            text=text,
            language='zh',
            context=context,
            confidence=1.0
        )
    
    def process_audio(self, audio_path: str, language: str = 'zh') -> MultimodalInput:
        """
        处理音频输入
        
        Args:
            audio_path: 音频文件路径
            language: 语言代码
            
        Returns:
            MultimodalInput: 多模态输入对象
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        # 验证文件格式
        _, ext = os.path.splitext(audio_path)
        if ext.lower() not in self.AUDIO_FORMATS:
            raise ValueError(f"Unsupported audio format: {ext}")
        
        # 编码为 base64
        audio_b64 = self._encode_file_to_base64(audio_path)
        
        return MultimodalInput(
            modality=InputModality.AUDIO,
            audio_path=audio_path,
            audio_base64=audio_b64,
            language=language,
            confidence=0.8
        )
    
    def process_image(self, image_path: str) -> MultimodalInput:
        """
        处理图片输入
        
        Args:
            image_path: 图片文件路径
            
        Returns:
            MultimodalInput: 多模态输入对象
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        # 验证文件格式
        _, ext = os.path.splitext(image_path)
        if ext.lower() not in self.IMAGE_FORMATS:
            raise ValueError(f"Unsupported image format: {ext}")
        
        # 编码为 base64
        image_b64 = self._encode_file_to_base64(image_path)
        
        return MultimodalInput(
            modality=InputModality.IMAGE,
            image_path=image_path,
            image_base64=image_b64,
            confidence=0.85
        )
    
    def process_mixed(self, 
                     text: Optional[str] = None,
                     audio_path: Optional[str] = None,
                     image_path: Optional[str] = None,
                     language: str = 'zh') -> MultimodalInput:
        """
        处理混合模态输入
        
        Args:
            text: 可选文本
            audio_path: 可选音频路径
            image_path: 可选图片路径
            language: 语言代码
            
        Returns:
            MultimodalInput: 多模态输入对象
        """
        input_data = MultimodalInput(
            modality=InputModality.MIXED,
            text=text,
            language=language,
            confidence=0.75
        )
        
        # 处理音频
        if audio_path:
            if os.path.exists(audio_path):
                input_data.audio_base64 = self._encode_file_to_base64(audio_path)
                input_data.audio_path = audio_path
        
        # 处理图片
        if image_path:
            if os.path.exists(image_path):
                input_data.image_base64 = self._encode_file_to_base64(image_path)
                input_data.image_path = image_path
        
        return input_data
    
    def _encode_file_to_base64(self, file_path: str) -> str:
        """
        将文件编码为 base64
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: Base64 编码字符串
        """
        with open(file_path, 'rb') as f:
            data = f.read()
            return base64.b64encode(data).decode('utf-8')
    
    def validate_input(self, input_data: MultimodalInput) -> bool:
        """
        验证输入数据
        
        Args:
            input_data: 多模态输入对象
            
        Returns:
            bool: 是否有效
        """
        if input_data.modality == InputModality.TEXT:
            return bool(input_data.text)
        elif input_data.modality == InputModality.AUDIO:
            return bool(input_data.audio_base64)
        elif input_data.modality == InputModality.IMAGE:
            return bool(input_data.image_base64)
        elif input_data.modality == InputModality.MIXED:
            return bool(input_data.text or input_data.audio_base64 or input_data.image_base64)
        
        return False
    
    def merge_context(self, input_data: MultimodalInput, 
                     context: Dict[str, Any]) -> MultimodalInput:
        """
        将上下文信息合并到输入数据
        
        Args:
            input_data: 多模态输入对象
            context: 上下文字典
            
        Returns:
            MultimodalInput: 更新后的对象
        """
        if input_data.context is None:
            input_data.context = {}
        
        input_data.context.update(context)
        return input_data
    
    def set_logger(self, logger_func):
        """设置日志函数"""
        self.logger = logger_func
