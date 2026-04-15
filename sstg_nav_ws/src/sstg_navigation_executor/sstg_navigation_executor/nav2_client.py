"""
Nav2 客户端 - 与 Navigation2 框架交互
"""

from typing import Optional, Callable
from geometry_msgs.msg import PoseStamped, Quaternion
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from rclpy.task import Future
import math


class Nav2Client:
    """
    Navigation2 客户端封装
    
    功能：
    - 发送导航目标到 Nav2
    - 原地旋转控制
    - 导航状态查询
    """
    
    def __init__(self, node: Node, namespace: str = ''):
        """
        初始化 Nav2 客户端
        
        Args:
            node: ROS2 节点
            namespace: 节点命名空间 (如果有的话)
        """
        self.node = node
        self.namespace = namespace
        self.logger = node.get_logger()
        
        # 创建导航动作客户端
        self.nav_action_client = ActionClient(
            node,
            NavigateToPose,
            'navigate_to_pose' if not namespace else f'{namespace}/navigate_to_pose'
        )
        
        # 创建旋转服务客户端 (可选，如果 Nav2 支持)
        # self.spin_client = node.create_client(Spin, 'spin') # 如果需要的话
        
        self.current_goal_handle = None
        self.navigation_in_progress = False
        
    def wait_for_nav2(self, timeout_sec: float = 10.0) -> bool:
        """
        等待 Nav2 可用
        
        Args:
            timeout_sec: 超时时间（秒）
            
        Returns:
            是否成功连接
        """
        if not self.nav_action_client.wait_for_server(timeout_sec=timeout_sec):
            self.logger.error("❌ Nav2 navigate_to_pose 服务不可用")
            return False
        self.logger.info("✓ Nav2 navigate_to_pose 服务可用")
        return True
    
    def send_goal(
        self,
        x: float,
        y: float,
        theta: float,
        frame_id: str = 'map',
        callback: Optional[Callable] = None
    ) -> bool:
        """
        发送导航目标
        
        Args:
            x: 目标 X 坐标
            y: 目标 Y 坐标
            theta: 目标方向（弧度）
            frame_id: 坐标系
            callback: 完成回调函数
            
        Returns:
            是否成功发送
        """
        if self.navigation_in_progress:
            self.logger.warn("⚠️  导航已在进行中，取消当前导航并切换到新目标")
            self.cancel_goal()
            self.current_goal_handle = None
            self.navigation_in_progress = False
        
        # 构造 PoseStamped
        pose = PoseStamped()
        pose.header.frame_id = frame_id
        pose.header.stamp = self.node.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.position.z = 0.0
        
        # 将欧拉角转换为四元数
        quat = self._euler_to_quaternion(0, 0, theta)
        pose.pose.orientation = quat
        
        # 创建导航目标
        goal = NavigateToPose.Goal()
        goal.pose = pose
        
        # 发送目标
        self.navigation_in_progress = True
        self.logger.info(f"📍 发送导航目标: ({x:.2f}, {y:.2f}), θ={math.degrees(theta):.1f}°")
        
        send_goal_future = self.nav_action_client.send_goal_async(goal)
        send_goal_future.add_done_callback(
            lambda future: self._goal_response_callback(future, callback)
        )
        
        return True
    
    def _goal_response_callback(self, future: Future, user_callback: Optional[Callable]):
        """处理目标发送响应"""
        goal_handle = future.result()
        
        if not goal_handle.accepted:
            self.logger.error("❌ 导航目标被拒绝")
            self.navigation_in_progress = False
            if user_callback:
                user_callback(False, "目标被拒绝")
            return
        
        self.logger.info("✓ 导航目标已接受")
        self.current_goal_handle = goal_handle
        
        # 等待结果
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(
            lambda future: self._get_result_callback(future, user_callback)
        )
    
    def _get_result_callback(self, future: Future, user_callback: Optional[Callable]):
        """处理导航结果"""
        try:
            result_wrapper = future.result()
            status = result_wrapper.status
            # action_msgs/GoalStatus codes:
            #   2=STATUS_ACCEPTED, 4=STATUS_SUCCEEDED, 5=STATUS_CANCELED, 6=STATUS_ABORTED
            STATUS_SUCCEEDED = 4
            STATUS_CANCELED = 5
            STATUS_ABORTED = 6

            self.navigation_in_progress = False

            if status == STATUS_SUCCEEDED:
                self.logger.info("✓ 导航完成")
                if user_callback:
                    user_callback(True, "导航成功")
            elif status == STATUS_CANCELED:
                self.logger.warn("🛑 导航已取消")
                if user_callback:
                    user_callback(False, "导航被取消")
            elif status == STATUS_ABORTED:
                self.logger.error("❌ 导航中止 (Nav2 abort)")
                if user_callback:
                    user_callback(False, "导航中止: 路径规划失败或机器人卡住，请检查定位和障碍物")
            else:
                self.logger.error(f"❌ 导航失败 (status={status})")
                if user_callback:
                    user_callback(False, f"导航异常 (status={status})")
        except Exception as e:
            self.navigation_in_progress = False
            self.logger.error(f"❌ 导航结果回调异常: {e}")
            if user_callback:
                user_callback(False, f"导航结果异常: {e}")
    
    def cancel_goal(self) -> bool:
        """
        取消当前导航
        
        Returns:
            是否成功取消
        """
        if not self.current_goal_handle:
            self.logger.warn("⚠️  没有正在进行的导航")
            return False
        
        self.logger.info("🛑 取消导航")
        cancel_future = self.current_goal_handle.cancel_goal_async()
        cancel_future.add_done_callback(self._cancel_callback)
        
        return True
    
    def _cancel_callback(self, future: Future):
        """处理取消响应"""
        if future.result().cancel_response.return_code == 1:  # CancelResponse.ERROR_GOAL_TERMINATED
            self.logger.info("✓ 导航已取消")
            self.navigation_in_progress = False
        else:
            self.logger.warn("⚠️  取消导航未成功")
    
    def is_navigating(self) -> bool:
        """
        查询导航状态
        
        Returns:
            是否正在导航
        """
        return self.navigation_in_progress
    
    def get_current_goal_id(self) -> Optional[int]:
        """
        获取当前目标 ID
        
        Returns:
            目标 ID（如果有的话）
        """
        if self.current_goal_handle:
            return self.current_goal_handle.goal_id.uuid[:4]  # 简化的 ID
        return None
    
    @staticmethod
    def _euler_to_quaternion(roll: float, pitch: float, yaw: float) -> Quaternion:
        """
        将欧拉角转换为四元数
        
        Args:
            roll: 滚转角（弧度）
            pitch: 俯仰角（弧度）
            yaw: 偏航角（弧度）
            
        Returns:
            四元数
        """
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)
        
        quat = Quaternion()
        quat.w = cr * cp * cy + sr * sp * sy
        quat.x = sr * cp * cy - cr * sp * sy
        quat.y = cr * sp * cy + sr * cp * sy
        quat.z = cr * cp * sy - sr * sp * cy
        
        return quat
    
    @staticmethod
    def _quaternion_to_euler(quat: Quaternion) -> tuple:
        """
        将四元数转换为欧拉角
        
        Args:
            quat: 四元数
            
        Returns:
            (roll, pitch, yaw) - 弧度
        """
        x, y, z, w = quat.x, quat.y, quat.z, quat.w
        
        # Roll (x-axis rotation)
        sinr_cosp = 2 * (w * x + y * z)
        cosr_cosp = 1 - 2 * (x * x + y * y)
        roll = math.atan2(sinr_cosp, cosr_cosp)
        
        # Pitch (y-axis rotation)
        sinp = 2 * (w * y - z * x)
        if abs(sinp) >= 1:
            pitch = math.copysign(math.pi / 2, sinp)
        else:
            pitch = math.asin(sinp)
        
        # Yaw (z-axis rotation)
        siny_cosp = 2 * (w * z + x * y)
        cosy_cosp = 1 - 2 * (y * y + z * z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        
        return roll, pitch, yaw
