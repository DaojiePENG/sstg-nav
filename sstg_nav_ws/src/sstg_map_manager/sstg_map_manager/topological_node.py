"""
Topological Node data structure for SSTG Navigation System.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


ROOM_TYPE_CN_TO_EN = {
    '客厅': 'living_room',
    '大厅': 'living_room',
    '厨房': 'kitchen',
    '餐厅': 'dining_room',
    '卧室': 'bedroom',
    '卫生间': 'bathroom',
    '浴室': 'bathroom',
    '洗手间': 'bathroom',
    '书房': 'study',
    '办公室': 'office',
    '会议室': 'meeting_room',
    '办公室/会议室': 'office_meeting_room',
    '走廊': 'corridor',
    '玄关': 'entryway',
    '阳台': 'balcony',
    '储物间': 'storage_room',
    '车库': 'garage',
    '实验室': 'laboratory',
}

ROOM_TYPE_EN_TO_CN = {
    value: key for key, value in ROOM_TYPE_CN_TO_EN.items()
}
ROOM_TYPE_EN_TO_CN.update({
    'living_room': '客厅',
    'kitchen': '厨房',
    'dining_room': '餐厅',
    'bedroom': '卧室',
    'bathroom': '卫生间',
    'study': '书房',
    'office': '办公室',
    'meeting_room': '会议室',
    'office_meeting_room': '办公室/会议室',
})


def _contains_chinese(text: str) -> bool:
    return any('\u4e00' <= ch <= '\u9fff' for ch in (text or ''))


def _slugify_ascii(text: str) -> str:
    normalized = (text or '').strip().lower()
    normalized = re.sub(r'[/\\\s-]+', '_', normalized)
    normalized = re.sub(r'[^a-z0-9_]+', '', normalized)
    normalized = re.sub(r'_+', '_', normalized).strip('_')
    return normalized


def _dedupe_strings(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        text = (value or '').strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _infer_room_type_cn(room_type: str, room_type_cn: str = '') -> str:
    explicit = (room_type_cn or '').strip()
    if explicit:
        return explicit

    raw = (room_type or '').strip()
    if not raw:
        return ''

    if _contains_chinese(raw):
        return raw

    return ROOM_TYPE_EN_TO_CN.get(_slugify_ascii(raw), raw)


def _normalize_room_type(room_type: str, room_type_cn: str = '') -> str:
    raw = (room_type or '').strip()
    if raw and not _contains_chinese(raw):
        slug = _slugify_ascii(raw)
        return slug or raw

    cn_value = _infer_room_type_cn(room_type, room_type_cn)
    if cn_value in ROOM_TYPE_CN_TO_EN:
        return ROOM_TYPE_CN_TO_EN[cn_value]

    parts = re.split(r'[/\\、,，\s]+', cn_value)
    mapped_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        mapped = ROOM_TYPE_CN_TO_EN.get(part)
        if mapped:
            mapped_parts.extend(mapped.split('_'))

    if mapped_parts:
        return _slugify_ascii('_'.join(mapped_parts))

    return _slugify_ascii(raw) or _slugify_ascii(cn_value) or 'unknown'


@dataclass
class SemanticObject:
    """Semantic object information."""
    name: str
    position: str
    quantity: int = 1
    confidence: float = 0.0
    name_cn: str = ""
    distance_hint: str = "unknown"
    salience: float = 0.5
    visibility: str = "unknown"
    image_region: str = "mixed"

    def __post_init__(self):
        self.name = (self.name or self.name_cn or '').strip()
        self.name_cn = (self.name_cn or (self.name if _contains_chinese(self.name) else '')).strip()
        self.position = (self.position or '').strip()

    def to_dict(self):
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

    @staticmethod
    def from_dict(data: Dict):
        return SemanticObject(
            name=data.get('name', '') or data.get('name_cn', ''),
            name_cn=data.get('name_cn', ''),
            position=data.get('position', ''),
            quantity=data.get('quantity', 1),
            confidence=data.get('confidence', 0.0),
            distance_hint=data.get('distance_hint', 'unknown'),
            salience=data.get('salience', 0.5),
            visibility=data.get('visibility', 'unknown'),
            image_region=data.get('image_region', 'mixed'),
        )


@dataclass
class SemanticInfo:
    """Semantic information for a topological node."""
    room_type: str
    confidence: float = 0.0
    objects: List[SemanticObject] = field(default_factory=list)
    description: str = ""
    room_type_cn: str = ""
    aliases: List[str] = field(default_factory=list)
    semantic_tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.room_type_cn = _infer_room_type_cn(self.room_type, self.room_type_cn)
        self.room_type = _normalize_room_type(self.room_type, self.room_type_cn)

        alias_candidates = list(self.aliases)
        if self.room_type_cn:
            alias_candidates.append(self.room_type_cn)
        for obj in self.objects:
            alias_candidates.append(obj.name_cn or obj.name)
        self.aliases = _dedupe_strings(alias_candidates)

        tag_candidates = list(self.semantic_tags)
        if self.room_type:
            tag_candidates.append(self.room_type)
        if self.room_type_cn:
            tag_candidates.append(self.room_type_cn)
        for obj in self.objects:
            tag_candidates.append(obj.name)
            tag_candidates.append(obj.name_cn)
        self.semantic_tags = _dedupe_strings(tag_candidates)

    def to_dict(self):
        return {
            'room_type': self.room_type,
            'room_type_cn': self.room_type_cn,
            'aliases': self.aliases,
            'confidence': self.confidence,
            'objects': [obj.to_dict() for obj in self.objects],
            'semantic_tags': self.semantic_tags,
            'description': self.description,
        }

    @staticmethod
    def from_dict(data: Dict):
        objects = [
            SemanticObject.from_dict(obj) for obj in data.get('objects', [])
        ]
        return SemanticInfo(
            room_type=data.get('room_type', ''),
            room_type_cn=data.get('room_type_cn', ''),
            aliases=data.get('aliases', []),
            confidence=data.get('confidence', 0.0),
            objects=objects,
            semantic_tags=data.get('semantic_tags', []),
            description=data.get('description', ''),
        )


@dataclass
class Viewpoint:
    """Single directional view at a topological node."""
    angle: int                              # 0, 90, 180, 270
    image_path: str = ""                    # 相对路径 (相对于 map session root)
    depth_path: str = ""                    # 深度图相对路径
    semantic_info: Optional[SemanticInfo] = None  # 该方向独立的 VLM 分析
    capture_time: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'angle': self.angle,
            'image_path': self.image_path,
            'depth_path': self.depth_path,
            'semantic_info': self.semantic_info.to_dict() if self.semantic_info else None,
            'capture_time': self.capture_time,
        }

    @staticmethod
    def from_dict(data: Dict) -> 'Viewpoint':
        semantic_data = data.get('semantic_info')
        return Viewpoint(
            angle=data.get('angle', 0),
            image_path=data.get('image_path', ''),
            depth_path=data.get('depth_path', ''),
            semantic_info=SemanticInfo.from_dict(semantic_data) if semantic_data else None,
            capture_time=data.get('capture_time', 0.0),
        )


@dataclass
class TopologicalNode:
    """Represents a node in the topological map."""
    node_id: int
    x: float
    y: float
    theta: float
    viewpoints: Dict[int, Viewpoint] = field(default_factory=dict)  # angle → Viewpoint
    panorama_paths: Dict[str, str] = field(default_factory=dict)  # 保留，向后兼容
    semantic_info: Optional[SemanticInfo] = None  # 保留，聚合缓存
    search_objects: Dict[str, Dict] = field(default_factory=dict)  # 排序友好聚合字段
    name: str = ""
    created_time: float = 0.0
    last_updated: float = 0.0

    def __post_init__(self):
        if not self.name:
            if self.semantic_info and self.semantic_info.room_type_cn:
                self.name = self.semantic_info.room_type_cn
            else:
                self.name = f"拓扑点{self.node_id}"

    def aggregate_semantic(self, strategy: str = 'union') -> None:
        """Aggregate viewpoint-level SemanticInfo into node-level cache.

        R8 "自修正" 语义：每次调用都**全量重建** search_objects（先清空再按当前
        viewpoints 重建），不做跨次调用的 merge。这样 VLM 新观察会立即反映为
        节点级证据的权威源，planner/memory-recall 都读这份。
        """
        # 无论是否有 viewpoint，都先清空（"自修正"：上次写过的条目不能在本次残留）
        self.search_objects = {}

        infos = [
            vp.semantic_info for vp in self.viewpoints.values()
            if vp.semantic_info is not None
        ]
        if not infos:
            return

        # Room type / 描述 / 聚合语义信息
        if len(infos) == 1:
            self.semantic_info = infos[0]
            room_type_cn = infos[0].room_type_cn
        else:
            # Room type: majority vote
            room_types = [info.room_type for info in infos]
            room_type = max(set(room_types), key=room_types.count)

            # Room type CN: pick from winner
            room_type_cn = ''
            for info in infos:
                if info.room_type == room_type and info.room_type_cn:
                    room_type_cn = info.room_type_cn
                    break

            # Confidence: average
            avg_confidence = sum(info.confidence for info in infos) / len(infos)

            # Objects: union with highest confidence per object
            obj_dict: Dict[str, 'SemanticObject'] = {}
            for info in infos:
                for obj in info.objects:
                    key = (obj.name or obj.name_cn or '').lower()
                    if key and (key not in obj_dict or obj.confidence > obj_dict[key].confidence):
                        obj_dict[key] = obj

            # Description: join non-empty
            descriptions = [info.description for info in infos if info.description]
            description = ' | '.join(descriptions)

            self.semantic_info = SemanticInfo(
                room_type=room_type,
                room_type_cn=room_type_cn,
                confidence=avg_confidence,
                objects=list(obj_dict.values()),
                description=description,
            )

        # search_objects 全量重建（无论 1 还是 N 个 viewpoint）
        obj_angles: Dict[str, List[int]] = {}
        best_view_angle: Dict[str, int] = {}
        best_view_score: Dict[str, float] = {}
        best_meta: Dict[str, 'SemanticObject'] = {}
        best_confidence: Dict[str, float] = {}
        for angle, vp in self.viewpoints.items():
            info = vp.semantic_info
            if not info:
                continue
            for obj in info.objects:
                key = (obj.name_cn or obj.name or '').lower()
                if not key:
                    continue
                obj_angles.setdefault(key, [])
                if angle not in obj_angles[key]:
                    obj_angles[key].append(angle)
                # best_confidence: max across all viewpoints (R8: 让 planner 按此过滤)
                if key not in best_confidence or obj.confidence > best_confidence[key]:
                    best_confidence[key] = obj.confidence
                # best_view_* 仍用综合分挑最佳展示视角
                score = self._object_view_score(obj)
                if key not in best_view_score or score > best_view_score[key]:
                    best_view_score[key] = score
                    best_view_angle[key] = angle
                    best_meta[key] = obj

        for key, obj in best_meta.items():
            self.search_objects[key] = {
                'supporting_angles': sorted(obj_angles.get(key, [])),
                'best_view_angle': best_view_angle.get(key, -1),
                'best_view_score': round(best_view_score.get(key, 0.0), 4),
                'best_confidence': best_confidence.get(key, obj.confidence),
                'distance_hint': obj.distance_hint,
                'salience': obj.salience,
                'visibility': obj.visibility,
                'image_region': obj.image_region,
                'name': obj.name,
                'name_cn': obj.name_cn,
            }

        if len(infos) > 1:
            # 生成辨识度更高的节点名: 合并不同 room_type + 特征物体
            self._generate_distinctive_name(infos, room_type_cn)

    # 通用/低辨识度物体，不适合作为节点特征标签
    _GENERIC_OBJECTS = frozenset({
        '地板', '天花板', '墙壁', '天花板灯', '灯', '门', '地毯',
        '踢脚线', '窗户', '玻璃墙', '隔断墙', '走廊', '过道',
        'floor', 'ceiling', 'wall', 'door', 'carpet', 'window',
    })

    def _generate_distinctive_name(self, infos: list, room_type_cn: str) -> None:
        """Generate a distinctive node name from room types + landmark objects."""
        # 收集所有不同的 room_type_cn
        unique_rooms = []
        seen = set()
        for info in infos:
            r = info.room_type_cn
            if r and r not in seen:
                seen.add(r)
                unique_rooms.append(r)

        # 找最具辨识度的物体 (高置信度 + 非通用)
        landmark = ''
        best_conf = 0.0
        for info in infos:
            for obj in info.objects:
                cn = (obj.name_cn or '').strip()
                if not cn or cn in self._GENERIC_OBJECTS:
                    continue
                if obj.confidence > best_conf:
                    best_conf = obj.confidence
                    landmark = cn

        # 组合名字
        if len(unique_rooms) > 1:
            base = '/'.join(unique_rooms[:2])
        else:
            base = room_type_cn or '未知区域'

        if landmark and best_conf >= 0.85:
            self.name = f"{base}-{landmark}旁"
        else:
            self.name = base

    @staticmethod
    def _object_view_score(obj: 'SemanticObject') -> float:
        distance_score = {
            'near': 1.0,
            'mid': 0.65,
            'far': 0.3,
        }.get((obj.distance_hint or 'unknown').lower(), 0.55)
        visibility_score = {
            'full': 1.0,
            'partial': 0.7,
            'occluded': 0.35,
        }.get((obj.visibility or 'unknown').lower(), 0.55)
        return round(
            0.40 * obj.confidence +
            0.25 * obj.salience +
            0.20 * distance_score +
            0.15 * visibility_score,
            4,
        )

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.node_id,
            'name': self.name,
            'pose': {
                'x': self.x,
                'y': self.y,
                'theta': self.theta,
            },
            'viewpoints': {
                str(angle): vp.to_dict()
                for angle, vp in sorted(self.viewpoints.items())
            },
            'panorama_paths': self.panorama_paths,
            'semantic_info': self.semantic_info.to_dict() if self.semantic_info else None,
            'search_objects': self.search_objects,
            'created_time': self.created_time,
            'last_updated': self.last_updated,
        }

    @staticmethod
    def from_dict(data: Dict):
        """Create TopologicalNode from dictionary. Backward-compatible with old format."""
        pose = data.get('pose', {})
        semantic_data = data.get('semantic_info')
        semantic_info = SemanticInfo.from_dict(semantic_data) if semantic_data else None

        # Load viewpoints (new format)
        viewpoints: Dict[int, Viewpoint] = {}
        vp_data = data.get('viewpoints', {})
        if vp_data:
            for angle_str, vp_dict in vp_data.items():
                angle = int(angle_str)
                viewpoints[angle] = Viewpoint.from_dict(vp_dict)
        else:
            # Backward compat: build viewpoints from old panorama_paths
            panorama_paths = data.get('panorama_paths', {})
            for angle_key, img_path in panorama_paths.items():
                # angle_key is like '0°', '90°', etc.
                angle = int(angle_key.replace('°', ''))
                viewpoints[angle] = Viewpoint(
                    angle=angle,
                    image_path=img_path,
                    semantic_info=semantic_info,  # share node-level semantic
                )

        return TopologicalNode(
            node_id=data.get('id', -1),
            x=pose.get('x', 0.0),
            y=pose.get('y', 0.0),
            theta=pose.get('theta', 0.0),
            viewpoints=viewpoints,
            panorama_paths=data.get('panorama_paths', {}),
            semantic_info=semantic_info,
            search_objects=data.get('search_objects', {}),
            name=data.get('name', ''),
            created_time=data.get('created_time', 0.0),
            last_updated=data.get('last_updated', 0.0),
        )
