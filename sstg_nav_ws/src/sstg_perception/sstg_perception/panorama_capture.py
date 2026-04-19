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

from sstg_perception.search_trace import search_trace as _search_trace_raw


def _trace(msg: str) -> None:
    """[SEARCH-TRACE] 日志：写入共享文件（stdout 由外部 logger_func 处理）."""
    _search_trace_raw('panorama', msg, None)


def _stream_and_trace(msg: str, logger_func: Callable) -> None:
    """同时落盘 + 走外部 logger（ROS logger.info 或 print）."""
    _trace(msg)
    try:
        logger_func(msg)
    except Exception:
        pass

# Nav2导航
try:
    from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
    from geometry_msgs.msg import PoseStamped, Quaternion, Twist
    import rclpy
    NAV2_AVAILABLE = True
except ImportError:
    NAV2_AVAILABLE = False
    print("Warning: Nav2 Simple Commander not available")
    try:
        from geometry_msgs.msg import Twist
    except ImportError:
        Twist = None


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
                 enable_navigation: bool = True,
                 heading_provider: Optional[Callable[[str], Optional[float]]] = None,
                 max_rotation_retries: int = 2,
                 max_capture_retries: int = 2,
                 cmd_vel_publisher=None,
                 rotation_max_angular_vel: float = 0.5,
                 rotation_tolerance_deg: float = 2.0,
                 rotation_timeout_s: float = 3.0,
                 rotation_kp: float = 1.5):
        """
        初始化全景图采集器

        Args:
            camera_subscriber: CameraSubscriber实例（必需）
            storage_path: 图像存储路径
            image_format: 图像格式 ('png' or 'jpg')
            enable_navigation: 是否启用自动导航（False时仅原地采集）
            cmd_vel_publisher: Twist publisher；非 None 时走 TF 闭环 cmd_vel 直驱
            rotation_max_angular_vel: 最大角速度 rad/s
            rotation_tolerance_deg: 到位容差 deg
            rotation_timeout_s: 单次旋转超时 s
            rotation_kp: 比例增益
        """
        # 先初始化日志函数（必须在最前面）
        self.get_logger_func = print

        self.camera = camera_subscriber
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.image_format = image_format
        self.panorama_angles = [0, 90, 180, 270]  # 四个采集方向
        self.enable_navigation = enable_navigation and NAV2_AVAILABLE
        self.heading_provider = heading_provider
        self.max_rotation_retries = max(1, int(max_rotation_retries))
        self.max_capture_retries = max(1, int(max_capture_retries))

        # cmd_vel 直驱参数（None 时走旧 Nav2 spin 作为 fallback）
        self.cmd_vel_pub = cmd_vel_publisher
        self._rot_max_w = float(rotation_max_angular_vel)
        self._rot_tol_rad = math.radians(float(rotation_tolerance_deg))
        self._rot_timeout = float(rotation_timeout_s)
        self._rot_kp = float(rotation_kp)

        # 状态
        self.images = {}  # {angle: image_array}
        self.image_paths = {}  # {angle: file_path}
        self.node_id = None
        self.timestamp = None
        self.pose = None
        self.current_heading_deg = 0.0
        self._start_yaw_deg = 0.0  # capture_at_pose 入口锁定，4 方向相对此基准
        self.lock = threading.Lock()

        # 导航器 — 延迟初始化（只在首次需要时创建）
        # 避免在 Nav2 未启动时创建 BasicNavigator 导致节点崩溃
        self.navigator = None
        self._navigator_init_attempted = False

    def set_logger(self, logger_func: Callable) -> None:
        """设置日志函数"""
        self.get_logger_func = logger_func

    def _ensure_navigator(self) -> bool:
        """
        延迟初始化 BasicNavigator。
        仅在真正需要导航时才创建，避免 Nav2 未启动时崩溃。
        """
        if self.navigator is not None:
            return True
        if not self.enable_navigation:
            return False
        if self._navigator_init_attempted:
            return False  # 上次已失败，不再重试（可调 restart_node 后重新尝试）

        self._navigator_init_attempted = True
        try:
            self.navigator = BasicNavigator()
            self.get_logger_func('✓ Navigation enabled (Nav2 BasicNavigator)')
            return True
        except Exception as e:
            self.get_logger_func(f'✗ Failed to initialize navigator: {e}')
            self.get_logger_func('  Nav2 may not be running. Navigation disabled for this session.')
            self.enable_navigation = False
            return False

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
        self.current_heading_deg = float(pose.get('theta', 0.0))
        self._refresh_heading(frame_id)
        self._reset_current_panorama()

        self.get_logger_func(
            f'[SEARCH-TRACE] panorama.start node={node_id} '
            f'angles={self.panorama_angles} wait={wait_after_rotation}s'
        )
        _trace(
            f'[SEARCH-TRACE] panorama.start node={node_id} '
            f'angles={self.panorama_angles} wait={wait_after_rotation}s'
        )
        self.get_logger_func(f'\n{"="*60}')
        self.get_logger_func(f'🎯 Starting panorama capture at node {node_id}')
        self.get_logger_func(f'   Target: x={pose["x"]:.2f}, y={pose["y"]:.2f}, θ={pose["theta"]:.1f}°')
        self.get_logger_func(f'{"="*60}')

        # 步骤1: 导航到目标点（如果需要）
        if navigate and self.enable_navigation:
            if self._ensure_navigator():
                self.get_logger_func(f'\n[Step 1/3] 🚗 Navigating to target pose...')
                if not self._navigate_to_pose(pose, frame_id):
                    self.get_logger_func(f'✗ Navigation failed')
                    return None
                self.get_logger_func(f'✓ Arrived at target')
            else:
                self.get_logger_func(f'\n[Step 1/3] ⚠️  Navigator init failed, capturing at current location')
        else:
            if navigate and not self.enable_navigation:
                self.get_logger_func(f'\n[Step 1/3] ⚠️  Navigation disabled, capturing at current location')
            else:
                self.get_logger_func(f'\n[Step 1/3] ⏭️  Skipping navigation, capturing at current location')

        # 步骤2: 旋转并采集四个方向
        # 单角度失败时不再 fail-fast，改为 skip 当前角度继续下一个。
        # 返回时带上 failed_angles / error_message，由上游决定是否接纳部分成功。
        self.get_logger_func(f'\n[Step 2/3] 📸 Capturing 4 directions...')
        # 锁定 4 方向基准朝向：导航完成后/跳过导航后当前实时 yaw
        self._refresh_heading(frame_id)
        self._start_yaw_deg = float(self.current_heading_deg)
        _trace(
            f'[SEARCH-TRACE] panorama.start_yaw node={node_id} '
            f'start_yaw_deg={self._start_yaw_deg:.1f}'
        )
        all_paths = {}
        failed_angles = []
        error_messages = []

        for idx, angle in enumerate(self.panorama_angles):
            self.get_logger_func(
                f'[SEARCH-TRACE] panorama.angle_begin node={node_id} angle={angle} '
                f'idx={idx+1}/{len(self.panorama_angles)}'
            )
            _trace(
                f'[SEARCH-TRACE] panorama.angle_begin node={node_id} angle={angle} '
                f'idx={idx+1}/{len(self.panorama_angles)}'
            )
            self.get_logger_func(f'\n  Direction {idx+1}/4: {angle}°')
            image_path, error_message = self._capture_direction_with_retry(
                angle=angle,
                frame_id=frame_id,
                wait_after_rotation=wait_after_rotation,
            )
            if image_path is None:
                self.get_logger_func(
                    f'[SEARCH-TRACE] panorama.angle_end node={node_id} angle={angle} '
                    f'result=fail msg="{error_message}"'
                )
                _trace(
                    f'[SEARCH-TRACE] panorama.angle_end node={node_id} angle={angle} '
                    f'result=fail msg="{error_message}"'
                )
                self.get_logger_func(
                    f'  ⚠️  {angle}° failed ({error_message}), skip-continue 到下一方向'
                )
                failed_angles.append(angle)
                if error_message:
                    error_messages.append(f'{angle}°: {error_message}')
                continue

            all_paths[angle] = str(image_path)
            self.get_logger_func(
                f'[SEARCH-TRACE] panorama.angle_end node={node_id} angle={angle} '
                f'result=ok path={image_path.name}'
            )
            _trace(
                f'[SEARCH-TRACE] panorama.angle_end node={node_id} angle={angle} '
                f'result=ok path={image_path.name}'
            )
            self.get_logger_func(f'  ✓ Captured: {image_path.name}')

        # 所有方向都尝试完，根据成功角度数判断结果
        if not all_paths:
            combined_err = '; '.join(error_messages) or 'All directions failed'
            self.get_logger_func(
                f'[SEARCH-TRACE] panorama.all_failed node={node_id} '
                f'failed_angles={failed_angles}'
            )
            _trace(
                f'[SEARCH-TRACE] panorama.all_failed node={node_id} '
                f'failed_angles={failed_angles}'
            )
            panorama_data = {
                'node_id': node_id,
                'pose': pose,
                'timestamp': self.timestamp,
                'images': {},
                'complete': False,
                'failed_angle': failed_angles[0] if failed_angles else None,
                'failed_angles': failed_angles,
                'error_message': combined_err,
            }
            metadata_path = self.save_metadata(panorama_data)
            self.get_logger_func(
                f'✗ All {len(self.panorama_angles)} directions failed: {combined_err}'
            )
            self.get_logger_func(f'  Metadata saved: {metadata_path.name}')
            return panorama_data

        # 步骤3: 保存元数据
        is_complete = (len(failed_angles) == 0)
        combined_err = '; '.join(error_messages)
        self.get_logger_func(f'\n[Step 3/3] 💾 Saving metadata...')
        panorama_data = {
            'node_id': node_id,
            'pose': pose,
            'timestamp': self.timestamp,
            'images': all_paths,
            'complete': is_complete,
            'failed_angle': failed_angles[0] if failed_angles else None,
            'failed_angles': failed_angles,
            'error_message': combined_err,
        }

        metadata_path = self.save_metadata(panorama_data)
        self.get_logger_func(f'✓ Metadata saved: {metadata_path.name}')

        _trace_tag = 'panorama.complete' if is_complete else 'panorama.partial'
        self.get_logger_func(
            f'[SEARCH-TRACE] {_trace_tag} node={node_id} '
            f'captured_count={len(all_paths)} angles={list(all_paths.keys())} '
            f'failed_angles={failed_angles}'
        )
        _trace(
            f'[SEARCH-TRACE] {_trace_tag} node={node_id} '
            f'captured_count={len(all_paths)} angles={list(all_paths.keys())} '
            f'failed_angles={failed_angles}'
        )
        self.get_logger_func(f'\n{"="*60}')
        if is_complete:
            self.get_logger_func(f'✅ Panorama capture complete!')
        else:
            self.get_logger_func(
                f'⚠️  Panorama partial: {len(all_paths)}/{len(self.panorama_angles)} '
                f'directions captured, failed={failed_angles}'
            )
        self.get_logger_func(f'   Node: {node_id}')
        self.get_logger_func(f'   Images: {len(all_paths)} directions')
        self.get_logger_func(f'   Location: {self.storage_path}/node_{node_id}/')
        self.get_logger_func(f'{"="*60}\n')

        return panorama_data

    def _capture_direction_with_retry(self,
                                      angle: int,
                                      frame_id: str,
                                      wait_after_rotation: float) -> tuple[Optional[Path], str]:
        """对单个方向执行旋转+采集，带重试。"""
        last_error = ''

        for rotation_attempt in range(1, self.max_rotation_retries + 1):
            self._refresh_heading(frame_id)
            min_rgb_seq, min_depth_seq, _, _ = self.camera.get_frame_state()

            if self.enable_navigation:
                self.get_logger_func(
                    f'  🔄 Rotating to {angle}° '
                    f'(attempt {rotation_attempt}/{self.max_rotation_retries})...'
                )
                if not self._rotate_to_angle(angle, frame_id):
                    last_error = f'Rotation to {angle}° failed'
                    self.get_logger_func(f'  ✗ {last_error}')
                    time.sleep(0.5)
                    continue

                self.get_logger_func(f'  ⏳ Waiting {wait_after_rotation}s for stabilization...')
                self._wait_and_update_camera(wait_after_rotation)
            else:
                self.get_logger_func(f'  ⚠️  Manual mode: please rotate to {angle}° manually')
                time.sleep(1.0)

            for capture_attempt in range(1, self.max_capture_retries + 1):
                image_path = self._capture_current_view(
                    angle,
                    min_rgb_seq=min_rgb_seq,
                    min_depth_seq=min_depth_seq,
                )
                if image_path is not None:
                    return image_path, ''

                last_error = f'Capture failed at {angle}°'
                self.get_logger_func(
                    f'  ✗ {last_error} '
                    f'(attempt {capture_attempt}/{self.max_capture_retries})'
                )
                time.sleep(0.3)

        return None, last_error

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
        原地旋转到指定角度（相对 start_yaw_deg 基准）。

        cmd_vel_pub 非 None → 走 TF 闭环直驱（稳定）
        cmd_vel_pub 为 None → 走 Nav2 spin（旧路径，fallback）
        """
        if self.cmd_vel_pub is not None:
            target_yaw_deg = self._start_yaw_deg + float(angle_deg)
            return self._rotate_with_cmd_vel(target_yaw_deg, frame_id)
        return self._rotate_with_nav2_spin(angle_deg, frame_id)

    def _rotate_with_cmd_vel(self, target_yaw_deg: float, frame_id: str) -> bool:
        """TF 闭环 + P 控制 cmd_vel 直驱旋转到 target_yaw_deg（绝对 map yaw）."""
        target_yaw_rad = math.radians(target_yaw_deg)
        t0 = time.time()
        last_log_t = t0

        # 防御：Nav2 若有遗留任务则取消（idle 无副作用）
        try:
            if self.navigator is not None:
                self.navigator.cancelTask()
        except Exception:
            pass

        while True:
            self._refresh_heading(frame_id)
            yaw_now_rad = math.radians(self.current_heading_deg)
            err = self._normalize_angle(target_yaw_rad - yaw_now_rad)

            if abs(err) < self._rot_tol_rad:
                self._publish_twist(0.0)
                time.sleep(0.2)  # 稳定一拍
                _trace(
                    f'[SEARCH-TRACE] rotate.cmd_vel.done '
                    f'target={target_yaw_deg:.1f} yaw={self.current_heading_deg:.1f} '
                    f'err_deg={math.degrees(err):.2f}'
                )
                self.get_logger_func(
                    f'  ✓ cmd_vel rotate done: target={target_yaw_deg:.1f}° '
                    f'yaw={self.current_heading_deg:.1f}° err={math.degrees(err):.2f}°'
                )
                return True

            elapsed = time.time() - t0
            if elapsed > self._rot_timeout:
                self._publish_twist(0.0)
                _trace(
                    f'[SEARCH-TRACE] rotate.cmd_vel.timeout '
                    f'target={target_yaw_deg:.1f} yaw={self.current_heading_deg:.1f} '
                    f'err_deg={math.degrees(err):.2f} elapsed={elapsed:.2f}'
                )
                self.get_logger_func(
                    f'  ✗ cmd_vel rotate timeout: target={target_yaw_deg:.1f}° '
                    f'yaw={self.current_heading_deg:.1f}° err={math.degrees(err):.2f}° '
                    f'elapsed={elapsed:.2f}s'
                )
                return False

            w = math.copysign(min(abs(err) * self._rot_kp, self._rot_max_w), err)
            self._publish_twist(w)

            if time.time() - last_log_t > 0.5:
                last_log_t = time.time()
                _trace(
                    f'[SEARCH-TRACE] rotate.cmd_vel.step '
                    f'target={target_yaw_deg:.1f} yaw={self.current_heading_deg:.1f} '
                    f'err_deg={math.degrees(err):.2f} w={w:.3f}'
                )

            time.sleep(0.05)  # 20 Hz

    def _publish_twist(self, angular_z: float) -> None:
        if Twist is None or self.cmd_vel_pub is None:
            return
        msg = Twist()
        msg.angular.z = float(angular_z)
        try:
            self.cmd_vel_pub.publish(msg)
        except Exception as exc:
            self.get_logger_func(f'  ⚠️ cmd_vel publish failed: {exc}')

    @staticmethod
    def _normalize_angle(rad: float) -> float:
        while rad > math.pi:
            rad -= 2 * math.pi
        while rad < -math.pi:
            rad += 2 * math.pi
        return rad

    def _rotate_with_nav2_spin(self, angle_deg: float, frame_id: str) -> bool:
        """
        Fallback：原地旋转到指定角度（Nav2 spin BT）

        Args:
            angle_deg: 目标角度（度）
            frame_id: 坐标系

        Returns:
            成功返回True
        """
        if not self.navigator:
            return False

        self._refresh_heading(frame_id)
        delta_deg = angle_deg - self.current_heading_deg
        while delta_deg > 180.0:
            delta_deg -= 360.0
        while delta_deg < -180.0:
            delta_deg += 360.0

        if abs(delta_deg) < 5.0:
            self.get_logger_func(
                f'  ✓ Already near {angle_deg}° (current {self.current_heading_deg:.1f}°)'
            )
            self.current_heading_deg = float(angle_deg)
            return True

        spin_ok = self.navigator.spin(
            spin_dist=math.radians(delta_deg),
            time_allowance=15
        )
        if not spin_ok:
            self.get_logger_func(
                f'  ✗ Spin request rejected for {delta_deg:.1f}°'
            )
            return False

        # 等待完成（旋转应该很快）
        timeout = 20.0
        start_time = time.time()

        while not self.navigator.isTaskComplete():
            time.sleep(0.1)
            if time.time() - start_time > timeout:
                self.navigator.cancelTask()
                return False

        result = self.navigator.getResult()
        if result == TaskResult.SUCCEEDED:
            self.current_heading_deg = float(angle_deg)
            self._refresh_heading(frame_id)
            return True

        return False

    def _wait_and_update_camera(self, duration: float) -> None:
        """
        等待指定时间，同时持续处理相机消息

        Args:
            duration: 等待时间（秒）
        """
        time.sleep(duration)

    def _refresh_heading(self, frame_id: str) -> None:
        """尽量用 TF 读取当前真实朝向，失败时保留现值。"""
        if self.heading_provider is None:
            return

        try:
            heading = self.heading_provider(frame_id)
        except Exception as exc:
            self.get_logger_func(f'  ⚠️  Failed to query current heading: {exc}')
            return

        if heading is not None:
            self.current_heading_deg = float(heading)

    def _capture_current_view(self,
                              angle: int,
                              min_rgb_seq: int = 0,
                              min_depth_seq: int = 0) -> Optional[Path]:
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

        if not self.camera.wait_for_new_frames(
            min_rgb_seq=min_rgb_seq,
            min_depth_seq=min_depth_seq,
            timeout=2.0,
        ):
            self.get_logger_func('  ⚠️  No fresh frame observed after rotation, using latest available frame')

        time.sleep(0.15)

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
            try:
                self.navigator.lifecycleShutdown()
            except Exception:
                pass
            self.navigator = None
