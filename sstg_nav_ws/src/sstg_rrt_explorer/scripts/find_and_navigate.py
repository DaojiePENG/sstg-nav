#!/usr/bin/env python3
"""
find_and_navigate.py - 自然语言查找拓扑节点并导航

支持自然语言输入（如"我要找我的书包"），通过 LLM 语义匹配
拓扑图中的物体名称，找到最佳节点并导航。

用法:
    # 自然语言查找（推荐）
    ros2 run sstg_rrt_explorer find_and_navigate.py --query "我要找我的书包"

    # 精确匹配（不调 LLM）
    ros2 run sstg_rrt_explorer find_and_navigate.py --object 背包

    # 指定节点
    ros2 run sstg_rrt_explorer find_and_navigate.py --node-id 31

    # 列出所有节点
    ros2 run sstg_rrt_explorer find_and_navigate.py --list
"""

import argparse
import json
import os
import sys

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus

DEFAULT_MAP_FILE = os.path.join(
    os.path.expanduser('~'),
    'wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/maps/topological_map_manual.json')


def llm_match_object(query, all_objects, api_key):
    """用 LLM 将自然语言查询匹配到拓扑图中实际的物体名称。"""
    import requests

    objects_str = '、'.join(sorted(set(all_objects)))
    prompt = f"""用户说："{query}"

以下是环境中已知的物体列表：
{objects_str}

请从列表中找出用户最可能在找的物体。如果有多个相关物体，按相关度排序。
只输出 JSON 格式，不要其他文字：
{{"matches": ["物体1", "物体2"], "reason": "简短理由"}}

如果没有任何匹配，返回：
{{"matches": [], "reason": "未找到相关物体"}}"""

    try:
        resp = requests.post(
            'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'qwen-plus',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content']
        # 提取 JSON
        if '```' in content:
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
        result = json.loads(content.strip())
        return result.get('matches', []), result.get('reason', '')
    except Exception as e:
        return [], f'LLM error: {e}'


class FindAndNavigateNode(Node):
    def __init__(self, map_file):
        super().__init__('find_and_navigate')

        self.map_file = map_file
        self.topo_map = self._load_topo_map()

        # Nav2 action client
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.get_logger().info('Waiting for Nav2 action server...')
        if not self.nav_client.wait_for_server(timeout_sec=15.0):
            self.get_logger().error('Nav2 action server not available!')
            raise RuntimeError('Nav2 not available')
        self.get_logger().info('Nav2 ready')

    def _load_topo_map(self):
        try:
            with open(self.map_file, 'r') as f:
                data = json.load(f)
            nodes = data.get('nodes', [])
            semantic_count = sum(1 for n in nodes if n.get('semantic_info'))
            self.get_logger().info(
                f'Loaded {len(nodes)} nodes ({semantic_count} with semantic) '
                f'from {self.map_file}')
            return data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.get_logger().error(f'Failed to load map: {e}')
            raise

    def get_all_objects(self):
        """收集拓扑图中所有物体名称。"""
        objects = set()
        for node_data in self.topo_map.get('nodes', []):
            semantic = node_data.get('semantic_info')
            if not semantic:
                continue
            for obj in semantic.get('objects', []):
                name = obj.get('name_cn') or obj.get('name', '')
                if name:
                    objects.add(name)
        return list(objects)

    def find_by_object(self, object_name):
        """精确子串匹配。"""
        matches = []
        object_lower = object_name.lower()

        for node_data in self.topo_map.get('nodes', []):
            semantic = node_data.get('semantic_info')
            if not semantic:
                continue
            pose = node_data.get('pose', {})

            for obj in semantic.get('objects', []):
                candidates = [obj.get('name', ''), obj.get('name_cn', '')]
                if any(self._match_text(object_lower, c) for c in candidates):
                    matches.append({
                        'node_id': node_data.get('id', -1),
                        'name': node_data.get('name', ''),
                        'x': pose.get('x', 0.0),
                        'y': pose.get('y', 0.0),
                        'room_type': self._display_room_type(semantic),
                        'object_name': obj.get('name_cn') or obj.get('name', ''),
                        'confidence': obj.get('confidence', 0.0),
                    })
                    break
        return matches

    def find_by_query(self, query, api_key):
        """用 LLM 语义匹配自然语言查询。"""
        all_objects = self.get_all_objects()
        if not all_objects:
            self.get_logger().error('No objects in topological map')
            return []

        self.get_logger().info(
            f'Querying LLM to match "{query}" against {len(all_objects)} objects...')
        matched_names, reason = llm_match_object(query, all_objects, api_key)

        if not matched_names:
            self.get_logger().warn(f'LLM found no match. Reason: {reason}')
            return []

        self.get_logger().info(
            f'LLM matched: {matched_names} (reason: {reason})')

        # 对每个匹配的物体名在拓扑图中查找节点
        all_matches = []
        for obj_name in matched_names:
            results = self.find_by_object(obj_name)
            all_matches.extend(results)

        # 去重（同一节点只保留一次）
        seen = set()
        unique = []
        for m in all_matches:
            if m['node_id'] not in seen:
                seen.add(m['node_id'])
                unique.append(m)
        return unique

    def find_by_node_id(self, node_id):
        for node_data in self.topo_map.get('nodes', []):
            if node_data.get('id') == node_id:
                pose = node_data.get('pose', {})
                semantic = node_data.get('semantic_info') or {}
                return {
                    'node_id': node_id,
                    'name': node_data.get('name', f'Node_{node_id}'),
                    'x': pose.get('x', 0.0),
                    'y': pose.get('y', 0.0),
                    'room_type': self._display_room_type(semantic),
                }
        return None

    def _match_text(self, query, candidate):
        candidate_lower = (candidate or '').lower()
        return bool(candidate_lower) and (
            query in candidate_lower or candidate_lower in query
        )

    def _display_room_type(self, semantic):
        if not semantic:
            return 'unknown'
        return semantic.get('room_type_cn') or semantic.get('room_type', 'unknown')

    def navigate_to(self, x, y, node_id):
        self.get_logger().info(
            f'Navigating to node {node_id} at ({x:.2f}, {y:.2f})...')

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x)
        goal.pose.pose.position.y = float(y)
        goal.pose.pose.orientation.w = 1.0

        send_future = self.nav_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=10.0)

        goal_handle = send_future.result()
        if not goal_handle or not goal_handle.accepted:
            self.get_logger().error('Nav2 goal rejected')
            return False

        self.get_logger().info('Goal accepted, waiting for arrival...')
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=120.0)

        if result_future.result() is None:
            self.get_logger().error('Navigation timed out')
            return False

        status = result_future.result().status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(
                f'Arrived at node {node_id} ({x:.2f}, {y:.2f})')
            return True
        else:
            self.get_logger().error(
                f'Navigation failed with status {status}')
            return False

    def list_nodes(self):
        nodes = self.topo_map.get('nodes', [])
        if not nodes:
            self.get_logger().info('No nodes in map')
            return

        self.get_logger().info(f'\n=== Topological Map: {len(nodes)} nodes ===')
        for node_data in nodes:
            nid = node_data.get('id', -1)
            pose = node_data.get('pose', {})
            semantic = node_data.get('semantic_info')
            if semantic:
                room = self._display_room_type(semantic)
                objs = [
                    o.get('name_cn') or o.get('name', '')
                    for o in semantic.get('objects', [])
                ]
                self.get_logger().info(
                    f'  Node {nid} [{node_data.get("name", "")}]: '
                    f'({pose.get("x", 0):.2f}, {pose.get("y", 0):.2f}) '
                    f'room={room} objects={objs}')
            else:
                self.get_logger().info(
                    f'  Node {nid} [{node_data.get("name", "")}]: '
                    f'({pose.get("x", 0):.2f}, {pose.get("y", 0):.2f}) '
                    f'[no semantic]')


def main(args=None):
    parser = argparse.ArgumentParser(
        description='自然语言查找拓扑节点并导航')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--query', type=str,
                       help='自然语言查询（如"我要找我的书包"）')
    group.add_argument('--object', type=str,
                       help='精确匹配物体名称')
    group.add_argument('--node-id', type=int,
                       help='直接指定目标节点 ID')
    group.add_argument('--list', action='store_true',
                       help='列出所有节点及语义信息')
    parser.add_argument('--map-file', default=DEFAULT_MAP_FILE,
                        help='拓扑图 JSON 路径')
    parser.add_argument('--api-key',
                        default=os.getenv('DASHSCOPE_API_KEY', ''),
                        help='DashScope API Key')
    parser.add_argument('--no-nav', action='store_true',
                        help='只搜索不导航')

    parsed, remaining = parser.parse_known_args()
    rclpy.init(args=remaining)

    try:
        node = FindAndNavigateNode(map_file=parsed.map_file)

        if parsed.list:
            node.list_nodes()
            return

        target = None

        if parsed.query:
            if not parsed.api_key:
                node.get_logger().error(
                    'DASHSCOPE_API_KEY required for --query mode')
                return
            matches = node.find_by_query(parsed.query, parsed.api_key)

            if not matches:
                node.get_logger().error(
                    f'No matching nodes for: "{parsed.query}"')
                node.list_nodes()
                return

            target = matches[0]
            node.get_logger().info(
                f'Best match: node {target["node_id"]} ({target["name"]}) '
                f'at ({target["x"]:.2f}, {target["y"]:.2f}) '
                f'room={target["room_type"]} '
                f'object={target["object_name"]}')
            if len(matches) > 1:
                for m in matches[1:]:
                    node.get_logger().info(
                        f'  Also found: node {m["node_id"]} ({m["name"]}) '
                        f'object={m["object_name"]}')

        elif parsed.object:
            matches = node.find_by_object(parsed.object)
            if not matches:
                node.get_logger().error(
                    f'No nodes found containing "{parsed.object}"')
                node.list_nodes()
                return
            matches.sort(key=lambda m: m['confidence'], reverse=True)
            target = matches[0]
            node.get_logger().info(
                f'Found "{parsed.object}" at node {target["node_id"]} '
                f'({target["x"]:.2f}, {target["y"]:.2f}) '
                f'name={target["name"]} room={target["room_type"]}')

        elif parsed.node_id is not None:
            target = node.find_by_node_id(parsed.node_id)
            if not target:
                node.get_logger().error(
                    f'Node {parsed.node_id} not found in map')
                node.list_nodes()
                return

        if parsed.no_nav:
            node.get_logger().info('--no-nav: skip navigation')
            return

        success = node.navigate_to(target['x'], target['y'], target['node_id'])
        if success:
            node.get_logger().info('Mission accomplished!')
        else:
            node.get_logger().error('Navigation failed')

    except KeyboardInterrupt:
        print('\nCanceled by user')
    except ExternalShutdownException:
        pass
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
