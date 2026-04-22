#!/usr/bin/env python3
# coding:utf-8
import math
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
import numpy as np

RAD2DEG = 180 / math.pi


class ScanCompression(Node):
    def __init__(self):
        super().__init__('scan_dilute')
        self.multiple = 3
        self.pub = self.create_publisher(LaserScan, 'scan_dilute', 1000)
        self.laserSub = self.create_subscription(LaserScan, 'scan', self.laserCallback, 1000)

    def laserCallback(self, data):
        if not isinstance(data, LaserScan):
            return
        laser_scan = LaserScan()
        laser_scan.header.stamp = data.header.stamp
        laser_scan.header.frame_id = data.header.frame_id
        laser_scan.angle_increment = data.angle_increment * self.multiple
        laser_scan.time_increment = data.time_increment
        laser_scan.intensities = data.intensities
        laser_scan.scan_time = data.scan_time
        laser_scan.angle_min = data.angle_min
        laser_scan.angle_max = data.angle_max
        laser_scan.range_min = data.range_min
        laser_scan.range_max = data.range_max
        laser_scan.ranges = [data.ranges[i] for i in range(len(data.ranges)) if i % self.multiple == 0]
        self.pub.publish(laser_scan)


def main(args=None):
    rclpy.init(args=args)
    node = ScanCompression()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
