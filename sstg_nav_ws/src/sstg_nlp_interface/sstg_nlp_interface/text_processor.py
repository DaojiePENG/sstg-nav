"""
Text Input Processing - 文本输入处理模块
处理纯文本输入的解析和预处理
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import json
import logging


@dataclass
class TextQuery:
    """文本查询数据类"""
    text: str
    language: str = 'zh'  # 中文优先
    intent: Optional[str] = None
    entities: List[str] = None
    context: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    
    def __post_init__(self):
        if self.entities is None:
            self.entities = []


class TextProcessor:
    """
    文本处理器
    
    功能：
    - 文本标准化和清理
    - 意图识别
    - 实体提取
    - 语义理解
    """
    
    # 常见意图模式
    INTENT_PATTERNS = {
        'explore_new_home': [
            r'(探索|建图|探测|扫描)(这个|这|一下|)?(新家|家|房间|环境|房子|地方)',
            r'(帮我|请|开始)(探索|建图|扫描)',
            r'(explore|scan|map)\s*(this|the|my)?\s*(home|house|room|environment)',
        ],
        'navigate_to': [
            r'(去|前往|导航到|导航至|移动到|走到|来到|到达)([^。，；]*)',
            r'(带我去|我要去|请去|要去)([^。，；]*)',
            r'([^。，；]*)是在哪里|([^。，；]*)在哪\?',
        ],
        'locate_object': [
            r'(找|查找|搜索|寻找|看|看看)([^。，；]+)',
            r'([^。，；]*)在.*吗|([^。，；]*)呢\?',
            r'(有没有|有没|有没有看到)([^。，；]*)',
        ],
        'query_info': [
            r'(告诉我|告诉|说说|介绍|描述)([^。，；]*)',
            r'([^。，；]*)怎么样|([^。，；]*)如何\?',
            r'(这是|这个是|这个|这)([^。，；]*)吗',
        ],
        'ask_direction': [
            r'(哪个方向|往哪去|怎么走|如何到达)([^。，；]*)',
            r'(左|右|前|后|上|下)(面有|边有|方有)([^。，；]*)',
        ],
    }
    
    # 实体类型
    ENTITY_TYPES = {
        'LOCATION': [r'(房间|房|卧室|厨房|浴室|客厅|走廊|楼梯|办公室|会议室)'],
        'OBJECT': [r'(椅子|桌子|沙发|床|灯|植物|门|窗|书柜)'],
        'ACTION': [r'(放|拿|移动|推|拉|打开|关闭|转向)'],
        'DIRECTION': [r'(左|右|前|后|上|下|东|西|南|北)'],
    }
    
    def __init__(self, logger_func=None):
        """初始化处理器"""
        self.logger = logger_func if logger_func else print
        self.intent_cache = {}
        self.logger(f"✓ TextProcessor initialized")
    
    def process(self, text: str) -> TextQuery:
        """
        处理文本输入

        Args:
            text: 输入文本

        Returns:
            TextQuery: 处理后的查询对象
        """
        cleaned = self._clean_text(text)

        intent, confidence, groups = self._recognize_intent(cleaned)

        entities = self._extract_entities(cleaned)

        # 从 regex capture group 提取目标 (locate_object / navigate_to)
        if intent in ('locate_object', 'navigate_to') and groups:
            for g in groups:
                if g and g.strip() and len(g.strip()) > 0:
                    target = g.strip()
                    if target not in entities and len(target) <= 20:
                        entities.append(target)

        query = TextQuery(
            text=text,
            language='zh',
            intent=intent,
            entities=entities,
            confidence=confidence
        )

        return query
    
    def _clean_text(self, text: str) -> str:
        """
        清理文本
        
        Args:
            text: 原始文本
            
        Returns:
            str: 清理后的文本
        """
        # 移除多余空格
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 移除特殊字符（保留中文、英文、数字和基本符号）
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s.,;!?，。；！？]', '', text)
        
        return text.strip()
    
    def _recognize_intent(self, text: str) -> tuple:
        """
        识别用户意图

        Args:
            text: 清理后的文本

        Returns:
            tuple: (意图, 置信度, 匹配到的 capture groups)
        """
        best_intent = None
        best_confidence = 0.0
        best_groups = ()

        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                try:
                    match = re.search(pattern, text)
                    if match:
                        confidence = len(match.group(0)) / len(text)

                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_intent = intent
                            best_groups = match.groups()
                except re.error:
                    continue

        if best_intent is None:
            best_intent = 'query_info'
            best_confidence = 0.5

        return best_intent, best_confidence, best_groups
    
    def _extract_entities(self, text: str) -> List[str]:
        """
        从文本中提取实体
        
        Args:
            text: 清理后的文本
            
        Returns:
            List[str]: 提取的实体列表
        """
        entities = []
        
        for entity_type, patterns in self.ENTITY_TYPES.items():
            for pattern in patterns:
                try:
                    matches = re.findall(pattern, text)
                    if matches:
                        entities.extend(matches)
                except re.error:
                    continue
        
        return list(set(entities))  # 去重
    
    def build_query(self, text_query: TextQuery) -> Dict[str, Any]:
        """
        构建查询结构
        
        Args:
            text_query: 文本查询对象
            
        Returns:
            Dict: 查询结构
        """
        return {
            'modality': 'text',
            'original_input': text_query.text,
            'intent': text_query.intent,
            'entities': text_query.entities,
            'language': text_query.language,
            'confidence': text_query.confidence,
            'type': 'semantic_query'
        }
    
    def set_logger(self, logger_func):
        """设置日志函数"""
        self.logger = logger_func
