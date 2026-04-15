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
)
from sstg_msgs.msg import NavigationFeedback, TaskStatus, ObjectSearchTrace
from sstg_msgs.action import ExploreHome


class TaskState(Enum):
    IDLE = 'idle'
    UNDERSTANDING = 'understanding'
    PLANNING = 'planning'
    NAVIGATING = 'navigating'
    EXPLORING = 'exploring'
    SEARCHING = 'searching'
    CHECKING = 'checking'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELED = 'canceled'


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

        # --- 搜索状态 (Phase 3) ---
        self.search_target = ''
        self.search_candidates = []
        self.search_index = 0
        self.search_images = []
        self.search_image_index = 0
        self.search_visited_nodes = []
        self.search_failed_nodes = []

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

    def _watchdog_tick(self):
        """定期检查任务是否卡住，提供心跳反馈和超时保护"""
        state = self._get_state()
        if state in (TaskState.IDLE, TaskState.COMPLETED,
                     TaskState.FAILED, TaskState.CANCELED):
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
            self.current_intent = ''
            self.current_candidates = []
            self._history = []
            self.search_target = ''
            self.search_candidates = []
            self.search_index = 0

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
            self.current_intent = ''
            self.current_candidates = []
            self._history = []
            self.search_target = ''
            self.search_candidates = []
            self.search_index = 0

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
        target = ''
        try:
            data = json.loads(entities_json)
            entities = data.get('entities', [])
            if entities:
                target = entities[0]  # 取第一个实体作为搜索目标
        except (json.JSONDecodeError, KeyError):
            pass

        if not target:
            target = '未知物体'

        with self._lock:
            self.search_target = target
            self.search_candidates = []
            self.search_index = 0
            self.search_images = []
            self.search_image_index = 0
            self.search_visited_nodes = []
            self.search_failed_nodes = []

        self._set_state(TaskState.SEARCHING)
        self._publish_status(
            f'正在搜索 "{target}"，规划搜索路径...', progress=0.1)

        # 先调用 Planner 获取候选节点
        plan_req = PlanNavigation.Request()
        plan_req.intent = intent
        plan_req.entities = entities_json
        plan_req.confidence = confidence
        plan_req.current_node = -1

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
            total = len(self.search_candidates)

        self._publish_status(
            f'找到 {total} 个候选位置，开始搜索...', progress=0.15)
        self._publish_search_trace('planning', 'plan_ready',
            f'找到 {total} 个候选位置')
        self._navigate_to_search_node()

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
                total = len(self.search_candidates)
            self._publish_status(
                f'准备搜索 {total} 个位置...', progress=0.15)
            self._navigate_to_search_node()
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
            self._navigate_to_search_node()
            return

        if result is None or not result.success:
            with self._lock:
                node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
                self.search_failed_nodes.append(node_id)
                self.search_index += 1
            self._publish_search_trace('navigating', 'node_skip',
                f'节点 {node_id} 位姿获取失败，跳过', current_node_id=node_id)
            self._navigate_to_search_node()
            return

        with self._lock:
            node_id = self.search_candidates[self.search_index]

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
                self.search_index += 1
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

        from geometry_msgs.msg import PoseStamped
        capture_req = CaptureImage.Request()
        capture_req.node_id = int(node_id)
        capture_req.pose = PoseStamped()  # 使用当前位姿

        capture_future = self.capture_client.call_async(capture_req)
        capture_future.add_done_callback(self._on_search_capture_done)

    def _on_search_capture_done(self, future):
        """搜索: 拍照完成，开始逐张检查"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            self.get_logger().warn(f'拍照失败: {e}，跳过此节点')
            with self._lock:
                node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
                self.search_failed_nodes.append(node_id)
                self.search_index += 1
            self._publish_search_trace('navigating', 'node_skip',
                f'节点 {node_id} 拍照失败，跳过', current_node_id=node_id)
            self._navigate_to_search_node()
            return

        if result is None or not result.success or not result.image_paths:
            self.get_logger().warn('拍照失败或无图片，跳过此节点')
            with self._lock:
                node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
                self.search_failed_nodes.append(node_id)
                self.search_index += 1
            self._publish_search_trace('navigating', 'node_skip',
                f'节点 {node_id} 无图片，跳过', current_node_id=node_id)
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
            self.search_image_index = 0
            node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1

        self._publish_search_trace('checking', 'capture_ready',
            f'节点 {node_id} 拍照完成，{len(image_paths)} 张图待检查',
            current_node_id=node_id, total_images=len(image_paths))

        self._check_next_image()

    def _check_next_image(self):
        """逐张图片调用 VLM 检查物体"""
        if self._get_state() == TaskState.CANCELED:
            return

        with self._lock:
            idx = self.search_image_index
            images = self.search_images
            target = self.search_target

        if idx >= len(images):
            # 当前节点所有图片都检查完，未找到
            with self._lock:
                node_id = self.search_candidates[self.search_index]
                self.search_visited_nodes.append(node_id)
                self.search_index += 1
            self._publish_status(
                f'节点 {node_id} 未找到 "{target}"，继续搜索...')
            self._publish_search_trace('navigating', 'node_miss',
                f'节点 {node_id} 未找到 "{target}"', current_node_id=node_id)
            self._navigate_to_search_node()
            return

        image_path = images[idx]
        self._publish_status(
            f'正在检查图片 {idx + 1}/{len(images)}...')
        with self._lock:
            node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
        self._publish_search_trace('checking', 'image_check_start',
            f'检查图片 {idx + 1}/{len(images)}',
            current_node_id=node_id, current_image_index=idx,
            total_images=len(images), current_image_path=image_path)

        check_req = CheckObjectPresence.Request()
        check_req.image_path = image_path
        check_req.target_object = target

        check_future = self.check_object_client.call_async(check_req)
        check_future.add_done_callback(self._on_object_check_done)

    def _on_object_check_done(self, future):
        """VLM 物体检查结果"""
        if self._get_state() == TaskState.CANCELED:
            return

        try:
            result = future.result()
        except Exception as e:
            self.get_logger().warn(f'物体检查调用失败: {e}')
            with self._lock:
                self.search_image_index += 1
            self._check_next_image()
            return

        if result is not None and result.found and result.confidence >= 0.5:
            # 找到了!
            with self._lock:
                node_id = self.search_candidates[self.search_index]
                target = self.search_target
                image_path = self.search_images[self.search_image_index] if self.search_image_index < len(self.search_images) else ''

            self._set_state(TaskState.COMPLETED)
            desc = result.description or ''
            self._publish_status(
                f'找到了! "{target}" 在节点 {node_id}。{desc}',
                progress=1.0)
            self._publish_search_trace('completed', 'found',
                f'在节点 {node_id} 找到 "{target}"',
                current_node_id=node_id, found=True,
                confidence=result.confidence,
                evidence_image_path=image_path)
        else:
            # 未找到，检查下一张图
            with self._lock:
                node_id = self.search_candidates[self.search_index] if self.search_index < len(self.search_candidates) else -1
                self.search_image_index += 1
            self._publish_search_trace('checking', 'image_check_miss',
                f'图片未命中', current_node_id=node_id)
            self._check_next_image()

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
