"""
SSTG Interaction Manager - 异步回调链架构

核心编排节点，协调 NLP → Planner → Executor 全流程。
start_task < 100ms 返回，后续通过 /task_status topic 推送实时状态。

架构:
  start_task_callback  →  nlp_client.call_async()  →  _on_nlp_done
                                                         ├─ navigate_to     → _on_plan_done → _on_pose_done → _on_exec_done
                                                         ├─ explore_new_home → _handle_explore()  [Phase 2]
                                                         └─ locate_object    → _handle_locate_object()  [Phase 3]
"""

import datetime
import json
import time
import threading
from enum import Enum

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

from std_srvs.srv import Trigger
from sstg_msgs.srv import (
    ProcessNLPQuery,
    PlanNavigation,
    ExecuteNavigation,
    GetNodePose,
    CaptureImage,
    CheckObjectPresence,
    AnnotateSemantic,
    UpdateSemantic,
    ConfirmTask,
)
from sstg_msgs.msg import SemanticData
from sstg_msgs.msg import NavigationFeedback, TaskStatus, ObjectSearchTrace
from sstg_msgs.action import ExploreHome

from sstg_interaction_manager.target_normalizer import normalize_search_target, prefer_chinese_label
from sstg_interaction_manager.search_trace import search_trace as _search_trace_raw


class TaskState(Enum):
    IDLE = 'idle'
    UNDERSTANDING = 'understanding'
    PLANNING = 'planning'
    NAVIGATING = 'navigating'
    EXPLORING = 'exploring'
    SEARCHING = 'searching'
    CHECKING = 'checking'
    AWAITING_CONFIRMATION = 'awaiting_confirmation'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELED = 'canceled'


# Round 6: 远距离置信度降权 + 多节点 tentative 累积裁决
# distance_hint → VLM 原始 conf 的乘性权重；远处看到的"高分"在这里被打薄
DIST_WEIGHT = {'near': 1.0, 'mid': 0.7, 'far': 0.35, 'unknown': 0.85}
HARD_HIT_ADJ = 0.85       # 加权后 ≥0.85 且 near → 立即 early-exit 收尾
TENTATIVE_MIN_ADJ = 0.40  # 所有候选走完后，若无硬命中，需此阈值才能拿出来当"最佳猜测"
MIN_RAW_CONF = 0.5        # VLM 原始置信度下限（低于此直接 reject）

# 小拓中文语气润色资源（ROS 端只出"官方具体直接"的硬数据文案；前端会再跟一条 LLM 润色版）
DIST_LABEL_CN = {'near': '近处', 'mid': '中距离', 'far': '远距离', 'unknown': '距离不明'}

PHRASE_OBSERVATION = '节点 {nid}：未检测到 {target}{partial}。'
PHRASE_CONFIRM = '节点 {nid}：{angle}° 方向疑似 {target}，置信度 {conf}，近处。'
PHRASE_TENTATIVE = '节点 {nid}：{angle}° 方向疑似 {target}，置信度 {conf}，中距离。'
PHRASE_TENTATIVE_WEAK = '节点 {nid}：{angle}° 方向疑似 {target}，置信度 {conf}，远距离。'
PHRASE_TENTATIVE_UNKNOWN = '节点 {nid}：{angle}° 方向疑似 {target}，置信度 {conf}，距离不明。'
PHRASE_HARD_HIT = '发现 {target}：看第 {pos} 张图，节点 {nid} 的 {angle}° 方向，置信度 {conf}，近处。'
PHRASE_CONFIRMED = '发现 {target}：看第 {pos} 张图，节点 {nid} 的 {angle}° 方向，置信度 {conf}，近处。'
PHRASE_BEST_GUESS = '最相似候选：看第 {pos} 张图，节点 {nid} 的 {angle}° 方向，置信度 {conf}，{dist_cn}。'
PHRASE_BEST_GUESS_SHORT = '搜索完成：所有位置都看过了，最接近的还是刚才节点 {nid} {angle}° 方向看到的那个（置信度 {conf}，{dist_cn}）。'
PHRASE_BEST_GUESS_SINGLE = '搜索完成。节点 {nid} 那一处置信度 {conf}，我判断就是它了。'
PHRASE_MISS = '搜索完成：{n} 个候选位置均未检测到 {target}。'


class InteractionManagerNode(Node):
    def __init__(self):
        super().__init__('interaction_manager_node')

        self.cb_group = ReentrantCallbackGroup()

        # --- 共享状态 (受 _lock 保护) ---
        self._lock = threading.Lock()
        self.task_state = TaskState.IDLE
        self.current_task_id = ''
        self.current_intent = ''
        self.current_candidates = []
        self._history = []  # 状态变更历史

        # --- R8: Map session 位置（与 map_manager_node 对齐），供 viewpoint 图片刷新使用 ---
        # 从 sstg_map_manager 的 config/map_config.yaml 读取默认值；也可被 ROS 参数覆盖。
        import os as _os
        _maps_root_default = ''
        _active_map_default = 'default'
        try:
            from ament_index_python.packages import get_package_share_directory
            _mm_share = get_package_share_directory('sstg_map_manager')
            _maps_root_default = _os.path.join(_mm_share, 'maps')
            _cfg_path = _os.path.join(_mm_share, 'config', 'map_config.yaml')
            if _os.path.exists(_cfg_path):
                import yaml as _yaml
                with open(_cfg_path, 'r') as _f:
                    _cfg = _yaml.safe_load(_f) or {}
                _active_map_default = (_cfg.get('general', {}) or {}).get('active_map', 'default')
        except Exception:
            pass
        self.declare_parameter('maps_root', _maps_root_default)
        self.declare_parameter('active_map', _active_map_default)
        self.maps_root = self.get_parameter('maps_root').value or _maps_root_default
        self.active_map = self.get_parameter('active_map').value or _active_map_default
        self.session_dir = _os.path.join(self.maps_root, self.active_map) if self.maps_root else ''

        # --- Publisher: 实时状态推送 ---
        self.task_status_pub = self.create_publisher(TaskStatus, 'task_status', 10)
        self.search_trace_pub = self.create_publisher(ObjectSearchTrace, 'object_search_trace', 10)

        # --- Services: UI 调用入口 ---
        self.create_service(
            ProcessNLPQuery, 'start_task',
            self.start_task_callback, callback_group=self.cb_group)
        self.create_service(
            Trigger, 'cancel_task',
            self.cancel_task_callback, callback_group=self.cb_group)
        self.create_service(
            Trigger, 'query_task_status',
            self.query_task_status_callback, callback_group=self.cb_group)
        self.create_service(
            ConfirmTask, 'confirm_task',
            self._confirm_task_callback, callback_group=self.cb_group)

        # --- Clients: 异步调用下游服务 ---
        self.nlp_client = self.create_client(
            ProcessNLPQuery, 'process_nlp_query', callback_group=self.cb_group)
        self.plan_client = self.create_client(
            PlanNavigation, 'plan_navigation', callback_group=self.cb_group)
        self.get_pose_client = self.create_client(
            GetNodePose, 'get_node_pose', callback_group=self.cb_group)
        self.exec_client = self.create_client(
            ExecuteNavigation, 'execute_navigation', callback_group=self.cb_group)

        # --- Subscription: 导航反馈 ---
        self.create_subscription(
            NavigationFeedback, 'navigation_feedback',
            self.navigation_feedback_callback, 10,
            callback_group=self.cb_group)

        # --- Phase 2: ExploreHome Action Client ---
        self.explore_client = ActionClient(
            self, ExploreHome, 'explore_home', callback_group=self.cb_group)
        self._explore_goal_handle = None

        # --- Phase 3: 搜索物体服务 Clients ---
        self.capture_client = self.create_client(
            CaptureImage, 'capture_panorama', callback_group=self.cb_group)
        self.check_object_client = self.create_client(
            CheckObjectPresence, 'check_object_presence',
            callback_group=self.cb_group)
        self.annotate_client = self.create_client(
            AnnotateSemantic, 'annotate_semantic', callback_group=self.cb_group)
        self.update_semantic_client = self.create_client(
            UpdateSemantic, 'update_semantic', callback_group=self.cb_group)

        # --- 搜索状态 (Phase 3) ---
        self.current_session_id = ''
        self.search_target = ''
        self.search_candidates = []
        self.search_index = 0
        self.search_images = []
        self.search_visited_nodes = []
        self.search_failed_nodes = []
        self.search_raw_image_entries = []
        self._check_results = []
        self._check_pending = 0
        self.search_current_node_pose = None
        self.search_partial_capture = False
        self.search_capture_error = ''
        # Round 6: 候选距离提示（node_id → near/mid/far/unknown） + 所有节点的 tentative 观测缓存
        self.search_candidate_dist_hints = {}
        self.search_candidate_details = {}
        self.search_tentatives = []

        # --- 消息队列 (Phase 10) ---
        self._pending_queue = []  # [{text_input, context, session_id, sender_name, task_id}]
        self._MAX_QUEUE = 5
        self._queue_timer = None

        # --- Watchdog: 超时保护 ---
        self._last_activity_time = time.monotonic()
        self._watchdog_warn_sec = 30.0   # 30s 无活动 → 心跳提示
        self._watchdog_timeout_sec = 60.0  # 60s 无活动 → 超时失败
        self._watchdog_warned = False
        self.create_timer(10.0, self._watchdog_tick, callback_group=self.cb_group)

        # --- ChatEvent HTTP 桥接 ---
        self.declare_parameter('chat_api_port', 5173)
        self._chat_api_port = self.get_parameter('chat_api_port').value

        self.get_logger().info('InteractionManager initialized (async mode)')

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def _set_state(self, new_state: TaskState):
        """线程安全地设置状态，终态时自动触发队列处理"""
        with self._lock:
            self.task_state = new_state
        # 终态 → 延迟 1s 处理队列下一条
        if new_state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED):
            if self._queue_timer:
                self._queue_timer.cancel()
            self._queue_timer = threading.Timer(1.0, self._try_process_next)
            self._queue_timer.start()

    def _get_state(self) -> TaskState:
        """线程安全地获取状态"""
        with self._lock:
            return self.task_state

    def _publish_status(self, message: str, progress: float = 0.0):
        """发布 TaskStatus 到 /task_status topic"""
        self._last_activity_time = time.monotonic()
        self._watchdog_warned = False
        state = self._get_state()
        with self._lock:
            self._history.append(f'[{state.value}] {message}')
            history_str = '\n'.join(self._history[-20:])  # 最近20条

        msg = TaskStatus()
        msg.task_id = self.current_task_id
        msg.state = state.value
        msg.current_message = message
        msg.progress = progress
        msg.history = history_str
        msg.user_query_needed = ''
        self.task_status_pub.publish(msg)
        self.get_logger().info(f'[{state.value}] {message} (progress={progress:.1f})')

    def _fail(self, reason: str):
        """进入失败状态并推送"""
        self._set_state(TaskState.FAILED)
        self._publish_status(reason, progress=0.0)

    def _publish_search_trace(self, phase: str, event_type: str, message: str, **kwargs):
        """发布结构化搜索追踪事件到 /object_search_trace"""
        msg = ObjectSearchTrace()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.task_id = self.current_task_id
        msg.target_object = self.search_target
        msg.phase = phase
        msg.event_type = event_type
        msg.message = message
        msg.current_node_id = kwargs.get('current_node_id', -1)
        msg.candidate_node_ids = list(self.search_candidates)
        msg.visited_node_ids = list(self.search_visited_nodes)
        msg.failed_node_ids = list(self.search_failed_nodes)
        msg.current_candidate_index = self.search_index
        msg.total_candidates = len(self.search_candidates)
        msg.current_image_index = kwargs.get('current_image_index', 0)
        msg.total_images = kwargs.get('total_images', 0)
        msg.current_angle_deg = kwargs.get('current_angle_deg', 0)
        msg.current_image_path = kwargs.get('current_image_path', '')
        msg.found = kwargs.get('found', False)
        msg.confidence = kwargs.get('confidence', 0.0)
        msg.evidence_image_path = kwargs.get('evidence_image_path', '')
        self.search_trace_pub.publish(msg)

    def _trace(self, msg: str) -> None:
        """[SEARCH-TRACE] 日志：写入共享文件 + stdout (via ROS logger.info)."""
        _search_trace_raw('im', msg, self.get_logger())

    def _post_chat_event(self, event_data: dict):
        """HTTP POST ChatEvent 到 chatSyncPlugin（fire-and-forget）"""
        import urllib.request
        import urllib.error
        trace = (
            f"event={event_data.get('event_type')} "
            f"task={event_data.get('task_id')} "
            f"session={event_data.get('session_id')} "
            f"node={event_data.get('node_id')} "
            f"imgs={len(event_data.get('image_paths') or [])}"
        )
        url = f'http://localhost:{self._chat_api_port}/api/chat/ros-event'
        self._trace(
            f'[SEARCH-TRACE] chat_event.post_start {trace} url={url}'
        )
        try:
            body = json.dumps(event_data, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(url, data=body,
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                try:
                    resp_body = resp.read(512).decode('utf-8', errors='replace')
                except Exception:
                    resp_body = ''
                self._trace(
                    f'[SEARCH-TRACE] chat_event.post_done {trace} '
                    f'status={resp.status} body="{resp_body}"'
                )
                if resp.status != 200:
                    self.get_logger().warn(
                        f'ChatEvent POST status={resp.status} {trace} body={resp_body}')
        except Exception as e:
            self._trace(
                f'[SEARCH-TRACE] chat_event.post_error {trace} exc="{e!r}"'
            )
            self.get_logger().warn(f'ChatEvent POST failed: {e} {trace}')

    def _post_node_skip_event(self, node_id: int, reason: str):
        """搜索 skip 路径：emit 一条 search_node_observation 让用户看到跳过原因。
        空 image_paths + 明确 skip 文案，避免前端完全失明。"""
        with self._lock:
            target = self.search_target
            task_id = self.current_task_id
            session_id = self.current_session_id
        self._trace(
            f'[SEARCH-TRACE] skip_event.build node={node_id} reason="{reason}" '
            f'task={task_id} session={session_id} target="{target}"'
        )
        self._post_chat_event({
            'task_id': task_id,
            'session_id': session_id,
            'event_type': 'search_node_observation',
            'role': 'robot',
            'text': f'节点 {node_id} {reason}，去下一个位置看看。',
            'node_id': int(node_id),
            'found': False,
            'confidence': 0.0,
            'image_paths': [],
            'target_object': target,
            'source_phase': 'checking',
            'skip_reason': reason,
        })

    def _watchdog_tick(self):
        """定期检查任务是否卡住，提供心跳反馈和超时保护"""
        state = self._get_state()
        if state in (TaskState.IDLE, TaskState.COMPLETED,
                     TaskState.FAILED, TaskState.CANCELED,
                     TaskState.AWAITING_CONFIRMATION):
            return

        elapsed = time.monotonic() - self._last_activity_time

        if elapsed >= self._watchdog_timeout_sec:
            self.get_logger().warn(
                f'Watchdog timeout: state={state.value}, no activity for {elapsed:.0f}s')
            self._fail(f'操作超时了，可能是服务没有响应。你可以再试一次~')

        elif elapsed >= self._watchdog_warn_sec and not self._watchdog_warned:
            self._watchdog_warned = True
            self.get_logger().info(
                f'Watchdog heartbeat: state={state.value}, waiting {elapsed:.0f}s')
            # 发布心跳但不更新 _last_activity_time（避免无限续命）
            state_val = state.value
            msg = TaskStatus()
            msg.task_id = self.current_task_id
            msg.state = state_val
            msg.current_message = f'仍在处理中，请稍候...'
            msg.progress = 0.0
            msg.history = ''
            msg.user_query_needed = ''
            self.task_status_pub.publish(msg)

    # ========================================================================
    # Service Callbacks
    # ========================================================================

    def start_task_callback(self, request, response):
        """
        UI 调用入口。立即返回 (< 100ms)，后续通过 /task_status 推送进度。
        """
        import re
        current = self._get_state()

        # stop 关键词检测：即使任务繁忙也允许通过
        stop_pattern = re.compile(r'(停[下止]|取消|别走|不要去|算了|不去了|别去)')
        is_stop_request = bool(stop_pattern.search(request.text_input or ''))

        if is_stop_request and current not in (TaskState.IDLE, TaskState.COMPLETED,
                                                TaskState.FAILED, TaskState.CANCELED):
            # 先强制取消当前任务 + 清空队列
            if self._explore_goal_handle:
                try:
                    self._explore_goal_handle.cancel_goal_async()
                except Exception:
                    pass
            with self._lock:
                cleared_items = list(self._pending_queue)
                self._pending_queue.clear()
            # 通知排队中的前端：任务已取消
            self._notify_queue_canceled(cleared_items)
            self._set_state(TaskState.CANCELED)
            self.get_logger().info(f'Force-canceled task + cleared queue for stop request')

        current = self._get_state()
        if current not in (TaskState.IDLE, TaskState.COMPLETED,
                           TaskState.FAILED, TaskState.CANCELED):
            # 忙碌 → 入队而不是拒绝
            with self._lock:
                if len(self._pending_queue) >= self._MAX_QUEUE:
                    response.success = False
                    response.error_message = '队列已满，请稍后再试'
                    return response

                queued_task_id = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
                position = len(self._pending_queue) + 1
                self._pending_queue.append({
                    'text_input': request.text_input,
                    'context': request.context,
                    'session_id': getattr(request, 'session_id', '') or '',
                    'sender_name': getattr(request, 'sender_name', '') or '',
                    'task_id': queued_task_id,
                })

            self.get_logger().info(
                f'Task queued (position {position}): "{request.text_input}"')

            response.success = True
            response.intent = 'queued'
            response.confidence = 0.0
            response.query_json = json.dumps({
                'task_id': queued_task_id,
                'queued': True,
                'position': position,
            })
            response.error_message = ''
            return response

        # 重置状态
        with self._lock:
            self.current_task_id = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
            self.current_session_id = getattr(request, 'session_id', '') or ''
            self.current_intent = ''
            self.current_candidates = []
            self._history = []
            self.search_target = ''
            self.search_candidates = []
            self.search_index = 0
            self.search_raw_image_entries = []
            self._check_results = []
            self._check_pending = 0
            self.search_current_node_pose = None
            self.search_partial_capture = False
            self.search_capture_error = ''
            self.search_candidate_dist_hints = {}
            self.search_candidate_details = {}
            self.search_tentatives = []

        self._set_state(TaskState.UNDERSTANDING)
        self._publish_status('正在理解您的指令...', progress=0.05)

        self.get_logger().info(
            f'Start task {self.current_task_id}: "{request.text_input}"')

        # 异步调用 NLP
        nlp_req = ProcessNLPQuery.Request()
        nlp_req.text_input = request.text_input
        nlp_req.context = request.context
        nlp_req.session_id = getattr(request, 'session_id', '') or ''
        nlp_req.sender_name = getattr(request, 'sender_name', '') or ''

        future = self.nlp_client.call_async(nlp_req)
        future.add_done_callback(self._on_nlp_done)

        # 立即返回
        response.success = True
        response.intent = ''
        response.confidence = 0.0
        response.query_json = json.dumps({'task_id': self.current_task_id})
        response.error_message = ''
        return response

    def cancel_task_callback(self, request, response):
        """取消当前任务并清空队列"""
        current = self._get_state()
        if current in (TaskState.IDLE, TaskState.COMPLETED,
                       TaskState.FAILED, TaskState.CANCELED):
            response.success = False
            response.message = f'No active task to cancel ({current.value})'
            return response

        # 如果正在探索，取消 Action Goal
        if current == TaskState.EXPLORING and self._explore_goal_handle:
            self.get_logger().info('Canceling explore action goal...')
            self._explore_goal_handle.cancel_goal_async()

        # 清空队列
        with self._lock:
            cleared_items = list(self._pending_queue)
            self._pending_queue.clear()
        # 通知排队中的前端：任务已取消
        self._notify_queue_canceled(cleared_items)

        self._set_state(TaskState.CANCELED)
        self._publish_status('任务已取消')
        response.success = True
        response.message = f'Task canceled, {len(cleared_items)} queued items cleared'
        self.get_logger().info(f'Task {self.current_task_id} canceled, queue cleared ({len(cleared_items)})')
        return response

    def query_task_status_callback(self, request, response):
        """查询当前任务状态"""
        state = self._get_state()
        response.success = True
        response.message = state.value
        return response

    def _confirm_task_callback(self, request, response):
        """用户确认或拒绝搜索任务"""
        state = self._get_state()
        if state != TaskState.AWAITING_CONFIRMATION:
            response.success = False
            response.message = f'Not awaiting confirmation (state={state.value})'
            return response

        if request.confirmed:
            self.get_logger().info(
                f'User confirmed search for "{self.search_target}"')
            self._set_state(TaskState.SEARCHING)
            self._publish_status(
                f'好的，马上出发找{self.search_target}！', progress=0.2)
            self._publish_search_trace('planning', 'plan_ready',
                f'用户确认搜索，{len(self.search_candidates)} 个候选位置')
            self._navigate_to_search_node()
        else:
            self.get_logger().info(
                f'User rejected search for "{self.search_target}"')
            self._set_state(TaskState.COMPLETED)
            self._publish_status(
                f'好的，如果之后需要找{self.search_target}，随时告诉我~',
                progress=1.0)

        response.success = True
        response.message = 'confirmed' if request.confirmed else 'rejected'
        return response

    # ========================================================================
    # 消息队列: 自动处理下一条
    # ========================================================================

    def _notify_queue_canceled(self, items: list):
        """为被清除的队列项发布 canceled 状态，让前端解除排队等待"""
        for item in items:
            msg = TaskStatus()
            msg.task_id = item['task_id']
            msg.state = 'canceled'
            msg.current_message = '排队的任务已取消'
            msg.progress = 0.0
            msg.history = ''
            msg.user_query_needed = ''
            self.task_status_pub.publish(msg)

    def _try_process_next(self):
        """从队列取出下一条任务并处理"""
        current = self._get_state()
        if current not in (TaskState.IDLE, TaskState.COMPLETED,
                           TaskState.FAILED, TaskState.CANCELED):
            return

        with self._lock:
            if not self._pending_queue:
                return
            item = self._pending_queue.pop(0)
            remaining = len(self._pending_queue)

        self.get_logger().info(
            f'Dequeue task {item["task_id"]}: "{item["text_input"]}" '
            f'({remaining} remaining)')

        # 重置状态，使用预分配的 task_id
        with self._lock:
            self.current_task_id = item['task_id']
            self.current_session_id = item['session_id']
            self.current_intent = ''
            self.current_candidates = []
            self._history = []
            self.search_target = ''
            self.search_candidates = []
            self.search_index = 0
            self.search_raw_image_entries = []
            self._check_results = []
            self._check_pending = 0
            self.search_current_node_pose = None
            self.search_partial_capture = False
            self.search_capture_error = ''
            self.search_candidate_dist_hints = {}
            self.search_candidate_details = {}
            self.search_tentatives = []

        self._set_state(TaskState.UNDERSTANDING)
        self._publish_status('正在理解您的指令...', progress=0.05)

        # 异步调用 NLP
        nlp_req = ProcessNLPQuery.Request()
        nlp_req.text_input = item['text_input']
        nlp_req.context = item['context']
        nlp_req.session_id = item['session_id']
        nlp_req.sender_name = item['sender_name']

        future = self.nlp_client.call_async(nlp_req)
        future.add_done_callback(self._on_nlp_done)

    # ========================================================================
    # 异步回调链: navigate_to 场景
    # ========================================================================

    def _on_nlp_done(self, future):
        """NLP 返回后的回调"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            self._fail(f'NLP 服务调用失败: {e}')
            return

        if result is None or not result.success:
            err = result.error_message if result else 'timeout'
            self._fail(f'NLP 理解失败: {err}')
            return

        intent = result.intent
        entities_json = result.query_json
        confidence = result.confidence

        with self._lock:
            self.current_intent = intent

        self.get_logger().info(
            f'NLP result: intent={intent}, confidence={confidence:.2f}')

        # 提取小拓的自然语言回复
        chat_response = ''
        try:
            data = json.loads(entities_json)
            chat_response = data.get('chat_response', '')
        except (json.JSONDecodeError, TypeError):
            pass

        # 按意图分发
        if intent in ('navigate_to', 'navigate', 'ask_direction'):
            self._set_state(TaskState.PLANNING)
            msg = chat_response or f'意图: {intent}，正在规划路径...'
            self._publish_status(msg, progress=0.15)
            self._start_planning(intent, entities_json, confidence)

        elif intent == 'explore_new_home':
            if chat_response:
                self._publish_status(chat_response, progress=0.05)
            self._handle_explore()

        elif intent == 'locate_object':
            # 提取实体列表
            try:
                data = json.loads(entities_json) if entities_json else {}
                entities_list = data.get('entities', []) if isinstance(data, dict) else []
            except (json.JSONDecodeError, TypeError):
                entities_list = []

            # 过滤掉非物理物体的实体（如"地图"、"位置"等抽象概念）
            abstract_words = {'地图', '位置', '方向', '路线', '导航', '任务', '状态', '信息', '数据'}
            physical_entities = [e for e in entities_list if not any(aw in e for aw in abstract_words)]

            if not physical_entities:
                # 没有具体物理实体，降级为对话
                self._set_state(TaskState.COMPLETED)
                if not chat_response:
                    chat_response = '你可以告诉我具体想找什么物品哦~'
                self._publish_status(chat_response, progress=1.0)
            else:
                if chat_response:
                    self._publish_status(chat_response, progress=0.05)
                self._handle_locate_object(intent, entities_json, confidence)

        elif intent in ('chat', 'query_info', 'conversation'):
            # 对话/查询 — 不触发导航
            if not chat_response:
                chat_response = '你好！我是小拓，你的导航小伙伴~ 可以帮你去指定位置、找东西或探索新环境哦！'
            self._set_state(TaskState.COMPLETED)
            self._publish_status(chat_response, progress=1.0)

        elif intent == 'describe_scene':
            if chat_response:
                self._publish_status(chat_response, progress=0.05)
            self._handle_describe_scene()

        elif intent == 'stop_task':
            self._handle_stop_task(chat_response)

        else:
            # 未知意图也走导航
            self._set_state(TaskState.PLANNING)
            self._publish_status(
                f'意图: {intent}，尝试规划...', progress=0.15)
            self._start_planning(intent, entities_json, confidence)

    def _start_planning(self, intent: str, entities_json: str, confidence: float):
        """异步调用 Planner"""
        plan_req = PlanNavigation.Request()
        plan_req.intent = intent
        plan_req.entities = entities_json
        plan_req.confidence = confidence
        plan_req.current_node = -1

        future = self.plan_client.call_async(plan_req)
        future.add_done_callback(self._on_plan_done)

    def _on_plan_done(self, future):
        """Planner 返回后的回调"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            self._fail(f'规划服务调用失败: {e}')
            return

        if result is None or not result.success:
            self._fail('规划失败: 无法找到合适的目标节点')
            return

        if len(result.candidate_node_ids) == 0:
            self._fail('规划失败: 候选节点为空')
            return

        candidates = list(result.candidate_node_ids)
        target_node = candidates[0]

        with self._lock:
            self.current_candidates = candidates

        self._publish_status(
            f'规划完成，目标节点 {target_node}，正在获取位姿...',
            progress=0.35)

        # 获取目标节点位姿
        pose_req = GetNodePose.Request()
        pose_req.node_id = int(target_node)
        pose_future = self.get_pose_client.call_async(pose_req)
        pose_future.add_done_callback(self._on_pose_done)

    def _on_pose_done(self, future):
        """GetNodePose 返回后的回调"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            self._fail(f'获取位姿失败: {e}')
            return

        if result is None or not result.success:
            msg = result.message if result else 'timeout'
            self._fail(f'获取位姿失败: {msg}')
            return

        self._publish_status('位姿已获取，正在发送导航目标...', progress=0.5)

        # 发送导航命令
        with self._lock:
            target_node = self.current_candidates[0] if self.current_candidates else -1

        exec_req = ExecuteNavigation.Request()
        exec_req.target_pose = result.pose
        exec_req.node_id = int(target_node)

        exec_future = self.exec_client.call_async(exec_req)
        exec_future.add_done_callback(self._on_exec_done)

    def _on_exec_done(self, future):
        """ExecuteNavigation 返回后的回调"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            self._fail(f'导航执行失败: {e}')
            return

        if result is None or not result.success:
            msg = result.message if result else 'timeout'
            self._fail(f'导航执行失败: {msg}')
            return

        self._set_state(TaskState.NAVIGATING)
        self._publish_status('导航中，机器人正在前往目标...', progress=0.6)

    # ========================================================================
    # Topic Callback: 导航反馈
    # ========================================================================

    def navigation_feedback_callback(self, msg):
        """处理来自 Executor 的导航反馈"""
        current = self._get_state()

        if current == TaskState.NAVIGATING:
            if msg.status == 'reached':
                intent = ''
                with self._lock:
                    intent = self.current_intent

                if intent == 'locate_object':
                    # Phase 3: 到达搜索节点，开始拍照检查
                    self._on_search_node_reached()
                else:
                    # 普通导航完成
                    self._set_state(TaskState.COMPLETED)
                    self._publish_status(
                        f'已到达目标位置~ 节点 {msg.node_id}',
                        progress=1.0)

            elif msg.status == 'failed':
                self._fail(f'导航失败: {msg.error_message}')

            elif msg.status in ('navigating', 'moving'):
                # 中间进度更新
                p = 0.6 + 0.35 * msg.progress  # 映射到 0.6-0.95
                self._publish_status(
                    f'导航中... 距离目标 {msg.distance_to_target:.1f}m',
                    progress=p)

    # ========================================================================
    # Phase 2: 探索场景 — ExploreHome Action Client
    # ========================================================================

    def _handle_explore(self):
        """处理 explore_new_home 意图: 发送 ExploreHome Action Goal"""
        self._set_state(TaskState.EXPLORING)
        self._publish_status('正在启动探索...', progress=0.05)

        if not self.explore_client.wait_for_server(timeout_sec=5.0):
            self._fail('探索服务不可用 (explore_home action server 未启动)')
            return

        goal = ExploreHome.Goal()
        goal.session_id = self.current_task_id
        goal.map_prefix = ''

        send_goal_future = self.explore_client.send_goal_async(
            goal, feedback_callback=self._explore_feedback_cb)
        send_goal_future.add_done_callback(self._explore_goal_response_cb)

    def _explore_goal_response_cb(self, future):
        """Goal 是否被接受"""
        try:
            goal_handle = future.result()
        except Exception as e:
            self._fail(f'探索请求失败: {e}')
            return

        if not goal_handle.accepted:
            self._fail('探索请求被拒绝')
            return

        self._explore_goal_handle = goal_handle
        self._publish_status('探索已启动，正在检测前沿点...', progress=0.1)

        # 等待结果
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._explore_result_cb)

    def _explore_feedback_cb(self, feedback_msg):
        """探索中间反馈"""
        if self._get_state() != TaskState.EXPLORING:
            return
        fb = feedback_msg.feedback
        self._publish_status(
            f'探索中: {fb.status}，前沿点: {fb.frontier_count}',
            progress=fb.progress)

    def _explore_result_cb(self, future):
        """探索完成/失败/取消"""
        self._explore_goal_handle = None

        try:
            result = future.result()
        except Exception as e:
            self._fail(f'探索结果获取失败: {e}')
            return

        action_result = result.result
        status = result.status

        # status: 4=SUCCEED, 5=CANCELED, 6=ABORTED
        if status == 4:  # SUCCEED
            self._set_state(TaskState.COMPLETED)
            msg = f'探索完成! {action_result.message}'
            if action_result.map_yaml:
                msg += f' 地图已保存'
            self._publish_status(msg, progress=1.0)
        elif status == 5:  # CANCELED
            self._set_state(TaskState.CANCELED)
            self._publish_status('探索已取消', progress=0.0)
        else:  # ABORTED or other
            self._fail(f'探索失败: {action_result.message}')

    # ========================================================================
    # describe_scene — 拍照描述当前场景
    # ========================================================================

    def _handle_describe_scene(self):
        """拍照并用 VLM 描述当前场景"""
        self._set_state(TaskState.CHECKING)
        self._publish_status('正在拍照观察周围环境...', progress=0.2)

        capture_req = CaptureImage.Request()
        capture_req.save_path = '/tmp/sstg_scene_capture'
        future = self.capture_client.call_async(capture_req)
        future.add_done_callback(self._on_scene_capture_done)

    def _on_scene_capture_done(self, future):
        """场景拍照完成，调用 VLM 分析"""
        if self._get_state() == TaskState.CANCELED:
            return
        try:
            result = future.result()
        except Exception as e:
            self._fail(f'拍照失败: {e}')
            return

        if not result or not result.success:
            # 拍照服务不可用时，给出友好回复
            self._set_state(TaskState.COMPLETED)
            self._publish_status(
                '抱歉，我现在没法拍照看周围的环境，摄像头可能还没准备好~',
                progress=1.0)
            return

        self._publish_status('正在分析场景...', progress=0.6)

        # 用 check_object_presence 服务做通用场景描述
        check_req = CheckObjectPresence.Request()
        check_req.image_paths = result.image_paths if hasattr(result, 'image_paths') else []
        check_req.target_object = '请详细描述这个场景中你看到的所有物体、家具和环境特征'
        check_future = self.check_object_client.call_async(check_req)
        check_future.add_done_callback(self._on_scene_describe_done)

    def _on_scene_describe_done(self, future):
        """VLM 场景描述完成"""
        if self._get_state() == TaskState.CANCELED:
            return
        try:
            result = future.result()
            description = result.description if hasattr(result, 'description') and result.description else '我看了看周围，但没能识别出具体的内容~'
        except Exception as e:
            description = f'场景分析出了点问题: {e}'

        self._set_state(TaskState.COMPLETED)
        self._publish_status(description, progress=1.0)

    # ========================================================================
    # stop_task — 自然语言取消任务
    # ========================================================================

    def _handle_stop_task(self, chat_response: str):
        """通过自然语言停止当前任务"""
        current = self._get_state()
        active_states = {TaskState.PLANNING, TaskState.NAVIGATING,
                         TaskState.EXPLORING, TaskState.SEARCHING,
                         TaskState.CHECKING}

        # stop_task 本身已经创建了新 task，旧 task 已被覆盖
        # 但如果之前有探索 action goal，需要取消
        if self._explore_goal_handle:
            try:
                self._explore_goal_handle.cancel_goal_async()
            except Exception:
                pass

        if not chat_response:
            chat_response = '好的，已经停下来了~'
        self._set_state(TaskState.COMPLETED)
        self._publish_status(chat_response, progress=1.0)

    # ========================================================================
    # Phase 3: 找物体场景 — 异步搜索循环
    # ========================================================================

    def _handle_locate_object(self, intent: str, entities_json: str,
                              confidence: float):
        """
        处理 locate_object 意图。
        流程: Planner 获取候选节点 → 逐个导航 → 拍照 → VLM 检查 → 找到/继续
        """
        # 从 entities_json 中提取目标物体
        import re
        target = ''
        data = {}
        try:
            data = json.loads(entities_json) if entities_json else {}
            entities = data.get('entities', []) if isinstance(data, dict) else []
            # 过滤掉动词/功能词，只保留名词性物体
            non_object_words = {
                '找', '看', '帮', '拿', '给', '去', '在', '有', '要',
                '查', '搜', '取', '拍', '发', '送', '放', '带',
                '我', '你', '他', '的', '了', '吗', '呢', '吧',
                '一下', '一些', '什么', '哪里', '哪个', '这个', '那个',
            }
            filtered = [e for e in entities
                        if e and len(e) >= 2 and e not in non_object_words]
            if not filtered:
                filtered = [e for e in entities
                            if e and e not in non_object_words]
            if filtered:
                target = filtered[0]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # 回退：从原始文本中用正则提取物体名
        if not target:
            original = data.get('original_text', '') if isinstance(data, dict) else ''
            patterns = [
                r'(?:找|帮我找|帮忙找|搜|查|看看)(?:一下)?(.{1,8}?)(?:在哪|的位置|的图|$)',
                r'(?:我的|那个)?(.{1,6}?)(?:在哪|在哪里|的位置|去哪了)',
            ]
            for pat in patterns:
                m = re.search(pat, original)
                if m and m.group(1).strip():
                    target = m.group(1).strip()
                    break

        if not target:
            target = '未知物体'

        # 规范化: "我的书包"/"帮我找书包" → "书包"。保证 search_target 全链路
        # （planner / chatSyncPlugin 历史图检索 / 文案）使用同一个 canonical form。
        _raw_before_norm = target
        canonical = normalize_search_target(target)
        if canonical:
            target = canonical

        # 语言一致性：若 NLP 意外返回英文（如 "backpack"）但用户原话是中文（"找书包"），
        # 换回中文 canonical，下游所有文案/UI 展示保持与用户语言一致。
        _original_text = data.get('original_text', '') if isinstance(data, dict) else ''
        target = prefer_chinese_label(target, _original_text)

        try:
            _entities_dbg = data.get('entities', []) if isinstance(data, dict) else []
        except Exception:
            _entities_dbg = []
        self._trace(
            f'[SEARCH-TRACE] target.normalize raw="{_raw_before_norm}" '
            f'canonical="{target}" entities={_entities_dbg}'
        )

        with self._lock:
            self.search_target = target
            self.search_candidates = []
            self.search_index = 0
            self.search_images = []
            self.search_raw_image_entries = []
            self._check_results = []
            self._check_pending = 0
            self.search_visited_nodes = []
            self.search_failed_nodes = []
            self.search_candidate_dist_hints = {}
            self.search_candidate_details = {}
            self.search_tentatives = []
            self.search_partial_capture = False
            self.search_capture_error = ''
            self.search_current_node_pose = None

        self._set_state(TaskState.SEARCHING)
        self._publish_status(
            f'正在搜索 "{target}"，规划搜索路径...', progress=0.1)

        # 先调用 Planner 获取候选节点
        plan_req = PlanNavigation.Request()
        plan_req.intent = intent
        plan_req.entities = entities_json
        plan_req.confidence = confidence
        plan_req.current_node = -1
        self.get_logger().info(
            f'[IM][R7++][plan.call] target="{target}" intent={intent} '
            f'entities_json={entities_json}')

        future = self.plan_client.call_async(plan_req)
        future.add_done_callback(self._on_search_plan_done)

    def _on_search_plan_done(self, future):
        """搜索规划完成: 存储候选列表，开始逐节点搜索"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            self._fail(f'搜索规划失败: {e}')
            return

        if result is None or not result.success or len(result.candidate_node_ids) == 0:
            # 精确匹配失败 → 全局搜索：用所有可达节点作为候选
            target = getattr(self, 'search_target', '该物品')
            self.get_logger().warn(
                f'[IM][R7++][plan.empty] target="{target}" '
                f'result_success={getattr(result, "success", None)} '
                f'n_candidates={len(result.candidate_node_ids) if result else "N/A"} '
                f'→ fallback to global search (entities=["*"])')
            self.get_logger().info(
                f'No exact match for "{target}", falling back to global search')
            # 尝试用 navigate_to 意图获取所有节点
            fallback_req = PlanNavigation.Request()
            fallback_req.intent = 'navigate_to'
            fallback_req.entities = json.dumps({
                'intent': 'navigate_to', 'entities': ['*'], 'confidence': 0.5})
            fallback_req.confidence = 0.5
            fallback_req.current_node = -1
            fallback_future = self.plan_client.call_async(fallback_req)
            fallback_future.add_done_callback(self._on_global_search_plan_done)
            self._publish_status(
                f'没有找到"{target}"的精确位置，我去各个房间找找看~',
                progress=0.1)
            return

        with self._lock:
            self.search_candidates = list(result.candidate_node_ids)
            self.search_index = 0
            self.search_candidate_dist_hints, self.search_candidate_details = self._extract_plan_details(result)
            self.search_tentatives = []
            total = len(self.search_candidates)

        self._set_state(TaskState.AWAITING_CONFIRMATION)
        self._publish_status(
            f'找到 {total} 个可能的位置，等待确认...', progress=0.15)
        self._publish_search_trace('planning', 'plan_ready',
            f'找到 {total} 个候选位置，等待用户确认')

        self._post_chat_event({
            'task_id': self.current_task_id,
            'session_id': self.current_session_id,
            'event_type': 'search_confirmation_request',
            'role': 'robot',
            'text': f'我的记忆中有{self.search_target}的印象，'
                    f'需要我去现场确认一下吗？',
            'node_id': -1,
            'found': False,
            'confidence': 0.0,
            'image_paths': [],
            'target_object': self.search_target,
            'source_phase': 'confirming',
            'candidate_node_ids': list(result.candidate_node_ids),
            'reasoning': result.reasoning or '',
        })

    def _on_global_search_plan_done(self, future):
        """全局搜索规划完成：用所有返回的节点作为搜索候选"""
        if self._get_state() == TaskState.CANCELED:
            return
        try:
            result = future.result()
        except Exception:
            result = None

        if result and result.success and len(result.candidate_node_ids) > 0:
            with self._lock:
                self.search_candidates = list(result.candidate_node_ids)
                self.search_index = 0
                self.search_candidate_dist_hints, self.search_candidate_details = self._extract_plan_details(result)
                self.search_tentatives = []
                total = len(self.search_candidates)

            self._set_state(TaskState.AWAITING_CONFIRMATION)
            self._publish_status(
                f'准备搜索 {total} 个位置，等待确认...', progress=0.15)

            self._post_chat_event({
                'task_id': self.current_task_id,
                'session_id': self.current_session_id,
                'event_type': 'search_confirmation_request',
                'role': 'robot',
                'text': f'当前记忆中没有找到{self.search_target}的确切位置，'
                        f'我可以去 {total} 个位置逐个找找看，需要我出发吗？',
                'node_id': -1,
                'found': False,
                'confidence': 0.0,
                'image_paths': [],
                'target_object': self.search_target,
                'source_phase': 'confirming',
                'candidate_node_ids': list(result.candidate_node_ids),
                'reasoning': '',
            })
        else:
            target = getattr(self, 'search_target', '该物品')
            self._set_state(TaskState.COMPLETED)
            self._publish_status(
                f'抱歉，当前地图中没有可以搜索的位置。你可以先探索更多区域~',
                progress=1.0)

    def _navigate_to_search_node(self):
        """导航到当前搜索候选节点"""
        if self._get_state() == TaskState.CANCELED:
            return

        with self._lock:
            idx = self.search_index
            candidates = self.search_candidates
            target = self.search_target

        if idx >= len(candidates):
            self._post_chat_event({
                'task_id': self.current_task_id,
                'session_id': self.current_session_id,
                'event_type': 'search_task_summary',
                'role': 'robot',
                'text': f'我把所有候选位置都看过了，暂时没有找到{target}。',
                'node_id': -1,
                'found': False,
                'confidence': 0.0,
                'image_paths': [],
                'target_object': target,
                'source_phase': 'completed',
            })
            self._set_state(TaskState.COMPLETED)
            self._publish_status(
                f'我把 {len(candidates)} 个位置都看了一遍，没有找到"{target}"。'
                f'可能它不在当前地图范围内，你可以试试探索更多区域~',
                progress=1.0)
            self._publish_search_trace('completed', 'completed_not_found',
                f'所有 {len(candidates)} 个位置搜索完毕，未找到 "{target}"')
            return

        node_id = candidates[idx]
        total = len(candidates)
        self._set_state(TaskState.SEARCHING)
        self._publish_status(
            f'正在前往第 {idx + 1}/{total} 个位置 (节点{node_id}) 查找 "{target}"...',
            progress=0.2 + 0.6 * (idx / total))
        self._publish_search_trace('navigating', 'navigate_start',
            f'前往节点 {node_id}', current_node_id=node_id)

        # 获取位姿
        pose_req = GetNodePose.Request()
        pose_req.node_id = int(node_id)
        pose_future = self.get_pose_client.call_async(pose_req)
        pose_future.add_done_callback(self._on_search_pose_done)

    def _on_search_pose_done(self, future):
        """搜索: 获取位姿后发送导航命令"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            # 跳过此节点，继续下一个
            self.get_logger().warn(f'搜索节点位姿获取失败: {e}')
            with self._lock:
                node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
                self.search_failed_nodes.append(node_id)
                self.search_index += 1
            self._publish_search_trace('navigating', 'node_skip',
                f'节点 {node_id} 位姿获取失败，跳过', current_node_id=node_id)
            if node_id >= 0:
                self._post_node_skip_event(node_id, '位姿获取失败')
            self._navigate_to_search_node()
            return

        if result is None or not result.success:
            with self._lock:
                node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
                self.search_failed_nodes.append(node_id)
                self.search_index += 1
            self._publish_search_trace('navigating', 'node_skip',
                f'节点 {node_id} 位姿获取失败，跳过', current_node_id=node_id)
            if node_id >= 0:
                self._post_node_skip_event(node_id, '位姿获取失败')
            self._navigate_to_search_node()
            return

        with self._lock:
            node_id = self.search_candidates[self.search_index]
            self.search_current_node_pose = result.pose

        exec_req = ExecuteNavigation.Request()
        exec_req.target_pose = result.pose
        exec_req.node_id = int(node_id)

        exec_future = self.exec_client.call_async(exec_req)
        exec_future.add_done_callback(self._on_search_exec_done)

    def _on_search_exec_done(self, future):
        """搜索: 导航命令已发送"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            self._fail(f'搜索导航执行失败: {e}')
            return

        if result is None or not result.success:
            # 跳过此节点
            with self._lock:
                node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
                self.search_index += 1
            if node_id >= 0:
                self._post_node_skip_event(node_id, '导航执行未成功')
            self._navigate_to_search_node()
            return

        self._set_state(TaskState.NAVIGATING)
        self._publish_status('正在前往搜索位置...')

    def _on_search_node_reached(self):
        """到达搜索节点: 拍照"""
        with self._lock:
            node_id = self.search_candidates[self.search_index]
            target = self.search_target

        self._set_state(TaskState.CHECKING)
        self._publish_status(
            f'已到达节点 {node_id}，正在拍照检查 "{target}"...')
        self._publish_search_trace('capturing', 'navigate_reached',
            f'已到达节点 {node_id}', current_node_id=node_id)

        capture_req = CaptureImage.Request()
        capture_req.node_id = int(node_id)
        with self._lock:
            if self.search_current_node_pose is not None:
                capture_req.pose = self.search_current_node_pose
            else:
                from geometry_msgs.msg import PoseStamped
                capture_req.pose = PoseStamped()

        capture_future = self.capture_client.call_async(capture_req)
        capture_future.add_done_callback(self._on_search_capture_done)

    def _on_search_capture_done(self, future):
        """搜索: 拍照完成，开始逐张检查"""
        with self._lock:
            _node_dbg = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
        self._trace(
            f'[SEARCH-TRACE] capture_done.enter node={_node_dbg} '
            f'state={self._get_state()}'
        )
        if self._get_state() == TaskState.CANCELED:
            self._trace(
                f'[SEARCH-TRACE] capture_done.canceled node={_node_dbg}'
            )
            return

        try:
            result = future.result()
        except Exception as e:
            self.get_logger().warn(f'拍照失败: {e}，跳过此节点')
            with self._lock:
                node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
                self.search_failed_nodes.append(node_id)
                self.search_index += 1
            self._trace(
                f'[SEARCH-TRACE] capture_done.skip_branch reason="拍照异常" '
                f'node={node_id} exc="{e!r}"'
            )
            self._publish_search_trace('navigating', 'node_skip',
                f'节点 {node_id} 拍照失败，跳过', current_node_id=node_id)
            if node_id >= 0:
                self._post_node_skip_event(node_id, '拍照异常')
            self._navigate_to_search_node()
            return

        _paths_count = len(result.image_paths) if (result is not None and result.image_paths) else 0
        _success = bool(result.success) if result is not None else False
        _first = (result.image_paths[0] if _paths_count > 0 else '')
        _err = (result.error_message if result is not None else 'result=None')
        self._trace(
            f'[SEARCH-TRACE] capture_done.result node={_node_dbg} '
            f'success={_success} paths_count={_paths_count} '
            f'first_path="{_first}" err="{_err}"'
        )

        if result is None or not result.image_paths:
            self.get_logger().warn('拍照失败或无图片，跳过此节点')
            with self._lock:
                node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
                self.search_failed_nodes.append(node_id)
                self.search_index += 1
            self._trace(
                f'[SEARCH-TRACE] capture_done.skip_branch reason="未拿到可用的现场图片" '
                f'node={node_id} success={_success} paths_count={_paths_count}'
            )
            self._publish_search_trace('navigating', 'node_skip',
                f'节点 {node_id} 无图片，跳过', current_node_id=node_id)
            if node_id >= 0:
                self._post_node_skip_event(node_id, '未拿到可用的现场图片')
            self._navigate_to_search_node()
            return

        # 解析 image_paths (格式: "angle:path")
        image_paths = []
        for entry in result.image_paths:
            if ':' in entry:
                path = entry.split(':', 1)[1]
            else:
                path = entry
            image_paths.append(path)

        with self._lock:
            self.search_images = image_paths
            self.search_raw_image_entries = list(result.image_paths)
            self.search_partial_capture = (not _success) or (_paths_count < 4)
            self.search_capture_error = _err if self.search_partial_capture else ''
            node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1

        self._trace(
            f'[SEARCH-TRACE] capture_done.go_check node={node_id} '
            f'images_count={len(image_paths)} partial={not _success}'
        )
        self._publish_search_trace('checking', 'capture_ready',
            f'节点 {node_id} 拍照完成，{len(image_paths)} 张图待检查',
            current_node_id=node_id, total_images=len(image_paths))

        self._check_all_images_parallel()

    def _check_all_images_parallel(self):
        """并行检查所有图片"""
        if self._get_state() == TaskState.CANCELED:
            return

        with self._lock:
            images = list(self.search_images)
            target = self.search_target
            self._check_results = [None] * len(images)
            self._check_pending = len(images)

        self._publish_status(f'正在检查 {len(images)} 张图片...')

        for idx, image_path in enumerate(images):
            check_req = CheckObjectPresence.Request()
            check_req.image_path = image_path
            check_req.target_object = target
            future = self.check_object_client.call_async(check_req)
            future.add_done_callback(
                lambda f, i=idx: self._on_parallel_check_done(f, i))

    def _on_parallel_check_done(self, future, image_index):
        """单张图 check 完成回调"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            self.get_logger().warn(f'Check image {image_index} failed: {e}')
            result = None

        with self._lock:
            self._check_results[image_index] = result
            self._check_pending -= 1
            all_done = (self._check_pending <= 0)

        if all_done:
            self._on_all_checks_done()

    def _on_all_checks_done(self):
        """全部 check 完成：按 distance_hint 加权，tentative 则累积继续搜索，hard_hit 才立即收尾"""
        if self._get_state() == TaskState.CANCELED:
            return

        with self._lock:
            node_id = self.search_candidates[self.search_index]
            target = self.search_target
            images = list(self.search_images)
            results = list(self._check_results)
            raw_entries = list(self.search_raw_image_entries)
            partial = self.search_partial_capture
            dist_hint = self.search_candidate_dist_hints.get(node_id, 'unknown')
            is_last = (self.search_index + 1 >= len(self.search_candidates))

        hit_idx, hit_result = self._pick_best_hit(results)

        if hit_result:
            raw_conf = float(hit_result.confidence)
            adj_conf = raw_conf * DIST_WEIGHT.get(dist_hint, DIST_WEIGHT['unknown'])
            tier = self._classify_tier(raw_conf, dist_hint, adj_conf)
            hit_angle = self._idx_to_angle(images, hit_idx)
            evidence_path = images[hit_idx] if hit_idx is not None and hit_idx < len(images) else ''
            tentative = {
                'node_id': node_id,
                'target': target,
                'hit_idx': hit_idx,
                'hit_angle': hit_angle,
                'result': hit_result,
                'raw_conf': raw_conf,
                'adj_conf': adj_conf,
                'tier': tier,
                'dist_hint': dist_hint,
                'raw_entries': raw_entries,
                'images': images,
                'evidence_path': evidence_path,
                'partial': partial,
            }
            with self._lock:
                self.search_tentatives.append(tentative)
            self._publish_search_trace('checking', 'check_aggregate',
                f'节点 {node_id} tier={tier} raw={raw_conf:.2f} adj={adj_conf:.2f} dh={dist_hint}',
                current_node_id=node_id, confidence=adj_conf)

            if tier == 'hard_hit':
                # R8++: hard_hit 也必须触发后台 annotate/update_semantic/copy_viewpoint，
                # 否则 finalize_found 立刻 return，UI 端永远收不到 semantic_update_done，
                # 该节点 session 目录下的 rgb/depth 也不会被覆盖成本次搜索拍到的新图。
                self._fire_annotate_update_async(node_id, images)
                with self._lock:
                    prior = [x for x in self.search_tentatives if x is not tentative]
                    unvisited = list(self.search_candidates[self.search_index + 1:])
                self._finalize_found(tentative, via='hard_hit', backups=prior,
                                     unvisited_node_ids=unvisited)
                return

            # tentative / confirm / tentative_weak：发"疑似"事件，继续往下一节点
            self._post_tentative_event(tentative)
        else:
            # 本节点无任何 conf>=0.5 的命中
            partial_note = f'（仅拿到 {len(images)} 张图）' if partial else ''
            text = PHRASE_OBSERVATION.format(nid=node_id, target=target, partial=partial_note)
            self._post_chat_event({
                'task_id': self.current_task_id,
                'session_id': self.current_session_id,
                'event_type': 'search_node_observation',
                'role': 'robot',
                'text': text,
                'node_id': node_id,
                'found': False,
                'confidence': 0.0,
                'image_paths': raw_entries,
                'target_object': target,
                'source_phase': 'checking',
            })

        self._fire_annotate_update_async(node_id, images)

        with self._lock:
            self.search_visited_nodes.append(node_id)
            self.search_index += 1
            done_all = self.search_index >= len(self.search_candidates)

        if done_all:
            self._finalize_by_tentatives()
        else:
            self._publish_status(f'节点 {node_id} 未确认 "{target}"，继续搜索...')
            self._publish_search_trace('navigating', 'node_miss',
                f'节点 {node_id} 未确认 "{target}"', current_node_id=node_id)
            self._navigate_to_search_node()

    # ── Round 6 辅助方法 ─────────────────────────────────────────

    def _extract_plan_details(self, plan_result) -> tuple:
        """从 PlanNavigation.Response.plan_json 取 candidate_details。

        返回 (dist_hints, details)：
          - dist_hints: node_id → 距离级别字符串（走 _on_all_checks_done 的置信度加权）
          - details:    node_id → 完整候选明细 dict（relevance_score / best_view_angle /
                        distance_hint / room_type / node_name / match_reason 等，用于未访问
                        候选的 backup 合成，做到 hard_hit 早退后仍能展示规划排名靠后的位置）
        """
        dist_hints: dict = {}
        details: dict = {}
        try:
            payload = json.loads(getattr(plan_result, 'plan_json', '') or '{}')
            for c in payload.get('candidate_details', []) or []:
                nid = int(c.get('node_id', -1))
                if nid < 0:
                    continue
                dh = (c.get('distance_hint') or 'unknown').lower()
                dist_hints[nid] = dh if dh in DIST_WEIGHT else 'unknown'
                details[nid] = c
        except Exception as exc:
            self.get_logger().warn(f'[Round6] 解析 plan_json candidate_details 失败: {exc}')
        return dist_hints, details

    @staticmethod
    def _pick_best_hit(results):
        """遍历 VLM 结果，返回原始 conf 最高且 >= MIN_RAW_CONF 的 (idx, result)"""
        best_idx, best = None, None
        for i, r in enumerate(results):
            if r and getattr(r, 'found', False) and float(getattr(r, 'confidence', 0.0)) >= MIN_RAW_CONF:
                if best is None or r.confidence > best.confidence:
                    best_idx, best = i, r
        return best_idx, best

    @staticmethod
    def _classify_tier(raw_conf: float, dist_hint: str, adj_conf: float) -> str:
        # 高 raw 置信度早退：即便距离 unknown/far 被权重打折，只要原始 VLM 已经很确定
        # 且加权后仍过 0.70 门槛，就直接判 hard_hit，避免浪费后续候选 trip。
        # 例：raw=0.95, dist=unknown → adj=0.81 ≥ 0.70 → hard_hit；
        #     raw=0.6, dist=unknown → adj=0.51 < 0.70 → 仍走 tentative_unknown。
        if raw_conf >= 0.85 and adj_conf >= 0.70:
            return 'hard_hit'
        if adj_conf >= HARD_HIT_ADJ and dist_hint == 'near':
            return 'hard_hit'
        if dist_hint == 'near':
            return 'confirm'
        if dist_hint == 'mid':
            return 'tentative'
        if dist_hint == 'far':
            return 'tentative_weak'
        return 'tentative_unknown'

    @staticmethod
    def _idx_to_angle(images: list, hit_idx) -> int:
        """从命中的图片路径里解析出角度（文件名含 NNNdeg_...）"""
        if hit_idx is None or hit_idx >= len(images):
            return -1
        import re
        m = re.search(r'(\d{3})deg', str(images[hit_idx]))
        if m:
            return int(m.group(1))
        # 兜底：按典型 4 方向顺序（0/90/180/270）
        fallback = [0, 90, 180, 270]
        return fallback[hit_idx] if hit_idx < len(fallback) else -1

    @staticmethod
    def _angle_sort_with_hit(raw_entries: list, images: list, hit_idx) -> tuple:
        """按角度 0/90/180/270 排序 raw_entries，保持自然阅读顺序；同时返回命中图在排序后列表里的 1-indexed 位置（未命中返回 0）。"""
        import re
        indexed = list(enumerate(raw_entries or []))

        def _angle_of(i: int) -> int:
            src = ''
            if i < len(images or []):
                src = str(images[i])
            if not src and i < len(raw_entries or []):
                src = str(raw_entries[i])
            m = re.search(r'(\d{3})deg', src)
            if m:
                return int(m.group(1))
            # 兜底：保持原顺序
            return i * 90

        indexed.sort(key=lambda pair: _angle_of(pair[0]))
        sorted_entries = [entry for _, entry in indexed]
        hit_pos = 0
        if hit_idx is not None:
            for new_i, (orig_i, _) in enumerate(indexed):
                if orig_i == hit_idx:
                    hit_pos = new_i + 1
                    break
        return sorted_entries, hit_pos

    def _post_tentative_event(self, t: dict):
        """发"疑似，但离得远不太确定，我再去近处看看"事件"""
        target, nid, angle = t['target'], t['node_id'], t['hit_angle']
        conf = f'{t["adj_conf"]:.0%}'
        if t['tier'] == 'confirm':
            phrase = PHRASE_CONFIRM.format(nid=nid, angle=angle, target=target, conf=conf)
        elif t['tier'] == 'tentative':
            phrase = PHRASE_TENTATIVE.format(nid=nid, angle=angle, target=target, conf=conf)
        elif t['tier'] == 'tentative_weak':
            phrase = PHRASE_TENTATIVE_WEAK.format(nid=nid, angle=angle, target=target, conf=conf)
        else:  # tentative_unknown
            phrase = PHRASE_TENTATIVE_UNKNOWN.format(nid=nid, angle=angle, target=target, conf=conf)
        sorted_entries, _ = self._angle_sort_with_hit(t['raw_entries'], t['images'], t['hit_idx'])
        self._post_chat_event({
            'task_id': self.current_task_id,
            'session_id': self.current_session_id,
            'event_type': 'search_node_tentative',
            'role': 'robot',
            'text': phrase,
            'node_id': nid,
            'found': False,
            'confidence': t['adj_conf'],
            'image_paths': sorted_entries,
            'target_object': target,
            'source_phase': 'checking',
            'hit_angle': angle,
            'dist_hint': t['dist_hint'],
            'tier': t['tier'],
            'description': (getattr(t['result'], 'description', '') or '').strip(),
        })

    def _finalize_found(self, t: dict, via: str, backups: list = None, unvisited_node_ids: list = None):
        """统一的"找到啦"收尾：文案只给硬数据+"看第N张图"位置指引；image_paths 按角度 0/90/180/270 原序；description 单独塞事件里供 LLM 口语化"""
        target, nid, angle = t['target'], t['node_id'], t['hit_angle']
        desc = (getattr(t['result'], 'description', '') or '').strip()
        conf = f'{t["adj_conf"]:.0%}'
        dist_cn = DIST_LABEL_CN.get(t['dist_hint'], '距离不明')
        backups = backups or []
        # 只有在"没有确凿命中"（best_guess）时才提供备选建议；
        # hard_hit / confirmed 已经很确定，用户不需要被备选干扰。
        if via in ('hard_hit', 'confirmed'):
            backup_summary: list = []
            backup_note = ''
        else:
            backup_summary = self._summarize_backups(backups)
            backup_summary = self._extend_backups_from_planner(
                backup_summary, unvisited_node_ids or [], winner_node_id=nid, target_count=3)
            backup_note = self._format_backup_note(backup_summary)

        sorted_entries, hit_pos = self._angle_sort_with_hit(t['raw_entries'], t['images'], t['hit_idx'])
        pos = hit_pos if hit_pos > 0 else 1  # 兜底：至少给"第1张"

        if via == 'hard_hit':
            text = PHRASE_HARD_HIT.format(pos=pos, nid=nid, angle=angle, target=target, conf=conf)
            emit_images = sorted_entries
        elif via == 'confirmed':
            text = PHRASE_CONFIRMED.format(pos=pos, nid=nid, angle=angle, target=target, conf=conf)
            emit_images = sorted_entries
        else:
            # best_guess：winner 已在 tentative 阶段完整展示过图片，这里不再重复图组，
            # 只给一句收尾话 + 备选名单，避免用户看到同一张图出现两次。
            text = PHRASE_BEST_GUESS_SHORT.format(
                nid=nid, angle=angle, conf=conf, dist_cn=dist_cn)
            emit_images = []

        if backup_note:
            text = f'{text}\n{backup_note}'

        self._post_chat_event({
            'task_id': self.current_task_id,
            'session_id': self.current_session_id,
            'event_type': 'search_target_found',
            'role': 'robot',
            'text': text,
            'node_id': nid,
            'found': True,
            'confidence': t['adj_conf'],
            'image_paths': emit_images,
            'target_object': target,
            'source_phase': 'checking',
            'hit_angle': angle,
            'dist_hint': t['dist_hint'],
            'tier': t['tier'],
            'via': via,
            'backup_candidates': backup_summary,
            'hit_image_position': pos if emit_images else 0,
            'description': desc,
        })

        self._set_state(TaskState.COMPLETED)
        self._publish_status(
            f'找到了！"{target}" 在节点 {nid} 的 {angle}° 方向（{t["dist_hint"]}, 置信度 {t["adj_conf"]:.0%}）。',
            progress=1.0)
        self._publish_search_trace('completed', 'found',
            f'search.finalize via={via} node={nid} adj={t["adj_conf"]:.2f} dh={t["dist_hint"]} backups={len(backup_summary)} pos={pos}',
            current_node_id=nid, found=True,
            confidence=t['adj_conf'],
            evidence_image_path=t['evidence_path'])

    @staticmethod
    def _summarize_backups(backups: list, limit: int = 3) -> list:
        """把 tentative 字典精简为 ChatEvent 可序列化的备选条目（adj_conf 降序，取前 limit）"""
        if not backups:
            return []
        sorted_bk = sorted(backups, key=lambda x: x['adj_conf'], reverse=True)[:limit]
        out = []
        for b in sorted_bk:
            image = b['raw_entries'][b['hit_idx']] if (
                b.get('hit_idx') is not None and b['hit_idx'] < len(b['raw_entries'])
            ) else ''
            out.append({
                'node_id': b['node_id'],
                'hit_angle': b['hit_angle'],
                'adj_conf': b['adj_conf'],
                'raw_conf': b['raw_conf'],
                'dist_hint': b['dist_hint'],
                'tier': b['tier'],
                'image_path': image,
                'description': getattr(b['result'], 'description', '') or '',
            })
        return out

    @staticmethod
    def _format_backup_note(backup_summary: list) -> str:
        """把备选节点摘要拼成一句温暖的提示文案；planner_hint（未现场确认）额外加后缀。"""
        if not backup_summary:
            return ''
        items = []
        for b in backup_summary:
            tier = (b.get('tier') or '').lower()
            dist_cn = DIST_LABEL_CN.get(b.get('dist_hint'), b.get('dist_hint') or '')
            conf_pct = f'{b.get("adj_conf", 0.0):.0%}'
            tail = '，未现场确认' if tier == 'planner_hint' else ''
            items.append(f'节点 {b["node_id"]} {b["hit_angle"]}°（{conf_pct}, {dist_cn}{tail}）')
        lead = '另外还有这些位置也值得瞧一眼：' if len(items) > 1 else '再给你一个备选位置：'
        return lead + '、'.join(items) + '。如果第一个不对，可以告诉我，我去下一个看看~'

    def _extend_backups_from_planner(self, summary: list, unvisited_node_ids: list,
                                     winner_node_id: int = -1, target_count: int = 3) -> list:
        """用 planner 输出里未访问的候选（含 relevance_score/distance_hint/best_view_angle）
        补足 backup 列表到 target_count 条；tier 标为 'planner_hint' 表示仅凭规划分合成、尚未现场验证。
        触发时机：hard_hit 早退后 unvisited 队列非空；或任意裁决分支需要凑齐 3 个备选。
        """
        if len(summary) >= target_count or not unvisited_node_ids:
            return summary
        details = getattr(self, 'search_candidate_details', {}) or {}
        already = {b['node_id'] for b in summary}
        if winner_node_id >= 0:
            already.add(winner_node_id)
        for nid in unvisited_node_ids:
            if len(summary) >= target_count:
                break
            if nid in already:
                continue
            d = details.get(nid, {}) or {}
            try:
                relevance = float(d.get('relevance_score', 0.0) or 0.0)
            except (TypeError, ValueError):
                relevance = 0.0
            dist_hint = (d.get('distance_hint') or 'unknown').lower()
            try:
                best_angle = int(d.get('best_view_angle', -1))
            except (TypeError, ValueError):
                best_angle = -1
            if best_angle < 0:
                best_angle = 0
            summary.append({
                'node_id': nid,
                'hit_angle': best_angle,
                'adj_conf': relevance,       # 用 planner 综合相关度作参考展示值
                'raw_conf': 0.0,             # 未经 VLM 现场验证
                'dist_hint': dist_hint,
                'tier': 'planner_hint',
                'image_path': '',
                'description': d.get('match_reason', '') or '',
            })
            already.add(nid)
        return summary

    def _finalize_by_tentatives(self):
        """遍历完所有候选后的裁决：confirm > best_guess（任意 tentative）> miss。所有非 winner 都作为备选透出。"""
        with self._lock:
            tentatives = list(self.search_tentatives)
            candidates = list(self.search_candidates)
            target = self.search_target

        if not tentatives:
            # 纯 miss：全程没有任何节点 raw_conf>=0.5
            miss_text = PHRASE_MISS.format(n=len(candidates), target=target)
            self._post_chat_event({
                'task_id': self.current_task_id,
                'session_id': self.current_session_id,
                'event_type': 'search_task_summary',
                'role': 'robot',
                'text': miss_text,
                'node_id': -1,
                'found': False,
                'confidence': 0.0,
                'image_paths': [],
                'target_object': target,
                'source_phase': 'completed',
                'backup_candidates': [],
            })
            self._set_state(TaskState.COMPLETED)
            self._publish_status(
                f'{len(candidates)} 个位置都看过了，"{target}" 暂时没现身，可以换个说法或让我探更多地方~', progress=1.0)
            self._publish_search_trace('completed', 'completed_not_found',
                f'search.finalize via=miss 所有 {len(candidates)} 个位置都无 conf≥{MIN_RAW_CONF} 的观测')
            return

        confirmed = [t for t in tentatives if t['tier'] == 'confirm']
        if confirmed:
            winner = max(confirmed, key=lambda x: x['adj_conf'])
            via = 'confirmed'
        else:
            # 无 near 级命中：远/中距离疑似物也不抛弃，选 adj_conf 最高者为 best_guess，其余作备选
            winner = max(tentatives, key=lambda x: x['adj_conf'])
            via = 'best_guess'

        # 单候选 best_guess：tentative 阶段已完整展示图片+描述，finalize 不再重播；
        # 只发一条简短收尾 summary，明确"我判断就是它了"的定性。
        if via == 'best_guess' and len(tentatives) == 1:
            nid = winner['node_id']
            conf = f'{winner["adj_conf"]:.0%}'
            summary = PHRASE_BEST_GUESS_SINGLE.format(nid=nid, conf=conf)
            self._post_chat_event({
                'task_id': self.current_task_id,
                'session_id': self.current_session_id,
                'event_type': 'search_task_summary',
                'role': 'robot',
                'text': summary,
                'node_id': nid,
                'found': True,
                'confidence': winner['adj_conf'],
                'image_paths': [],
                'target_object': target,
                'source_phase': 'completed',
                'hit_angle': winner['hit_angle'],
                'dist_hint': winner['dist_hint'],
                'tier': winner['tier'],
                'via': via,
                'backup_candidates': [],
                'hit_image_position': 0,
                'description': (getattr(winner['result'], 'description', '') or '').strip(),
            })
            self._set_state(TaskState.COMPLETED)
            self._publish_status(
                f'找到了！"{target}" 在节点 {nid}（置信度 {winner["adj_conf"]:.0%}）。',
                progress=1.0)
            self._publish_search_trace('completed', 'found',
                f'search.finalize via=best_guess_single node={nid} adj={winner["adj_conf"]:.2f} dh={winner["dist_hint"]}',
                current_node_id=nid, found=True,
                confidence=winner['adj_conf'],
                evidence_image_path=winner['evidence_path'])
            return

        backups = [t for t in tentatives if t is not winner]
        # _finalize_by_tentatives 触发时 search_index 已经走到末尾，通常无 unvisited；
        # 但若未来有提前终止路径，也允许传空列表兜底。
        self._finalize_found(winner, via=via, backups=backups, unvisited_node_ids=[])

    def _fire_annotate_update_async(self, node_id: int, image_paths: list):
        """后台执行 annotate + update，不阻塞搜索主链路"""
        with self._lock:
            raw_entries = list(self.search_raw_image_entries)

        for entry in raw_entries:
            if ':' in entry:
                angle_str, path = entry.split(':', 1)
                try:
                    angle = int(angle_str)
                except ValueError:
                    angle = -1
            else:
                path = entry
                angle = -1

            ann_req = AnnotateSemantic.Request()
            ann_req.image_path = path
            ann_req.node_id = int(node_id)
            future = self.annotate_client.call_async(ann_req)
            future.add_done_callback(
                lambda f, a=angle, nid=node_id: self._on_bg_annotate_done(f, nid, a))

    def _on_bg_annotate_done(self, future, node_id, angle):
        """后台 annotate 完成 → 调用 update_semantic"""
        try:
            result = future.result()
        except Exception as e:
            self.get_logger().warn(
                f'BG annotate failed node={node_id} angle={angle}: {e}')
            return
        if not result or not result.success:
            return

        sem_data = SemanticData()
        sem_data.room_type = result.room_type or ''
        sem_data.confidence = result.confidence
        sem_data.objects = list(result.objects) if result.objects else []
        sem_data.description = result.description or ''

        # R8: annotate 成功 → 先把本次 panorama 的 rgb/depth 覆盖到 map session
        # 目录下（与 topological_map.json 里的 image_path 指向对齐），再回写 semantic。
        # 失败只记 warn，不影响 semantic 更新流程。
        self._copy_viewpoint_image(node_id, angle)

        update_req = UpdateSemantic.Request()
        update_req.node_id = node_id
        update_req.semantic_data = sem_data
        update_req.angle = angle
        update_future = self.update_semantic_client.call_async(update_req)
        update_future.add_done_callback(
            lambda f: self._on_bg_update_done(f, node_id, angle))

    def _copy_viewpoint_image(self, node_id: int, angle: int) -> None:
        """R8: 把本次搜索拍到的该节点该角度的 rgb/depth 图覆盖到 map session 目录下。

        源: self.search_raw_image_entries 里 "<angle>:<abs_path>" 格式（panorama_capture
            产出的绝对路径，默认落在 sstg_rrt_explorer/captured_nodes/node_X/）
        目的: {maps_root}/{active_map}/captured_nodes/node_{node_id}/{angle:03d}deg_{rgb,depth}.png
        """
        import os
        import shutil
        if not self.session_dir:
            return
        # 找到匹配 angle 的 raw entry
        src_rgb = ''
        with self._lock:
            entries = list(self.search_raw_image_entries)
        for entry in entries:
            if ':' not in entry:
                continue
            ang_str, path = entry.split(':', 1)
            try:
                if int(ang_str) == int(angle):
                    src_rgb = path
                    break
            except ValueError:
                continue
        if not src_rgb or not os.path.exists(src_rgb):
            self.get_logger().debug(
                f'[R8][copy.skip] node={node_id} angle={angle} no src rgb entry')
            return

        dst_dir = os.path.join(self.session_dir, 'captured_nodes', f'node_{node_id}')
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as exc:
            self.get_logger().warn(f'[R8][copy.mkdir] failed: {exc}')
            return

        dst_rgb = os.path.join(dst_dir, f'{int(angle):03d}deg_rgb.png')
        copied = []
        try:
            shutil.copy2(src_rgb, dst_rgb)
            copied.append('rgb')
        except Exception as exc:
            self.get_logger().warn(
                f'[R8][copy.rgb] node={node_id} angle={angle} src={src_rgb} err={exc}')

        # depth 图同目录同名换后缀: 000deg_rgb.png → 000deg_depth.png
        src_depth = src_rgb.replace('_rgb.', '_depth.') if '_rgb.' in src_rgb else ''
        if src_depth and os.path.exists(src_depth):
            dst_depth = os.path.join(dst_dir, f'{int(angle):03d}deg_depth.png')
            try:
                shutil.copy2(src_depth, dst_depth)
                copied.append('depth')
            except Exception as exc:
                self.get_logger().warn(
                    f'[R8][copy.depth] node={node_id} angle={angle} err={exc}')

        if copied:
            self._trace(
                f'[SEARCH-TRACE] copy.image.ok node={node_id} angle={angle} '
                f'kinds={",".join(copied)} dst={dst_dir}')

    def _on_bg_update_done(self, future, node_id, angle):
        try:
            result = future.result()
            if result and result.success:
                self.get_logger().debug(
                    f'BG semantic update OK: node={node_id} angle={angle}')
                # R8+: 通知 UI 该 viewpoint 已写盘，触发 topology 重拉 + 图片 cache-bust
                self._publish_search_trace(
                    'updating', 'semantic_update_done',
                    f'node={node_id} angle={angle} semantic persisted',
                    current_node_id=int(node_id), current_angle_deg=int(angle))
        except Exception as e:
            self.get_logger().warn(f'BG semantic update failed: {e}')

    # ========================================================================
    # 生命周期
    # ========================================================================

    def safe_shutdown(self):
        self.get_logger().info('InteractionManagerNode shutting down')


def main(args=None):
    rclpy.init(args=args)
    node = InteractionManagerNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.safe_shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
