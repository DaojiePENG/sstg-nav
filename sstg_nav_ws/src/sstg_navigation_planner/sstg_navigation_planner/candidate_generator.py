"""
候选点生成器 - 生成和评分候选导航目标
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import math


@dataclass
class CandidatePoint:
    """候选点"""
    node_id: int
    node_name: str
    pose_x: float
    pose_y: float
    pose_z: float
    room_type: str
    relevance_score: float  # 0.0-1.0，综合评分
    semantic_score: float   # 语义匹配得分
    distance_score: float   # 距离得分
    accessibility_score: float  # 可达性得分
    match_reason: str
    evidence_score: float = 0.0  # 目标证据分（支持角度/显著性/可见性）
    best_view_angle: int = -1
    supporting_angles: List[int] = field(default_factory=list)
    distance_hint: str = 'unknown'  # near/mid/far/unknown，供交互层做远距离置信度降权

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'node_id': self.node_id,
            'node_name': self.node_name,
            'pose': {'x': self.pose_x, 'y': self.pose_y, 'z': self.pose_z},
            'room_type': self.room_type,
            'relevance_score': self.relevance_score,
            'semantic_score': self.semantic_score,
            'evidence_score': self.evidence_score,
            'distance_score': self.distance_score,
            'accessibility_score': self.accessibility_score,
            'match_reason': self.match_reason,
            'best_view_angle': self.best_view_angle,
            'supporting_angles': self.supporting_angles,
            'distance_hint': self.distance_hint,
        }


class CandidateGenerator:
    """
    候选点生成器
    
    功能：
    - 从匹配结果生成候选点
    - 计算多维度评分
    - 进行候选点排序和去重
    """
    
    def __init__(self, max_candidates: int = 10):
        """
        初始化生成器
        
        Args:
            max_candidates: 最多返回的候选点数
        """
        self.max_candidates = max_candidates
        self.logger: Optional[callable] = None
        
    def set_logger(self, logger_func):
        """设置日志函数"""
        self.logger = logger_func
    
    def _log(self, msg: str):
        """记录日志"""
        if self.logger:
            self.logger(f"[CandidateGenerator] {msg}")
    
    def generate_candidates(self,
                          match_results: List,
                          topological_nodes: Dict,
                          current_pose: Optional[Tuple] = None) -> List[CandidatePoint]:
        """
        生成候选点
        
        Args:
            match_results: 语义匹配结果列表
            topological_nodes: 拓扑图节点 {node_id: node_info}
            current_pose: 当前位置 (x, y, z)，可选
        
        Returns:
            候选点列表，按综合得分从高到低排序
        """
        candidates = []
        
        for match_result in match_results:
            node_id = match_result.node_id
            
            # 获取节点信息
            if node_id not in topological_nodes:
                self._log(f"警告: 节点 {node_id} 不在拓扑图中")
                continue
            
            node_info = topological_nodes[node_id]
            
            # 获取节点位置
            pose = node_info.get('pose', {})
            pose_x = pose.get('x', 0.0)
            pose_y = pose.get('y', 0.0)
            pose_z = pose.get('z', 0.0)
            
            # 计算多维度得分
            semantic_score = match_result.match_score
            search_meta = getattr(match_result, 'search_meta', {}) or {}
            evidence_score = self._calculate_evidence_score(search_meta, semantic_score)
            distance_score = self._calculate_distance_score(current_pose, (pose_x, pose_y, pose_z))
            accessibility_score = self._calculate_accessibility_score(node_info)
            
            # 计算综合得分 (加权平均)
            if search_meta:
                relevance_score = (
                    evidence_score * 0.7 +
                    distance_score * 0.2 +
                    accessibility_score * 0.1
                )
            else:
                relevance_score = (
                    semantic_score * 0.5 +
                    distance_score * 0.3 +
                    accessibility_score * 0.2
                )
            
            candidate = CandidatePoint(
                node_id=node_id,
                node_name=node_info.get('name', f'Node_{node_id}'),
                pose_x=pose_x,
                pose_y=pose_y,
                pose_z=pose_z,
                room_type=node_info.get('room_type', 'unknown'),
                relevance_score=relevance_score,
                semantic_score=semantic_score,
                evidence_score=evidence_score,
                distance_score=distance_score,
                accessibility_score=accessibility_score,
                match_reason=match_result.match_reason,
                best_view_angle=search_meta.get('best_view_angle', -1),
                supporting_angles=list(search_meta.get('supporting_angles', [])),
                distance_hint=(search_meta.get('distance_hint', 'unknown') or 'unknown').lower(),
            )
            
            candidates.append(candidate)
        
        # 去重 (按 node_id)
        unique_candidates = {}
        for candidate in candidates:
            if candidate.node_id not in unique_candidates:
                unique_candidates[candidate.node_id] = candidate
            else:
                # 保留得分更高的
                if candidate.relevance_score > unique_candidates[candidate.node_id].relevance_score:
                    unique_candidates[candidate.node_id] = candidate
        
        # 按综合得分从高到低排序
        sorted_candidates = sorted(
            unique_candidates.values(),
            key=lambda c: c.relevance_score,
            reverse=True
        )
        
        # 返回前 max_candidates 个
        result = sorted_candidates[:self.max_candidates]
        
        self._log(f"生成 {len(result)} 个候选点 (共 {len(candidates)} 个，{len(unique_candidates)} 个去重后)")
        
        return result

    def _calculate_evidence_score(self, search_meta: Dict, semantic_score: float) -> float:
        if not search_meta:
            return semantic_score
        best_view_score = float(search_meta.get('best_view_score', 0.0) or 0.0)
        best_confidence = float(search_meta.get('best_confidence', 0.0) or 0.0)
        salience = float(search_meta.get('salience', 0.0) or 0.0)
        visibility = (search_meta.get('visibility', 'unknown') or 'unknown').lower()
        distance_hint = (search_meta.get('distance_hint', 'unknown') or 'unknown').lower()
        supporting_angles = search_meta.get('supporting_angles', []) or []

        visibility_score = {'full': 1.0, 'partial': 0.7, 'occluded': 0.35}.get(visibility, 0.55)
        distance_score = {'near': 1.0, 'mid': 0.65, 'far': 0.3}.get(distance_hint, 0.55)
        angle_support = min(1.0, 0.25 * len(supporting_angles) + 0.15)

        return (
            semantic_score * 0.35 +
            best_view_score * 0.25 +
            best_confidence * 0.15 +
            salience * 0.10 +
            angle_support * 0.10 +
            ((visibility_score + distance_score) / 2.0) * 0.05
        )
    
    def _calculate_distance_score(self,
                                 current_pose: Optional[Tuple],
                                 target_pose: Tuple) -> float:
        """
        计算距离得分
        距离越近得分越高
        """
        if current_pose is None:
            return 0.5  # 中立得分
        
        dx = target_pose[0] - current_pose[0]
        dy = target_pose[1] - current_pose[1]
        distance = math.sqrt(dx**2 + dy**2)
        
        # 距离得分函数: exp(-distance/scale)
        # 0m: 1.0, 5m: 0.37, 10m: 0.14
        scale = 5.0
        distance_score = math.exp(-distance / scale)
        
        return distance_score
    
    def _calculate_accessibility_score(self, node_info: Dict) -> float:
        """
        计算可达性得分
        基于节点的连接数和通达性
        """
        # 可通行标志
        is_accessible = node_info.get('accessible', True)
        if not is_accessible:
            return 0.2  # 低可达性
        
        # 连接数越多，可达性越高
        connections = node_info.get('connections', [])
        num_connections = len(connections) if connections else 0
        
        # 根据连接数计算得分
        if num_connections >= 4:
            accessibility_score = 1.0
        elif num_connections >= 3:
            accessibility_score = 0.9
        elif num_connections >= 2:
            accessibility_score = 0.8
        elif num_connections >= 1:
            accessibility_score = 0.6
        else:
            accessibility_score = 0.4
        
        return accessibility_score
    
    def rank_candidates(self, candidates: List[CandidatePoint]) -> List[CandidatePoint]:
        """
        对候选点进行排序
        """
        return sorted(
            candidates,
            key=lambda c: c.relevance_score,
            reverse=True
        )
    
    def filter_by_threshold(self,
                           candidates: List[CandidatePoint],
                           min_score: float = 0.3) -> List[CandidatePoint]:
        """
        按得分阈值过滤候选点
        """
        return [c for c in candidates if c.relevance_score >= min_score]
    
    def get_top_candidate(self, candidates: List[CandidatePoint]) -> Optional[CandidatePoint]:
        """
        获取最优候选点
        """
        return candidates[0] if candidates else None
    
    def get_top_n_candidates(self,
                           candidates: List[CandidatePoint],
                           n: int = 3) -> List[CandidatePoint]:
        """
        获取前 N 个候选点
        """
        return candidates[:n]
