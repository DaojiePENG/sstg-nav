"""
全景图采集管理器 - 自主导航并采集四方向图像
集成Nav2导航功能，给定位姿即可完成采集
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Optional, Callable
from datetime import datetime
import json
import threading
import time
import math

# Nav2导航
try:
    from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
    from geometry_msgs.msg import PoseStamped, Quaternion
    import rclpy
    NAV2_AVAILABLE = True
except ImportError:
    NAV2_AVAILABLE = False
    print("Warning: Nav2 Simple Commander not available")


class PanoramaCapture:
    """
    全景图采集管理器

    功能：
    - 自动导航到目标位姿（使用Nav2）
    - 自动旋转到四个方向（0°, 90°, 180°, 270°）
    - 采集RGB-D图像
    - 保存图像和元数据

    使用方式：
        capture = PanoramaCapture(
            camera_subscriber=camera,
            storage_path='/tmp/sstg_perception'
        )

        # 自动导航并采集
        result = capture.capture_at_pose(
            node_id=0,
            pose={'x': 2.0, 'y': 1.5, 'theta': 0.0},
            frame_id='map'
        )
    """

    def __init__(self,
                 camera_subscriber,
                 storage_path: str = '/tmp/sstg_panorama',
                 image_format: str = 'png',
                 enable_navigation: bool = True):
        """
        初始化全景图采集器

        Args:
            camera_subscriber: CameraSubscriber实例（必需）
            storage_path: 图像存储路径
            image_format: 图像格式 ('png' or 'jpg')
            enable_navigation: 是否启用自动导航（False时仅原地采集）
        """
        # 先初始化日志函数（必须在最前面）
        self.get_logger_func = print

        self.camera = camera_subscriber
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.image_format = image_format
        self.panorama_angles = [0, 90, 180, 270]  # 四个采集方向
        self.enable_navigation = enable_navigation and NAV2_AVAILABLE

        # 状态
        self.images = {}  # {angle: image_array}
        self.image_paths = {}  # {angle: file_path}
        self.node_id = None
        self.timestamp = None
        self.pose = None
        self.lock = threading.Lock()

        # 导航器（在日志函数初始化后）
        self.navigator = None
        if self.enable_navigation:
            try:
                self.navigator = BasicNavigator()
                self.get_logger_func(f'✓ Navigation enabled (Nav2)')
            except Exception as e:
                self.get_logger_func(f'✗ Failed to initialize navigator: {e}')
                self.enable_navigation = False

    def set_logger(self, logger_func: Callable) -> None:
        """设置日志函数"""
        self.get_logger_func = logger_func

    def capture_at_pose(self,
                       node_id: int,
                       pose: Dict,
                       frame_id: str = 'map',
                       navigate: bool = True,
                       wait_after_rotation: float = 2.0) -> Optional[Dict]:
        """
        在指定位姿采集全景图（主入口方法）

        Args:
            node_id: 拓扑节点ID
            pose: 目标位姿 {'x': float, 'y': float, 'theta': float}
            frame_id: 坐标系（'map' or 'odom'）
            navigate: 是否导航到目标点（False则在当前位置采集）
            wait_after_rotation: 旋转后等待时间（秒）

        Returns:
            成功返回采集数据字典，失败返回None
            {
                'node_id': int,
                'pose': dict,
                'timestamp': str,
                'images': {angle: path},
                'complete': bool
            }
        """
        self.node_id = node_id
        self.pose = pose
        self._reset_current_panorama()

        self.get_logger_func(f'\n{"="*60}')
        self.get_logger_func(f'🎯 Starting panorama capture at node {node_id}')
        self.get_logger_func(f'   Target: x={pose["x"]:.2f}, y={pose["y"]:.2f}, θ={pose["theta"]:.1f}°')
        self.get_logger_func(f'{"="*60}')

        # 步骤1: 导航到目标点（如果需要）
        if navigate and self.enable_navigation:
            self.get_logger_func(f'\n[Step 1/3] 🚗 Navigating to target pose...')
            if not self._navigate_to_pose(pose, frame_id):
                self.get_logger_func(f'✗ Navigation failed')
                return None
            self.get_logger_func(f'✓ Arrived at target')
        else:
            if navigate and not self.enable_navigation:
                self.get_logger_func(f'\n[Step 1/3] ⚠️  Navigation disabled, capturing at current location')
            else:
                self.get_logger_func(f'\n[Step 1/3] ⏭️  Skipping navigation, capturing at current location')

        # 步骤2: 旋转并采集四个方向
        self.get_logger_func(f'\n[Step 2/3] 📸 Capturing 4 directions...')
        all_paths = {}

        for idx, angle in enumerate(self.panorama_angles):
            self.get_logger_func(f'\n  Direction {idx+1}/4: {angle}°')

            # 旋转到目标角度
            if self.enable_navigation:
                self.get_logger_func(f'  🔄 Rotating to {angle}°...')
                if not self._rotate_to_angle(angle, frame_id):
                    self.get_logger_func(f'  ✗ Rotation failed')
                    return None

                # 等待稳定
                self.get_logger_func(f'  ⏳ Waiting {wait_after_rotation}s for stabilization...')
                time.sleep(wait_after_rotation)
            else:
                self.get_logger_func(f'  ⚠️  Manual mode: please rotate to {angle}° manually')
                time.sleep(1.0)

            # 采集当前视角
            image_path = self._capture_current_view(angle)
            if image_path is None:
                self.get_logger_func(f'  ✗ Capture failed at {angle}°')
                return None

            all_paths[angle] = str(image_path)
            self.get_logger_func(f'  ✓ Captured: {image_path.name}')

        # 步骤3: 保存元数据
        self.get_logger_func(f'\n[Step 3/3] 💾 Saving metadata...')
        panorama_data = {
            'node_id': node_id,
            'pose': pose,
            'timestamp': self.timestamp,
            'images': all_paths,
            'complete': True
        }

        metadata_path = self.save_metadata(panorama_data)
        self.get_logger_func(f'✓ Metadata saved: {metadata_path.name}')

        self.get_logger_func(f'\n{"="*60}')
        self.get_logger_func(f'✅ Panorama capture complete!')
        self.get_logger_func(f'   Node: {node_id}')
        self.get_logger_func(f'   Images: {len(all_paths)} directions')
        self.get_logger_func(f'   Location: {self.storage_path}/node_{node_id}/')
        self.get_logger_func(f'{"="*60}\n')

        return panorama_data

    def _navigate_to_pose(self, pose: Dict, frame_id: str) -> bool:
        """
        导航到目标位姿

        Args:
            pose: {'x': float, 'y': float, 'theta': float}
            frame_id: 坐标系

        Returns:
            成功返回True
        """
        if not self.navigator:
            return False

        # 构造目标位姿
        goal_pose = PoseStamped()
        goal_pose.header.frame_id = frame_id
        goal_pose.header.stamp = self.navigator.get_clock().now().to_msg()
        goal_pose.pose.position.x = pose['x']
        goal_pose.pose.position.y = pose['y']
        goal_pose.pose.position.z = 0.0

        # 转换角度为四元数
        theta = math.radians(pose['theta'])
        goal_pose.pose.orientation = self._yaw_to_quaternion(theta)

        # 发送导航目标
        self.navigator.goToPose(goal_pose)

        # 等待导航完成
        timeout = 60.0  # 60秒超时
        start_time = time.time()

        while not self.navigator.isTaskComplete():
            time.sleep(0.1)

            if time.time() - start_time > timeout:
                self.get_logger_func(f'  ⏱️  Navigation timeout after {timeout}s')
                self.navigator.cancelTask()
                return False

        # 检查结果
        result = self.navigator.getResult()
        if result == TaskResult.SUCCEEDED:
            return True
        elif result == TaskResult.CANCELED:
            self.get_logger_func(f'  ⚠️  Navigation was canceled')
            return False
        elif result == TaskResult.FAILED:
            self.get_logger_func(f'  ✗ Navigation failed')
            return False
        else:
            return False

    def _rotate_to_angle(self, angle_deg: float, frame_id: str) -> bool:
        """
        原地旋转到指定角度

        Args:
            angle_deg: 目标角度（度）
            frame_id: 坐标系

        Returns:
            成功返回True
        """
        if not self.navigator:
            return False

        # 获取当前位置，只改变朝向
        # 注意：这需要从tf获取当前位置，简化起见使用存储的pose
        current_pose = PoseStamped()
        current_pose.header.frame_id = frame_id
        current_pose.header.stamp = self.navigator.get_clock().now().to_msg()

        if self.pose:
            current_pose.pose.position.x = self.pose['x']
            current_pose.pose.position.y = self.pose['y']
        else:
            current_pose.pose.position.x = 0.0
            current_pose.pose.position.y = 0.0

        current_pose.pose.position.z = 0.0

        # 设置目标朝向
        theta = math.radians(angle_deg)
        current_pose.pose.orientation = self._yaw_to_quaternion(theta)

        # 执行旋转（实际上是导航到相同位置但不同朝向）
        self.navigator.goToPose(current_pose)

        # 等待完成（旋转应该很快）
        timeout = 10.0
        start_time = time.time()

        while not self.navigator.isTaskComplete():
            time.sleep(0.1)
            if time.time() - start_time > timeout:
                self.navigator.cancelTask()
                return False

        result = self.navigator.getResult()
        return result == TaskResult.SUCCEEDED

    def _capture_current_view(self, angle: int) -> Optional[Path]:
        """
        采集当前视角的图像

        Args:
            angle: 当前角度

        Returns:
            成功返回图像路径，失败返回None
        """
        # 检查相机就绪
        if not self.camera.is_ready():
            self.get_logger_func(f'  ✗ Camera not ready')
            return None

        # 获取图像
        rgb, depth = self.camera.get_latest_pair()

        # 验证图像
        if rgb is None or rgb.size == 0:
            self.get_logger_func(f'  ✗ Invalid RGB image')
            return None

        if depth is None or depth.size == 0:
            self.get_logger_func(f'  ⚠️  No depth image')
            depth = None

        # 保存图像
        with self.lock:
            self.timestamp = datetime.now().isoformat()
            self.images[angle] = rgb.copy()

            rgb_path = self._save_image(rgb, angle, is_depth=False)
            self.image_paths[angle] = str(rgb_path)

            if depth is not None:
                self._save_image(depth, angle, is_depth=True)

        return rgb_path

    def _save_image(self, image: np.ndarray, angle: int, is_depth: bool = False) -> Path:
        """保存图像到文件"""
        if self.node_id is None:
            node_dir = self.storage_path / 'temp'
        else:
            node_dir = self.storage_path / f'node_{self.node_id}'

        node_dir.mkdir(parents=True, exist_ok=True)

        suffix = 'depth' if is_depth else 'rgb'
        filename = f'{angle:03d}deg_{suffix}.{self.image_format}'
        filepath = node_dir / filename

        cv2.imwrite(str(filepath), image)
        return filepath

    def _reset_current_panorama(self) -> None:
        """重置当前全景数据"""
        with self.lock:
            self.images.clear()
            self.image_paths.clear()

    def _yaw_to_quaternion(self, yaw: float) -> Quaternion:
        """将yaw角度转换为四元数"""
        q = Quaternion()
        q.x = 0.0
        q.y = 0.0
        q.z = math.sin(yaw / 2.0)
        q.w = math.cos(yaw / 2.0)
        return q

    # ========== 辅助方法 ==========

    def get_panorama_data(self) -> Optional[Dict]:
        """获取完整的全景数据"""
        with self.lock:
            if len(self.images) < len(self.panorama_angles):
                return None

            return {
                'node_id': self.node_id,
                'timestamp': self.timestamp,
                'pose': self.pose,
                'images': self.image_paths.copy(),
                'complete': True
            }

    def is_panorama_complete(self) -> bool:
        """检查全景采集是否完成"""
        with self.lock:
            return len(self.images) >= len(self.panorama_angles)

    def get_image_by_angle(self, angle: int) -> Optional[np.ndarray]:
        """获取指定角度的图像"""
        with self.lock:
            return self.images.get(angle)

    def save_metadata(self, metadata: Dict, filename: str = 'panorama_metadata.json') -> Path:
        """保存全景元数据"""
        if self.node_id is not None:
            node_dir = self.storage_path / f'node_{self.node_id}'
            node_dir.mkdir(parents=True, exist_ok=True)
            filepath = node_dir / filename
        else:
            filepath = self.storage_path / filename

        with open(filepath, 'w') as f:
            json.dump(metadata, f, indent=2)

        return filepath

    def shutdown(self):
        """关闭导航器"""
        if self.navigator:
            self.navigator.lifecycleShutdown()
