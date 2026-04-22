#!/usr/bin/env python3
"""
migrate_and_analyze.py — 迁移/重建 session 节点数据，并用 VLM 逐张分析每张图片。

默认用法: python3 migrate_and_analyze.py
增强重建:
  python3 migrate_and_analyze.py --session-name lab_20260402 --reuse-existing-captured
"""
import base64
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import argparse

# ── 配置 ──
API_KEY = 'sk-942e8661f10f492280744a26fe7b953b'
MODEL = 'qwen-vl-plus'
API_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'

SRC_CAPTURED = '/home/daojie/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/captured_nodes'
SRC_REPORT = '/home/daojie/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/maps/manual_capture_report.json'
DST_MAP_ROOT = '/home/daojie/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_map_manager/maps'
SESSION_NAME = 'lab_20260402'

ANGLES = [0, 90, 180, 270]

VLM_PROMPT = """请分析这张室内导航图片，只返回严格 JSON，不要 markdown。
{
  "room_type": "房间类型英文(如 office, corridor, kitchen)",
  "room_type_cn": "房间类型中文",
  "confidence": 0.0到1.0,
  "objects": [
    {
      "name": "英文名",
      "name_cn": "中文名",
      "position": "位置描述",
      "quantity": 数量,
      "confidence": 0.0到1.0,
      "distance_hint": "near|mid|far",
      "salience": 0.0到1.0,
      "visibility": "full|partial|occluded",
      "image_region": "center|left|right|top|bottom|mixed"
    }
  ],
  "description": "场景一句话描述（中文）"
}
要求：
1. 如果某个物体很靠近镜头、位于前景、很显眼，请提高 salience，并优先标为 near。
2. 如果物体在远处、尽头、背景，请标为 far。
3. salience 表示该物体作为后续搜索目标时的显著程度，范围 0.0~1.0。
4. visibility 表示完整可见程度。
5. 只返回 JSON。"""

TARGET_SYNONYMS = {
    '书包': ['书包', '背包', '包', 'backpack', 'schoolbag', 'bag'],
}
DISTANCE_SCORE = {'near': 1.0, 'mid': 0.65, 'far': 0.3, 'unknown': 0.55}
VISIBILITY_SCORE = {'full': 1.0, 'partial': 0.7, 'occluded': 0.35, 'unknown': 0.55}


def vlm_analyze(image_path: str) -> dict | None:
    """调用 qwen-vl-plus 分析单张图片，返回解析后的 dict。"""
    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": VLM_PROMPT},
        ]}],
        "max_tokens": 1024,
    }

    req = urllib.request.Request(API_URL,
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'})

    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read())
            content = result['choices'][0]['message']['content']
            parsed = _parse_json(content)
            return _normalize_semantic(parsed) if parsed else None
        except Exception as e:
            print(f'    [retry {attempt+1}] {e}')
            time.sleep(2)
    return None


def _parse_json(text: str) -> dict | None:
    """从 VLM 响应中提取 JSON。"""
    # 去掉 markdown 代码块
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        # 尝试找 { ... }
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    print(f'    [WARN] Failed to parse JSON: {text[:200]}')
    return None


def _normalize_semantic(sem: dict) -> dict:
    objects = []
    for obj in sem.get('objects', []):
        objects.append({
            'name': obj.get('name', ''),
            'name_cn': obj.get('name_cn', ''),
            'position': obj.get('position', ''),
            'quantity': int(obj.get('quantity', 1) or 1),
            'confidence': _clamp(obj.get('confidence', 0.5)),
            'distance_hint': _normalize_distance(obj.get('distance_hint', 'unknown')),
            'salience': _clamp(obj.get('salience', 0.5)),
            'visibility': _normalize_visibility(obj.get('visibility', 'unknown')),
            'image_region': str(obj.get('image_region', 'mixed') or 'mixed'),
        })
    return {
        'room_type': sem.get('room_type', 'unknown'),
        'room_type_cn': sem.get('room_type_cn', ''),
        'confidence': _clamp(sem.get('confidence', 0.5)),
        'objects': objects,
        'description': sem.get('description', ''),
    }


def _clamp(value) -> float:
    try:
        x = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, x))


def _normalize_distance(value: str) -> str:
    raw = (value or '').strip().lower()
    return raw if raw in DISTANCE_SCORE else 'unknown'


def _normalize_visibility(value: str) -> str:
    raw = (value or '').strip().lower()
    return raw if raw in VISIBILITY_SCORE else 'unknown'


def _dedupe_strings(values: list[str]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        text = (value or '').strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _canonical_object_key(obj: dict) -> str:
    for key in (obj.get('name_cn', ''), obj.get('name', '')):
        value = (key or '').strip().lower()
        if value:
            return value
    return ''


def _object_view_score(obj: dict) -> float:
    conf = _clamp(obj.get('confidence', 0.0))
    salience = _clamp(obj.get('salience', 0.5))
    distance = DISTANCE_SCORE.get(obj.get('distance_hint', 'unknown'), 0.55)
    visibility = VISIBILITY_SCORE.get(obj.get('visibility', 'unknown'), 0.55)
    return round(0.40 * conf + 0.25 * salience + 0.20 * distance + 0.15 * visibility, 4)


def _rank_target(nodes: list[dict], target: str) -> list[dict]:
    synonyms = {s.lower() for s in TARGET_SYNONYMS.get(target, [target])}
    ranked = []
    for node in nodes:
        search_objects = node.get('search_objects', {})
        support = []
        for key, meta in search_objects.items():
            names = {key.lower(), (meta.get('name', '') or '').lower(), (meta.get('name_cn', '') or '').lower()}
            if names & synonyms:
                support.append((key, meta))
        if not support:
            continue
        key, meta = max(
            support,
            key=lambda item: (
                item[1].get('best_view_score', 0.0),
                len(item[1].get('supporting_angles', [])),
                item[1].get('best_confidence', 0.0),
            )
        )
        viewpoint_support = min(1.0, 0.25 * len(meta.get('supporting_angles', [])) + 0.15)
        evidence_score = (
            0.35 * 1.0
            + 0.25 * viewpoint_support
            + 0.20 * _clamp(meta.get('best_confidence', 0.0))
            + 0.20 * DISTANCE_SCORE.get(meta.get('distance_hint', 'unknown'), 0.55)
        )
        ranked.append({
            'node_id': node['id'],
            'node_name': node.get('name', f'节点{node["id"]}'),
            'target_key': key,
            'supporting_angles': meta.get('supporting_angles', []),
            'best_view_angle': meta.get('best_view_angle', -1),
            'best_view_score': meta.get('best_view_score', 0.0),
            'distance_hint': meta.get('distance_hint', 'unknown'),
            'visibility': meta.get('visibility', 'unknown'),
            'salience': meta.get('salience', 0.0),
            'best_confidence': meta.get('best_confidence', 0.0),
            'evidence_score': round(evidence_score, 4),
        })
    ranked.sort(
        key=lambda item: (
            item['evidence_score'],
            item['best_view_score'],
            len(item['supporting_angles']),
            item['best_confidence'],
        ),
        reverse=True,
    )
    return ranked


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session-name', default=SESSION_NAME)
    parser.add_argument('--reuse-existing-captured', action='store_true',
                        help='直接复用 session 目录下现有 captured_nodes，不从 SRC_CAPTURED 拷贝')
    parser.add_argument('--target', default='书包',
                        help='重建后额外输出目标物体的排序验证结果')
    return parser.parse_args()


def main():
    args = parse_args()
    session_name = args.session_name
    session_dir = os.path.join(DST_MAP_ROOT, session_name)
    dst_captured = os.path.join(session_dir, 'captured_nodes')
    os.makedirs(dst_captured, exist_ok=True)

    existing_map_file = os.path.join(session_dir, 'topological_map.json')

    if args.reuse_existing_captured and os.path.exists(existing_map_file):
        with open(existing_map_file, 'r', encoding='utf-8') as f:
            existing_map = json.load(f)
        source_nodes = existing_map.get('nodes', [])
    else:
        # 读取旧报告获取节点坐标
        with open(SRC_REPORT, 'r') as f:
            report = json.load(f)
        source_nodes = []
        for record in report['records']:
            source_nodes.append({
                'id': record['node_id'],
                'name': f'拓扑点{record["node_id"]}',
                'pose': {
                    'x': record['pose']['x'],
                    'y': record['pose']['y'],
                    'theta': 0.0,
                },
                'viewpoints': {},
                'panorama_paths': {},
                'semantic_info': None,
                'created_time': time.time(),
                'last_updated': time.time(),
            })

    nodes = []
    total_images = 0
    total_success = 0
    name_counter = {}

    for src_node in source_nodes:
        node_id = src_node['id']
        pose = src_node.get('pose', {})
        x = pose.get('x', 0.0)
        y = pose.get('y', 0.0)
        print(f'\n=== Node {node_id} ({x:.3f}, {y:.3f}) ===')

        src_node_dir = os.path.join(SRC_CAPTURED, f'node_{node_id}')
        dst_node_dir = os.path.join(dst_captured, f'node_{node_id}')

        if not args.reuse_existing_captured:
            if os.path.exists(dst_node_dir):
                shutil.rmtree(dst_node_dir)
            shutil.copytree(src_node_dir, dst_node_dir)
            print(f'  Copied to {dst_node_dir}')
        else:
            print(f'  Reusing {dst_node_dir}')

        viewpoints = {}
        for angle in ANGLES:
            rgb_file = f'{angle:03d}deg_rgb.png'
            rgb_path = os.path.join(dst_node_dir, rgb_file)
            depth_file = f'{angle:03d}deg_depth.png'

            total_images += 1
            print(f'  [{angle:3d}°] Analyzing {rgb_file} ...', end=' ', flush=True)

            sem = vlm_analyze(rgb_path)
            if sem:
                total_success += 1
                obj_names = [o.get('name_cn', o.get('name', '?')) for o in sem.get('objects', [])]
                print(f'OK — {sem.get("room_type_cn", sem.get("room_type", "?"))}, '
                      f'{len(obj_names)} objects: {", ".join(obj_names[:5])}')
            else:
                print('FAILED')

            viewpoints[str(angle)] = {
                'angle': angle,
                'image_path': f'captured_nodes/node_{node_id}/{rgb_file}',
                'depth_path': f'captured_nodes/node_{node_id}/{depth_file}',
                'semantic_info': _build_semantic_info(sem) if sem else None,
                'capture_time': time.time(),
            }

        agg, search_objects = _aggregate(viewpoints)

        base_name = agg.get('room_type_cn', f'拓扑点{node_id}') if agg else f'拓扑点{node_id}'
        if base_name in name_counter:
            name_counter[base_name] += 1
            unique_name = f'{base_name}{name_counter[base_name]}'
        else:
            name_counter[base_name] = 1
            unique_name = base_name

        node_data = {
            'id': node_id,
            'name': unique_name,
            'pose': {'x': x, 'y': y, 'theta': pose.get('theta', 0.0)},
            'viewpoints': viewpoints,
            'panorama_paths': src_node.get('panorama_paths', {}),
            'semantic_info': agg,
            'search_objects': search_objects,
            'created_time': src_node.get('created_time', time.time()),
            'last_updated': time.time(),
        }
        nodes.append(node_data)

    # 生成 topological_map.json
    topo_map = {
        'nodes': nodes,
        'edges': existing_map.get('edges', []) if args.reuse_existing_captured and os.path.exists(existing_map_file) else [],
        'metadata': {
            'graph_type': 'DiGraph',
            'node_count': len(nodes),
            'edge_count': len(existing_map.get('edges', [])) if args.reuse_existing_captured and os.path.exists(existing_map_file) else 0,
            'v35_enhanced': True,
            'enhanced_at': time.time(),
            'enhanced_model': MODEL,
        }
    }

    map_file = os.path.join(session_dir, 'topological_map.json')
    with open(map_file, 'w', encoding='utf-8') as f:
        json.dump(topo_map, f, ensure_ascii=False, indent=2)

    ranking = _rank_target(nodes, args.target)
    ranking_file = os.path.join(session_dir, f'ranking_{args.target}.json')
    with open(ranking_file, 'w', encoding='utf-8') as f:
        json.dump({'target': args.target, 'ranking': ranking}, f, ensure_ascii=False, indent=2)

    print(f'\n{"="*60}')
    print(f'Done! {total_success}/{total_images} images analyzed successfully')
    print(f'Map saved: {map_file}')
    print(f'Ranking:   {ranking_file}')
    print(f'Session:   {session_dir}')
    if ranking:
        print('Ranking preview:')
        for item in ranking:
            print(f'  node={item["node_id"]} score={item["evidence_score"]} '
                  f'best_angle={item["best_view_angle"]} angles={item["supporting_angles"]}')


def _build_semantic_info(sem: dict) -> dict:
    """将 VLM 返回转为 topological_node SemanticInfo 格式。"""
    objects = []
    for obj in sem.get('objects', []):
        objects.append({
            'name': obj.get('name', ''),
            'name_cn': obj.get('name_cn', ''),
            'position': obj.get('position', ''),
            'quantity': obj.get('quantity', 1),
            'confidence': obj.get('confidence', 0.5),
            'distance_hint': obj.get('distance_hint', 'unknown'),
            'salience': obj.get('salience', 0.5),
            'visibility': obj.get('visibility', 'unknown'),
            'image_region': obj.get('image_region', 'mixed'),
        })
    return {
        'room_type': sem.get('room_type', 'unknown'),
        'room_type_cn': sem.get('room_type_cn', ''),
        'confidence': sem.get('confidence', 0.5),
        'objects': objects,
        'description': sem.get('description', ''),
        'aliases': _dedupe_strings([sem.get('room_type_cn', '')] + [o.get('name_cn', '') for o in objects]),
        'semantic_tags': _dedupe_strings(
            [sem.get('room_type', ''), sem.get('room_type_cn', '')] +
            [x for o in objects for x in (o.get('name', ''), o.get('name_cn', ''))]
        ),
    }


def _aggregate(viewpoints: dict) -> tuple[dict | None, dict]:
    """从 viewpoints 聚合节点级语义。"""
    infos = [vp['semantic_info'] for vp in viewpoints.values() if vp.get('semantic_info')]
    if not infos:
        return None, {}

    # Room type: majority vote
    types = [i['room_type'] for i in infos]
    room_type = max(set(types), key=types.count)
    types_cn = [i.get('room_type_cn', '') for i in infos if i.get('room_type_cn')]
    room_type_cn = max(set(types_cn), key=types_cn.count) if types_cn else ''

    # Objects: union, keep highest confidence + search aggregation
    obj_dict = {}
    obj_angles = {}
    best_view_angle = {}
    best_view_score = {}
    best_meta = {}
    descriptions = []
    for angle_str, vp in viewpoints.items():
        angle = int(angle_str)
        info = vp.get('semantic_info') or {}
        if info.get('description'):
            descriptions.append(info['description'])
        for obj in info.get('objects', []):
            key = _canonical_object_key(obj)
            if not key:
                continue
            score = _object_view_score(obj)
            obj_angles.setdefault(key, [])
            if angle not in obj_angles[key]:
                obj_angles[key].append(angle)
            if key not in best_view_score or score > best_view_score[key]:
                best_view_score[key] = score
                best_view_angle[key] = angle
                best_meta[key] = obj

    for info in infos:
        for obj in info.get('objects', []):
            key = (obj.get('name') or obj.get('name_cn', '')).lower()
            if key and (key not in obj_dict or obj['confidence'] > obj_dict[key]['confidence']):
                obj_dict[key] = obj

    aggregate_objects = list(obj_dict.values())
    search_objects = {}
    for key, obj in best_meta.items():
        search_objects[key] = {
            'supporting_angles': sorted(obj_angles.get(key, [])),
            'best_view_angle': best_view_angle.get(key, -1),
            'best_view_score': round(best_view_score.get(key, 0.0), 4),
            'best_confidence': obj.get('confidence', 0.0),
            'distance_hint': obj.get('distance_hint', 'unknown'),
            'salience': obj.get('salience', 0.5),
            'visibility': obj.get('visibility', 'unknown'),
            'image_region': obj.get('image_region', 'mixed'),
            'name': obj.get('name', ''),
            'name_cn': obj.get('name_cn', ''),
        }

    agg = {
        'room_type': room_type,
        'room_type_cn': room_type_cn,
        'confidence': sum(i['confidence'] for i in infos) / len(infos),
        'objects': aggregate_objects,
        'description': ' | '.join(descriptions),
        'aliases': _dedupe_strings([room_type_cn] + [o.get('name_cn', '') for o in aggregate_objects]),
        'semantic_tags': _dedupe_strings(
            [room_type, room_type_cn] +
            [x for o in aggregate_objects for x in (o.get('name', ''), o.get('name_cn', ''))]
        ),
    }
    return agg, search_objects


def _rank_target(nodes: list[dict], target: str) -> list[dict]:
    synonyms = {s.lower() for s in TARGET_SYNONYMS.get(target, [target])}
    ranked = []
    for node in nodes:
        search_objects = node.get('search_objects', {})
        support = []
        for key, meta in search_objects.items():
            names = {key.lower(), (meta.get('name', '') or '').lower(), (meta.get('name_cn', '') or '').lower()}
            if names & synonyms:
                support.append((key, meta))
        if not support:
            continue
        key, meta = max(
            support,
            key=lambda item: (
                item[1].get('best_view_score', 0.0),
                len(item[1].get('supporting_angles', [])),
                item[1].get('best_confidence', 0.0),
            ),
        )
        viewpoint_support = min(1.0, 0.25 * len(meta.get('supporting_angles', [])) + 0.15)
        evidence_score = (
            0.35 * 1.0
            + 0.25 * viewpoint_support
            + 0.20 * _clamp(meta.get('best_confidence', 0.0))
            + 0.20 * DISTANCE_SCORE.get(meta.get('distance_hint', 'unknown'), 0.55)
        )
        ranked.append({
            'node_id': node['id'],
            'node_name': node.get('name', f'节点{node["id"]}'),
            'target_key': key,
            'supporting_angles': meta.get('supporting_angles', []),
            'best_view_angle': meta.get('best_view_angle', -1),
            'best_view_score': meta.get('best_view_score', 0.0),
            'distance_hint': meta.get('distance_hint', 'unknown'),
            'visibility': meta.get('visibility', 'unknown'),
            'salience': meta.get('salience', 0.0),
            'best_confidence': meta.get('best_confidence', 0.0),
            'evidence_score': round(evidence_score, 4),
        })
    ranked.sort(
        key=lambda item: (
            item['evidence_score'],
            item['best_view_score'],
            len(item['supporting_angles']),
            item['best_confidence'],
        ),
        reverse=True,
    )
    return ranked


if __name__ == '__main__':
    main()
