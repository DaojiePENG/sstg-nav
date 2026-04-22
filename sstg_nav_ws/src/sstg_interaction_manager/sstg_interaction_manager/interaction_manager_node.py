import datetime
from enum import Enum

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.task import Future

from std_srvs.srv import Trigger
from sstg_msgs.srv import ProcessNLPQuery, PlanNavigation, ExecuteNavigation, GetNodePose
from sstg_msgs.msg import NavigationFeedback


class TaskState(Enum):
    IDLE = 'idle'
    UNDERSTANDING = 'understanding'
    PLANNING = 'planning'
    NAVIGATING = 'navigating'
    CHECKING = 'checking'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELED = 'canceled'


class InteractionManagerNode(Node):
    def __init__(self):
        super().__init__('interaction_manager_node')

        self.callback_group = ReentrantCallbackGroup()

        self.task_state = TaskState.IDLE
        self.current_task_id = ''
        self.current_intent = ''
        self.current_candidates = []

        self.start_task_srv = self.create_service(
            ProcessNLPQuery,
            'start_task',
            self.start_task_callback,
            callback_group=self.callback_group
        )

        self.cancel_task_srv = self.create_service(
            Trigger,
            'cancel_task',
            self.cancel_task_callback,
            callback_group=self.callback_group
        )

        self.query_status_srv = self.create_service(
            Trigger,
            'query_task_status',
            self.query_task_status_callback,
            callback_group=self.callback_group
        )

        self.nlp_client = self.create_client(ProcessNLPQuery, 'process_nlp_query')
        self.plan_client = self.create_client(PlanNavigation, 'plan_navigation')
        self.get_pose_client = self.create_client(GetNodePose, 'get_node_pose')
        self.exec_client = self.create_client(ExecuteNavigation, 'execute_navigation')

        self.feedback_sub = self.create_subscription(
            NavigationFeedback,
            'navigation_feedback',
            self.navigation_feedback_callback,
            10,
            callback_group=self.callback_group
        )

        # 等待所有依赖服务就绪
        self.get_logger().info('Waiting for dependent services...')
        self._wait_for_services()
        
        self.get_logger().info('sstg_interaction_manager initialized')

    def _wait_for_services(self):
        """等待所有依赖服务就绪"""
        services_to_wait = [
            ('process_nlp_query', self.nlp_client),
            ('plan_navigation', self.plan_client),
            ('get_node_pose', self.get_pose_client),
            ('execute_navigation', self.exec_client)
        ]
        
        for service_name, client in services_to_wait:
            self.get_logger().info(f'Waiting for {service_name} service...')
            if not client.wait_for_service(timeout_sec=10.0):
                self.get_logger().warn(f'Service {service_name} not available after 10s, continuing anyway')
            else:
                self.get_logger().info(f'✓ Service {service_name} is ready')

    def start_task_callback(self, request, response):
        if self.task_state not in [TaskState.IDLE, TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED]:
            response.success = False
            response.error_message = f'TaskBusy: current state={self.task_state.value}'
            return response

        self.current_task_id = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        self.task_state = TaskState.UNDERSTANDING
        self.get_logger().info(f'Start task {self.current_task_id}: {request.text_input}')

        # 1) NLP Intent分析
        if not self.nlp_client.wait_for_service(timeout_sec=3.0):
            self.get_logger().warn('NLP service process_nlp_query not available, fallback to placeholder')
            nlp_intent = 'navigate'
            nlp_entities = ''
            nlp_confidence = 0.7
        else:
            nlp_req = ProcessNLPQuery.Request()
            nlp_req.text_input = request.text_input
            nlp_req.context = request.context
            nlp_future = self.nlp_client.call_async(nlp_req)
            rclpy.spin_until_future_complete(self, nlp_future, timeout_sec=5.0)
            nlp_result = nlp_future.result() if nlp_future.done() else None
            if not nlp_result or not nlp_result.success:
                response.success = False
                response.error_message = 'NLP failed: ' + (nlp_result.error_message if nlp_result else 'timeout')
                self.task_state = TaskState.FAILED
                return response

            nlp_intent = nlp_result.intent
            nlp_entities = nlp_result.query_json
            nlp_confidence = nlp_result.confidence

        self.current_intent = nlp_intent
        self.task_state = TaskState.PLANNING

        # 2) 规划候选点
        if not self.plan_client.wait_for_service(timeout_sec=3.0):
            response.success = False
            response.error_message = 'Plan service plan_navigation unavailable'
            self.task_state = TaskState.FAILED
            return response

        plan_req = PlanNavigation.Request()
        plan_req.intent = nlp_intent
        plan_req.entities = nlp_entities
        plan_req.confidence = nlp_confidence
        plan_req.current_node = -1

        plan_future = self.plan_client.call_async(plan_req)
        rclpy.spin_until_future_complete(self, plan_future, timeout_sec=5.0)
        plan_result = plan_future.result() if plan_future.done() else None

        if not plan_result or not plan_result.success or len(plan_result.candidate_node_ids) == 0:
            response.success = False
            response.error_message = 'Plan failed or no candidate nodes'
            self.task_state = TaskState.FAILED
            return response

        self.current_candidates = plan_result.candidate_node_ids
        target_node = self.current_candidates[0]

        # 3) 获取目标节点位姿
        if not self.get_pose_client.wait_for_service(timeout_sec=3.0):
            response.success = False
            response.error_message = 'Map manager service get_node_pose unavailable'
            self.task_state = TaskState.FAILED
            return response

        pose_req = GetNodePose.Request()
        pose_req.node_id = int(target_node)
        pose_future = self.get_pose_client.call_async(pose_req)
        rclpy.spin_until_future_complete(self, pose_future, timeout_sec=5.0)
        pose_result = pose_future.result() if pose_future.done() else None

        if not pose_result:
            response.success = False
            response.error_message = 'GetNodePose failed'
            self.task_state = TaskState.FAILED
            return response

        # 4) 发送导航目标
        if not self.exec_client.wait_for_service(timeout_sec=3.0):
            response.success = False
            response.error_message = 'Executor service execute_navigation unavailable'
            self.task_state = TaskState.FAILED
            return response

        exec_req = ExecuteNavigation.Request()
        exec_req.target_pose = pose_result.pose
        exec_req.node_id = int(target_node)

        exec_future = self.exec_client.call_async(exec_req)
        rclpy.spin_until_future_complete(self, exec_future, timeout_sec=5.0)
        exec_result = exec_future.result() if exec_future.done() else None

        if not exec_result or not exec_result.success:
            response.success = False
            response.error_message = 'Execute navigation failed: ' + (exec_result.message if exec_result else 'timeout')
            self.task_state = TaskState.FAILED
            return response

        self.task_state = TaskState.NAVIGATING
        response.success = True
        response.query_json = plan_result.plan_json
        response.intent = nlp_intent
        response.confidence = nlp_confidence
        response.error_message = ''

        self.get_logger().info(f'Task {self.current_task_id} navigation started node {target_node}')
        return response

    def cancel_task_callback(self, request, response):
        if self.task_state not in [TaskState.NAVIGATING, TaskState.PLANNING, TaskState.UNDERSTANDING]:
            response.success = False
            response.message = f'No active task to cancel ({self.task_state.value})'
            return response

        self.task_state = TaskState.CANCELED
        response.success = True
        response.message = 'Task canceled'
        self.get_logger().info(f'Task {self.current_task_id} canceled')
        return response

    def query_task_status_callback(self, request, response):
        response.success = True
        response.message = f'{self.task_state.value}'
        return response

    def navigation_feedback_callback(self, msg):
        if self.task_state != TaskState.NAVIGATING:
            return

        # 监听 executor 的反馈，将状态推进到 completed/failed
        if msg.status == 'reached':
            self.task_state = TaskState.COMPLETED
            self.get_logger().info(f'Task {self.current_task_id} completed')
        elif msg.status == 'failed':
            self.task_state = TaskState.FAILED
            self.get_logger().warn(f'Task {self.current_task_id} failed: {msg.error_message}')

    def safe_shutdown(self):
        self.get_logger().info('InteractionManagerNode shutting down')


def main(args=None):
    rclpy.init(args=args)
    node = InteractionManagerNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.safe_shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
