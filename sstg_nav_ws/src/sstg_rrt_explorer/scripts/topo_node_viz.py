#!/usr/bin/env python3
"""发布拓扑节点为 RViz MarkerArray，持续刷新。"""
import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray

MAP_FILE = '/home/daojie/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/maps/topological_map_manual.json'

class TopoViz(Node):
    def __init__(self):
        super().__init__('topo_node_viz')
        self.declare_parameter('map_file', MAP_FILE)
        map_file = self.get_parameter('map_file').get_parameter_value().string_value
        self.pub = self.create_publisher(MarkerArray, '/topo_node_markers', 10)
        with open(map_file) as f:
            data = json.load(f)
        self.nodes = data.get('nodes', [])
        self.get_logger().info(f'Loaded {len(self.nodes)} topo nodes from {map_file}')
        self.timer = self.create_timer(1.0, self.publish_markers)

    def publish_markers(self):
        ma = MarkerArray()

        for i, n in enumerate(self.nodes):
            pose = n.get('pose', n.get('position', {}))
            x, y = pose.get('x', 0.0), pose.get('y', 0.0)
            sem = n.get('semantic_info', {})
            room = sem.get('room_type_cn', sem.get('room_type', ''))
            objects = [o.get('name_cn', o.get('name', '')) for o in sem.get('objects', [])]
            label = f"N{n['id']}: {room}\n{', '.join(objects[:4])}"

            # Sphere marker
            m = Marker()
            m.header.frame_id = 'map'
            m.header.stamp = self.get_clock().now().to_msg()
            m.ns = 'topo_nodes'
            m.id = i
            m.type = Marker.SPHERE
            m.action = Marker.ADD
            m.pose.position.x = x
            m.pose.position.y = y
            m.pose.position.z = 0.15
            m.pose.orientation.w = 1.0
            m.scale.x = m.scale.y = m.scale.z = 0.25
            m.color = ColorRGBA(r=0.2, g=0.6, b=1.0, a=0.9)
            ma.markers.append(m)

            # Text marker
            t = Marker()
            t.header.frame_id = 'map'
            t.header.stamp = self.get_clock().now().to_msg()
            t.ns = 'topo_labels'
            t.id = i
            t.type = Marker.TEXT_VIEW_FACING
            t.action = Marker.ADD
            t.pose.position.x = x
            t.pose.position.y = y
            t.pose.position.z = 0.4
            t.pose.orientation.w = 1.0
            t.scale.z = 0.15
            t.color = ColorRGBA(r=1.0, g=1.0, b=1.0, a=1.0)
            t.text = label
            ma.markers.append(t)

        self.pub.publish(ma)

def main():
    rclpy.init()
    node = TopoViz()
    rclpy.spin(node)

if __name__ == '__main__':
    main()
