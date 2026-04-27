import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


class ScanDownsampler(Node):
    def __init__(self):
        super().__init__('scan_downsampler')
        self.declare_parameter('input_scan_topic', '/scan')
        self.declare_parameter('output_scan_topic', '/scan_gmapping')
        self.declare_parameter('max_beams', 1800)

        input_topic = self.get_parameter('input_scan_topic').value
        output_topic = self.get_parameter('output_scan_topic').value
        self.max_beams = int(self.get_parameter('max_beams').value)

        if self.max_beams < 2:
            raise ValueError('max_beams must be >= 2')

        self.publisher = self.create_publisher(LaserScan, output_topic, 10)
        self.subscription = self.create_subscription(
            LaserScan,
            input_topic,
            self.scan_callback,
            10,
        )
        self.get_logger().info(
            f'Downsampling {input_topic} -> {output_topic}, max_beams={self.max_beams}'
        )

    def scan_callback(self, msg):
        beam_count = len(msg.ranges)
        if beam_count <= self.max_beams:
            self.publisher.publish(msg)
            return

        step = int(math.ceil(beam_count / self.max_beams))
        ranges = msg.ranges[::step]

        out = LaserScan()
        out.header = msg.header
        out.angle_min = msg.angle_min
        out.angle_increment = msg.angle_increment * step
        out.angle_max = out.angle_min + out.angle_increment * (len(ranges) - 1)
        out.time_increment = msg.time_increment * step
        out.scan_time = msg.scan_time
        out.range_min = msg.range_min
        out.range_max = msg.range_max
        out.ranges = ranges

        if len(msg.intensities) == beam_count:
            out.intensities = msg.intensities[::step]
        else:
            out.intensities = msg.intensities

        self.publisher.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = ScanDownsampler()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
