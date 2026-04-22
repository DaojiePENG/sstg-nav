#!/usr/bin/env python3

# ROS2 conversion of frontier_opencv_detector.py
import rclpy
from rclpy.node import Node
from visualization_msgs.msg import Marker
from nav_msgs.msg import OccupancyGrid
from geometry_msgs.msg import PointStamped
from getfrontier_ros2 import getfrontier


class DetectorNode(Node):
    def __init__(self):
        super().__init__('detector')

        # Declare parameters
        self.declare_parameter('map_topic', '/map')

        # Get parameters
        map_topic = self.get_parameter('map_topic').value

        # Initialize variables
        self.mapData = OccupancyGrid()

        # Subscribers
        self.map_sub = self.create_subscription(
            OccupancyGrid, map_topic, self.mapCallBack, 10)

        # Publishers
        self.targets_pub = self.create_publisher(PointStamped, '/detected_points', 10)
        self.shapes_pub = self.create_publisher(Marker, 'shapes', 10)

        self.get_logger().info('Detector node initialized')

    def mapCallBack(self, data):
        self.mapData = data

    def run(self):
        # Wait for map
        while len(self.mapData.data) < 1 and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.1)

        # Initialize marker
        points = Marker()
        points.header.frame_id = self.mapData.header.frame_id
        points.ns = "markers"
        points.id = 0
        points.type = Marker.POINTS
        points.action = Marker.ADD
        points.pose.orientation.w = 1.0
        points.scale.x = 0.3
        points.scale.y = 0.3
        points.color.r = 1.0
        points.color.g = 0.0
        points.color.b = 0.0
        points.color.a = 1.0

        rate = self.create_rate(50)

        # Main loop
        while rclpy.ok():
            frontiers = getfrontier(self.mapData)
            for i in range(len(frontiers)):
                x = frontiers[i]
                exploration_goal = PointStamped()
                exploration_goal.header.frame_id = self.mapData.header.frame_id
                exploration_goal.header.stamp = rclpy.time.Time().to_msg()
                exploration_goal.point.x = float(x[0])
                exploration_goal.point.y = float(x[1])
                exploration_goal.point.z = 0.0

                self.targets_pub.publish(exploration_goal)
                points.points = [exploration_goal.point]
                points.header.stamp = self.get_clock().now().to_msg()
                self.shapes_pub.publish(points)

            rate.sleep()


def main(args=None):
    rclpy.init(args=args)
    node = DetectorNode()
    node.run()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
