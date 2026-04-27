import time

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from tf2_ros import Buffer, TransformException, TransformListener


class SystemChecker(Node):
    def __init__(self):
        super().__init__('hw_robot_nav_check_system')
        self.declare_parameter('scan_topic', '/scan')
        self.declare_parameter('odom_topic', '/odom')
        self.declare_parameter('cmd_vel_topic', '/cmd_vel')
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_footprint')
        self.declare_parameter('laser_frame', 'laser')
        self.declare_parameter('timeout_sec', 5.0)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

    def topic_exists(self, topic_name):
        return any(name == topic_name for name, _ in self.get_topic_names_and_types())

    def wait_for_topic(self, topic_name, timeout_sec):
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.topic_exists(topic_name):
                return True
        return False

    def wait_for_transform(self, target_frame, source_frame, timeout_sec):
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            try:
                if self.tf_buffer.can_transform(
                    target_frame,
                    source_frame,
                    rclpy.time.Time(),
                    timeout=Duration(seconds=0.1),
                ):
                    return True
            except TransformException:
                pass
        return False

    def run_checks(self):
        timeout_sec = float(self.get_parameter('timeout_sec').value)
        scan_topic = self.get_parameter('scan_topic').value
        odom_topic = self.get_parameter('odom_topic').value
        cmd_vel_topic = self.get_parameter('cmd_vel_topic').value
        odom_frame = self.get_parameter('odom_frame').value
        base_frame = self.get_parameter('base_frame').value
        laser_frame = self.get_parameter('laser_frame').value

        checks = [
            (f'topic {scan_topic}', self.wait_for_topic(scan_topic, timeout_sec)),
            (f'topic {odom_topic}', self.wait_for_topic(odom_topic, timeout_sec)),
            (f'topic {cmd_vel_topic}', self.wait_for_topic(cmd_vel_topic, timeout_sec)),
            (
                f'tf {base_frame} -> {laser_frame}',
                self.wait_for_transform(base_frame, laser_frame, timeout_sec),
            ),
            (
                f'tf {odom_frame} -> {base_frame}',
                self.wait_for_transform(odom_frame, base_frame, timeout_sec),
            ),
        ]

        all_ok = True
        for label, ok in checks:
            if ok:
                self.get_logger().info(f'[OK] {label}')
            else:
                self.get_logger().error(f'[MISSING] {label}')
                all_ok = False

        if not all_ok:
            self.get_logger().error(
                'Navigation will not be stable until every required topic and TF is present.'
            )
            return 1

        self.get_logger().info('hw_robot navigation interfaces look ready.')
        return 0


def main(args=None):
    rclpy.init(args=args)
    node = SystemChecker()
    try:
        return_code = node.run_checks()
    finally:
        node.destroy_node()
        rclpy.shutdown()
    raise SystemExit(return_code)
