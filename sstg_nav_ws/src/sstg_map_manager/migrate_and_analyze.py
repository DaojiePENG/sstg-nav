#!/usr/bin/env python3
"""
migrate_and_analyze.py — 迁移旧节点数据到新 V3.2 目录结构，并用 VLM 逐张分析每张图片。

用法: python3 migrate_and_analyze.py
"""
import base64
import json
import os
import re
import shutil
import sys
import time
import urllib.request

# ── 配置 ──
API_KEY = 'sk-942e8661f10f492280744a26fe7b953b'
MODEL = 'qwen-vl-plus'
API_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'

SRC_CAPTURED = '/home/daojie/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/captured_nodes'
SRC_REPORT = '/home/daojie/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/maps/manual_capture_report.json'
DST_MAP_ROOT = '/home/daojie/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_map_manager/maps'
SESSION_NAME = 'lab_20260402'

ANGLES = [0, 90, 180, 270]

VLM_PROMPT = """请分析这张室内图片，返回严格的JSON格式（不要markdown代码块，不要```json标记）：
{
  "room_type": "房间类型英文(如 office, corridor, kitchen)",
  "room_type_cn": "房间类型中文",
  "confidence": 0.0到1.0,
  "objects": [
    {"name": "英文名", "name_cn": "中文名", "position": "位置描述", "quantity": 数量, "confidence": 0.0到1.0}
  ],
  "description": "场景一句话描述（中文）"
}"""


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
            return _parse_json(content)
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

def main():
    session_dir = os.path.join(DST_MAP_ROOT, SESSION_NAME)
    dst_captured = os.path.join(session_dir, 'captured_nodes')
    os.makedirs(dst_captured, exist_ok=True)

    # 读取旧报告获取节点坐标
    with open(SRC_REPORT, 'r') as f:
        report = json.load(f)

    nodes = []
    total_images = 0
    total_success = 0
    name_counter = {}  # 用于节点名称去重: base_name → count

    for record in report['records']:
        node_id = record['node_id']
        x = record['pose']['x']
        y = record['pose']['y']
        print(f'\n=== Node {node_id} ({x:.3f}, {y:.3f}) ===')

        # 复制图片到新目录
        src_node_dir = os.path.join(SRC_CAPTURED, f'node_{node_id}')
        dst_node_dir = os.path.join(dst_captured, f'node_{node_id}')

        if os.path.exists(dst_node_dir):
            shutil.rmtree(dst_node_dir)
        shutil.copytree(src_node_dir, dst_node_dir)
        print(f'  Copied to {dst_node_dir}')

        # 逐方向 VLM 分析
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

        # 聚合节点级语义
        agg = _aggregate(viewpoints)

        # 节点名称去重: 走廊 → 走廊, 走廊2, 走廊3 ...
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
            'pose': {'x': x, 'y': y, 'theta': 0.0},
            'viewpoints': viewpoints,
            'panorama_paths': {},
            'semantic_info': agg,
            'created_time': time.time(),
            'last_updated': time.time(),
        }
        nodes.append(node_data)

    # 生成 topological_map.json
    topo_map = {
        'nodes': nodes,
        'edges': [],
        'metadata': {
            'graph_type': 'DiGraph',
            'node_count': len(nodes),
            'edge_count': 0,
        }
    }

    map_file = os.path.join(session_dir, 'topological_map.json')
    with open(map_file, 'w', encoding='utf-8') as f:
        json.dump(topo_map, f, ensure_ascii=False, indent=2)

    print(f'\n{"="*60}')
    print(f'Done! {total_success}/{total_images} images analyzed successfully')
    print(f'Map saved: {map_file}')
    print(f'Session:   {session_dir}')


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
        })
    return {
        'room_type': sem.get('room_type', 'unknown'),
        'room_type_cn': sem.get('room_type_cn', ''),
        'confidence': sem.get('confidence', 0.5),
        'objects': objects,
        'description': sem.get('description', ''),
        'aliases': [],
        'semantic_tags': [],
    }


def _aggregate(viewpoints: dict) -> dict | None:
    """从 viewpoints 聚合节点级语义。"""
    infos = [vp['semantic_info'] for vp in viewpoints.values() if vp.get('semantic_info')]
    if not infos:
        return None

    # Room type: majority vote
    types = [i['room_type'] for i in infos]
    room_type = max(set(types), key=types.count)
    types_cn = [i.get('room_type_cn', '') for i in infos if i.get('room_type_cn')]
    room_type_cn = max(set(types_cn), key=types_cn.count) if types_cn else ''

    # Objects: union, keep highest confidence
    obj_dict = {}
    for info in infos:
        for obj in info.get('objects', []):
            key = (obj.get('name') or obj.get('name_cn', '')).lower()
            if key and (key not in obj_dict or obj['confidence'] > obj_dict[key]['confidence']):
                obj_dict[key] = obj

    descs = [i['description'] for i in infos if i.get('description')]
    return {
        'room_type': room_type,
        'room_type_cn': room_type_cn,
        'confidence': sum(i['confidence'] for i in infos) / len(infos),
        'objects': list(obj_dict.values()),
        'description': ' | '.join(descs),
        'aliases': [],
        'semantic_tags': [],
    }


if __name__ == '__main__':
    main()
