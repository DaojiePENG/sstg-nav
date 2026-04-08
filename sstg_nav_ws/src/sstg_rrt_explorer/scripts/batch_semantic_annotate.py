#!/usr/bin/env python3
"""
batch_semantic_annotate.py - 批量对已拍照的节点做 VLM 语义标注

用法:
  source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
  export DASHSCOPE_API_KEY=sk-942e8661f10f492280744a26fe7b953b
  python3 batch_semantic_annotate.py --nodes 17 18 19 20 21 22 23 24 25

功能:
  1. 读取 captured_nodes/node_X/ 下的照片
  2. 调用 /annotate_semantic 服务做 VLM 标注
  3. 如果节点不在拓扑图中，先通过 /create_node 创建
  4. 调用 /update_semantic 写入拓扑图
"""

import argparse
import json
import os
import sys
import time

import rclpy
from rclpy.node import Node
from sstg_msgs.srv import AnnotateSemantic, CreateNode, UpdateSemantic
from sstg_msgs.msg import SemanticData, SemanticObject
from geometry_msgs.msg import PoseStamped


CAPTURED_DIR = os.path.expanduser(
    '~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/captured_nodes')
MAP_FILE = os.path.expanduser(
    '~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/maps/topological_map_manual.json')
REPORT_FILE = os.path.expanduser(
    '~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/maps/manual_capture_report.json')


class BatchAnnotator(Node):
    def __init__(self):
        super().__init__('batch_annotator')
        self.annotate_cli = self.create_client(AnnotateSemantic, '/annotate_semantic')
        self.create_cli = self.create_client(CreateNode, '/create_node')
        self.update_cli = self.create_client(UpdateSemantic, '/update_semantic')

        for cli, name in [(self.annotate_cli, 'annotate_semantic'),
                          (self.create_cli, 'create_node'),
                          (self.update_cli, 'update_semantic')]:
            if not cli.wait_for_service(timeout_sec=10.0):
                self.get_logger().error(f'{name} service not available')
                sys.exit(1)
        self.get_logger().info('All services connected')

    def get_node_pose_from_report(self, node_id):
        """从 capture report 中获取节点位姿"""
        if os.path.exists(REPORT_FILE):
            with open(REPORT_FILE) as f:
                report = json.load(f)
            for rec in report.get('records', []):
                if rec.get('node_id') == node_id:
                    return rec['pose']['x'], rec['pose']['y']
        return None, None

    def get_node_pose_from_map(self, node_id):
        """从拓扑图中获取节点位姿"""
        if os.path.exists(MAP_FILE):
            with open(MAP_FILE) as f:
                data = json.load(f)
            for node in data.get('nodes', []):
                if node['id'] == node_id:
                    return node['pose']['x'], node['pose']['y']
        return None, None

    def node_exists_in_map(self, node_id):
        """检查节点是否在拓扑图中"""
        if os.path.exists(MAP_FILE):
            with open(MAP_FILE) as f:
                data = json.load(f)
            return any(n['id'] == node_id for n in data.get('nodes', []))
        return False

    def create_topo_node(self, node_id, x, y):
        """在拓扑图中创建节点"""
        req = CreateNode.Request()
        req.pose = PoseStamped()
        req.pose.header.frame_id = 'map'
        req.pose.pose.position.x = x
        req.pose.pose.position.y = y
        req.pose.pose.orientation.w = 1.0

        future = self.create_cli.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        if future.result() and future.result().success:
            new_id = future.result().node_id
            self.get_logger().info(f'Created topo node {new_id} at ({x:.2f}, {y:.2f})')
            return new_id
        else:
            msg = future.result().message if future.result() else 'timeout'
            self.get_logger().error(f'Failed to create node: {msg}')
            return None

    def annotate_image(self, image_path, node_id):
        """对单张图片做 VLM 语义标注"""
        req = AnnotateSemantic.Request()
        req.image_path = image_path
        req.node_id = node_id

        future = self.annotate_cli.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=60.0)
        if future.result() and future.result().success:
            return future.result()
        else:
            err = future.result().error_message if future.result() else 'timeout'
            self.get_logger().warn(f'Annotate failed for {os.path.basename(image_path)}: {err}')
            return None

    def update_semantic(self, node_id, room_type, objects, confidence, description):
        """更新节点的语义信息"""
        req = UpdateSemantic.Request()
        req.node_id = node_id
        req.semantic_data = SemanticData()
        req.semantic_data.room_type = room_type
        req.semantic_data.confidence = confidence
        req.semantic_data.description = description
        req.semantic_data.objects = objects

        future = self.update_cli.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        if future.result() and future.result().success:
            self.get_logger().info(f'Node {node_id} semantic updated: {room_type}')
            return True
        else:
            msg = future.result().message if future.result() else 'timeout'
            self.get_logger().error(f'Update semantic failed: {msg}')
            return False

    def process_node(self, node_id):
        """处理单个节点：标注所有照片，合并结果，写入拓扑图"""
        node_dir = os.path.join(CAPTURED_DIR, f'node_{node_id}')
        if not os.path.isdir(node_dir):
            self.get_logger().error(f'node_{node_id} directory not found')
            return False

        # 找所有 RGB 图片
        rgb_files = sorted([f for f in os.listdir(node_dir) if f.endswith('_rgb.png')])
        if not rgb_files:
            self.get_logger().error(f'node_{node_id}: no RGB images found')
            return False

        self.get_logger().info(f'--- Processing node {node_id} ({len(rgb_files)} images) ---')

        # 如果节点不在拓扑图中，先创建
        if not self.node_exists_in_map(node_id):
            x, y = self.get_node_pose_from_report(node_id)
            if x is None:
                self.get_logger().error(f'node_{node_id}: pose not found in report')
                return False
            actual_id = self.create_topo_node(node_id, x, y)
            if actual_id is None:
                return False
            # map_manager 可能分配了不同的 ID
            if actual_id != node_id:
                self.get_logger().warn(
                    f'map_manager assigned id={actual_id} instead of {node_id}')
                node_id = actual_id

        # 标注所有图片，收集结果
        all_objects = []
        all_room_types = []
        all_descriptions = []
        best_confidence = 0.0

        for rgb_file in rgb_files:
            image_path = os.path.join(node_dir, rgb_file)
            self.get_logger().info(f'  Annotating {rgb_file}...')
            result = self.annotate_image(image_path, node_id)
            if result:
                all_room_types.append(result.room_type)
                all_objects.extend(result.objects)
                all_descriptions.append(result.description)
                best_confidence = max(best_confidence, result.confidence)
                self.get_logger().info(
                    f'    → {result.room_type} ({result.confidence:.2f}), '
                    f'{len(result.objects)} objects')
            time.sleep(1)  # API rate limit

        if not all_room_types:
            self.get_logger().error(f'node_{node_id}: all annotations failed')
            return False

        # 合并：取最常见的 room_type
        from collections import Counter
        room_type = Counter(all_room_types).most_common(1)[0][0]

        # 合并描述
        description = ' | '.join(all_descriptions)

        # 去重 objects（按 name 合并）
        merged = {}
        for obj in all_objects:
            key = obj.name
            if key not in merged:
                merged[key] = obj
            else:
                merged[key].quantity = max(merged[key].quantity, obj.quantity)
                merged[key].confidence = max(merged[key].confidence, obj.confidence)
        unique_objects = list(merged.values())

        # 写入拓扑图
        self.update_semantic(node_id, room_type, unique_objects,
                            best_confidence, description)
        return True


def main():
    global MAP_FILE, REPORT_FILE

    parser = argparse.ArgumentParser()
    parser.add_argument('--nodes', nargs='+', type=int, required=True,
                        help='Node IDs to annotate (e.g. 17 18 19)')
    parser.add_argument('--map-file', default=MAP_FILE)
    parser.add_argument('--report-file', default=REPORT_FILE)
    args = parser.parse_args()

    MAP_FILE = args.map_file
    REPORT_FILE = args.report_file

    rclpy.init()
    annotator = BatchAnnotator()

    success = 0
    failed = 0
    for nid in args.nodes:
        try:
            if annotator.process_node(nid):
                success += 1
            else:
                failed += 1
        except Exception as e:
            annotator.get_logger().error(f'node_{nid} exception: {e}')
            failed += 1

    annotator.get_logger().info(f'Done: {success} succeeded, {failed} failed')
    annotator.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
