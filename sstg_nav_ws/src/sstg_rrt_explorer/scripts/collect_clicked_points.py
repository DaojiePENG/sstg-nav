#!/usr/bin/env python3
"""
collect_clicked_points.py - 从 RViz /clicked_point 手动采集拓扑节点

用法:
    ros2 run sstg_rrt_explorer collect_clicked_points.py \
      --output /path/to/manual_node_positions.json

在 RViz 中使用 Publish Point 工具点击地图，自定义节点位置。
按 Ctrl+C 退出时自动保存为 node_positions.json 兼容格式。
"""

import argparse
import json
import math
import os
import sys

import rclpy
from geometry_msgs.msg import PointStamped
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray


class ClickedPointCollector(Node):
    def __init__(self, output_path, min_distance, marker_topic, click_topic):
        super().__init__('collect_clicked_points')

        self.output_path = output_path
        self.min_distance = min_distance
        self.marker_topic = marker_topic
        self.click_topic = click_topic
        self.nodes = []

        self.click_sub = self.create_subscription(
            PointStamped, self.click_topic, self.clicked_point_callback, 10)
        self.marker_pub = self.create_publisher(
            MarkerArray, self.marker_topic, 10)
        self.timer = self.create_timer(1.0, self.publish_markers)

        self.get_logger().info(
            f'Listening on {self.click_topic}, output={self.output_path}')
        self.get_logger().info(
            f'Use RViz Publish Point to select nodes, min_distance={self.min_distance} m')

    def clicked_point_callback(self, msg):
        x = round(float(msg.point.x), 3)
        y = round(float(msg.point.y), 3)

        for existing in self.nodes:
            dx = existing['x'] - x
            dy = existing['y'] - y
            if math.hypot(dx, dy) < self.min_distance:
                self.get_logger().warn(
                    f'Ignored point ({x:.2f}, {y:.2f}) - too close to existing node')
                return

        self.nodes.append({'x': x, 'y': y})
        self.get_logger().info(
            f'Added node {len(self.nodes) - 1}: ({x:.2f}, {y:.2f})')
        self.save_nodes()

    def publish_markers(self):
        markers = MarkerArray()

        delete_marker = Marker()
        delete_marker.action = Marker.DELETEALL
        markers.markers.append(delete_marker)

        for i, node_pos in enumerate(self.nodes):
            sphere = Marker()
            sphere.header.frame_id = 'map'
            sphere.header.stamp = self.get_clock().now().to_msg()
            sphere.ns = 'manual_topo_nodes'
            sphere.id = i
            sphere.type = Marker.SPHERE
            sphere.action = Marker.ADD
            sphere.pose.position.x = float(node_pos['x'])
            sphere.pose.position.y = float(node_pos['y'])
            sphere.pose.position.z = 0.15
            sphere.pose.orientation.w = 1.0
            sphere.scale.x = 0.35
            sphere.scale.y = 0.35
            sphere.scale.z = 0.35
            sphere.color = ColorRGBA(r=0.1, g=0.9, b=0.2, a=0.9)
            markers.markers.append(sphere)

            label = Marker()
            label.header.frame_id = 'map'
            label.header.stamp = self.get_clock().now().to_msg()
            label.ns = 'manual_topo_labels'
            label.id = i
            label.type = Marker.TEXT_VIEW_FACING
            label.action = Marker.ADD
            label.pose.position.x = float(node_pos['x'])
            label.pose.position.y = float(node_pos['y'])
            label.pose.position.z = 0.55
            label.pose.orientation.w = 1.0
            label.scale.z = 0.28
            label.color = ColorRGBA(r=1.0, g=1.0, b=1.0, a=1.0)
            label.text = str(i)
            markers.markers.append(label)

        self.marker_pub.publish(markers)

    def save_nodes(self):
        result = {
            'source': 'rviz_clicked_points',
            'spacing': None,
            'wall_clearance': None,
            'resolution': None,
            'origin': None,
            'node_count': len(self.nodes),
            'nodes': self.nodes,
        }
        os.makedirs(os.path.dirname(self.output_path) or '.', exist_ok=True)
        with open(self.output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)


def main(args=None):
    parser = argparse.ArgumentParser(
        description='从 RViz /clicked_point 手动采集拓扑节点')
    parser.add_argument('--output', required=True,
                        help='输出 node_positions.json 路径')
    parser.add_argument('--min-distance', type=float, default=0.5,
                        help='与已有点的最小间距，小于该值则忽略')
    parser.add_argument('--marker-topic', default='/topo_node_placement',
                        help='已选节点 MarkerArray 发布话题')
    parser.add_argument('--click-topic', default='/clicked_point',
                        help='RViz Publish Point 话题')

    parsed, remaining = parser.parse_known_args(args=args)
    rclpy.init(args=remaining)

    node = None
    try:
        node = ClickedPointCollector(
            output_path=parsed.output,
            min_distance=parsed.min_distance,
            marker_topic=parsed.marker_topic,
            click_topic=parsed.click_topic,
        )
        rclpy.spin(node)
    except KeyboardInterrupt:
        if node is not None:
            node.save_nodes()
            node.get_logger().info(
                f'Saved {len(node.nodes)} nodes to {node.output_path}')
    except ExternalShutdownException:
        pass
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        raise
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
