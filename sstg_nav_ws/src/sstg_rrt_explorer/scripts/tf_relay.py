#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from tf2_ros import TransformBroadcaster
from tf2_msgs.msg import TFMessage

class TFRelay(Node):
    def __init__(self):
        super().__init__('tf_relay')

        self.tf_broadcaster = TransformBroadcaster(self)

        # Subscribe to robot1's TF
        self.tf_sub = self.create_subscription(
            TFMessage,
            '/tf',
            self.tf_callback,
            10
        )

        self.get_logger().info('TF relay started')

    def tf_callback(self, msg):
        for transform in msg.transforms:
            # Only relay transforms with robot1/ prefix
            if 'robot1/' in transform.header.frame_id or 'robot1/' in transform.child_frame_id:
                # Remove robot1/ prefix
                transform.header.frame_id = transform.header.frame_id.replace('robot1/', '')
                transform.child_frame_id = transform.child_frame_id.replace('robot1/', '')

                # Republish
                self.tf_broadcaster.sendTransform(transform)

def main():
    rclpy.init()
    node = TFRelay()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
