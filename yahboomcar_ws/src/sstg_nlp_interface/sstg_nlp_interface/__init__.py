"""
SSTG NLP Interface Package
多模态自然语言理解模块
"""

from .text_processor import TextProcessor, TextQuery
from .multimodal_input import MultimodalInputHandler, MultimodalInput, InputModality
from .vlm_client import VLMClient, VLMClientWithRetry, VLMResponse
from .query_builder import QueryBuilder, QueryValidator, SemanticQuery
from .nlp_node import NLPNode, main

__all__ = [
    'TextProcessor',
    'TextQuery',
    'MultimodalInputHandler',
    'MultimodalInput',
    'InputModality',
    'VLMClient',
    'VLMClientWithRetry',
    'VLMResponse',
    'QueryBuilder',
    'QueryValidator',
    'SemanticQuery',
    'NLPNode',
    'main',
]

__version__ = '0.1.0'
