"""
ROS2 相机订阅器 - RGB-D 图像捕获
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import numpy as np
from collections import deque
from typing import Callable, Optional
import threading


class CameraSubscriber(Node):
    """
    订阅 RGB-D 相机话题，提供最新图像获取功能
    
    支持的话题：
    - /camera/rgb/image_raw (sensor_msgs/Image)
    - /camera/depth/image_raw (sensor_msgs/Image)
    """
    
    def __init__(self, rgb_topic: str = '/camera/color/image_raw',
                 depth_topic: str = '/camera/depth/image_raw',
                 image_buffer_size: int = 5):
        """
        初始化相机订阅器
        
        Args:
            rgb_topic: RGB 图像话题
            depth_topic: 深度图话题
            image_buffer_size: 图像缓冲区大小
        """
        super().__init__('camera_subscriber')
        
        self.rgb_topic = rgb_topic
        self.depth_topic = depth_topic
        self.bridge = CvBridge()
        
        self.rgb_image = None
        self.depth_image = None
        self.rgb_buffer = deque(maxlen=image_buffer_size)
        self.depth_buffer = deque(maxlen=image_buffer_size)
        
        self.lock = threading.Lock()
        self.callbacks = []
        
        # 订阅相机话题 - 使用RELIABLE QoS以匹配相机发布者
        qos_profile = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            durability=rclpy.qos.DurabilityPolicy.VOLATILE,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=10
        )

        self.rgb_subscription = self.create_subscription(
            Image,
            rgb_topic,
            self._rgb_callback,
            qos_profile=qos_profile
        )

        self.depth_subscription = self.create_subscription(
            Image,
            depth_topic,
            self._depth_callback,
            qos_profile=qos_profile
        )
        
        self.get_logger().info(
            f'CameraSubscriber initialized:\n'
            f'  RGB Topic: {rgb_topic}\n'
            f'  Depth Topic: {depth_topic}'
        )
    
    def _rgb_callback(self, msg: Image) -> None:
        """RGB 图像回调"""
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            with self.lock:
                self.rgb_image = cv_image
                self.rgb_buffer.append(cv_image.copy())
            
            for callback in self.callbacks:
                callback('rgb', cv_image)
                
        except Exception as e:
            self.get_logger().error(f'RGB callback error: {e}')
    
    def _depth_callback(self, msg: Image) -> None:
        """深度图回调"""
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
            with self.lock:
                self.depth_image = cv_image
                self.depth_buffer.append(cv_image.copy())
                
        except Exception as e:
            self.get_logger().error(f'Depth callback error: {e}')
    
    def get_latest_rgb(self) -> Optional[np.ndarray]:
        """获取最新的 RGB 图像"""
        with self.lock:
            return self.rgb_image.copy() if self.rgb_image is not None else None
    
    def get_latest_depth(self) -> Optional[np.ndarray]:
        """获取最新的深度图"""
        with self.lock:
            return self.depth_image.copy() if self.depth_image is not None else None
    
    def get_latest_pair(self) -> tuple:
        """获取最新的 RGB-D 图像对"""
        with self.lock:
            rgb = self.rgb_image.copy() if self.rgb_image is not None else None
            depth = self.depth_image.copy() if self.depth_image is not None else None
        return rgb, depth
    
    def register_callback(self, callback: Callable) -> None:
        """注册图像获取回调"""
        self.callbacks.append(callback)
    
    def is_ready(self) -> bool:
        """检查是否已收到图像"""
        with self.lock:
            return self.rgb_image is not None and self.depth_image is not None
    
    def wait_for_images(self, timeout: float = 10.0) -> bool:
        """等待第一次接收图像"""
        import time

        # 给节点一点时间建立订阅连接
        self.get_logger().info('Waiting for subscriptions to establish...')
        time.sleep(0.5)

        start_time = time.time()
        check_count = 0
        while time.time() - start_time < timeout:
            # 核心修复：处理 ROS2 消息，让回调被触发
            rclpy.spin_once(self, timeout_sec=0.1)
            check_count += 1

            if check_count % 10 == 0:
                rgb_ready = self.rgb_image is not None
                depth_ready = self.depth_image is not None
                self.get_logger().info(
                    f'Checking... RGB: {rgb_ready}, Depth: {depth_ready}'
                )

            if self.is_ready():
                self.get_logger().info('Images received!')
                return True

        self.get_logger().warn(
            f'Timeout waiting for images after {timeout}s. '
            f'RGB: {self.rgb_image is not None}, Depth: {self.depth_image is not None}'
        )
        return False


def main(args=None):
    """测试相机订阅"""
    rclpy.init(args=args)
    node = CameraSubscriber()
    
    try:
        if node.wait_for_images(timeout=10):
            print("✓ Camera is working!")
        else:
            print("✗ Camera not responding")
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
