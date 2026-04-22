#!/usr/bin/env python3

from copy import copy
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from visualization_msgs.msg import Marker
from geometry_msgs.msg import Point, PointStamped
from nav_msgs.msg import OccupancyGrid
from tf2_ros import Buffer, TransformListener
import tf2_geometry_msgs  # noqa: F401
from functions_ros2 import gridValue, informationGain
from sklearn.cluster import MeanShift
from sstg_msgs.msg import PointArray


class FilterNode(Node):
    def __init__(self):
        super().__init__('filter')

        self.declare_parameter('map_topic', '/map')
        self.declare_parameter('info_radius', 1.0)
        self.declare_parameter('costmap_clearing_threshold', 70.0)
        self.declare_parameter('goals_topic', '/detected_points')
        self.declare_parameter('n_robots', 1)
        self.declare_parameter('namespace', '')
        self.declare_parameter('namespace_init_count', 1)
        self.declare_parameter('rate', 10.0)
        self.declare_parameter('global_costmap_topic', '/global_costmap/costmap')
        self.declare_parameter('cluster_bandwidth', 0.45)
        self.declare_parameter('min_frontier_separation', 0.20)
        self.declare_parameter('max_frontier_samples', 250)

        map_topic = self.get_parameter('map_topic').value
        self.info_radius = float(self.get_parameter('info_radius').value)
        self.costmap_clearing_threshold = float(self.get_parameter('costmap_clearing_threshold').value)
        goals_topic = self.get_parameter('goals_topic').value
        self.n_robots = int(self.get_parameter('n_robots').value)
        namespace = self.get_parameter('namespace').value
        namespace_init_count = int(self.get_parameter('namespace_init_count').value)
        self.rate_hz = float(self.get_parameter('rate').value)
        global_costmap_topic = self.get_parameter('global_costmap_topic').value
        self.cluster_bandwidth = float(self.get_parameter('cluster_bandwidth').value)
        self.min_frontier_separation = float(self.get_parameter('min_frontier_separation').value)
        self.max_frontier_samples = int(self.get_parameter('max_frontier_samples').value)

        self.frontiers = np.empty((0, 2), dtype=float)
        self.mapData = OccupancyGrid()
        self.globalmaps = [OccupancyGrid() for _ in range(self.n_robots)]
        self.wait_state = ''
        self.last_wait_log_ns = 0

        latched_qos = QoSProfile(depth=1)
        latched_qos.reliability = ReliabilityPolicy.RELIABLE
        latched_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.map_sub = self.create_subscription(
            OccupancyGrid, map_topic, self.mapCallBack, latched_qos)

        self.global_costmap_subs = []
        for i in range(self.n_robots):
            if namespace:
                topic = '/' + namespace + str(i + namespace_init_count) + global_costmap_topic
            else:
                topic = global_costmap_topic
            sub = self.create_subscription(
                OccupancyGrid,
                topic,
                lambda msg, idx=i: self.globalMapCallBack(msg, idx),
                latched_qos)
            self.global_costmap_subs.append(sub)

        self.goals_sub = self.create_subscription(
            PointStamped, goals_topic, self.goalsCallBack, 50)

        self.frontiers_pub = self.create_publisher(Marker, 'frontiers', 10)
        self.centroids_pub = self.create_publisher(Marker, 'centroids', 10)
        self.filtered_pub = self.create_publisher(PointArray, 'filtered_points', 10)

        self.timer = self.create_timer(max(0.05, 1.0 / max(self.rate_hz, 1.0)), self.on_timer)
        self.get_logger().info('Filter node initialized')

    def throttled_info(self, msg):
        now_ns = self.get_clock().now().nanoseconds
        if self.wait_state != msg or now_ns - self.last_wait_log_ns > 2_000_000_000:
            self.get_logger().info(msg)
            self.wait_state = msg
            self.last_wait_log_ns = now_ns

    def clear_wait_state(self):
        self.wait_state = ''

    def goalsCallBack(self, data):
        if len(self.mapData.data) < 1 or not self.mapData.header.frame_id:
            return

        try:
            if (not data.header.frame_id) or data.header.frame_id == self.mapData.header.frame_id:
                transformed = data
            else:
                transformed = self.tf_buffer.transform(data, self.mapData.header.frame_id)

            x = np.array([[transformed.point.x, transformed.point.y]], dtype=float)
            if len(self.frontiers) > 0:
                distances = np.linalg.norm(self.frontiers - x[0], axis=1)
                if np.min(distances) < self.min_frontier_separation:
                    return
                self.frontiers = np.vstack((self.frontiers, x))
            else:
                self.frontiers = x

            if self.max_frontier_samples > 0 and len(self.frontiers) > self.max_frontier_samples:
                self.frontiers = self.frontiers[-self.max_frontier_samples:]
        except Exception as exc:
            self.get_logger().warn(f'Transform failed in goalsCallBack: {exc}')

    def mapCallBack(self, data):
        self.mapData = data

    def globalMapCallBack(self, data, robot_idx):
        self.globalmaps[robot_idx] = data

    def publish_outputs(self, raw_frontiers, centroids):
        frame_id = self.mapData.header.frame_id if self.mapData.header.frame_id else 'map'
        now = self.get_clock().now().to_msg()

        points = Marker()
        points.header.frame_id = frame_id
        points.header.stamp = now
        points.ns = 'markers2'
        points.id = 0
        points.type = Marker.POINTS
        points.action = Marker.ADD
        points.pose.orientation.w = 1.0
        points.scale.x = 0.2
        points.scale.y = 0.2
        points.color.r = 1.0
        points.color.g = 1.0
        points.color.b = 0.0
        points.color.a = 1.0

        points_clust = Marker()
        points_clust.header.frame_id = frame_id
        points_clust.header.stamp = now
        points_clust.ns = 'markers3'
        points_clust.id = 4
        points_clust.type = Marker.POINTS
        points_clust.action = Marker.ADD
        points_clust.pose.orientation.w = 1.0
        points_clust.scale.x = 0.2
        points_clust.scale.y = 0.2
        points_clust.color.r = 0.0
        points_clust.color.g = 1.0
        points_clust.color.b = 0.0
        points_clust.color.a = 1.0

        arraypoints = PointArray()

        for point_xy in raw_frontiers:
            p = Point()
            p.x = float(point_xy[0])
            p.y = float(point_xy[1])
            p.z = 0.0
            points.points.append(p)

        for point_xy in centroids:
            p = Point()
            p.x = float(point_xy[0])
            p.y = float(point_xy[1])
            p.z = 0.0
            points_clust.points.append(p)
            arraypoints.points.append(copy(p))

        self.filtered_pub.publish(arraypoints)
        self.frontiers_pub.publish(points)
        self.centroids_pub.publish(points_clust)

    def on_timer(self):
        if len(self.mapData.data) < 1 or not self.mapData.header.frame_id:
            self.throttled_info('Waiting for map')
            return

        for global_map in self.globalmaps:
            if len(global_map.data) < 1:
                self.throttled_info('Waiting for global costmap')
                self.publish_outputs(np.empty((0, 2), dtype=float), np.empty((0, 2), dtype=float))
                return

        if len(self.frontiers) < 1:
            self.throttled_info('Waiting for frontiers')
            self.publish_outputs(np.empty((0, 2), dtype=float), np.empty((0, 2), dtype=float))
            return

        self.clear_wait_state()

        front = np.array(self.frontiers, dtype=float)
        raw_frontiers = np.empty((0, 2), dtype=float)

        if self.max_frontier_samples > 0 and len(front) > self.max_frontier_samples:
            sample_idx = np.linspace(0, len(front) - 1, self.max_frontier_samples, dtype=int)
            front = front[sample_idx]

        if len(front) > 1:
            try:
                ms = MeanShift(bandwidth=self.cluster_bandwidth)
                ms.fit(front)
                raw_frontiers = ms.cluster_centers_
            except Exception as exc:
                self.get_logger().warn(f'MeanShift failed, using raw frontiers: {exc}')
                raw_frontiers = front
        elif len(front) == 1:
            raw_frontiers = front

        centroids = np.array(raw_frontiers, dtype=float)
        self.frontiers = np.array(raw_frontiers, dtype=float)

        z = 0
        while z < len(centroids):
            cond = False
            temp_point = PointStamped()
            temp_point.header.frame_id = self.mapData.header.frame_id
            temp_point.header.stamp = self.get_clock().now().to_msg()
            temp_point.point.x = float(centroids[z][0])
            temp_point.point.y = float(centroids[z][1])
            temp_point.point.z = 0.0

            for global_map in self.globalmaps:
                try:
                    if (not global_map.header.frame_id) or global_map.header.frame_id == temp_point.header.frame_id:
                        x = np.array([temp_point.point.x, temp_point.point.y], dtype=float)
                    else:
                        transformed = self.tf_buffer.transform(temp_point, global_map.header.frame_id)
                        x = np.array([transformed.point.x, transformed.point.y], dtype=float)
                    cond = (gridValue(global_map, x) > self.costmap_clearing_threshold) or cond
                except Exception:
                    pass

            if cond or informationGain(self.mapData, [centroids[z][0], centroids[z][1]], self.info_radius * 0.5) < 0.2:
                centroids = np.delete(centroids, z, axis=0)
                z -= 1
            z += 1

        self.publish_outputs(raw_frontiers, centroids)


def main(args=None):
    rclpy.init(args=args)
    node = FilterNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
