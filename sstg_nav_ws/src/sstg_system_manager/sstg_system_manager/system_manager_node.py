"""
SSTG System Manager Node - 硬件启停和系统状态监控

功能:
- /system/launch_mode: 切换 exploration/navigation/stop 模式
- /system/get_status: 查询当前系统状态
- /system/status (topic): 定期发布系统状态 (CPU/内存/设备/节点数)
- /system/log (topic): 推送 launch subprocess 的日志
"""

import os
import signal
import subprocess
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String
from builtin_interfaces.msg import Time

try:
    import sstg_msgs.srv as sstg_srv
    import sstg_msgs.msg as sstg_msg
except ImportError:
    sstg_srv = None
    sstg_msg = None

# 设备路径
DEVICES = {
    'chassis': {'name': '底盘 CH340', 'path': '/dev/chassis'},
    'lidar': {'name': '雷达 RPLidar S2', 'path': '/dev/rplidar'},
    'camera': {'name': '相机 Gemini 336L', 'path': '/dev/Gemini_336L'},
}

# Launch 文件映射
LAUNCH_MODES = {
    'exploration': {
        'package': 'sstg_rrt_explorer',
        'launch_file': 'rrt_exploration_full.launch.py',
        'description': 'RRT 自主探索 (SLAM + Nav2 + RRT)',
    },
    'navigation': {
        'package': 'sstg_rrt_explorer',
        'launch_file': 'navigation_full.launch.py',
        'description': 'AMCL 导航 (定位 + Nav2 + 相机)',
    },
}


class SystemManagerNode(Node):

    def __init__(self):
        super().__init__('system_manager_node')

        self._current_mode = 'idle'
        self._process = None          # subprocess.Popen
        self._process_lock = threading.Lock()
        self._log_thread = None

        # Services
        self.create_service(
            sstg_srv.LaunchMode,
            'system/launch_mode',
            self._launch_mode_callback,
        )
        self.create_service(
            sstg_srv.GetSystemStatus,
            'system/get_status',
            self._get_status_callback,
        )

        # Publishers
        self._status_pub = self.create_publisher(
            sstg_msg.SystemStatus, 'system/status', 10)
        self._log_pub = self.create_publisher(
            String, 'system/log', 50)

        # Timer: 每 3 秒发布系统状态
        self.create_timer(3.0, self._publish_status)

        # 节点上线检测
        self._known_nodes: set = set()
        self._startup_announced = False

        # SSTG 核心节点列表（用于启动进度追踪）
        self._sstg_core_nodes = {
            '/rosbridge_websocket': 'WebSocket 桥接',
            '/map_manager_node': '地图管理器',
            '/system_manager_node': '系统管理器',
            '/nlp_node': 'NLP 语义理解',
            '/planning_node': '路径规划器',
            '/executor_node': '导航执行器',
            '/perception_node': '视觉感知',
            '/exploration_action_server': '探索服务',
            '/interaction_manager_node': '交互编排中心',
        }

        self._publish_log('SSTG 系统启动中...')
        self.get_logger().info('SystemManager initialized (mode=idle)')

    # ── Services ──────────────────────────────────────────────

    def _launch_mode_callback(self, request, response):
        mode = request.mode.strip().lower()
        self.get_logger().info(f'LaunchMode request: {mode}')

        if mode == 'stop':
            ok, msg = self._stop_current()
            response.success = ok
            response.message = msg
            response.launched_nodes = []
            return response

        if mode not in LAUNCH_MODES:
            response.success = False
            response.message = f'Unknown mode: {mode}. Valid: {list(LAUNCH_MODES.keys())}'
            response.launched_nodes = []
            return response

        # 如果当前有模式在运行，先停止
        if self._current_mode != 'idle':
            self.get_logger().info(
                f'Stopping current mode ({self._current_mode}) before switching...')
            self._stop_current()
            time.sleep(2.0)  # 等待串口释放

        ok, msg = self._start_mode(mode)
        response.success = ok
        response.message = msg
        response.launched_nodes = []
        # 重置节点检测，让新启动的节点重新播报
        self._known_nodes.clear()
        self._startup_announced = False
        return response

    def _get_status_callback(self, request, response):
        response.mode = self._current_mode
        response.hardware_ok = all(
            os.path.exists(d['path']) for d in DEVICES.values())
        response.device_status = [
            f'{"OK" if os.path.exists(d["path"]) else "MISSING"}:{d["name"]}:{d["path"]}'
            for d in DEVICES.values()
        ]
        # 获取活跃节点列表
        try:
            result = subprocess.run(
                ['ros2', 'node', 'list'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                nodes = [n.strip() for n in result.stdout.strip().split('\n') if n.strip()]
                response.active_nodes = nodes
            else:
                response.active_nodes = []
        except Exception:
            response.active_nodes = []

        return response

    # ── Launch Management ─────────────────────────────────────

    def _start_mode(self, mode: str) -> tuple:
        cfg = LAUNCH_MODES[mode]
        cmd = [
            'ros2', 'launch',
            cfg['package'],
            cfg['launch_file'],
        ]
        self.get_logger().info(f'Starting {mode}: {" ".join(cmd)}')
        self._publish_log(f'Starting {mode} mode: {cfg["description"]}')

        try:
            with self._process_lock:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid,
                    text=True,
                    bufsize=1,
                )
                self._current_mode = mode

            # 后台线程读取 stdout 并推送日志
            self._log_thread = threading.Thread(
                target=self._read_process_output,
                daemon=True,
            )
            self._log_thread.start()

            return True, f'{mode} mode started (pid={self._process.pid})'

        except Exception as e:
            self._current_mode = 'idle'
            msg = f'Failed to start {mode}: {e}'
            self.get_logger().error(msg)
            return False, msg

    # Nav2 相关进程关键字（用于残留清理）
    _NAV2_PATTERNS = [
        'controller_server', 'planner_server', 'bt_navigator', 'behavior_server',
        'nav2_amcl/amcl', 'map_server', 'lifecycle_manager', 'ekf_node',
        'Mcnamu_driver', 'sllidar_node', 'joint_state_publisher', 'robot_state_publisher',
    ]

    def _stop_current(self) -> tuple:
        with self._process_lock:
            if self._process is None or self._process.poll() is not None:
                self._current_mode = 'idle'
                return True, 'No active process'

            pid = self._process.pid
            pgid = os.getpgid(pid)
            self.get_logger().info(f'Stopping process group {pgid}...')
            self._publish_log(f'Stopping {self._current_mode} mode...')

            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        # 等待进程退出 (不在锁内)，给 Nav2 足够的关闭时间
        try:
            self._process.wait(timeout=15.0)
        except subprocess.TimeoutExpired:
            self.get_logger().warn(f'SIGTERM timeout (15s), sending SIGKILL to pgid {pgid}')
            try:
                os.killpg(pgid, signal.SIGKILL)
                self._process.wait(timeout=5.0)
            except Exception:
                pass

        with self._process_lock:
            old_mode = self._current_mode
            self._current_mode = 'idle'
            self._process = None

        # 兜底：扫描清理可能逃逸的 Nav2 子进程
        orphans = self._cleanup_orphaned_processes()
        if orphans > 0:
            self.get_logger().warn(f'Cleaned {orphans} orphaned Nav2 processes')
            self._publish_log(f'清理了 {orphans} 个残留进程')

        self._publish_log(f'{old_mode} mode stopped')
        return True, f'Stopped {old_mode}'

    def _cleanup_orphaned_processes(self) -> int:
        """扫描并清理残留的 Nav2 相关进程"""
        cleaned = 0
        for pattern in self._NAV2_PATTERNS:
            try:
                subprocess.run(
                    ['pkill', '-9', '-f', pattern],
                    capture_output=True, timeout=3,
                )
                cleaned += 1
            except Exception:
                pass
        return cleaned

    def _read_process_output(self):
        """后台读取 subprocess stdout 并推送到 /system/log"""
        proc = self._process
        if proc is None:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip('\n')
                if line:
                    self._publish_log(line)
        except Exception:
            pass

    # ── Status Publishing ─────────────────────────────────────

    def _publish_status(self):
        msg = sstg_msg.SystemStatus()
        msg.mode = self._current_mode
        msg.stamp = self.get_clock().now().to_msg()

        # CPU / 内存
        try:
            import psutil
            msg.cpu_percent = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            msg.memory_percent = mem.percent
        except ImportError:
            msg.cpu_percent = self._read_cpu_fallback()
            msg.memory_percent = self._read_mem_fallback()

        # 设备状态
        msg.device_status = [
            f'{"OK" if os.path.exists(d["path"]) else "MISSING"}:{d["name"]}:{d["path"]}'
            for d in DEVICES.values()
        ]

        # 节点数 (快速检查) + 上线检测
        try:
            result = subprocess.run(
                ['ros2', 'node', 'list'],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                nodes = [n for n in result.stdout.strip().split('\n') if n.strip()]
                msg.active_node_count = len(nodes)

                # 检测新上线的节点
                current_nodes = set(nodes)
                new_nodes = current_nodes - self._known_nodes
                for node_name in sorted(new_nodes):
                    label = self._sstg_core_nodes.get(node_name, '')
                    if label:
                        self._publish_log(f'✔ {label} ({node_name}) 已启动')
                    elif node_name.startswith('/'):
                        self._publish_log(f'✔ {node_name} 已启动')
                self._known_nodes = current_nodes

                # 所有核心节点就绪时通知一次
                if not self._startup_announced:
                    ready = set(self._sstg_core_nodes.keys()) & current_nodes
                    if len(ready) >= len(self._sstg_core_nodes):
                        self._publish_log('✔ SSTG 所有核心节点已就绪，系统准备完毕')
                        self._startup_announced = True
            else:
                msg.active_node_count = 0
        except Exception:
            msg.active_node_count = 0

        self._status_pub.publish(msg)

    def _publish_log(self, text: str):
        msg = String()
        msg.data = text
        self._log_pub.publish(msg)

    # ── Fallback CPU/Memory (无 psutil 时) ────────────────────

    @staticmethod
    def _read_cpu_fallback() -> float:
        try:
            with open('/proc/loadavg', 'r') as f:
                load1 = float(f.read().split()[0])
                cpus = os.cpu_count() or 1
                return min(100.0, (load1 / cpus) * 100.0)
        except Exception:
            return -1.0

    @staticmethod
    def _read_mem_fallback() -> float:
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
            info = {}
            for line in lines[:5]:
                parts = line.split()
                info[parts[0].rstrip(':')] = int(parts[1])
            total = info.get('MemTotal', 1)
            avail = info.get('MemAvailable', total)
            return ((total - avail) / total) * 100.0
        except Exception:
            return -1.0

    def destroy_node(self):
        self._stop_current()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = SystemManagerNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        print('\nShutting down SystemManager...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
