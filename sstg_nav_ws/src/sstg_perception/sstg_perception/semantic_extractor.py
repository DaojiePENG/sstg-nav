"""
语义提取器 - 解析 VLM 响应并提取结构化的语义信息
"""

import json
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ConfidenceLevel(Enum):
    """置信度级别"""
    LOW = 0.5
    MEDIUM = 0.7
    HIGH = 0.85
    VERY_HIGH = 0.95


@dataclass
class SemanticObject:
    """语义对象"""
    name: str
    position: str
    quantity: int
    confidence: float
    name_cn: str = ""
    distance_hint: str = "unknown"
    salience: float = 0.5
    visibility: str = "unknown"
    image_region: str = "mixed"
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'name_cn': self.name_cn,
            'position': self.position,
            'quantity': self.quantity,
            'confidence': self.confidence,
            'distance_hint': self.distance_hint,
            'salience': self.salience,
            'visibility': self.visibility,
            'image_region': self.image_region,
        }


@dataclass
class SemanticInfo:
    """语义信息"""
    room_type: str
    objects: List[SemanticObject]
    description: str
    confidence: float
    
    def to_dict(self) -> Dict:
        return {
            'room_type': self.room_type,
            'objects': [obj.to_dict() for obj in self.objects],
            'description': self.description,
            'confidence': self.confidence
        }


class SemanticExtractor:
    """
    语义提取器
    
    功能：
    - 解析 VLM 的 JSON 响应
    - 验证和清理数据
    - 构建结构化的语义信息对象
    """
    
    def __init__(self, confidence_threshold: float = 0.5):
        """
        初始化语义提取器
        
        Args:
            confidence_threshold: 置信度阈值
        """
        self.confidence_threshold = confidence_threshold
        self.logger_func = print
    
    def set_logger(self, logger_func) -> None:
        """设置日志函数"""
        self.logger_func = logger_func
    
    def extract_semantic_info(self, vlm_response: str) -> Tuple[bool, SemanticInfo, Optional[str]]:
        """
        从 VLM 响应中提取语义信息
        
        Args:
            vlm_response: VLM 的响应文本
        
        Returns:
            (成功标志, SemanticInfo, 错误信息)
        """
        # 步骤 1: 提取 JSON
        json_data = self._extract_json(vlm_response)
        if json_data is None:
            return False, None, 'Failed to extract JSON from response'
        
        # 步骤 2: 验证必要字段
        required_fields = ['room_type', 'confidence', 'objects', 'description']
        missing = [f for f in required_fields if f not in json_data]
        if missing:
            return False, None, f'Missing required fields: {missing}'
        
        # 步骤 3: 清理和验证数据
        room_type = str(json_data.get('room_type', 'unknown')).strip()
        description = str(json_data.get('description', '')).strip()
        confidence = float(json_data.get('confidence', 0.5))
        
        # 确保置信度在 0-1 之间
        confidence = max(0.0, min(1.0, confidence))
        
        # 步骤 4: 处理对象列表
        objects = []
        objects_data = json_data.get('objects', [])
        if not isinstance(objects_data, list):
            return False, None, 'Objects field is not a list'
        
        for obj_data in objects_data:
            try:
                obj = self._parse_object(obj_data)
                
                # 过滤低置信度的对象
                if obj.confidence >= self.confidence_threshold:
                    objects.append(obj)
            except ValueError as e:
                self.logger_func(f'Warning: Failed to parse object: {e}')
                continue
        
        # 步骤 5: 构建 SemanticInfo
        semantic_info = SemanticInfo(
            room_type=room_type,
            objects=objects,
            description=description,
            confidence=confidence
        )
        
        return True, semantic_info, None
    
    def _extract_json(self, text: str) -> Optional[Dict]:
        """从文本中提取 JSON 对象"""
        # 方法 1: 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 方法 2: 查找 JSON 块 (包含代码块)
        patterns = [
            r'```json\s*(.*?)\s*```',
            r'```\s*(.*?)\s*```',
            r'\{[\s\S]*\}'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue
        
        self.logger_func(f'Warning: Could not extract JSON from response')
        return None
    
    def _parse_object(self, obj_data: Dict) -> SemanticObject:
        """解析单个对象"""
        if not isinstance(obj_data, dict):
            raise ValueError('Object data is not a dictionary')
        
        name = str(obj_data.get('name', obj_data.get('name_cn', 'unknown'))).strip()
        if not name:
            raise ValueError('Object name is empty')

        name_cn = str(obj_data.get('name_cn', '')).strip()
        position = str(obj_data.get('position', 'center')).strip().lower()
        quantity = int(obj_data.get('quantity', 1))
        confidence = float(obj_data.get('confidence', 0.5))
        distance_hint = str(obj_data.get('distance_hint', 'unknown')).strip().lower()
        salience = max(0.0, min(1.0, float(obj_data.get('salience', 0.5))))
        visibility = str(obj_data.get('visibility', 'unknown')).strip().lower()
        image_region = str(obj_data.get('image_region', 'mixed')).strip().lower()
        
        # 验证
        if quantity <= 0:
            raise ValueError('Quantity must be positive')
        
        confidence = max(0.0, min(1.0, confidence))
        
        return SemanticObject(
            name=name,
            name_cn=name_cn,
            position=position,
            quantity=quantity,
            confidence=confidence,
            distance_hint=distance_hint if distance_hint in {'near', 'mid', 'far'} else 'unknown',
            salience=salience,
            visibility=visibility if visibility in {'full', 'partial', 'occluded'} else 'unknown',
            image_region=image_region or 'mixed',
        )
    
    def merge_semantic_infos(self, infos: List[SemanticInfo],
                            strategy: str = 'average') -> SemanticInfo:
        """
        合并多个方向的语义信息
        
        Args:
            infos: 语义信息列表（来自不同角度）
            strategy: 合并策略 ('average', 'union', 'intersection')
        
        Returns:
            合并后的 SemanticInfo
        """
        if not infos:
            raise ValueError('Empty infos list')
        
        if len(infos) == 1:
            return infos[0]
        
        # 房间类型投票（选择最常见的）
        room_types = [info.room_type for info in infos]
        room_type = max(set(room_types), key=room_types.count)
        
        # 平均置信度
        avg_confidence = sum(info.confidence for info in infos) / len(infos)
        
        # 合并对象
        if strategy == 'union':
            merged_objects = self._merge_objects_union(infos)
        elif strategy == 'intersection':
            merged_objects = self._merge_objects_intersection(infos)
        else:  # average
            merged_objects = self._merge_objects_average(infos)
        
        # 合并描述
        descriptions = [info.description for info in infos if info.description]
        description = ' | '.join(descriptions) if descriptions else ''
        
        return SemanticInfo(
            room_type=room_type,
            objects=merged_objects,
            description=description,
            confidence=avg_confidence
        )
    
    def _merge_objects_union(self, infos: List[SemanticInfo]) -> List[SemanticObject]:
        """并集合并：保留所有出现的对象"""
        object_dict = {}
        
        for info in infos:
            for obj in info.objects:
                key = obj.name.lower()
                if key not in object_dict:
                    object_dict[key] = obj
                else:
                    # 更新信息（保留更高置信度的）
                    if obj.confidence > object_dict[key].confidence:
                        object_dict[key] = obj
        
        return list(object_dict.values())
    
    def _merge_objects_intersection(self, infos: List[SemanticInfo]) -> List[SemanticObject]:
        """交集合并：只保留所有视图中都出现的对象"""
        if not infos:
            return []
        
        # 获取所有视图中的对象名称集合
        all_object_names = [
            {obj.name.lower() for obj in info.objects}
            for info in infos
        ]
        
        # 求交集
        common_names = set.intersection(*all_object_names) if all_object_names else set()
        
        # 构建交集对象列表
        result = []
        for info in infos:
            for obj in info.objects:
                if obj.name.lower() in common_names:
                    result.append(obj)
                    common_names.discard(obj.name.lower())
        
        return result
    
    def _merge_objects_average(self, infos: List[SemanticInfo]) -> List[SemanticObject]:
        """平均合并：对象出现多次时，对置信度和数量取平均"""
        object_dict = {}
        object_count = {}
        
        for info in infos:
            for obj in info.objects:
                key = obj.name.lower()
                
                if key not in object_dict:
                    object_dict[key] = SemanticObject(
                        name=obj.name,
                        position=obj.position,
                        quantity=obj.quantity,
                        confidence=obj.confidence
                    )
                    object_count[key] = 1
                else:
                    # 平均置信度和数量
                    existing = object_dict[key]
                    existing.confidence = (existing.confidence + obj.confidence) / 2
                    existing.quantity = (existing.quantity + obj.quantity) // 2
                    object_count[key] += 1
        
        return list(object_dict.values())
