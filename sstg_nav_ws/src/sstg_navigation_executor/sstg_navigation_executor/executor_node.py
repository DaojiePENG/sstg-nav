"""
Navigation Executor Node - Main ROS2 Node
"""

import rclpy
from rclpy.node import Node
import sys
import json
import math
from typing import Optional, Dict

try:
    import sstg_msgs.srv as sstg_srv
    import sstg_msgs.msg as sstg_msg
except ImportError:
    class DummyModule:
        pass
    sstg_srv = DummyModule()
    sstg_msg = DummyModule()

from sstg_navigation_executor.nav2_client import Nav2Client
from sstg_navigation_executor.navigation_monitor import NavigationMonitor
from sstg_navigation_executor.feedback_handler import FeedbackHandler, NavigationStatus


print("OK Nav2Client initialized")
print("OK NavigationMonitor initialized")
print("OK FeedbackHandler initialized")


class ExecutorNode(Node):
    """
    Navigation Executor Node
    
    Functions:
    - Receive navigation plans
    - Call Nav2 for navigation
    - Monitor navigation progress
    - Publish feedback
    """
    
    def __init__(self):
        super().__init__('executor_node')
        
        self.declare_parameter('nav2_available', True)
        self.declare_parameter('position_threshold', 0.2)
        self.declare_parameter('orientation_threshold', 0.1)
        self.declare_parameter('update_rate', 10)
        
        self.nav2_available = self.get_parameter('nav2_available').value
        self.position_threshold = self.get_parameter('position_threshold').value
        self.orientation_threshold = self.get_parameter('orientation_threshold').value
        update_rate = self.get_parameter('update_rate').value
        
        self.nav2_client = Nav2Client(self) if self.nav2_available else None
        self.monitor = NavigationMonitor(self)
        self.feedback_handler = FeedbackHandler()
        
        self.current_node_id = None
        self.initial_distance = 0.0
        
        self.feedback_pub = self.create_publisher(
            sstg_msg.NavigationFeedback,
            'navigation_feedback',
            qos_profile=rclpy.qos.QoSProfile(depth=10)
        )
        
        try:
            self.create_service(
                sstg_srv.ExecuteNavigation,
                'execute_navigation',
                self._execute_navigation_callback
            )
            self.get_logger().info("OK ExecuteNavigation service registered")
        except Exception as e:
            self.get_logger().warn(f"Could not register ExecuteNavigation service: {e}")
        
        timer_period = 1.0 / update_rate
        self.timer = self.create_timer(timer_period, self._update_progress)
        
        self.get_logger().info('OK Executor Node initialized')
    
    def _execute_navigation_callback(self, request, response):
        """
        Handle navigation execution request
        """
        try:
            node_id = request.node_id if hasattr(request, 'node_id') else 0
            target_x = request.target_pose.pose.position.x if hasattr(request, 'target_pose') else 0.0
            target_y = request.target_pose.pose.position.y if hasattr(request, 'target_pose') else 0.0
            
            if hasattr(request, 'target_pose') and hasattr(request.target_pose, 'pose') and request.target_pose.pose.orientation:
                quat = request.target_pose.pose.orientation
                from tf_transformations import euler_from_quaternion
                _, _, target_theta = euler_from_quaternion([quat.x, quat.y, quat.z, quat.w])
            else:
                target_theta = 0.0
            
            self.get_logger().info(f"Executing navigation: node {node_id}, pos ({target_x:.2f}, {target_y:.2f})")
            
            self._start_navigation(node_id, target_x, target_y, target_theta)
            
            response.success = True
            response.message = f"Navigation started: node {node_id}"
            
        except Exception as e:
            response.success = False
            response.message = str(e)
            self.get_logger().error(f"Error executing navigation: {e}")
        
        return response
    
    def _start_navigation(self, node_id: int, x: float, y: float, theta: float = 0.0):
        """
        Start navigation
        """
        self.feedback_handler.start_navigation(node_id)
        self.current_node_id = node_id
        
        self.monitor.set_target(x, y, theta)
        self.initial_distance = self.monitor.get_distance_to_target()
        
        if self.nav2_available and self.nav2_client:
            self.nav2_client.send_goal(x, y, theta, callback=self._navigate_complete_callback)
        else:
            self.get_logger().info("Nav2 not available, using simulation")
            self._simulate_navigation(x, y, theta)
    
    def _navigate_complete_callback(self, success: bool, message: str):
        """Nav2 navigation complete callback"""
        if success:
            self.feedback_handler.on_reached()
            self.get_logger().info("OK Nav2 navigation succeeded")
        else:
            self.feedback_handler.on_failed(message)
            self.get_logger().error(f"ERROR Nav2 navigation failed: {message}")
        
        self._publish_feedback()
    
    def _simulate_navigation(self, x: float, y: float, theta: float):
        """
        Simulate navigation for testing
        """
        self.get_logger().info("SIMULATION Navigation started")
        self.feedback_handler.on_reached()
        self._publish_feedback()
    
    def _update_progress(self):
        """Update navigation progress regularly"""
        feedback = self.feedback_handler.get_current_feedback()
        
        if not feedback or feedback.status not in [NavigationStatus.STARTING, NavigationStatus.IN_PROGRESS]:
            return
        
        distance = self.monitor.get_distance_to_target()
        progress = self.monitor.get_progress(self.initial_distance)
        current_pose = self.monitor.get_current_pose()
        
        estimated_speed = 0.5
        estimated_time = distance / estimated_speed if estimated_speed > 0 else 0.0
        
        self.feedback_handler.update_progress(
            progress=progress,
            current_pose=current_pose,
            distance_to_target=distance,
            estimated_time=estimated_time
        )
        
        if self.monitor.is_near_target(threshold=self.position_threshold):
            if not self.nav2_available:
                self.feedback_handler.on_reached()
                self.get_logger().info("OK Reached target")
        
        self._publish_feedback()
    
    def _publish_feedback(self):
        """Publish feedback information"""
        feedback = self.feedback_handler.get_current_feedback()
        if not feedback:
            return
        
        try:
            msg = sstg_msg.NavigationFeedback()
            msg.node_id = feedback.node_id
            msg.status = feedback.status.value
            msg.progress = feedback.progress
            msg.distance_to_target = feedback.distance_to_target
            msg.estimated_time_remaining = feedback.estimated_time_remaining
            msg.error_message = feedback.error_message
            
            msg.current_pose.position.x = feedback.current_pose[0]
            msg.current_pose.position.y = feedback.current_pose[1]
            
            self.feedback_pub.publish(msg)
            
        except Exception as e:
            self.get_logger().debug(f"Could not publish feedback: {e}")


def main(args=None):
    """Main function"""
    rclpy.init(args=args)
    
    try:
        node = ExecutorNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
