#!/usr/bin/env python3
"""
click_and_capture.py - 在 RViz 点击目标点后，机器人自动导航并拍照

流程:
    /clicked_point -> create_node -> NavigateToPose -> capture_panorama

用法:
    ros2 run sstg_rrt_explorer click_and_capture.py \
      --report-file /path/to/manual_capture_report.json
"""

import argparse
import json
import math
import os
import sys
import threading
import time
from collections import deque

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PointStamped, PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray

from sstg_msgs.msg import SemanticData
from sstg_msgs.srv import AnnotateSemantic, CaptureImage, CreateNode, UpdateSemantic


class ClickAndCaptureNode(Node):
    def __init__(self, report_file, map_file, click_topic, marker_topic, min_distance):
        super().__init__('click_and_capture')

        self.report_file = report_file
        self.map_file = map_file
        self.click_topic = click_topic
        self.marker_topic = marker_topic
        self.min_distance = min_distance

        self.pending = deque()
        self.records = []
        self.busy = False
        self.nodes_for_viz = []

        self.click_sub = self.create_subscription(
            PointStamped, self.click_topic, self._clicked_point_callback, 10)
        self.marker_pub = self.create_publisher(MarkerArray, self.marker_topic, 10)
        self.timer = self.create_timer(0.5, self._process_queue)
        self.marker_timer = self.create_timer(1.0, self._publish_markers)

        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.create_node_cli = self.create_client(CreateNode, 'create_node')
        self.capture_cli = self.create_client(CaptureImage, 'capture_panorama')
        self.annotate_cli = self.create_client(AnnotateSemantic, 'annotate_semantic')
        self.update_sem_cli = self.create_client(UpdateSemantic, 'update_semantic')

        self.get_logger().info(f'Listening for clicks on {self.click_topic}')
        self.get_logger().info(f'Report file: {self.report_file}')
        self.get_logger().info(f'Topological map file: {self.map_file}')
        self.get_logger().info('Click a point in RViz with Publish Point')

        if not self.nav_client.wait_for_server(timeout_sec=15.0):
            raise RuntimeError('Nav2 action server not available')
        if not self.create_node_cli.wait_for_service(timeout_sec=10.0):
            raise RuntimeError('create_node service not available')
        if not self.capture_cli.wait_for_service(timeout_sec=10.0):
            raise RuntimeError('capture_panorama service not available')
        self.has_annotation = self.annotate_cli.wait_for_service(timeout_sec=2.0)
        self.has_update_semantic = self.update_sem_cli.wait_for_service(timeout_sec=2.0)

        self._load_existing_nodes()

    def _load_existing_nodes(self):
        """从 topological_map_manual.json 加载已有节点，重启后继续显示在 RViz 上。"""
        if not self.map_file or not os.path.exists(self.map_file):
            return
        try:
            with open(self.map_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            nodes = data.get('nodes', [])
            for node_data in nodes:
                pose = node_data.get('pose', {})
                x = pose.get('x', 0.0)
                y = pose.get('y', 0.0)
                semantic = node_data.get('semantic_info')
                has_images = bool(node_data.get('panorama_paths'))
                if semantic:
                    status = 'semantic'
                elif has_images:
                    status = 'captured'
                else:
                    status = 'pending'
                self.records.append({
                    'pose': {'x': x, 'y': y},
                    'status': 'loaded',
                    'node_id': node_data.get('id'),
                    'image_paths': [],
                    'semantic': None,
                    'capture_complete': True,
                    'capture_error': '',
                })
                self.nodes_for_viz.append({'x': x, 'y': y, 'status': status})
            if nodes:
                self.get_logger().info(
                    f'Loaded {len(nodes)} existing nodes from {self.map_file}')
        except Exception as e:
            self.get_logger().warn(f'Failed to load existing nodes: {e}')

    def _clicked_point_callback(self, msg):
        x = round(float(msg.point.x), 3)
        y = round(float(msg.point.y), 3)

        all_points = list(self.pending) + [r['pose'] for r in self.records]
        for point in all_points:
            dx = point['x'] - x
            dy = point['y'] - y
            if math.hypot(dx, dy) < self.min_distance:
                self.get_logger().warn(
                    f'Ignored click ({x:.2f}, {y:.2f}) - too close to existing target')
                return

        self.pending.append({'x': x, 'y': y})
        self.nodes_for_viz.append({'x': x, 'y': y, 'status': 'pending'})
        self.get_logger().info(
            f'Queued target {len(self.pending)}: ({x:.2f}, {y:.2f})')

    def _process_queue(self):
        if self.busy or not self.pending:
            return

        self.busy = True
        target = self.pending.popleft()
        threading.Thread(
            target=self._handle_target,
            args=(target,),
            daemon=True,
        ).start()

    def _handle_target(self, target):
        x = target['x']
        y = target['y']

        record = {
            'pose': {'x': x, 'y': y},
            'status': 'started',
            'node_id': None,
            'image_paths': [],
            'semantic': None,
            'capture_complete': False,
            'capture_error': '',
        }
        self.records.append(record)
        viz_idx = len(self.records) - 1

        try:
            node_id = self._create_topo_node(x, y)
            if node_id is None:
                record['status'] = 'create_failed'
                self.nodes_for_viz[viz_idx]['status'] = 'failed'
                self._save_report()
                return

            record['node_id'] = node_id
            self.get_logger().info(f'Created topo node {node_id} for ({x:.2f}, {y:.2f})')

            nav_ok = self._navigate_to(x, y)
            if not nav_ok:
                record['status'] = 'nav_failed'
                self.nodes_for_viz[viz_idx]['status'] = 'failed'
                self._save_report()
                return

            self.get_logger().info(f'Arrived at node {node_id}, capturing panorama...')
            capture_result = self._capture_panorama(node_id, x, y)
            image_paths = capture_result['image_paths']
            record['image_paths'] = image_paths
            record['capture_complete'] = capture_result['success']
            record['capture_error'] = capture_result['error_message']

            if capture_result['success']:
                record['status'] = 'captured'
            elif image_paths:
                record['status'] = 'capture_partial'
            else:
                record['status'] = 'capture_failed'

            if image_paths:
                self._update_map_panorama_paths(node_id, image_paths)
                if capture_result['success']:
                    semantic = self._annotate_and_update(node_id, image_paths)
                    if semantic:
                        record['semantic'] = semantic
                        record['status'] = 'semantic_updated'
                    self._update_map_panorama_paths(node_id, image_paths)
            self.nodes_for_viz[viz_idx]['status'] = (
                'captured' if capture_result['success'] else
                ('partial' if image_paths else 'failed')
            )
            if record['status'] == 'semantic_updated':
                self.nodes_for_viz[viz_idx]['status'] = 'semantic'
            self._save_report()
        except Exception as exc:
            record['status'] = 'exception'
            record['error'] = str(exc)
            self.nodes_for_viz[viz_idx]['status'] = 'failed'
            self.get_logger().error(f'Failed processing target ({x:.2f}, {y:.2f}): {exc}')
            self._save_report()
        finally:
            self.busy = False

    def _create_topo_node(self, x, y):
        req = CreateNode.Request()
        req.pose = PoseStamped()
        req.pose.header.frame_id = 'map'
        req.pose.header.stamp = self.get_clock().now().to_msg()
        req.pose.pose.position.x = float(x)
        req.pose.pose.position.y = float(y)
        req.pose.pose.orientation.w = 1.0

        future = self.create_node_cli.call_async(req)
        if not self._wait_future(future, 5.0):
            self.get_logger().warn('create_node timed out')
            return None
        resp = future.result()
        if resp and resp.success:
            return resp.node_id
        return None

    def _navigate_to(self, x, y):
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x)
        goal.pose.pose.position.y = float(y)
        goal.pose.pose.orientation.w = 1.0

        send_future = self.nav_client.send_goal_async(goal)
        if not self._wait_future(send_future, 10.0):
            self.get_logger().warn('NavigateToPose goal send timed out')
            return False
        goal_handle = send_future.result()
        if not goal_handle or not goal_handle.accepted:
            self.get_logger().warn('Nav2 goal rejected')
            return False

        result_future = goal_handle.get_result_async()
        if not self._wait_future(result_future, 180.0):
            self.get_logger().warn('Navigation timed out')
            return False
        result = result_future.result()
        if result is None:
            return False

        return result.status == GoalStatus.STATUS_SUCCEEDED

    def _capture_panorama(self, node_id, x, y):
        req = CaptureImage.Request()
        req.node_id = node_id
        req.pose = PoseStamped()
        req.pose.header.frame_id = 'map'
        req.pose.header.stamp = self.get_clock().now().to_msg()
        req.pose.pose.position.x = float(x)
        req.pose.pose.position.y = float(y)
        req.pose.pose.orientation.w = 1.0

        future = self.capture_cli.call_async(req)
        if not self._wait_future(future, 60.0):
            self.get_logger().warn('capture_panorama timed out')
            return {
                'success': False,
                'image_paths': [],
                'error_message': 'capture_panorama timed out',
            }
        resp = future.result()

        if not resp or not resp.success:
            msg = resp.error_message if resp else 'timeout'
            image_paths = list(resp.image_paths) if resp else []
            self.get_logger().warn(
                f'capture_panorama failed: {msg}, partial images={len(image_paths)}')
            return {
                'success': False,
                'image_paths': image_paths,
                'error_message': msg,
            }

        self.get_logger().info(
            f'Captured {len(resp.image_paths)} images for node {node_id}')
        return {
            'success': True,
            'image_paths': list(resp.image_paths),
            'error_message': '',
        }

    def _annotate_and_update(self, node_id, image_paths):
        if not self.has_annotation:
            self.get_logger().warn('annotate_semantic service not available, skip semantic')
            return None
        if not self.has_update_semantic:
            self.get_logger().warn('update_semantic service not available, skip semantic')
            return None

        best_room_type = ''
        best_confidence = 0.0
        best_description = ''
        all_results = []

        for path_entry in image_paths:
            parts = path_entry.split(':', 1)
            if len(parts) == 2:
                angle_deg = int(parts[0])
                image_path = parts[1]
            else:
                angle_deg = -1
                image_path = path_entry

            req = AnnotateSemantic.Request()
            req.image_path = image_path
            req.node_id = node_id
            future = self.annotate_cli.call_async(req)
            if not self._wait_future(future, 30.0):
                self.get_logger().warn(f'annotate_semantic timed out for {image_path}')
                continue

            resp = future.result()
            if not resp or not resp.success:
                msg = resp.error_message if resp else 'timeout'
                self.get_logger().warn(f'annotate_semantic failed for {image_path}: {msg}')
                continue

            if resp.confidence > best_confidence:
                best_room_type = resp.room_type
                best_confidence = resp.confidence
                best_description = resp.description

            sem_data = SemanticData()
            sem_data.room_type = resp.room_type
            sem_data.confidence = resp.confidence
            sem_data.description = resp.description
            sem_data.objects = list(resp.objects)

            upd_req = UpdateSemantic.Request()
            upd_req.node_id = node_id
            upd_req.semantic_data = sem_data
            upd_req.angle = angle_deg
            future = self.update_sem_cli.call_async(upd_req)
            if not self._wait_future(future, 5.0):
                self.get_logger().warn(f'update_semantic timed out for node {node_id} angle {angle_deg}')
                continue

            upd_resp = future.result()
            if not upd_resp or not upd_resp.success:
                msg = upd_resp.message if upd_resp else 'timeout'
                self.get_logger().warn(f'update_semantic failed for node {node_id} angle {angle_deg}: {msg}')
                continue

            all_results.append({
                'angle': angle_deg,
                'room_type': resp.room_type,
                'objects': [o.name_cn or o.name for o in resp.objects],
            })

        if not all_results:
            return None

        self.get_logger().info(
            f'Updated semantic for node {node_id}: room={best_room_type}, viewpoints={len(all_results)}')
        return {
            'room_type': best_room_type,
            'confidence': best_confidence,
            'description': best_description,
            'viewpoints': all_results,
        }

    def _image_paths_to_panorama_paths(self, image_paths):
        panorama_paths = {}
        for entry in image_paths:
            parts = entry.split(':', 1)
            if len(parts) == 2:
                angle, image_path = parts
            else:
                image_path = entry
                angle = os.path.splitext(os.path.basename(image_path))[0]
            panorama_paths[str(angle)] = image_path
        return panorama_paths

    def _update_map_panorama_paths(self, node_id, image_paths):
        if not self.map_file:
            return

        try:
            if not os.path.exists(self.map_file):
                self.get_logger().warn(f'Map file not found, skip panorama update: {self.map_file}')
                return

            with open(self.map_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            panorama_paths = self._image_paths_to_panorama_paths(image_paths)
            updated = False
            for node_data in data.get('nodes', []):
                if node_data.get('id') != node_id:
                    continue
                node_data['panorama_paths'] = panorama_paths
                node_data['last_updated'] = time.time()
                updated = True
                break

            if not updated:
                self.get_logger().warn(f'Node {node_id} not found in map file, skip panorama update')
                return

            os.makedirs(os.path.dirname(self.map_file) or '.', exist_ok=True)
            with open(self.map_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.get_logger().info(f'Updated panorama paths for node {node_id} in {self.map_file}')
        except Exception as exc:
            self.get_logger().warn(f'Failed to update panorama paths for node {node_id}: {exc}')

    def _publish_markers(self):
        markers = MarkerArray()

        delete_marker = Marker()
        delete_marker.action = Marker.DELETEALL
        markers.markers.append(delete_marker)

        for i, node_pos in enumerate(self.nodes_for_viz):
            marker = Marker()
            marker.header.frame_id = 'map'
            marker.header.stamp = self.get_clock().now().to_msg()
            marker.ns = 'click_capture_nodes'
            marker.id = i
            marker.type = Marker.SPHERE
            marker.action = Marker.ADD
            marker.pose.position.x = float(node_pos['x'])
            marker.pose.position.y = float(node_pos['y'])
            marker.pose.position.z = 0.15
            marker.pose.orientation.w = 1.0
            marker.scale.x = 0.35
            marker.scale.y = 0.35
            marker.scale.z = 0.35

            status = node_pos['status']
            if status == 'captured':
                marker.color = ColorRGBA(r=0.1, g=0.9, b=0.2, a=0.9)
            elif status == 'semantic':
                marker.color = ColorRGBA(r=0.1, g=0.6, b=1.0, a=0.9)
            elif status == 'partial':
                marker.color = ColorRGBA(r=1.0, g=0.5, b=0.1, a=0.9)
            elif status == 'failed':
                marker.color = ColorRGBA(r=1.0, g=0.1, b=0.1, a=0.9)
            else:
                marker.color = ColorRGBA(r=1.0, g=0.9, b=0.1, a=0.9)
            markers.markers.append(marker)

            label = Marker()
            label.header.frame_id = 'map'
            label.header.stamp = self.get_clock().now().to_msg()
            label.ns = 'click_capture_labels'
            label.id = i
            label.type = Marker.TEXT_VIEW_FACING
            label.action = Marker.ADD
            label.pose.position.x = float(node_pos['x'])
            label.pose.position.y = float(node_pos['y'])
            label.pose.position.z = 0.55
            label.pose.orientation.w = 1.0
            label.scale.z = 0.28
            label.color = ColorRGBA(r=1.0, g=1.0, b=1.0, a=1.0)
            label.text = f'{i}:{status}'
            markers.markers.append(label)

        self.marker_pub.publish(markers)

    def _wait_future(self, future, timeout_sec):
        deadline = time.time() + timeout_sec
        while rclpy.ok() and not future.done():
            if time.time() >= deadline:
                return False
            time.sleep(0.05)
        return future.done()

    def _save_report(self):
        os.makedirs(os.path.dirname(self.report_file) or '.', exist_ok=True)
        with open(self.report_file, 'w', encoding='utf-8') as f:
            json.dump(
                {
                    'records': self.records,
                    'pending_count': len(self.pending),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )


def main(args=None):
    parser = argparse.ArgumentParser(
        description='点击 RViz 点位后自动导航并拍照')
    parser.add_argument('--report-file', required=True,
                        help='输出采集报告 JSON')
    parser.add_argument('--map-file', default='',
                        help='拓扑地图 JSON 路径，默认与 report-file 同目录的 topological_map_manual.json')
    parser.add_argument('--click-topic', default='/clicked_point',
                        help='RViz Publish Point 话题')
    parser.add_argument('--marker-topic', default='/topo_node_placement',
                        help='节点状态 MarkerArray 话题')
    parser.add_argument('--min-distance', type=float, default=0.5,
                        help='与已有点的最小间距')

    parsed, remaining = parser.parse_known_args(args=args)
    rclpy.init(args=remaining)

    try:
        map_file = parsed.map_file or os.path.join(
            os.path.dirname(parsed.report_file),
            'topological_map_manual.json',
        )
        node = ClickAndCaptureNode(
            report_file=parsed.report_file,
            map_file=map_file,
            click_topic=parsed.click_topic,
            marker_topic=parsed.marker_topic,
            min_distance=parsed.min_distance,
        )
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except ExternalShutdownException:
        pass
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        raise
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
