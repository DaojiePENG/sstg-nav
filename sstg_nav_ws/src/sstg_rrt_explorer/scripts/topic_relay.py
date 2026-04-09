#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry

class TopicRelay(Node):
    def __init__(self):
        super().__init__('topic_relay')

        # QoS for sensor data
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=5
        )

        # Relay scan and remove namespace from frame_id
        self.scan_sub = self.create_subscription(LaserScan, '/robot1/scan', self.scan_callback, sensor_qos)
        self.scan_pub = self.create_publisher(LaserScan, '/scan', sensor_qos)

        # Relay odom and remove namespace from frame_ids
        self.odom_sub = self.create_subscription(Odometry, '/robot1/odom', self.odom_callback, 10)
        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)

        self.get_logger().info('Topic relay started')

    def scan_callback(self, msg):
        # Remove robot1/ prefix from frame_id
        msg.header.frame_id = msg.header.frame_id.replace('robot1/', '')
        self.scan_pub.publish(msg)

    def odom_callback(self, msg):
        # Remove robot1/ prefix from frame_ids
        msg.header.frame_id = msg.header.frame_id.replace('robot1/', '')
        msg.child_frame_id = msg.child_frame_id.replace('robot1/', '')
        self.odom_pub.publish(msg)

def main():
    rclpy.init()
    node = TopicRelay()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
