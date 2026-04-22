"""
Topological Node data structure for SSTG Navigation System.
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from geometry_msgs.msg import Pose, PoseStamped


@dataclass
class SemanticObject:
    """Semantic object information."""
    name: str
    position: str
    quantity: int = 1
    confidence: float = 0.0

    def to_dict(self):
        return asdict(self)


@dataclass
class SemanticInfo:
    """Semantic information for a topological node."""
    room_type: str
    confidence: float = 0.0
    objects: List[SemanticObject] = field(default_factory=list)
    description: str = ""

    def to_dict(self):
        return {
            'room_type': self.room_type,
            'confidence': self.confidence,
            'objects': [obj.to_dict() for obj in self.objects],
            'description': self.description,
        }


@dataclass
class TopologicalNode:
    """Represents a node in the topological map."""
    node_id: int
    x: float
    y: float
    theta: float
    panorama_paths: Dict[str, str] = field(default_factory=dict)  # {'0°': path, '90°': path, ...}
    semantic_info: Optional[SemanticInfo] = None
    created_time: float = 0.0
    last_updated: float = 0.0

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.node_id,
            'pose': {
                'x': self.x,
                'y': self.y,
                'theta': self.theta,
            },
            'panorama_paths': self.panorama_paths,
            'semantic_info': self.semantic_info.to_dict() if self.semantic_info else None,
            'created_time': self.created_time,
            'last_updated': self.last_updated,
        }

    @staticmethod
    def from_dict(data: Dict):
        """Create TopologicalNode from dictionary."""
        pose = data.get('pose', {})
        semantic_data = data.get('semantic_info')
        semantic_info = None
        
        if semantic_data:
            objects = [
                SemanticObject(**obj) for obj in semantic_data.get('objects', [])
            ]
            semantic_info = SemanticInfo(
                room_type=semantic_data.get('room_type', ''),
                confidence=semantic_data.get('confidence', 0.0),
                objects=objects,
                description=semantic_data.get('description', ''),
            )
        
        return TopologicalNode(
            node_id=data.get('id', -1),
            x=pose.get('x', 0.0),
            y=pose.get('y', 0.0),
            theta=pose.get('theta', 0.0),
            panorama_paths=data.get('panorama_paths', {}),
            semantic_info=semantic_info,
            created_time=data.get('created_time', 0.0),
            last_updated=data.get('last_updated', 0.0),
        )
