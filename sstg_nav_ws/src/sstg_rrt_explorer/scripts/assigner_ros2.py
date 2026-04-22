#!/usr/bin/env python3

from copy import copy
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from nav_msgs.msg import OccupancyGrid
from visualization_msgs.msg import Marker
from geometry_msgs.msg import Point
from sstg_msgs.msg import GoalTraceEvent, PointArray
from functions_ros2 import robot, informationGain, discount
from numpy.linalg import norm


class AssignerNode(Node):
    def __init__(self):
        super().__init__('assigner')

        self.declare_parameter('map_topic', '/map')
        self.declare_parameter('info_radius', 1.0)
        self.declare_parameter('info_multiplier', 3.0)
        self.declare_parameter('hysteresis_radius', 3.0)
        self.declare_parameter('hysteresis_gain', 2.0)
        self.declare_parameter('frontiers_topic', '/filtered_points')
        self.declare_parameter('n_robots', 1)
        self.declare_parameter('namespace', '')
        self.declare_parameter('namespace_init_count', 1)
        self.declare_parameter('assignment_period', 0.5)
        self.declare_parameter('goal_tolerance', 0.25)
        self.declare_parameter('min_target_distance', 0.35)
        self.declare_parameter('repeat_target_radius', 0.30)
        self.declare_parameter('repeat_target_cooldown', 8.0)

        map_topic = self.get_parameter('map_topic').value
        self.info_radius = float(self.get_parameter('info_radius').value)
        self.info_multiplier = float(self.get_parameter('info_multiplier').value)
        self.hysteresis_radius = float(self.get_parameter('hysteresis_radius').value)
        self.hysteresis_gain = float(self.get_parameter('hysteresis_gain').value)
        frontiers_topic = self.get_parameter('frontiers_topic').value
        n_robots = int(self.get_parameter('n_robots').value)
        namespace = self.get_parameter('namespace').value
        namespace_init_count = int(self.get_parameter('namespace_init_count').value)
        assignment_period = float(self.get_parameter('assignment_period').value)
        self.goal_tolerance = float(self.get_parameter('goal_tolerance').value)
        self.min_target_distance = float(self.get_parameter('min_target_distance').value)
        self.repeat_target_radius = float(self.get_parameter('repeat_target_radius').value)
        self.repeat_target_cooldown = float(self.get_parameter('repeat_target_cooldown').value)

        self.frontiers = []
        self.mapData = OccupancyGrid()
        self.wait_state = ''
        self.last_wait_log_ns = 0
        self.last_sent_target = None
        self.last_sent_target_time_ns = 0
        self.goal_visual_active = False
        self.goal_sequence = 0

        latched_map_qos = QoSProfile(depth=1)
        latched_map_qos.reliability = ReliabilityPolicy.RELIABLE
        latched_map_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.map_sub = self.create_subscription(
            OccupancyGrid, map_topic, self.mapCallBack, latched_map_qos)
        self.frontiers_sub = self.create_subscription(
            PointArray, frontiers_topic, self.callBack, 10)
        self.goal_marker_pub = self.create_publisher(Marker, 'assigned_goal_marker', 10)
        self.goal_event_pub = self.create_publisher(GoalTraceEvent, 'rrt_goal_event', 20)

        self.robots = []
        for i in range(n_robots):
            if namespace:
                robot_name = namespace + str(i + namespace_init_count)
            else:
                robot_name = '' if n_robots == 1 else str(i + namespace_init_count)
            robot_obj = robot(self, robot_name)
            robot_obj.set_goal_event_callback(self.publish_goal_event)
            self.robots.append(robot_obj)

        self.timer = self.create_timer(max(assignment_period, 0.1), self.on_timer)
        self.get_logger().info('Assigner node initialized')

    def throttled_info(self, msg):
        now_ns = self.get_clock().now().nanoseconds
        if self.wait_state != msg or now_ns - self.last_wait_log_ns > 2_000_000_000:
            self.get_logger().info(msg)
            self.wait_state = msg
            self.last_wait_log_ns = now_ns

    def clear_wait_state(self):
        self.wait_state = ''

    def goal_frame_id(self):
        if self.mapData.header.frame_id:
            return self.mapData.header.frame_id
        return 'map'

    def publish_goal_visualization(self, robot_position, goal_point):
        frame_id = self.goal_frame_id()
        now = self.get_clock().now().to_msg()

        goal_marker = Marker()
        goal_marker.header.frame_id = frame_id
        goal_marker.header.stamp = now
        goal_marker.ns = 'assigned_goal'
        goal_marker.id = 0
        goal_marker.type = Marker.SPHERE
        goal_marker.action = Marker.ADD
        goal_marker.pose.orientation.w = 1.0
        goal_marker.pose.position.x = float(goal_point[0])
        goal_marker.pose.position.y = float(goal_point[1])
        goal_marker.pose.position.z = 0.0
        goal_marker.scale.x = 0.45
        goal_marker.scale.y = 0.45
        goal_marker.scale.z = 0.45
        goal_marker.color.r = 1.0
        goal_marker.color.g = 0.0
        goal_marker.color.b = 0.0
        goal_marker.color.a = 0.95
        self.goal_marker_pub.publish(goal_marker)

        line_marker = Marker()
        line_marker.header.frame_id = frame_id
        line_marker.header.stamp = now
        line_marker.ns = 'assigned_goal'
        line_marker.id = 1
        line_marker.type = Marker.LINE_STRIP
        line_marker.action = Marker.ADD
        line_marker.pose.orientation.w = 1.0
        line_marker.scale.x = 0.12
        line_marker.color.r = 0.0
        line_marker.color.g = 1.0
        line_marker.color.b = 1.0
        line_marker.color.a = 1.0

        p_robot = Point()
        p_robot.x = float(robot_position[0])
        p_robot.y = float(robot_position[1])
        p_robot.z = 0.0
        p_goal = Point()
        p_goal.x = float(goal_point[0])
        p_goal.y = float(goal_point[1])
        p_goal.z = 0.0
        line_marker.points = [p_robot, p_goal]
        self.goal_marker_pub.publish(line_marker)
        self.goal_visual_active = True

    def clear_goal_visualization(self):
        if not self.goal_visual_active:
            return

        now = self.get_clock().now().to_msg()
        frame_id = self.goal_frame_id()
        for marker_id in (0, 1):
            marker = Marker()
            marker.header.frame_id = frame_id
            marker.header.stamp = now
            marker.ns = 'assigned_goal'
            marker.id = marker_id
            marker.action = Marker.DELETE
            self.goal_marker_pub.publish(marker)
        self.goal_visual_active = False

    def callBack(self, data):
        self.frontiers = []
        for point in data.points:
            self.frontiers.append(np.array([point.x, point.y], dtype=float))

    def publish_goal_event(self, robot_name, goal_id, event_type, point, nav_status):
        msg = GoalTraceEvent()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.goal_frame_id()
        msg.goal_id = int(goal_id)
        msg.robot_name = robot_name
        msg.event_type = event_type
        msg.point.x = float(point[0])
        msg.point.y = float(point[1])
        msg.point.z = 0.0
        msg.nav_status = int(nav_status)
        self.goal_event_pub.publish(msg)

    def mapCallBack(self, data):
        self.mapData = data

    def on_timer(self):
        available = []
        busy = []
        robot_positions = {}
        for idx, robot_obj in enumerate(self.robots):
            robot_positions[idx] = robot_obj.getPosition()
            if robot_obj.getState() == 1 and len(robot_obj.assigned_point) > 0:
                busy.append(idx)
            else:
                available.append(idx)

        if busy:
            first_busy = busy[0]
            self.publish_goal_visualization(robot_positions[first_busy], self.robots[first_busy].assigned_point)
        else:
            self.clear_goal_visualization()

        if len(self.mapData.data) < 1:
            self.throttled_info('Waiting for map')
            return

        if len(self.frontiers) < 1:
            self.throttled_info('Waiting for filtered frontiers')
            return

        self.clear_wait_state()
        centroids = copy(self.frontiers)
        if len(centroids) < 1:
            return

        info_gain = []
        for centroid in centroids:
            info_gain.append(informationGain(self.mapData, [centroid[0], centroid[1]], self.info_radius))

        if len(available) < 1:
            return

        for idx in busy + available:
            assigned = self.robots[idx].assigned_point
            if len(assigned) == 0:
                continue
            info_gain = discount(self.mapData, assigned, centroids, info_gain, self.info_radius)

        revenue_record = []
        centroid_record = []
        id_record = []

        for robot_idx in available:
            robot_obj = self.robots[robot_idx]
            robot_position = robot_positions[robot_idx]
            for centroid_idx, centroid in enumerate(centroids):
                cost = norm(robot_position - centroid)
                if cost < self.min_target_distance:
                    continue

                if self.last_sent_target is not None:
                    age_sec = (self.get_clock().now().nanoseconds - self.last_sent_target_time_ns) / 1e9
                    if age_sec < self.repeat_target_cooldown and norm(self.last_sent_target - centroid) < self.repeat_target_radius:
                        continue

                information_gain = info_gain[centroid_idx]
                if cost <= self.hysteresis_radius:
                    information_gain *= self.hysteresis_gain
                revenue = information_gain * self.info_multiplier - cost
                revenue_record.append(revenue)
                centroid_record.append(np.array(centroid, dtype=float))
                id_record.append(robot_idx)

        if len(id_record) < 1:
            self.throttled_info('No valid frontier beyond min_target_distance')
            return

        winner_idx = revenue_record.index(max(revenue_record))
        robot_idx = id_record[winner_idx]
        robot_obj = self.robots[robot_idx]
        target = np.array(centroid_record[winner_idx], dtype=float)

        if len(robot_obj.assigned_point) > 0 and norm(robot_obj.assigned_point - target) < self.repeat_target_radius:
            if robot_obj.getState() == 1:
                return

        if self.last_sent_target is not None:
            age_sec = (self.get_clock().now().nanoseconds - self.last_sent_target_time_ns) / 1e9
            if age_sec < self.repeat_target_cooldown and norm(self.last_sent_target - target) < self.repeat_target_radius:
                return

        goal_id = self.goal_sequence
        self.goal_sequence += 1

        robot_obj.sendGoal(target, goal_id=goal_id)
        self.last_sent_target = np.array(target, dtype=float)
        self.last_sent_target_time_ns = self.get_clock().now().nanoseconds
        self.publish_goal_visualization(robot_positions[robot_idx], target)
        self.get_logger().info(f'Robot {robot_idx} assigned goal_id={goal_id} to {target}')


def main(args=None):
    rclpy.init(args=args)
    node = AssignerNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
