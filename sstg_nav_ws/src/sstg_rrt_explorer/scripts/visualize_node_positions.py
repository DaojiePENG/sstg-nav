#!/usr/bin/env python3
"""
visualize_node_positions.py - 将 node_positions.json 发布到 RViz

用法:
    ros2 run sstg_rrt_explorer visualize_node_positions.py \
      --nodes /path/to/node_positions.json
"""

import argparse
import json
import sys

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray


class NodePositionsVisualizer(Node):
    def __init__(self, nodes_file, topic, frame_id):
        super().__init__('visualize_node_positions')

        self.nodes_file = nodes_file
        self.topic = topic
        self.frame_id = frame_id
        self.nodes = self._load_nodes()
        self.marker_pub = self.create_publisher(MarkerArray, self.topic, 10)
        self.timer = self.create_timer(1.0, self.publish_markers)

        self.get_logger().info(
            f'Loaded {len(self.nodes)} nodes from {self.nodes_file}')
        self.get_logger().info(
            f'Publishing markers to {self.topic} in frame {self.frame_id}')

    def _load_nodes(self):
        with open(self.nodes_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        nodes = data.get('nodes', [])
        if not nodes:
            raise RuntimeError(f'No nodes found in {self.nodes_file}')
        return nodes

    def publish_markers(self):
        markers = MarkerArray()

        delete_marker = Marker()
        delete_marker.action = Marker.DELETEALL
        markers.markers.append(delete_marker)

        for i, node_pos in enumerate(self.nodes):
            sphere = Marker()
            sphere.header.frame_id = self.frame_id
            sphere.header.stamp = self.get_clock().now().to_msg()
            sphere.ns = 'saved_topo_nodes'
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
            label.header.frame_id = self.frame_id
            label.header.stamp = self.get_clock().now().to_msg()
            label.ns = 'saved_topo_labels'
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


def main(args=None):
    parser = argparse.ArgumentParser(
        description='将 node_positions.json 发布到 RViz')
    parser.add_argument('--nodes', required=True,
                        help='node_positions.json 文件路径')
    parser.add_argument('--topic', default='/topo_node_placement',
                        help='MarkerArray 发布话题')
    parser.add_argument('--frame-id', default='map',
                        help='RViz 坐标系 frame_id')

    parsed, remaining = parser.parse_known_args(args=args)
    rclpy.init(args=remaining)

    try:
        node = NodePositionsVisualizer(
            nodes_file=parsed.nodes,
            topic=parsed.topic,
            frame_id=parsed.frame_id,
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
