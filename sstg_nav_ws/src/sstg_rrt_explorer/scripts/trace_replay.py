#!/usr/bin/env python3

import json
import math

import rclpy
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_msgs.action import ComputePathToPose, NavigateToPose
from nav_msgs.msg import OccupancyGrid, Path


class TraceReplayNode(Node):
    def __init__(self):
        super().__init__('trace_replay')

        self.declare_parameter('trace_file', '')
        self.declare_parameter('global_frame', 'map')
        self.declare_parameter('navigate_action', 'navigate_to_pose')
        self.declare_parameter('compute_path_action', 'compute_path_to_pose')
        self.declare_parameter('goal_topic', '/goal_pose')
        self.declare_parameter('map_topic', '/map')
        self.declare_parameter('costmap_topic', '/global_costmap/costmap')
        self.declare_parameter('amcl_pose_topic', '/amcl_pose')
        self.declare_parameter('min_goal_separation', 0.45)
        self.declare_parameter('skip_goal_distance', 0.35)
        self.declare_parameter('safety_radius', 0.30)
        self.declare_parameter('blocked_cost_threshold', 70)
        self.declare_parameter('treat_unknown_as_blocked', True)
        self.declare_parameter('require_costmap_for_safety', True)
        self.declare_parameter('max_goal_retries', 1)
        self.declare_parameter('max_consecutive_failures', 2)
        self.declare_parameter('max_pose_variance', 0.50)
        self.declare_parameter('max_yaw_variance', 0.30)

        self.trace_file = self.get_parameter('trace_file').value
        self.global_frame = self.get_parameter('global_frame').value
        self.navigate_action = self.get_parameter('navigate_action').value
        self.compute_path_action = self.get_parameter('compute_path_action').value
        self.min_goal_separation = float(self.get_parameter('min_goal_separation').value)
        self.skip_goal_distance = float(self.get_parameter('skip_goal_distance').value)
        self.safety_radius = float(self.get_parameter('safety_radius').value)
        self.blocked_cost_threshold = int(self.get_parameter('blocked_cost_threshold').value)
        self.treat_unknown_as_blocked = bool(self.get_parameter('treat_unknown_as_blocked').value)
        self.require_costmap_for_safety = bool(self.get_parameter('require_costmap_for_safety').value)
        self.max_goal_retries = int(self.get_parameter('max_goal_retries').value)
        self.max_consecutive_failures = int(self.get_parameter('max_consecutive_failures').value)
        self.max_pose_variance = float(self.get_parameter('max_pose_variance').value)
        self.max_yaw_variance = float(self.get_parameter('max_yaw_variance').value)

        self.goal_pub = self.create_publisher(
            PoseStamped, self.get_parameter('goal_topic').value, 10)
        self.nav_client = ActionClient(self, NavigateToPose, self.navigate_action)
        self.plan_client = ActionClient(self, ComputePathToPose, self.compute_path_action)

        map_qos = QoSProfile(depth=1)
        map_qos.reliability = ReliabilityPolicy.RELIABLE
        map_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.map_sub = self.create_subscription(
            OccupancyGrid,
            self.get_parameter('map_topic').value,
            self.map_callback,
            map_qos,
        )
        self.costmap_sub = self.create_subscription(
            OccupancyGrid,
            self.get_parameter('costmap_topic').value,
            self.costmap_callback,
            map_qos,
        )
        self.pose_sub = self.create_subscription(
            PoseWithCovarianceStamped,
            self.get_parameter('amcl_pose_topic').value,
            self.pose_callback,
            10,
        )

        self.goal_index = 0
        self.retry_count = 0
        self.consecutive_failures = 0
        self.started = False
        self.trace_loaded = False
        self.shutdown_requested = False
        self.precheck_in_progress = False
        self.goal_points = []
        self.latest_map = OccupancyGrid()
        self.latest_costmap = OccupancyGrid()
        self.latest_pose = None
        self.pending_goal_entry = None
        self.wait_state = ''
        self.last_wait_log_ns = 0
        self.shutdown_timer = None

        self.start_timer = self.create_timer(0.5, self.start_replay)

    def throttled_info(self, msg):
        now_ns = self.get_clock().now().nanoseconds
        if self.wait_state != msg or now_ns - self.last_wait_log_ns > 2_000_000_000:
            self.get_logger().info(msg)
            self.wait_state = msg
            self.last_wait_log_ns = now_ns

    def clear_wait_state(self):
        self.wait_state = ''

    def map_callback(self, msg):
        self.latest_map = msg

    def costmap_callback(self, msg):
        self.latest_costmap = msg

    def pose_callback(self, msg):
        self.latest_pose = msg

    def load_trace(self):
        if not self.trace_file:
            raise RuntimeError('trace_file parameter is empty')

        with open(self.trace_file, 'r', encoding='utf-8') as trace_handle:
            payload = json.load(trace_handle)

        reached_goals = [
            goal for goal in payload.get('goals', [])
            if goal.get('status') == 'reached'
        ]
        if not reached_goals:
            raise RuntimeError('trace file does not contain any reached goals')

        self.goal_points = self.compress_goals(reached_goals)
        self.trace_loaded = True

    def compress_goals(self, goals):
        compressed = []
        skipped = 0
        for goal in goals:
            if not compressed:
                compressed.append(goal)
                continue
            if self.goal_distance(goal, compressed[-1]) < self.min_goal_separation:
                skipped += 1
                continue
            compressed.append(goal)

        if skipped:
            self.get_logger().info(
                f'Compressed replay goals from {len(goals)} to {len(compressed)} '
                f'using min_goal_separation={self.min_goal_separation:.2f}'
            )
        return compressed

    def start_replay(self):
        if self.started:
            return

        if not self.trace_loaded:
            try:
                self.load_trace()
            except Exception as exc:
                self.get_logger().error(f'Failed to load trace replay file: {exc}')
                self.request_shutdown()
                return

        if not self.nav_client.server_is_ready():
            if not self.nav_client.wait_for_server(timeout_sec=0.1):
                self.throttled_info('Waiting for navigate_to_pose action server')
                return

        if not self.plan_client.server_is_ready():
            if not self.plan_client.wait_for_server(timeout_sec=0.1):
                self.throttled_info('Waiting for compute_path_to_pose action server')
                return

        if len(self.latest_map.data) < 1:
            self.throttled_info('Waiting for replay map')
            return

        if self.require_costmap_for_safety and len(self.latest_costmap.data) < 1:
            self.throttled_info('Waiting for global costmap for replay safety checks')
            return

        if self.latest_pose is None:
            self.throttled_info('Waiting for AMCL pose before replay')
            return

        if not self.localization_is_stable():
            self.throttled_info('Waiting for localization covariance to settle')
            return

        self.started = True
        self.start_timer.cancel()
        self.clear_wait_state()

        self.get_logger().info(
            f'Loaded {len(self.goal_points)} replay goals from {self.trace_file}'
        )
        self.send_next_goal()

    def localization_is_stable(self):
        if self.latest_pose is None:
            return False
        covariance = self.latest_pose.pose.covariance
        xy_variance = max(covariance[0], covariance[7])
        yaw_variance = covariance[35]
        return xy_variance <= self.max_pose_variance and yaw_variance <= self.max_yaw_variance

    def current_pose_stamped(self):
        if self.latest_pose is None:
            return None

        pose_msg = PoseStamped()
        pose_msg.header.frame_id = self.global_frame
        pose_msg.header.stamp = self.get_clock().now().to_msg()
        pose_msg.pose = self.latest_pose.pose.pose
        return pose_msg

    def send_next_goal(self):
        if self.shutdown_requested or self.precheck_in_progress:
            return

        if self.goal_index >= len(self.goal_points):
            self.get_logger().info('Trace replay finished')
            self.request_shutdown()
            return

        if self.latest_pose is None or not self.localization_is_stable():
            self.get_logger().error(
                'Stopping replay because localization is no longer stable enough'
            )
            self.request_shutdown()
            return

        goal_entry = self.goal_points[self.goal_index]
        goal_position = (float(goal_entry['x']), float(goal_entry['y']))
        current_position = self.current_position()
        if current_position is None:
            self.get_logger().error('Stopping replay because current pose is unavailable')
            self.request_shutdown()
            return

        if self.distance_xy(current_position, goal_position) < self.skip_goal_distance:
            self.get_logger().info(
                f"Skipping replay goal {self.goal_index + 1}/{len(self.goal_points)} "
                f"id={goal_entry.get('id', -1)} because it is already within "
                f'{self.skip_goal_distance:.2f} m'
            )
            self.retry_count = 0
            self.consecutive_failures = 0
            self.goal_index += 1
            self.send_next_goal()
            return

        blocked, reason = self.goal_area_blocked(goal_position)
        if blocked:
            self.get_logger().warn(
                f"Skipping replay goal {self.goal_index + 1}/{len(self.goal_points)} "
                f"id={goal_entry.get('id', -1)}: {reason}"
            )
            self.handle_goal_failure(reason)
            return

        self.begin_plan_precheck(goal_entry)

    def begin_plan_precheck(self, goal_entry):
        start_pose = self.current_pose_stamped()
        if start_pose is None:
            self.handle_goal_failure('current pose unavailable during precheck')
            return

        self.precheck_in_progress = True
        self.pending_goal_entry = goal_entry

        goal_msg = ComputePathToPose.Goal()
        goal_msg.goal = self.goal_pose_stamped(goal_entry)
        goal_msg.start = start_pose
        goal_msg.use_start = True
        goal_msg.planner_id = ''

        future = self.plan_client.send_goal_async(goal_msg)
        future.add_done_callback(self.plan_response_callback)

    def plan_response_callback(self, future):
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.precheck_in_progress = False
            self.handle_goal_failure(f'plan precheck request failed: {exc}')
            return

        if not goal_handle.accepted:
            self.precheck_in_progress = False
            self.handle_goal_failure('plan precheck was rejected by Nav2')
            return

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.plan_result_callback)

    def plan_result_callback(self, future):
        self.precheck_in_progress = False

        try:
            wrapped_result = future.result()
        except Exception as exc:
            self.handle_goal_failure(f'plan precheck result failed: {exc}')
            return

        status = wrapped_result.status
        path = wrapped_result.result.path
        if status != GoalStatus.STATUS_SUCCEEDED:
            self.handle_goal_failure(
                f'plan precheck returned nav status {status} for replay goal'
            )
            return

        if len(path.poses) < 2 or self.path_length(path) <= 0.05:
            self.handle_goal_failure('plan precheck returned an empty or degenerate path')
            return

        goal_entry = self.pending_goal_entry
        self.pending_goal_entry = None
        self.dispatch_navigation_goal(goal_entry)

    def dispatch_navigation_goal(self, goal_entry):
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = self.goal_pose_stamped(goal_entry)

        pose_msg = PoseStamped()
        pose_msg.header = goal_msg.pose.header
        pose_msg.pose = goal_msg.pose.pose
        self.goal_pub.publish(pose_msg)

        self.get_logger().info(
            f"Replaying goal {self.goal_index + 1}/{len(self.goal_points)} "
            f"id={goal_entry.get('id', -1)} retry={self.retry_count}"
        )

        future = self.nav_client.send_goal_async(goal_msg)
        future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.handle_goal_failure(f'navigation goal submission failed: {exc}')
            return

        if not goal_handle.accepted:
            self.handle_goal_failure('replay goal rejected by Nav2')
            return

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.goal_result_callback)

    def goal_result_callback(self, future):
        try:
            wrapped_result = future.result()
        except Exception as exc:
            self.handle_goal_failure(f'navigation result failed: {exc}')
            return

        status = wrapped_result.status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.retry_count = 0
            self.consecutive_failures = 0
            self.goal_index += 1
            self.send_next_goal()
            return

        self.handle_goal_failure(f'replay goal failed with nav status {status}')

    def handle_goal_failure(self, reason):
        if self.retry_count < self.max_goal_retries:
            self.retry_count += 1
            self.get_logger().warn(
                f'{reason}; retrying current replay goal once '
                f'({self.retry_count}/{self.max_goal_retries})'
            )
            self.send_next_goal()
            return

        self.get_logger().warn(
            f'{reason}; skipping replay goal after {self.max_goal_retries} retries'
        )

        self.retry_count = 0
        self.consecutive_failures += 1
        self.goal_index += 1

        if self.consecutive_failures >= self.max_consecutive_failures:
            self.get_logger().error(
                f'Stopping replay after {self.consecutive_failures} consecutive failures'
            )
            self.request_shutdown()
            return

        self.send_next_goal()

    def goal_pose_stamped(self, goal_entry):
        goal_pose = PoseStamped()
        goal_pose.header.frame_id = self.global_frame
        goal_pose.header.stamp = self.get_clock().now().to_msg()
        goal_pose.pose.position.x = float(goal_entry['x'])
        goal_pose.pose.position.y = float(goal_entry['y'])
        goal_pose.pose.orientation.w = 1.0
        return goal_pose

    def current_position(self):
        if self.latest_pose is None:
            return None
        pose = self.latest_pose.pose.pose.position
        return (float(pose.x), float(pose.y))

    def goal_distance(self, goal_a, goal_b):
        point_a = (float(goal_a['x']), float(goal_a['y']))
        point_b = (float(goal_b['x']), float(goal_b['y']))
        return self.distance_xy(point_a, point_b)

    def distance_xy(self, point_a, point_b):
        return math.hypot(point_a[0] - point_b[0], point_a[1] - point_b[1])

    def goal_area_blocked(self, goal_position):
        if len(self.latest_costmap.data) > 0:
            blocked, reason = self.grid_area_blocked(
                self.latest_costmap, goal_position, self.safety_radius, self.blocked_cost_threshold
            )
            if blocked:
                return True, f'goal area blocked in costmap: {reason}'

        if len(self.latest_map.data) > 0:
            blocked, reason = self.grid_area_blocked(
                self.latest_map, goal_position, self.safety_radius, 50
            )
            if blocked:
                return True, f'goal area blocked in saved map: {reason}'

        return False, ''

    def grid_area_blocked(self, grid, goal_position, radius, blocked_threshold):
        resolution = grid.info.resolution
        if resolution <= 0.0:
            return True, 'invalid grid resolution'

        origin_x = grid.info.origin.position.x
        origin_y = grid.info.origin.position.y
        width = int(grid.info.width)
        height = int(grid.info.height)
        if width <= 0 or height <= 0:
            return True, 'empty grid'

        center_col = int(math.floor((goal_position[0] - origin_x) / resolution))
        center_row = int(math.floor((goal_position[1] - origin_y) / resolution))
        radius_cells = max(int(math.ceil(radius / resolution)), 1)

        if center_col < 0 or center_col >= width or center_row < 0 or center_row >= height:
            return True, 'goal outside grid bounds'

        min_col = max(center_col - radius_cells, 0)
        max_col = min(center_col + radius_cells, width - 1)
        min_row = max(center_row - radius_cells, 0)
        max_row = min(center_row + radius_cells, height - 1)

        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                cell_x = origin_x + (col + 0.5) * resolution
                cell_y = origin_y + (row + 0.5) * resolution
                if self.distance_xy(goal_position, (cell_x, cell_y)) > radius:
                    continue

                index = row * width + col
                if index < 0 or index >= len(grid.data):
                    return True, 'goal footprint crosses invalid cells'

                cost = int(grid.data[index])
                if cost < 0 and self.treat_unknown_as_blocked:
                    return True, f'unknown cell near goal (index={index})'
                if cost >= blocked_threshold:
                    return True, f'blocked cell near goal (cost={cost})'

        return False, ''

    def path_length(self, path):
        if not isinstance(path, Path) or len(path.poses) < 2:
            return 0.0

        total = 0.0
        for idx in range(1, len(path.poses)):
            prev_pose = path.poses[idx - 1].pose.position
            curr_pose = path.poses[idx].pose.position
            total += math.hypot(
                curr_pose.x - prev_pose.x,
                curr_pose.y - prev_pose.y,
            )
        return total

    def request_shutdown(self):
        if self.shutdown_requested:
            return
        self.shutdown_requested = True
        self.shutdown_timer = self.create_timer(0.1, self.shutdown_once)

    def shutdown_once(self):
        if self.shutdown_timer is not None:
            self.shutdown_timer.cancel()
            self.shutdown_timer = None
        if rclpy.ok():
            rclpy.shutdown()


def main(args=None):
    rclpy.init(args=args)
    node = TraceReplayNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
