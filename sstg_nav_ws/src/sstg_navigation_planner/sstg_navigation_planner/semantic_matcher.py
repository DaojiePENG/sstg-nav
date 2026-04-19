"""
语义匹配器 - 将自然语言查询与拓扑图节点进行语义匹配
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import logging
import re

from sstg_navigation_planner.target_normalizer import normalize_search_target


# R8: 搜索候选纳入阈值 —— 节点级 search_objects[key].best_confidence 必须 ≥ 此值
# 才会被 planner 作为 locate_object 候选。低于此值的证据视为模糊记忆，不发车。
CANDIDATE_MIN_CONF = 0.6


@dataclass
class MatchResult:
    """匹配结果"""
    node_id: int
    node_name: str
    room_type: str
    semantic_tags: List[str]
    match_score: float  # 0.0-1.0
    match_reason: str
    search_meta: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'node_id': self.node_id,
            'node_name': self.node_name,
            'room_type': self.room_type,
            'semantic_tags': self.semantic_tags,
            'match_score': self.match_score,
            'match_reason': self.match_reason,
            'search_meta': self.search_meta,
        }


class SemanticMatcher:
    """
    语义匹配器
    
    功能：
    - 意图到节点类型的映射
    - 实体与语义标签的匹配
    - 置信度评分
    """
    
    # 意图到房间类型的映射
    INTENT_TO_ROOM_MAPPING = {
        'navigate_to': ['room', 'location', 'area', 'living_room', 'kitchen', 'bedroom', 'bathroom', 'study', 'dining_room'],
        'locate_object': ['room', 'furniture', 'equipment'],
        'query_info': ['room', 'context'],
        'ask_direction': ['room', 'location']
    }
    
    # 房间类型别名
    ROOM_TYPE_ALIASES = {
        '客厅': ['living_room', 'lounge', '客間'],
        '卧室': ['bedroom', '寝室', 'sleeping_room'],
        '厨房': ['kitchen', '台所'],
        '卫生间': ['bathroom', 'restroom', '浴室'],
        '书房': ['study', 'study_room', '書斎'],
        '餐厅': ['dining_room', 'dinning_room', '食堂'],
        '走廊': ['corridor', 'hallway', '通路'],
    }
    
    # 物体类型映射
    OBJECT_TYPE_MAPPING = {
        '椅子': ['chair', 'seat', '座椅', 'office chair'],
        '桌子': ['table', 'desk', '机桌'],
        '床': ['bed', 'couch', 'sofa'],
        '门': ['door', 'gate'],
        '窗': ['window', 'window_frame'],
        '灯': ['lamp', 'light', 'bulb', 'lighting', 'ceiling_light'],
        '沙发': ['sofa', 'couch', 'settee'],
        '书包': ['backpack', 'bag', 'schoolbag', '背包', '双肩包', '挎包'],
        '背包': ['backpack', 'bag', 'schoolbag', '书包', '双肩包', '挎包'],
        '包': ['backpack', 'bag', 'handbag', '书包', '背包', '手提包'],
        '书': ['book', 'books'],
        '电脑': ['computer', 'computer_monitor', 'monitor', 'laptop'],
        '冰箱': ['refrigerator', 'fridge'],
        '垃圾桶': ['trash_can', 'trash bin', 'dustbin'],
        '柜子': ['cabinet', 'file cabinet', 'cupboard'],
        '灭火器': ['fire_extinguisher', 'fire_extinguisher_cabinet'],
        '水瓶': ['water_bottle', 'water_bottles', 'bottle'],
        '耳机': ['headphones', 'earphone'],
        '玩具': ['toy', 'toys'],
        '地毯': ['carpet', 'rug'],
        '人': ['person', 'people'],
    }
    
    def __init__(self):
        """初始化匹配器"""
        self.logger: Optional[callable] = None
        
    def set_logger(self, logger_func):
        """设置日志函数"""
        self.logger = logger_func
    
    def _log(self, msg: str):
        """记录日志"""
        if self.logger:
            self.logger(f"[SemanticMatcher] {msg}")
    
    def match_query_to_nodes(self,
                            intent: str,
                            entities: List[str],
                            confidence: float,
                            topological_nodes: Dict) -> List[MatchResult]:
        """
        将查询匹配到拓扑图节点
        
        Args:
            intent: 识别的意图 (navigate_to, locate_object, etc.)
            entities: 提取的实体列表
            confidence: 查询置信度
            topological_nodes: 拓扑图节点字典 {node_id: node_info}
        
        Returns:
            匹配结果列表，按得分从高到低排序
        """
        matches = []
        
        # 根据意图和实体生成匹配候选
        candidates = self._generate_candidates(intent, entities, topological_nodes)
        
        # 为每个候选计算匹配得分
        for node_id, node_info, entity in candidates:
            score = self._calculate_match_score(
                intent=intent,
                entity=entity,
                node_info=node_info,
                query_confidence=confidence
            )
            search_meta = self._extract_search_meta(intent, entity, node_info)
            
            # 构建匹配结果
            match = MatchResult(
                node_id=node_id,
                node_name=node_info.get('name', f'Node_{node_id}'),
                room_type=node_info.get('room_type', 'unknown'),
                semantic_tags=node_info.get('semantic_tags', []),
                match_score=score,
                match_reason=self._generate_match_reason(
                    intent, entity, node_info, score
                ),
                search_meta=search_meta,
            )
            
            matches.append(match)
        
        # 按得分从高到低排序
        matches.sort(key=lambda m: m.match_score, reverse=True)
        
        self._log(f"匹配完成: 找到 {len(matches)} 个候选项")
        
        return matches
    
    def _generate_candidates(self,
                            intent: str,
                            entities: List[str],
                            topological_nodes: Dict) -> List[Tuple]:
        """
        生成匹配候选
        
        Returns:
            候选列表 [(node_id, node_info, entity), ...]
        """
        candidates = []

        for entity in entities:
            # 通配符 / 空串 → 全节点兜底（IM 在精确匹配失败后会用 entities=['*'] 再发一次请求，
            # 必须保证这里不会再返空——否则任务会直接结束"当前地图中没有可以搜索的位置"）
            if entity in ('*', ''):
                for node_id, node_info in topological_nodes.items():
                    candidates.append((node_id, node_info, '*'))
                continue

            # 按房间类型匹配
            if intent == 'navigate_to':
                room_candidates = self._match_room_type(entity, topological_nodes)
                for node_id, node_info in room_candidates:
                    candidates.append((node_id, node_info, entity))

            # 按物体匹配
            elif intent == 'locate_object':
                object_candidates = self._match_object(entity, topological_nodes)
                for node_id, node_info in object_candidates:
                    candidates.append((node_id, node_info, entity))

            # 按语义标签匹配
            else:
                semantic_candidates = self._match_semantic_tags(entity, topological_nodes)
                for node_id, node_info in semantic_candidates:
                    candidates.append((node_id, node_info, entity))

        # 如果没有实体匹配，返回所有相关节点
        if not candidates:
            room_types = self.INTENT_TO_ROOM_MAPPING.get(intent, ['room'])
            for node_id, node_info in topological_nodes.items():
                if node_info.get('room_type') in room_types:
                    candidates.append((node_id, node_info, 'default'))
            # 最终兜底：连房间类型都匹配不上（例如地图里全是 corridor/office 这类不在白名单的类型），
            # 仍然把所有可达节点作为候选返回，让上层有机会"去每个节点转一圈找找看"。
            if not candidates:
                for node_id, node_info in topological_nodes.items():
                    candidates.append((node_id, node_info, 'default'))

        return candidates
    
    def _match_room_type(self, entity: str, topological_nodes: Dict) -> List[Tuple]:
        """
        匹配房间类型
        
        Returns:
            [(node_id, node_info), ...]
        """
        matches = []
        
        for node_id, node_info in topological_nodes.items():
            room_type = node_info.get('room_type', '').lower()
            node_name = node_info.get('name', '').lower()
            entity_lower = entity.lower()
            
            # 完全匹配或别名匹配
            if self._is_room_match(entity_lower, room_type, node_name):
                matches.append((node_id, node_info))
        
        return matches
    
    def _match_object(self, entity: str, topological_nodes: Dict) -> List[Tuple]:
        """
        匹配物体类型 - 查找包含该物体的房间

        R8: 只读 search_objects 权威源，且按 best_confidence ≥ CANDIDATE_MIN_CONF 过滤。
        移除 semantic_tags 子串兜底——那会把历史片段 tag 当做"有证据"带来幽灵候选。

        Returns:
            [(node_id, node_info), ...]
        """
        matches = []
        entity_norm = normalize_search_target(entity) or entity
        entity_lower = entity_norm.lower()

        for node_id, node_info in topological_nodes.items():
            search_objects = node_info.get('search_objects', {}) or {}
            if not search_objects:
                continue
            for key, meta in search_objects.items():
                try:
                    best_conf = float(meta.get('best_confidence', 0.0) or 0.0)
                except (TypeError, ValueError):
                    best_conf = 0.0
                if best_conf < CANDIDATE_MIN_CONF:
                    continue
                names = [
                    key,
                    meta.get('name', ''),
                    meta.get('name_cn', ''),
                ]
                if any(self._is_object_match(entity_lower, (name or '').lower())
                       for name in names if name):
                    matches.append((node_id, node_info))
                    break

        return matches
    
    def _match_semantic_tags(self, entity: str, topological_nodes: Dict) -> List[Tuple]:
        """
        按语义标签匹配
        
        Returns:
            [(node_id, node_info), ...]
        """
        matches = []
        entity_lower = entity.lower()
        
        for node_id, node_info in topological_nodes.items():
            semantic_tags = node_info.get('semantic_tags', [])
            
            # 检查是否有匹配的语义标签
            for tag in semantic_tags:
                if self._string_similarity(entity_lower, tag.lower()) > 0.6:
                    matches.append((node_id, node_info))
                    break
        
        return matches
    
    def _is_room_match(self, entity: str, room_type: str, node_name: str) -> bool:
        """
        检查房间是否匹配
        """
        # 直接匹配
        if entity in room_type or entity in node_name:
            return True
        
        # 别名匹配
        for chinese_name, aliases in self.ROOM_TYPE_ALIASES.items():
            if entity == chinese_name.lower():
                if room_type in [a.lower() for a in aliases]:
                    return True
            
            for alias in aliases:
                if entity == alias.lower() or entity in alias.lower():
                    if room_type == chinese_name.lower():
                        return True
        
        return False
    
    def _is_object_match(self, entity: str, tag: str) -> bool:
        """检查物体是否匹配"""
        return self._object_match_score(entity, tag) > 0.0

    def _object_match_score(self, entity: str, tag: str) -> float:
        """
        物体匹配得分: 1.0=精确/别名, 0.3=子串
        """
        # 直接匹配
        if entity == tag:
            return 1.0

        # 别名匹配 (中文→英文)
        for chinese_name, aliases in self.OBJECT_TYPE_MAPPING.items():
            if entity == chinese_name.lower():
                if tag in [a.lower() for a in aliases]:
                    return 1.0
            for alias in aliases:
                if entity == alias.lower():
                    if tag == chinese_name.lower():
                        return 1.0

        # 子串包含匹配: 低分，避免 "书" 匹配 "book" 和 "书包" 匹配 "backpack" 同分
        if entity in tag or tag in entity:
            return 0.3

        return 0.0

    def _string_similarity(self, s1: str, s2: str) -> float:
        """
        计算字符串相似度 (0.0-1.0)
        使用简单的编辑距离算法
        """
        if not s1 or not s2:
            return 1.0 if s1 == s2 else 0.0
        
        # 计算最长公共子序列长度
        longer = s1 if len(s1) > len(s2) else s2
        shorter = s2 if len(s1) > len(s2) else s1
        
        if len(longer) == 0:
            return 1.0
        
        match_length = self._lcs_length(longer, shorter)
        return match_length / len(longer)
    
    def _lcs_length(self, s1: str, s2: str) -> int:
        """最长公共子序列长度"""
        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if s1[i-1] == s2[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])
        
        return dp[m][n]
    
    def _calculate_match_score(self,
                              intent: str,
                              entity: str,
                              node_info: Dict,
                              query_confidence: float) -> float:
        """
        计算匹配得分

        得分计算：
        1. 物体直接匹配 (50%) — locate_object 时最重要
        2. 基础相似度得分 (20%)
        3. 类型匹配得分 (15%)
        4. 置信度得分 (15%)
        """
        # 通配符/兜底实体：给一个 min_match_score 以上的基线分，避免被过滤掉；排序改由距离分决定
        if entity in ('*', 'default', ''):
            return 0.5
        entity_norm = normalize_search_target(entity) or entity
        entity_lower = entity_norm.lower()

        # 物体直接匹配: 检查 semantic_tags 里是否有匹配的物体
        object_score = 0.0
        search_meta = {}
        if intent == 'locate_object':
            search_objects = node_info.get('search_objects', {})
            best_obj_score = 0.0
            best_evidence = 0.0
            best_meta = None

            for key, meta in search_objects.items():
                names = [key, meta.get('name', ''), meta.get('name_cn', '')]
                match_strength = max(
                    self._object_match_score(entity_lower, (name or '').lower())
                    for name in names if name
                ) if any(names) else 0.0
                if match_strength <= 0.0:
                    continue

                supporting_angles = meta.get('supporting_angles', []) or []
                angle_support = min(1.0, 0.25 * len(supporting_angles) + 0.15)
                best_conf = float(meta.get('best_confidence', 0.0) or 0.0)
                distance_hint = (meta.get('distance_hint', 'unknown') or 'unknown').lower()
                salience = float(meta.get('salience', 0.0) or 0.0)
                visibility = (meta.get('visibility', 'unknown') or 'unknown').lower()

                distance_score = {'near': 1.0, 'mid': 0.65, 'far': 0.3}.get(distance_hint, 0.55)
                visibility_score = {'full': 1.0, 'partial': 0.7, 'occluded': 0.35}.get(visibility, 0.55)

                evidence_score = (
                    0.35 * match_strength +
                    0.20 * angle_support +
                    0.20 * best_conf +
                    0.15 * salience +
                    0.10 * ((distance_score + visibility_score) / 2.0)
                )
                if evidence_score > best_evidence:
                    best_evidence = evidence_score
                    best_obj_score = match_strength
                    best_meta = meta

            if best_meta is None:
                semantic_tags = node_info.get('semantic_tags', [])
                for tag in semantic_tags:
                    s = self._object_match_score(entity_lower, tag.lower())
                    if s > best_obj_score:
                        best_obj_score = s
                object_score = best_obj_score * 0.5
            else:
                search_meta = {
                    'supporting_angles': best_meta.get('supporting_angles', []),
                    'best_view_angle': best_meta.get('best_view_angle', -1),
                    'best_view_score': best_meta.get('best_view_score', 0.0),
                    'distance_hint': best_meta.get('distance_hint', 'unknown'),
                    'visibility': best_meta.get('visibility', 'unknown'),
                    'salience': best_meta.get('salience', 0.0),
                    'best_confidence': best_meta.get('best_confidence', 0.0),
                }
                object_score = min(0.7, best_evidence)

        # 基础相似度得分 (entity vs node name)
        similarity = self._string_similarity(
            entity_lower,
            node_info.get('name', '').lower()
        )
        similarity_score = similarity * 0.2

        # 类型匹配得分
        type_match = 0.15 if self._check_type_match(intent, node_info) else 0.0

        # 置信度得分
        confidence_score = query_confidence * 0.15

        if intent == 'locate_object' and search_meta:
            similarity_score *= 0.5
            type_match *= 0.5
            confidence_score *= 0.5

        total_score = object_score + similarity_score + type_match + confidence_score

        return min(1.0, total_score)
    
    def _check_type_match(self, intent: str, node_info: Dict) -> bool:
        """检查节点类型是否与意图匹配"""
        room_types = self.INTENT_TO_ROOM_MAPPING.get(intent, [])
        node_room_type = node_info.get('room_type', '').lower()
        
        return any(rt.lower() in node_room_type or node_room_type in rt.lower()
                  for rt in room_types)

    def _extract_search_meta(self, intent: str, entity: str, node_info: Dict) -> Dict:
        if intent != 'locate_object':
            return {}
        search_objects = node_info.get('search_objects', {})
        entity_lower = entity.lower()
        best_meta = {}
        best_score = 0.0
        for key, meta in search_objects.items():
            names = [key, meta.get('name', ''), meta.get('name_cn', '')]
            match_strength = max(
                self._object_match_score(entity_lower, (name or '').lower())
                for name in names if name
            ) if any(names) else 0.0
            if match_strength <= 0.0:
                continue
            evidence = float(meta.get('best_view_score', 0.0) or 0.0) + 0.1 * len(meta.get('supporting_angles', []))
            if evidence > best_score:
                best_score = evidence
                best_meta = meta
        return dict(best_meta) if best_meta else {}
    
    def _generate_match_reason(self,
                              intent: str,
                              entity: str,
                              node_info: Dict,
                              score: float) -> str:
        """
        生成匹配原因说明
        """
        reasons = []
        
        node_name = node_info.get('name', 'Unknown')
        node_type = node_info.get('room_type', 'unknown')
        
        if score > 0.8:
            reasons.append(f"高相似度匹配: '{entity}' → '{node_name}'")
        elif score > 0.6:
            reasons.append(f"中等相似度: '{entity}' 与 '{node_name}' 部分匹配")
        else:
            reasons.append(f"低相似度匹配: '{entity}' 与 '{node_name}'")

        search_objects = node_info.get('search_objects', {})
        if intent == 'locate_object' and search_objects:
            for key, meta in search_objects.items():
                names = [key, meta.get('name', ''), meta.get('name_cn', '')]
                if any(self._is_object_match(entity.lower(), (name or '').lower()) for name in names if name):
                    angles = meta.get('supporting_angles', [])
                    reasons.append(
                        f"视角支持: {len(angles)}个方向, best_angle={meta.get('best_view_angle', -1)}"
                    )
                    reasons.append(
                        f"证据: score={meta.get('best_view_score', 0.0):.2f}, dist={meta.get('distance_hint', 'unknown')}"
                    )
                    break

        if self._check_type_match(intent, node_info):
            reasons.append(f"类型匹配: {intent} → {node_type}")

        return "; ".join(reasons)
