#!/usr/bin/env python3
"""
node_semantic_collector.py - 逐个到达拓扑节点，采集语义信息

读取 auto_node_placer.py 生成的 node_positions.json，
对每个节点：导航到达 → 注册拓扑节点 → 拍摄全景 → VLM 语义标注 → 更新节点。

用法:
    ros2 run sstg_rrt_explorer node_semantic_collector.py --nodes node_positions.json
    ros2 run sstg_rrt_explorer node_semantic_collector.py --nodes node_positions.json --skip-semantic
    ros2 run sstg_rrt_explorer node_semantic_collector.py --nodes node_positions.json --start-index 5
"""

import argparse
import json
import os
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus

from sstg_msgs.srv import CreateNode, CaptureImage, AnnotateSemantic, UpdateSemantic
from sstg_msgs.msg import SemanticData, SemanticObject


class NodeSemanticCollector(Node):
    def __init__(self, nodes_file, map_file, skip_semantic, start_index):
        super().__init__('node_semantic_collector')

        self.skip_semantic = skip_semantic
        self.start_index = start_index
        self.map_file = map_file

        # 读取节点位置
        with open(nodes_file, 'r') as f:
            data = json.load(f)
        self.node_positions = data['nodes']
        self.total = len(self.node_positions)
        self.get_logger().info(
            f'Loaded {self.total} node positions from {nodes_file}')

        # 记录结果
        self.results = []
        self.failed_nodes = []

        # Nav2 action client
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.get_logger().info('Waiting for Nav2 navigate_to_pose action...')
        if not self.nav_client.wait_for_server(timeout_sec=15.0):
            self.get_logger().error('Nav2 action server not available!')
            raise RuntimeError('Nav2 not available')
        self.get_logger().info('Nav2 action server ready')

        # Service clients
        self.create_node_cli = self.create_client(CreateNode, 'create_node')
        self._wait_service(self.create_node_cli, 'create_node')

        if not self.skip_semantic:
            self.capture_cli = self.create_client(CaptureImage, 'capture_panorama')
            self.annotate_cli = self.create_client(
                AnnotateSemantic, 'annotate_semantic')
            self.update_sem_cli = self.create_client(
                UpdateSemantic, 'update_semantic')

            self._wait_service(self.capture_cli, 'capture_panorama')
            self._wait_service(self.annotate_cli, 'annotate_semantic')
            self._wait_service(self.update_sem_cli, 'update_semantic')

    def _wait_service(self, client, name):
        self.get_logger().info(f'Waiting for {name} service...')
        if not client.wait_for_service(timeout_sec=10.0):
            self.get_logger().warn(f'{name} service not available after 10s')
        else:
            self.get_logger().info(f'{name} service ready')

    def run(self):
        """执行完整的节点采集流程。"""
        self.get_logger().info(
            f'=== Starting collection: {self.total} nodes '
            f'(from index {self.start_index}) ===')

        for i in range(self.start_index, self.total):
            pos = self.node_positions[i]
            x, y = pos['x'], pos['y']
            self.get_logger().info(
                f'\n[{i + 1}/{self.total}] Processing node at ({x:.2f}, {y:.2f})')

            result = {'index': i, 'x': x, 'y': y}

            # Step 1: 注册拓扑节点
            node_id = self._create_topo_node(x, y)
            if node_id is None:
                self.get_logger().error(f'  Failed to create topo node, skipping')
                result['status'] = 'create_failed'
                self.failed_nodes.append(result)
                continue
            result['node_id'] = node_id
            self.get_logger().info(f'  Created topo node_id={node_id}')

            # Step 2: 导航到节点
            nav_ok = self._navigate_to(x, y)
            if not nav_ok:
                self.get_logger().warn(
                    f'  Navigation failed for node {node_id}, skipping semantic')
                result['status'] = 'nav_failed'
                self.failed_nodes.append(result)
                continue

            self.get_logger().info(f'  Arrived at node {node_id}')

            # Step 3: 语义采集（可选）
            if self.skip_semantic:
                result['status'] = 'ok_no_semantic'
                result['semantic'] = None
            else:
                semantic = self._collect_semantic(node_id, x, y)
                result['status'] = 'ok' if semantic else 'semantic_failed'
                result['semantic'] = semantic

            self.results.append(result)
            self.get_logger().info(
                f'  Node {node_id} done: {result["status"]}')

        # 完成
        self._save_results()
        self.get_logger().info(
            f'\n=== Collection complete ===\n'
            f'  Success: {len(self.results)}\n'
            f'  Failed:  {len(self.failed_nodes)}\n'
            f'  Map:     {self.map_file}')

    def _create_topo_node(self, x, y):
        """调用 create_node 服务注册拓扑节点。"""
        req = CreateNode.Request()
        req.pose = PoseStamped()
        req.pose.header.frame_id = 'map'
        req.pose.header.stamp = self.get_clock().now().to_msg()
        req.pose.pose.position.x = float(x)
        req.pose.pose.position.y = float(y)
        req.pose.pose.orientation.w = 1.0

        future = self.create_node_cli.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        resp = future.result()
        if resp and resp.success:
            return resp.node_id
        return None

    def _navigate_to(self, x, y):
        """用 Nav2 导航到指定坐标，阻塞直到完成。"""
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
            self.get_logger().warn('  Nav2 goal rejected')
            return False

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=120.0)

        if result_future.result() is None:
            self.get_logger().warn('  Nav2 result timeout')
            return False

        status = result_future.result().status
        return status == GoalStatus.STATUS_SUCCEEDED

    def _collect_semantic(self, node_id, x, y):
        """拍摄全景 + VLM 标注 + 更新节点语义。"""
        # Capture panorama
        cap_req = CaptureImage.Request()
        cap_req.node_id = node_id
        cap_req.pose = PoseStamped()
        cap_req.pose.header.frame_id = 'map'
        cap_req.pose.header.stamp = self.get_clock().now().to_msg()
        cap_req.pose.pose.position.x = float(x)
        cap_req.pose.pose.position.y = float(y)
        cap_req.pose.pose.orientation.w = 1.0

        cap_future = self.capture_cli.call_async(cap_req)
        rclpy.spin_until_future_complete(self, cap_future, timeout_sec=30.0)
        cap_resp = cap_future.result()

        if not cap_resp or not cap_resp.success:
            err = cap_resp.error_message if cap_resp else 'timeout'
            self.get_logger().warn(f'  Panorama capture failed: {err}')
            return None

        self.get_logger().info(
            f'  Captured {len(cap_resp.image_paths)} images')

        # Annotate each image
        all_objects = []
        best_room_type = ''
        best_confidence = 0.0
        best_description = ''

        for path_entry in cap_resp.image_paths:
            # path_entry 格式: "angle:path"
            parts = path_entry.split(':', 1)
            image_path = parts[1] if len(parts) == 2 else path_entry

            ann_req = AnnotateSemantic.Request()
            ann_req.image_path = image_path
            ann_req.node_id = node_id

            ann_future = self.annotate_cli.call_async(ann_req)
            rclpy.spin_until_future_complete(self, ann_future, timeout_sec=30.0)
            ann_resp = ann_future.result()

            if ann_resp and ann_resp.success:
                for obj in ann_resp.objects:
                    all_objects.append(obj)
                if ann_resp.confidence > best_confidence:
                    best_room_type = ann_resp.room_type
                    best_confidence = ann_resp.confidence
                    best_description = ann_resp.description
                self.get_logger().info(
                    f'    Annotated: room={ann_resp.room_type}, '
                    f'objects={[o.name for o in ann_resp.objects]}')
            else:
                err = ann_resp.error_message if ann_resp else 'timeout'
                self.get_logger().warn(f'    Annotation failed: {err}')

        if not best_room_type and not all_objects:
            self.get_logger().warn('  No semantic data extracted')
            return None

        # Deduplicate objects by name
        seen = set()
        unique_objects = []
        for obj in all_objects:
            if obj.name.lower() not in seen:
                seen.add(obj.name.lower())
                unique_objects.append(obj)

        # Update semantic data on node
        sem_data = SemanticData()
        sem_data.room_type = best_room_type
        sem_data.confidence = best_confidence
        sem_data.description = best_description
        sem_data.objects = unique_objects

        upd_req = UpdateSemantic.Request()
        upd_req.node_id = node_id
        upd_req.semantic_data = sem_data

        upd_future = self.update_sem_cli.call_async(upd_req)
        rclpy.spin_until_future_complete(self, upd_future, timeout_sec=5.0)
        upd_resp = upd_future.result()

        if not upd_resp or not upd_resp.success:
            self.get_logger().warn('  Failed to update semantic on map_manager')

        return {
            'room_type': best_room_type,
            'confidence': best_confidence,
            'objects': [o.name for o in unique_objects],
            'description': best_description,
        }

    def _save_results(self):
        """保存采集结果摘要。"""
        # 触发 map_manager 保存（它会在 shutdown 时自动保存到 map_file）
        summary_path = self.map_file.replace('.json', '_collection_report.json')
        report = {
            'total_planned': self.total,
            'start_index': self.start_index,
            'successful': len(self.results),
            'failed': len(self.failed_nodes),
            'nodes': self.results,
            'failed_nodes': self.failed_nodes,
            'topo_map_file': self.map_file,
        }
        try:
            os.makedirs(os.path.dirname(summary_path) or '.', exist_ok=True)
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            self.get_logger().info(f'Report saved: {summary_path}')
        except Exception as e:
            self.get_logger().error(f'Failed to save report: {e}')


def main(args=None):
    parser = argparse.ArgumentParser(
        description='逐个到达拓扑节点，采集语义信息')
    parser.add_argument('--nodes', required=True,
                        help='node_positions.json 文件路径')
    parser.add_argument('--map-file', default='/tmp/topological_map.json',
                        help='拓扑图输出路径 (map_manager 使用)')
    parser.add_argument('--skip-semantic', action='store_true',
                        help='跳过语义采集，只注册节点坐标并导航验证')
    parser.add_argument('--start-index', type=int, default=0,
                        help='从第几个节点开始 (便于中断后续做)')

    # ROS2 会传入额外参数，需要 parse_known_args
    parsed, remaining = parser.parse_known_args()

    rclpy.init(args=remaining)

    try:
        collector = NodeSemanticCollector(
            nodes_file=parsed.nodes,
            map_file=parsed.map_file,
            skip_semantic=parsed.skip_semantic,
            start_index=parsed.start_index,
        )
        collector.run()
    except KeyboardInterrupt:
        print('\nInterrupted by user')
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
