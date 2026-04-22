#!/usr/bin/env python3
"""
Exploration Action Server
将 RRT 探索 launch 包装为 ROS2 Action Server，
供 InteractionManager 通过 ExploreHome Action 调用。

功能:
- 用 subprocess 启动 rrt_exploration_ros2.launch.py
- 订阅 /rrt_exploration_status 跟踪进度
- 定期发布 feedback (frontier_count, progress, status)
- 完成时调用 /save_rrt_session 获取 map_yaml + trace_json
- 支持 cancel (终止 subprocess)
"""

import os
import signal
import subprocess
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

from std_msgs.msg import String
from sstg_msgs.action import ExploreHome
from sstg_msgs.srv import SaveRrtSession
from sstg_msgs.msg import PointArray


class ExplorationActionServer(Node):
    def __init__(self):
        super().__init__('exploration_action_server')

        self.cb_group = ReentrantCallbackGroup()

        # RRT 状态追踪
        self._lock = threading.Lock()
        self._rrt_status = 'waiting'
        self._frontier_count = 0
        self._process = None
        self._executing = False

        # 订阅 RRT trace_manager 的 status
        self.create_subscription(
            String, '/rrt_exploration_status',
            self._status_callback, 10,
            callback_group=self.cb_group)

        # 订阅 frontier 点以获取 count
        self.create_subscription(
            PointArray, '/filtered_points',
            self._filtered_points_callback, 10,
            callback_group=self.cb_group)

        # SaveRrtSession 客户端
        self.save_client = self.create_client(
            SaveRrtSession, 'save_rrt_session',
            callback_group=self.cb_group)

        # Action Server
        self._action_server = ActionServer(
            self, ExploreHome, 'explore_home',
            execute_callback=self._execute_callback,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            callback_group=self.cb_group)

        self.get_logger().info('ExplorationActionServer ready')

    # ------------------------------------------------------------------
    # Subscription Callbacks
    # ------------------------------------------------------------------

    def _status_callback(self, msg):
        with self._lock:
            self._rrt_status = msg.data

    def _filtered_points_callback(self, msg):
        with self._lock:
            self._frontier_count = len(msg.points)

    # ------------------------------------------------------------------
    # Action Callbacks
    # ------------------------------------------------------------------

    def _goal_callback(self, goal_request):
        self.get_logger().info(
            f'Received explore goal: session_id={goal_request.session_id}')
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        self.get_logger().info('Cancel requested for exploration')
        return CancelResponse.ACCEPT

    def _execute_callback(self, goal_handle):
        """主要执行逻辑: 启动 RRT subprocess，轮询状态，发布 feedback"""
        self.get_logger().info('Executing exploration...')

        with self._lock:
            self._rrt_status = 'waiting'
            self._frontier_count = 0
            self._executing = True

        result = ExploreHome.Result()

        # 启动 RRT exploration launch
        try:
            cmd = [
                'ros2', 'launch', 'sstg_rrt_explorer',
                'rrt_exploration_ros2.launch.py'
            ]
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid  # 创建进程组，方便整体 kill
            )
            self.get_logger().info(f'RRT launch started, PID={self._process.pid}')
        except Exception as e:
            self.get_logger().error(f'Failed to launch RRT: {e}')
            result.success = False
            result.message = f'Failed to launch RRT: {e}'
            goal_handle.abort()
            return result

        # 轮询循环: 发 feedback，检查 cancel/completion
        feedback = ExploreHome.Feedback()
        poll_rate = 1.0  # 秒

        while rclpy.ok():
            time.sleep(poll_rate)

            # 检查 cancel
            if goal_handle.is_cancel_requested:
                self.get_logger().info('Exploration canceled by client')
                self._kill_rrt_process()
                result.success = False
                result.message = 'Exploration canceled'
                goal_handle.canceled()
                self._executing = False
                return result

            # 检查 subprocess 是否意外退出
            if self._process and self._process.poll() is not None:
                retcode = self._process.returncode
                self.get_logger().warn(
                    f'RRT process exited with code {retcode}')
                # 进程退出但 status 是 completed，算成功
                with self._lock:
                    status = self._rrt_status
                if status != 'completed':
                    result.success = False
                    result.message = f'RRT process exited unexpectedly (code={retcode})'
                    goal_handle.abort()
                    self._executing = False
                    return result

            # 读取当前状态
            with self._lock:
                status = self._rrt_status
                fc = self._frontier_count

            # 计算进度
            if status == 'waiting':
                progress = 0.05
            elif status == 'running':
                progress = 0.1 + min(0.6, fc * 0.02)  # frontier 越多进度越高
            elif status == 'settling':
                progress = 0.8
            elif status == 'completed':
                progress = 0.95
            else:
                progress = 0.1

            # 发送 feedback
            feedback.status = status
            feedback.frontier_count = fc
            feedback.progress = progress
            goal_handle.publish_feedback(feedback)

            # 完成
            if status == 'completed':
                self.get_logger().info('RRT exploration completed')
                break

        # 探索完成: 调用 save_rrt_session 获取结果
        map_yaml = ''
        trace_json = ''
        try:
            if self.save_client.wait_for_service(timeout_sec=5.0):
                req = SaveRrtSession.Request()
                req.requested_prefix = goal_handle.request.map_prefix or ''
                future = self.save_client.call_async(req)
                # 简单等待
                timeout = 10.0
                start = time.time()
                while not future.done() and (time.time() - start) < timeout:
                    time.sleep(0.2)
                if future.done():
                    save_result = future.result()
                    if save_result and save_result.success:
                        map_yaml = save_result.map_yaml
                        trace_json = save_result.trace_json
                        self.get_logger().info(
                            f'Session saved: {save_result.session_id}')
                    else:
                        self.get_logger().warn('save_rrt_session returned failure')
                else:
                    self.get_logger().warn('save_rrt_session timed out')
            else:
                self.get_logger().warn('save_rrt_session service not available')
        except Exception as e:
            self.get_logger().error(f'Error saving session: {e}')

        # 清理 RRT 进程
        self._kill_rrt_process()

        result.success = True
        result.message = 'Exploration completed'
        result.map_yaml = map_yaml
        result.trace_json = trace_json
        goal_handle.succeed()
        self._executing = False
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _kill_rrt_process(self):
        """终止 RRT subprocess 及其整个进程组"""
        if self._process is None:
            return
        try:
            pgid = os.getpgid(self._process.pid)
            os.killpg(pgid, signal.SIGTERM)
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.get_logger().warn('RRT process did not terminate, killing...')
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                self._process.wait(timeout=3)
            except Exception:
                pass
        except Exception as e:
            self.get_logger().warn(f'Error killing RRT process: {e}')
        finally:
            self._process = None


def main(args=None):
    rclpy.init(args=args)
    node = ExplorationActionServer()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node._kill_rrt_process()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
