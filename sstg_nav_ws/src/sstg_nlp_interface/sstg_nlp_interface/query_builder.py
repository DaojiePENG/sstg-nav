"""
Query Builder - 语义查询构建器
将NLP理解结果转换为可执行的语义查询
"""

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
import json
import logging


@dataclass
class SemanticQuery:
    """语义查询数据类"""
    query_type: str  # 查询类型
    intent: str  # 用户意图
    entities: List[str]  # 提取的实体
    target_locations: Optional[List[str]] = None  # 目标位置
    target_objects: Optional[List[str]] = None  # 目标物体
    context: Optional[Dict[str, Any]] = None  # 上下文
    confidence: float = 0.0  # 置信度
    original_text: Optional[str] = None  # 原始输入文本
    multimodal_data: Optional[Dict[str, Any]] = None  # 多模态数据
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    def to_json(self) -> str:
        """转换为JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class QueryBuilder:
    """
    查询构建器
    
    功能：
    - 将 NLP 理解结果转换为可执行查询
    - 处理多模态信息融合
    - 上下文管理
    - 查询规范化
    """
    
    # 查询类型映射
    INTENT_TO_QUERY_TYPE = {
        'navigate_to': 'navigation_query',
        'locate_object': 'object_localization',
        'query_info': 'information_query',
        'ask_direction': 'direction_query',
        'explore_new_home': 'exploration_query',
    }
    
    def __init__(self, logger_func=None):
        """初始化查询构建器"""
        self.logger = logger_func if logger_func else print
        self.context_stack = []
        self.logger(f"✓ QueryBuilder initialized")
    
    def build_query(self,
                   intent: str,
                   entities: List[str],
                   original_text: str,
                   confidence: float = 0.0,
                   context: Optional[Dict[str, Any]] = None,
                   multimodal_data: Optional[Dict[str, Any]] = None) -> SemanticQuery:
        """
        构建语义查询
        
        Args:
            intent: 用户意图
            entities: 提取的实体
            original_text: 原始输入文本
            confidence: 置信度
            context: 上下文
            multimodal_data: 多模态数据
            
        Returns:
            SemanticQuery: 构建的查询
        """
        # 确定查询类型
        query_type = self.INTENT_TO_QUERY_TYPE.get(intent, 'general_query')
        
        # 分离位置和物体
        target_locations, target_objects = self._extract_location_and_objects(entities)
        
        # 创建查询
        query = SemanticQuery(
            query_type=query_type,
            intent=intent,
            entities=entities,
            target_locations=target_locations,
            target_objects=target_objects,
            context=context or {},
            confidence=confidence,
            original_text=original_text,
            multimodal_data=multimodal_data
        )
        
        return query
    
    def _extract_location_and_objects(self, entities: List[str]) -> tuple:
        """
        从实体列表中分离位置和物体
        
        Args:
            entities: 实体列表
            
        Returns:
            tuple: (位置列表, 物体列表)
        """
        location_keywords = {'房间', '房', '卧室', '厨房', '浴室', '客厅', '走廊', '楼梯', '办公室', '会议室'}
        object_keywords = {'椅子', '桌子', '沙发', '床', '灯', '植物', '门', '窗', '书柜'}
        
        locations = [e for e in entities if any(kw in e for kw in location_keywords)]
        objects = [e for e in entities if any(kw in e for kw in object_keywords)]
        
        return locations, objects
    
    def merge_queries(self, queries: List[SemanticQuery]) -> SemanticQuery:
        """
        合并多个查询
        
        Args:
            queries: 查询列表
            
        Returns:
            SemanticQuery: 合并后的查询
        """
        if not queries:
            raise ValueError("No queries to merge")
        
        if len(queries) == 1:
            return queries[0]
        
        # 合并所有实体
        all_entities = []
        all_locations = []
        all_objects = []
        avg_confidence = 0.0
        
        for q in queries:
            all_entities.extend(q.entities)
            if q.target_locations:
                all_locations.extend(q.target_locations)
            if q.target_objects:
                all_objects.extend(q.target_objects)
            avg_confidence += q.confidence
        
        avg_confidence /= len(queries)
        
        # 去重
        all_entities = list(set(all_entities))
        all_locations = list(set(all_locations))
        all_objects = list(set(all_objects))
        
        # 使用第一个查询作为基础
        merged = SemanticQuery(
            query_type=queries[0].query_type,
            intent=queries[0].intent,
            entities=all_entities,
            target_locations=all_locations if all_locations else None,
            target_objects=all_objects if all_objects else None,
            context=queries[0].context,
            confidence=avg_confidence,
            original_text='; '.join([q.original_text for q in queries if q.original_text])
        )
        
        return merged
    
    def push_context(self, context: Dict[str, Any]):
        """推送上下文"""
        self.context_stack.append(context)
    
    def pop_context(self) -> Optional[Dict[str, Any]]:
        """弹出上下文"""
        if self.context_stack:
            return self.context_stack.pop()
        return None
    
    def get_current_context(self) -> Dict[str, Any]:
        """获取当前上下文"""
        if self.context_stack:
            return self.context_stack[-1]
        return {}
    
    def set_logger(self, logger_func):
        """设置日志函数"""
        self.logger = logger_func


class QueryValidator:
    """查询验证器"""
    
    def __init__(self, logger_func=None):
        """初始化验证器"""
        self.logger = logger_func if logger_func else print
        self.logger(f"✓ QueryValidator initialized")
    
    def validate(self, query: SemanticQuery) -> tuple:
        """
        验证查询有效性
        
        Args:
            query: 要验证的查询
            
        Returns:
            tuple: (是否有效, 错误消息列表)
        """
        errors = []
        
        # 检查必要字段
        if not query.intent:
            errors.append("Missing intent")

        # 纯对话/查询/探索意图不需要实体
        if query.intent not in ('explore_new_home', 'chat', 'query_info', 'conversation', 'describe_scene', 'stop_task'):
            if not query.entities and not query.target_locations and not query.target_objects:
                errors.append("No entities or targets specified")
        
        # 检查置信度
        if query.confidence < 0.3:
            self.logger(f"Warning: Low confidence query (conf={query.confidence})")
        
        return len(errors) == 0, errors
    
    def set_logger(self, logger_func):
        """设置日志函数"""
        self.logger = logger_func
