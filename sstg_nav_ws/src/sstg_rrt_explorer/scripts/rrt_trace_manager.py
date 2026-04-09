#!/usr/bin/env python3

import json
import os
import subprocess
from datetime import datetime

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from tf2_ros import Buffer, TransformListener
from visualization_msgs.msg import Marker, MarkerArray
from std_msgs.msg import String
from geometry_msgs.msg import Point
from nav_msgs.msg import OccupancyGrid

from sstg_msgs.msg import GoalTraceEvent, PointArray
from sstg_msgs.srv import SaveRrtSession


class RRTTraceManager(Node):
    def __init__(self):
        super().__init__('rrt_trace_manager')

        self.declare_parameter('global_frame', 'map')
        self.declare_parameter('robot_frame', 'base_link')
        self.declare_parameter('map_topic', '/map')
        self.declare_parameter('filtered_points_topic', '/filtered_points')
        self.declare_parameter('goal_event_topic', '/rrt_goal_event')
        self.declare_parameter('trace_marker_topic', '/rrt_trace_markers')
        self.declare_parameter('status_topic', '/rrt_exploration_status')
        self.declare_parameter(
            'trace_output_dir',
            'maps',
        )
        self.declare_parameter('trajectory_distance_threshold', 0.05)
        self.declare_parameter('trajectory_time_threshold', 0.5)
        self.declare_parameter('completion_patience', 10.0)
        self.declare_parameter('sample_period', 0.2)

        self.global_frame = self.get_parameter('global_frame').value
        self.robot_frame = self.get_parameter('robot_frame').value
        self.trace_output_dir = self.get_parameter('trace_output_dir').value
        self.trajectory_distance_threshold = float(
            self.get_parameter('trajectory_distance_threshold').value
        )
        self.trajectory_time_threshold = float(
            self.get_parameter('trajectory_time_threshold').value
        )
        self.completion_patience = float(self.get_parameter('completion_patience').value)
        self.sample_period = float(self.get_parameter('sample_period').value)

        self.map_frame = self.global_frame
        self.session_id = self.make_session_id()
        self.goals = []
        self.goal_index_by_id = {}
        self.trajectory = []
        self.current_goal_id = None
        self.filtered_frontier_count = 0
        self.last_nonempty_frontier_ns = self.get_clock().now().nanoseconds
        self.status = 'waiting'
        self.last_tf_warn_ns = 0
        self.last_trajectory_ns = 0

        latched_qos = QoSProfile(depth=1)
        latched_qos.reliability = ReliabilityPolicy.RELIABLE
        latched_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.map_sub = self.create_subscription(
            OccupancyGrid,
            self.get_parameter('map_topic').value,
            self.map_callback,
            latched_qos,
        )
        self.goal_event_sub = self.create_subscription(
            GoalTraceEvent,
            self.get_parameter('goal_event_topic').value,
            self.goal_event_callback,
            50,
        )
        self.filtered_points_sub = self.create_subscription(
            PointArray,
            self.get_parameter('filtered_points_topic').value,
            self.filtered_points_callback,
            10,
        )

        self.marker_pub = self.create_publisher(
            MarkerArray, self.get_parameter('trace_marker_topic').value, 10
        )
        self.status_pub = self.create_publisher(
            String, self.get_parameter('status_topic').value, 10
        )
        self.save_service = self.create_service(
            SaveRrtSession, 'save_rrt_session', self.save_session_callback
        )

        self.sample_timer = self.create_timer(max(self.sample_period, 0.05), self.sample_trajectory)
        self.publish_timer = self.create_timer(0.5, self.on_publish_timer)

        self.get_logger().info(
            f'RRT trace manager initialized, session_id={self.session_id}, output_dir={self.trace_output_dir}'
        )

    def make_session_id(self):
        return datetime.now().strftime('%Y%m%d_%H%M%S')

    def format_timestamp(self):
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S CST')

    def map_callback(self, msg):
        if msg.header.frame_id:
            self.map_frame = msg.header.frame_id

    def filtered_points_callback(self, msg):
        self.filtered_frontier_count = len(msg.points)
        if self.filtered_frontier_count > 0:
            self.last_nonempty_frontier_ns = self.get_clock().now().nanoseconds

    def goal_event_callback(self, msg):
        goal_id = int(msg.goal_id)
        event_type = msg.event_type
        point_xy = [float(msg.point.x), float(msg.point.y)]
        now_str = self.format_timestamp()

        goal_index = self.goal_index_by_id.get(goal_id)
        if goal_index is None:
            goal_index = len(self.goals)
            self.goal_index_by_id[goal_id] = goal_index
            self.goals.append({
                'id': goal_id,
                'robot_name': msg.robot_name,
                'x': point_xy[0],
                'y': point_xy[1],
                'status': 'assigned',
                'nav_status': int(msg.nav_status),
                'assigned_at': now_str,
                'reached_at': '',
                'failed_at': '',
                'canceled_at': '',
            })

        goal_entry = self.goals[goal_index]
        goal_entry['x'] = point_xy[0]
        goal_entry['y'] = point_xy[1]
        goal_entry['robot_name'] = msg.robot_name
        goal_entry['nav_status'] = int(msg.nav_status)

        if event_type == 'assigned':
            goal_entry['status'] = 'assigned'
            goal_entry['assigned_at'] = now_str
            self.current_goal_id = goal_id
        elif event_type == 'reached':
            goal_entry['status'] = 'reached'
            goal_entry['reached_at'] = now_str
            if self.current_goal_id == goal_id:
                self.current_goal_id = None
        elif event_type == 'canceled':
            goal_entry['status'] = 'canceled'
            goal_entry['canceled_at'] = now_str
            if self.current_goal_id == goal_id:
                self.current_goal_id = None
        else:
            goal_entry['status'] = 'failed'
            goal_entry['failed_at'] = now_str
            if self.current_goal_id == goal_id:
                self.current_goal_id = None

    def lookup_robot_position(self):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.global_frame,
                self.robot_frame,
                rclpy.time.Time(),
            )
            return [
                float(transform.transform.translation.x),
                float(transform.transform.translation.y),
            ]
        except Exception as exc:
            now_ns = self.get_clock().now().nanoseconds
            if now_ns - self.last_tf_warn_ns > 2_000_000_000:
                self.get_logger().warn(f'Robot transform unavailable: {exc}')
                self.last_tf_warn_ns = now_ns
            return None

    def sample_trajectory(self):
        position = self.lookup_robot_position()
        if position is None:
            return

        now_ns = self.get_clock().now().nanoseconds
        if not self.trajectory:
            self.trajectory.append({
                'x': position[0],
                'y': position[1],
                't': self.format_timestamp(),
            })
            self.last_trajectory_ns = now_ns
            return

        last = self.trajectory[-1]
        dx = position[0] - last['x']
        dy = position[1] - last['y']
        dist = (dx * dx + dy * dy) ** 0.5
        elapsed = (now_ns - self.last_trajectory_ns) / 1e9

        if dist >= self.trajectory_distance_threshold or (
            elapsed >= self.trajectory_time_threshold and dist >= self.trajectory_distance_threshold * 0.5
        ):
            self.trajectory.append({
                'x': position[0],
                'y': position[1],
                't': self.format_timestamp(),
            })
            self.last_trajectory_ns = now_ns

    def get_current_goal_entry(self):
        if self.current_goal_id is None:
            return None
        index = self.goal_index_by_id.get(self.current_goal_id)
        if index is None:
            return None
        goal_entry = self.goals[index]
        if goal_entry['status'] != 'assigned':
            return None
        return goal_entry

    def evaluate_status(self):
        if not self.goals and not self.trajectory:
            new_status = 'waiting'
        elif self.get_current_goal_entry() is not None or self.filtered_frontier_count > 0:
            new_status = 'running'
        else:
            elapsed = (self.get_clock().now().nanoseconds - self.last_nonempty_frontier_ns) / 1e9
            new_status = 'completed' if elapsed >= self.completion_patience else 'settling'

        if new_status != self.status:
            self.get_logger().info(f'Exploration status -> {new_status}')
            self.status = new_status

    def build_markers(self):
        markers = MarkerArray()
        now = self.get_clock().now().to_msg()

        current_goal_marker = Marker()
        current_goal_marker.header.frame_id = self.map_frame
        current_goal_marker.header.stamp = now
        current_goal_marker.ns = 'rrt_trace'
        current_goal_marker.id = 0
        current_goal_marker.type = Marker.SPHERE
        current_goal_marker.pose.orientation.w = 1.0
        current_goal_marker.scale.x = 0.40
        current_goal_marker.scale.y = 0.40
        current_goal_marker.scale.z = 0.40
        current_goal_marker.color.r = 1.0
        current_goal_marker.color.g = 0.0
        current_goal_marker.color.b = 0.0
        current_goal_marker.color.a = 0.95

        current_goal = self.get_current_goal_entry()
        if current_goal is None:
            current_goal_marker.action = Marker.DELETE
        else:
            current_goal_marker.action = Marker.ADD
            current_goal_marker.pose.position.x = current_goal['x']
            current_goal_marker.pose.position.y = current_goal['y']
            current_goal_marker.pose.position.z = 0.0
        markers.markers.append(current_goal_marker)

        reached_marker = Marker()
        reached_marker.header.frame_id = self.map_frame
        reached_marker.header.stamp = now
        reached_marker.ns = 'rrt_trace'
        reached_marker.id = 1
        reached_marker.type = Marker.SPHERE_LIST
        reached_marker.action = Marker.ADD
        reached_marker.pose.orientation.w = 1.0
        reached_marker.scale.x = 0.24
        reached_marker.scale.y = 0.24
        reached_marker.scale.z = 0.24
        reached_marker.color.r = 1.0
        reached_marker.color.g = 0.55
        reached_marker.color.b = 0.0
        reached_marker.color.a = 1.0

        failed_marker = Marker()
        failed_marker.header.frame_id = self.map_frame
        failed_marker.header.stamp = now
        failed_marker.ns = 'rrt_trace'
        failed_marker.id = 2
        failed_marker.type = Marker.SPHERE_LIST
        failed_marker.action = Marker.ADD
        failed_marker.pose.orientation.w = 1.0
        failed_marker.scale.x = 0.20
        failed_marker.scale.y = 0.20
        failed_marker.scale.z = 0.20
        failed_marker.color.r = 0.5
        failed_marker.color.g = 0.5
        failed_marker.color.b = 0.5
        failed_marker.color.a = 0.9

        for goal_entry in self.goals:
            point = Point()
            point.x = float(goal_entry['x'])
            point.y = float(goal_entry['y'])
            point.z = 0.0
            if goal_entry['status'] == 'reached':
                reached_marker.points.append(point)
            elif goal_entry['status'] in ('failed', 'canceled'):
                failed_marker.points.append(point)

        markers.markers.append(reached_marker)
        markers.markers.append(failed_marker)

        trajectory_marker = Marker()
        trajectory_marker.header.frame_id = self.map_frame
        trajectory_marker.header.stamp = now
        trajectory_marker.ns = 'rrt_trace'
        trajectory_marker.id = 3
        trajectory_marker.type = Marker.LINE_STRIP
        trajectory_marker.action = Marker.ADD
        trajectory_marker.pose.orientation.w = 1.0
        trajectory_marker.scale.x = 0.07
        trajectory_marker.color.r = 1.0
        trajectory_marker.color.g = 0.1
        trajectory_marker.color.b = 0.1
        trajectory_marker.color.a = 0.95
        for pose in self.trajectory:
            point = Point()
            point.x = float(pose['x'])
            point.y = float(pose['y'])
            point.z = 0.0
            trajectory_marker.points.append(point)
        markers.markers.append(trajectory_marker)
        return markers

    def on_publish_timer(self):
        self.evaluate_status()
        self.marker_pub.publish(self.build_markers())
        status_msg = String()
        status_msg.data = self.status
        self.status_pub.publish(status_msg)

    def build_trace_payload(self, prefix):
        return {
            'session_id': self.session_id,
            'saved_prefix': prefix,
            'saved_at': self.format_timestamp(),
            'frame_id': self.map_frame,
            'map_yaml': f'{prefix}.yaml',
            'exploration_status': self.status,
            'filtered_frontier_count': self.filtered_frontier_count,
            'goals': self.goals,
            'trajectory': self.trajectory,
        }

    def save_session_callback(self, request, response):
        prefix = request.requested_prefix.strip() or self.session_id
        os.makedirs(self.trace_output_dir, exist_ok=True)
        base_path = os.path.join(self.trace_output_dir, prefix)

        command = ['ros2', 'run', 'nav2_map_server', 'map_saver_cli', '-f', base_path]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            response.success = False
            response.message = (result.stderr or result.stdout).strip()
            response.session_id = self.session_id
            return response

        trace_path = f'{base_path}.trace.json'
        with open(trace_path, 'w', encoding='utf-8') as trace_file:
            json.dump(self.build_trace_payload(prefix), trace_file, ensure_ascii=False, indent=2)

        response.success = True
        response.message = 'RRT session saved'
        response.session_id = self.session_id
        response.map_yaml = f'{base_path}.yaml'
        response.map_pgm = f'{base_path}.pgm'
        response.trace_json = trace_path
        self.get_logger().info(
            f'Saved session prefix={prefix} map={response.map_yaml} trace={response.trace_json}'
        )
        return response


def main(args=None):
    rclpy.init(args=args)
    node = RRTTraceManager()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
