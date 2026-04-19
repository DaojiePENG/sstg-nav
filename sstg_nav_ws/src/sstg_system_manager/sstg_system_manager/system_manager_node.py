"""
SSTG System Manager Node - 硬件启停和系统状态监控

功能:
- /system/launch_mode: 切换 exploration/navigation/stop 模式
- /system/get_status: 查询当前系统状态
- /system/status (topic): 定期发布系统状态 (CPU/内存/设备/节点数)
- /system/log (topic): 推送 launch subprocess 的日志
"""

import json
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

# UI AI 引擎配置 single-source-of-truth（与 vite-plugins/chatSyncPlugin.ts、perception_node.py 对齐）
LLM_CONFIG_PATH = os.path.expanduser('~/sstg-data/chat/llm-config.json')

# provider → 该 provider 对应的 SDK 惯例环境变量名
# 统一再额外注入 SSTG_LLM_API_KEY / SSTG_LLM_BASE_URL / SSTG_LLM_MODEL，方便下游通用读取
_PROVIDER_ENV_KEYS = {
    'DashScope (阿里云)': 'DASHSCOPE_API_KEY',
    'DeepSeek (深度求索)': 'DEEPSEEK_API_KEY',
    'ZhipuAI (智谱清言)': 'ZHIPUAI_API_KEY',
    'Ollama (本地私有化)': 'OLLAMA_API_KEY',
    'OpenAI': 'OPENAI_API_KEY',
}


def _build_llm_env(base_env: dict) -> dict:
    """
    从 UI 的 llm-config.json 读取 activeProvider，注入所有相关环境变量。
    这样 ros2 launch 起来的所有子进程（perception/nlp/planning/...）都能自动拿到 key。
    找不到配置时返回 base_env 的浅拷贝，不破坏原环境。
    """
    env = dict(base_env)
    try:
        with open(LLM_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return env

    active = cfg.get('activeProvider', '')
    providers = cfg.get('providers', {}) or {}
    if not active or active not in providers:
        return env

    p = providers[active] or {}
    api_key = (p.get('apiKey') or '').strip()
    base_url = (p.get('baseUrl') or '').strip()
    model = (p.get('model') or '').strip()

    if not api_key:
        return env

    # 1. 通用变量（下游自写节点推荐读这几个）
    env['SSTG_LLM_PROVIDER'] = active
    env['SSTG_LLM_API_KEY'] = api_key
    env['SSTG_LLM_BASE_URL'] = base_url
    env['SSTG_LLM_MODEL'] = model

    # 2. provider 专用变量（兼容第三方 SDK 的默认查找路径，例如 DASHSCOPE_API_KEY）
    provider_env_name = _PROVIDER_ENV_KEYS.get(active)
    if provider_env_name:
        env[provider_env_name] = api_key

    return env


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
        self.create_service(
            sstg_srv.RestartNode,
            'system/restart_node',
            self._restart_node_callback,
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
        # 获取活跃节点列表（直接走 DDS 发现，不依赖 ros2 daemon）
        try:
            names_and_ns = self.get_node_names_and_namespaces()
            nodes = list(set(
                f'{ns.rstrip("/")}/{name}' if ns != '/' else f'/{name}'
                for name, ns in names_and_ns
            ))
            response.active_nodes = nodes
        except Exception:
            response.active_nodes = []

        return response

    # 允许单独重启的节点白名单（仅 SSTG 核心）
    _RESTARTABLE_NODES = {
        'interaction_manager_node': {
            'package': 'sstg_interaction_manager',
            'executable': 'interaction_manager_node',
        },
        'map_manager_node': {
            'package': 'sstg_map_manager',
            'executable': 'map_manager_node',
        },
        'nlp_node': {
            'package': 'sstg_nlp_interface',
            'executable': 'nlp_node',
        },
        'planning_node': {
            'package': 'sstg_navigation_planner',
            'executable': 'planning_node',
        },
        'executor_node': {
            'package': 'sstg_navigation_executor',
            'executable': 'executor_node',
        },
        'perception_node': {
            'package': 'sstg_perception',
            'executable': 'perception_node',
        },
        'exploration_action_server': {
            'package': 'sstg_rrt_explorer',
            'executable': 'exploration_action_server.py',
        },
        'webrtc_camera_bridge': {
            'package': 'sstg_system_manager',
            'executable': 'webrtc_camera_bridge',
        },
        'system_manager_node': {
            'package': 'sstg_system_manager',
            'executable': 'system_manager_node',
        },
        'topo_node_viz': {
            'package': 'sstg_rrt_explorer',
            'executable': 'topo_node_viz.py',
        },
        'rosbridge_websocket': None,  # 不支持单独重启，由 launch 管理
    }

    def _restart_node_callback(self, request, response):
        node_name = request.node_name.strip().lstrip('/')
        kill_duplicates = request.kill_duplicates
        self.get_logger().info(
            f'RestartNode request: {node_name} (kill_duplicates={kill_duplicates})')

        # 白名单检查
        if node_name not in self._RESTARTABLE_NODES:
            response.success = False
            response.message = (
                f'节点 {node_name} 不支持单独重启。'
                '仅 SSTG 核心节点可重启，Nav2/硬件节点请使用模式切换。')
            response.killed_pids = []
            return response

        node_cfg = self._RESTARTABLE_NODES[node_name]
        if node_cfg is None:
            response.success = False
            response.message = f'节点 {node_name} 由 launch 文件管理，不支持单独重启'
            response.killed_pids = []
            return response

        # 查找所有匹配 PID
        killed_pids = []
        try:
            result = subprocess.run(
                ['pgrep', '-f', node_cfg['executable']],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
            else:
                pids = []
        except Exception:
            pids = []

        # Kill 进程
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
                killed_pids.append(pid)
                self._publish_log(f'已终止 {node_name} (PID {pid})')
            except (ProcessLookupError, ValueError):
                pass

        # 等待进程退出
        if killed_pids:
            time.sleep(3.0)
            # 确认是否还在运行，强杀残留
            for pid in killed_pids:
                try:
                    os.kill(int(pid), 0)  # 检查进程是否存在
                    os.kill(int(pid), signal.SIGKILL)
                    self._publish_log(f'强制终止 {node_name} (PID {pid})')
                except (ProcessLookupError, ValueError):
                    pass
            time.sleep(1.0)

        # 重启一个新实例
        try:
            cmd = ['ros2', 'run', node_cfg['package'], node_cfg['executable']]
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
                env=_build_llm_env(os.environ),
            )
            self._publish_log(f'✔ 已重启 {node_name}')
            response.success = True
            response.message = (
                f'已重启 {node_name}'
                f'（终止 {len(killed_pids)} 个旧实例）')
            response.killed_pids = killed_pids
        except Exception as e:
            response.success = False
            response.message = f'重启 {node_name} 失败: {e}'
            response.killed_pids = killed_pids

        return response

    # ── Launch Management ─────────────────────────────────────

    def _kill_stale_launches(self, launch_file: str):
        """杀掉同名 launch 文件的残留进程组（防止 system_manager 重启后丢失旧进程引用）"""
        try:
            result = subprocess.run(
                ['pgrep', '-f', f'ros2 launch.*{launch_file}'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode != 0:
                return
            for pid_str in result.stdout.strip().split('\n'):
                pid = int(pid_str.strip())
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, signal.SIGTERM)
                    self._publish_log(f'清理残留 launch 进程组 (pgid={pgid})')
                    self.get_logger().info(f'Killed stale launch pgid {pgid}')
                except (ProcessLookupError, PermissionError):
                    pass
        except Exception as e:
            self.get_logger().warn(f'_kill_stale_launches: {e}')

    def _start_mode(self, mode: str) -> tuple:
        cfg = LAUNCH_MODES[mode]
        cmd = [
            'ros2', 'launch',
            cfg['package'],
            cfg['launch_file'],
        ]
        self.get_logger().info(f'Starting {mode}: {" ".join(cmd)}')
        self._publish_log(f'Starting {mode} mode: {cfg["description"]}')

        # 清理同名 launch 残留（即使 self._process 为 None）
        self._kill_stale_launches(cfg['launch_file'])
        self._cleanup_orphaned_processes()
        time.sleep(1.0)

        try:
            with self._process_lock:
                launch_env = _build_llm_env(os.environ)
                llm_key_ok = bool(launch_env.get('SSTG_LLM_API_KEY'))
                self._publish_log(
                    f'LLM env injected: provider={launch_env.get("SSTG_LLM_PROVIDER", "<none>")} '
                    f'key_loaded={llm_key_ok} model={launch_env.get("SSTG_LLM_MODEL", "")}'
                )
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid,
                    text=True,
                    bufsize=1,
                    env=launch_env,
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
                # 即使没有跟踪到进程，也尝试清理残留 launch
                for cfg in LAUNCH_MODES.values():
                    self._kill_stale_launches(cfg['launch_file'])
                orphans = self._cleanup_orphaned_processes()
                self._current_mode = 'idle'
                if orphans > 0:
                    return True, f'No tracked process, cleaned {orphans} orphans'
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

        # 节点数 (直接走 DDS 发现，不依赖 ros2 daemon) + 上线检测
        try:
            names_and_ns = self.get_node_names_and_namespaces()
            nodes = list(set(
                f'{ns.rstrip("/")}/{name}' if ns != '/' else f'/{name}'
                for name, ns in names_and_ns
            ))
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
