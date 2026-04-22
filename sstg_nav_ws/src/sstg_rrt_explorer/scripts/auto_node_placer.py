#!/usr/bin/env python3
"""
auto_node_placer.py - 在已完成的栅格地图上自动布局拓扑节点

在线模式（默认）：
    订阅 Nav2 代价地图，基于真实代价值布点，在 RViz 中可视化，
    可选调用 ComputePathToPose 验证每个节点可达性。

离线模式（--offline）：
    直接读取 PGM 文件做几何分析（不需要 ROS 环境）。

用法:
    # 在线模式（需要 Nav2 + AMCL 运行）
    ros2 run sstg_rrt_explorer auto_node_placer.py --spacing 2.0

    # 在线 + 路径可达性验证
    ros2 run sstg_rrt_explorer auto_node_placer.py --spacing 2.0 --verify-paths

    # 离线模式
    python3 auto_node_placer.py --offline --map maps/xxx.yaml --spacing 2.0
"""

import argparse
import json
import math
import os
import sys

import cv2
import numpy as np
import yaml


# ──────────────────────────────────────────────
# 离线工具函数（不依赖 ROS）
# ──────────────────────────────────────────────

def load_map_from_file(yaml_path):
    """读取 ROS2 map_server 格式的地图文件。"""
    with open(yaml_path, 'r') as f:
        map_info = yaml.safe_load(f)

    resolution = float(map_info['resolution'])
    origin = map_info['origin']  # [x, y, theta]
    negate = int(map_info.get('negate', 0))
    free_thresh = float(map_info.get('free_thresh', 0.196))

    image_file = map_info['image']
    if not os.path.isabs(image_file):
        image_file = os.path.join(os.path.dirname(yaml_path), image_file)

    map_image = cv2.imread(image_file, cv2.IMREAD_GRAYSCALE)
    if map_image is None:
        raise FileNotFoundError(f'无法读取地图图像: {image_file}')

    return map_image, resolution, origin, negate, free_thresh


def compute_free_mask_from_image(map_image, negate, free_thresh):
    """从 PGM 图像计算自由空间掩码。"""
    if negate:
        occ_prob = map_image.astype(np.float32) / 255.0
    else:
        occ_prob = (255.0 - map_image.astype(np.float32)) / 255.0
    return (occ_prob < free_thresh).astype(np.uint8)


def compute_safe_mask_from_costmap(costmap_data, width, height, cost_threshold):
    """从代价地图数据计算安全区域掩码。

    Nav2 costmap 值:
        0       = 完全自由
        1-252   = 不同代价等级
        253     = 内切膨胀区（inscribed）
        254     = 致命障碍（lethal）
        255     = 未知
    """
    grid = np.array(costmap_data, dtype=np.int16).reshape((height, width))
    # 安全区域：代价低于阈值且不是未知(-1 在 OccupancyGrid 中)
    safe = np.zeros_like(grid, dtype=np.uint8)
    safe[(grid >= 0) & (grid < cost_threshold)] = 1
    return safe


def erode_mask(mask, clearance, resolution):
    """腐蚀掩码，保持离障碍物安全距离。"""
    kernel_radius = max(1, int(math.ceil(clearance / resolution)))
    kernel_size = 2 * kernel_radius + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    return cv2.erode(mask, kernel)


def grid_sample(safe_mask, spacing, resolution, origin_x, origin_y, map_height):
    """在安全区域上等间距网格采样。

    Returns:
        list of {'x': float, 'y': float}
    """
    grid_step = max(1, int(math.ceil(spacing / resolution)))
    height, width = safe_mask.shape
    nodes = []

    for row in range(grid_step // 2, height, grid_step):
        for col in range(grid_step // 2, width, grid_step):
            if safe_mask[row, col] > 0:
                x = col * resolution + origin_x
                y = (map_height - 1 - row) * resolution + origin_y
                nodes.append({'x': round(x, 3), 'y': round(y, 3)})
    return nodes


def save_json(nodes, output_path, source, spacing, wall_clearance, resolution, origin):
    """保存节点位置到 JSON。"""
    result = {
        'source': source,
        'spacing': spacing,
        'wall_clearance': wall_clearance,
        'resolution': resolution,
        'origin': origin if isinstance(origin, list) else [origin[0], origin[1], 0.0],
        'node_count': len(nodes),
        'nodes': nodes,
    }
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return output_path


# ──────────────────────────────────────────────
# ROS2 在线模式
# ──────────────────────────────────────────────

def run_online(args, remaining_args):
    """在线模式：订阅代价地图、RViz 可视化、可选路径验证。"""
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from rclpy.action import ActionClient
    from rclpy.executors import ExternalShutdownException
    from nav_msgs.msg import OccupancyGrid
    from geometry_msgs.msg import PoseStamped, Point
    from visualization_msgs.msg import Marker, MarkerArray
    from std_msgs.msg import ColorRGBA
    from action_msgs.msg import GoalStatus

    try:
        from nav2_msgs.action import ComputePathToPose
        HAS_COMPUTE_PATH = True
    except ImportError:
        HAS_COMPUTE_PATH = False

    class AutoNodePlacerNode(Node):
        def __init__(self):
            super().__init__('auto_node_placer')

            self.spacing = args.spacing
            self.wall_clearance = args.wall_clearance
            self.cost_threshold = args.cost_threshold
            self.verify_paths = args.verify_paths and HAS_COMPUTE_PATH
            self.output = args.output or '/tmp/node_positions.json'

            self.costmap_received = False
            self.nodes = []
            self.node_status = []  # 'pending' / 'reachable' / 'unreachable'

            # 订阅代价地图
            costmap_qos = QoSProfile(depth=1)
            costmap_qos.reliability = ReliabilityPolicy.RELIABLE
            costmap_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

            self.costmap_sub = self.create_subscription(
                OccupancyGrid,
                args.costmap_topic,
                self.costmap_callback,
                costmap_qos)

            # RViz 可视化发布
            self.marker_pub = self.create_publisher(
                MarkerArray, '/topo_node_placement', 10)

            # 定时发布 markers（保持 RViz 显示）
            self.publish_timer = self.create_timer(1.0, self.publish_markers)

            # 路径验证
            if self.verify_paths:
                self.path_client = ActionClient(
                    self, ComputePathToPose, 'compute_path_to_pose')
                self.get_logger().info('路径验证已启用，等待 compute_path_to_pose...')
            else:
                self.path_client = None
                if args.verify_paths and not HAS_COMPUTE_PATH:
                    self.get_logger().warn(
                        'nav2_msgs.action.ComputePathToPose 不可用，跳过路径验证')

            self.get_logger().info(
                f'等待代价地图 ({args.costmap_topic})...\n'
                f'  spacing={self.spacing}m, wall_clearance={self.wall_clearance}m, '
                f'cost_threshold={self.cost_threshold}')

        def costmap_callback(self, msg):
            """收到代价地图，计算节点位置。"""
            if self.costmap_received:
                return  # 只处理第一次

            self.costmap_received = True
            width = msg.info.width
            height = msg.info.height
            resolution = msg.info.resolution
            origin_x = msg.info.origin.position.x
            origin_y = msg.info.origin.position.y

            self.get_logger().info(
                f'收到代价地图: {width}x{height} px, '
                f'分辨率 {resolution} m/px, '
                f'范围 {width * resolution:.1f}x{height * resolution:.1f} m')

            # 从代价地图计算安全区域
            safe_mask = compute_safe_mask_from_costmap(
                msg.data, width, height, self.cost_threshold)

            safe_count = np.count_nonzero(safe_mask)
            self.get_logger().info(
                f'安全区域 (cost<{self.cost_threshold}): '
                f'{safe_count}/{width * height} px '
                f'({safe_count / (width * height) * 100:.1f}%)')

            # 腐蚀（额外安全边距）
            if self.wall_clearance > 0:
                safe_mask = erode_mask(
                    safe_mask, self.wall_clearance, resolution)
                eroded_count = np.count_nonzero(safe_mask)
                self.get_logger().info(
                    f'腐蚀后 (clearance={self.wall_clearance}m): '
                    f'{eroded_count} px')

            # 网格采样
            self.nodes = grid_sample(
                safe_mask, self.spacing, resolution,
                origin_x, origin_y, height)

            self.node_status = ['pending'] * len(self.nodes)
            self.get_logger().info(f'生成 {len(self.nodes)} 个候选节点')

            for i, n in enumerate(self.nodes):
                self.get_logger().info(f'  Node {i}: ({n["x"]:.2f}, {n["y"]:.2f})')

            if len(self.nodes) == 0:
                self.get_logger().warn('未生成节点! 尝试减小 spacing 或增大 cost_threshold')
                self._save_and_report(resolution, [origin_x, origin_y, 0.0])
                return

            # 路径验证
            if self.verify_paths:
                self._verify_all_paths(resolution, origin_x, origin_y)
            else:
                # 不验证，全部标记为 reachable
                self.node_status = ['reachable'] * len(self.nodes)
                self._save_and_report(resolution, [origin_x, origin_y, 0.0])

        def _verify_all_paths(self, resolution, origin_x, origin_y):
            """验证每个节点是否可达。"""
            if not self.path_client.wait_for_server(timeout_sec=5.0):
                self.get_logger().warn(
                    'compute_path_to_pose 不可用，跳过验证')
                self.node_status = ['reachable'] * len(self.nodes)
                self._save_and_report(resolution, [origin_x, origin_y, 0.0])
                return

            self.get_logger().info('开始路径可达性验证...')
            reachable = 0
            unreachable = 0

            for i, node_pos in enumerate(self.nodes):
                goal_msg = ComputePathToPose.Goal()
                goal_msg.goal.header.frame_id = 'map'
                goal_msg.goal.header.stamp = self.get_clock().now().to_msg()
                goal_msg.goal.pose.position.x = float(node_pos['x'])
                goal_msg.goal.pose.position.y = float(node_pos['y'])
                goal_msg.goal.pose.orientation.w = 1.0

                send_future = self.path_client.send_goal_async(goal_msg)
                rclpy.spin_until_future_complete(self, send_future, timeout_sec=5.0)

                goal_handle = send_future.result()
                if not goal_handle or not goal_handle.accepted:
                    self.node_status[i] = 'unreachable'
                    unreachable += 1
                    continue

                result_future = goal_handle.get_result_async()
                rclpy.spin_until_future_complete(self, result_future, timeout_sec=10.0)

                result = result_future.result()
                if result and result.status == GoalStatus.STATUS_SUCCEEDED:
                    path = result.result.path
                    if len(path.poses) > 0:
                        self.node_status[i] = 'reachable'
                        reachable += 1
                    else:
                        self.node_status[i] = 'unreachable'
                        unreachable += 1
                else:
                    self.node_status[i] = 'unreachable'
                    unreachable += 1

                self.get_logger().info(
                    f'  Node {i}: ({node_pos["x"]:.2f}, {node_pos["y"]:.2f}) '
                    f'→ {self.node_status[i]}')

            self.get_logger().info(
                f'验证完成: {reachable} 可达, {unreachable} 不可达')

            self._save_and_report(resolution, [origin_x, origin_y, 0.0])

        def _save_and_report(self, resolution, origin):
            """保存结果（只保留可达节点）。"""
            reachable_nodes = [
                n for n, s in zip(self.nodes, self.node_status)
                if s != 'unreachable'
            ]
            removed = len(self.nodes) - len(reachable_nodes)

            if removed > 0:
                self.get_logger().info(
                    f'剔除 {removed} 个不可达节点，保留 {len(reachable_nodes)} 个')

            path = save_json(
                reachable_nodes, self.output, 'costmap',
                self.spacing, self.wall_clearance, resolution, origin)

            self.get_logger().info(
                f'节点位置已保存: {path}\n'
                f'  共 {len(reachable_nodes)} 个节点\n'
                f'  在 RViz 中查看: /topo_node_placement 话题\n'
                f'  按 Ctrl+C 退出，或保持运行以继续显示标记')

        def publish_markers(self):
            """发布节点标记到 RViz。"""
            if not self.nodes:
                return

            markers = MarkerArray()

            # 清除旧标记
            delete_marker = Marker()
            delete_marker.action = Marker.DELETEALL
            markers.markers.append(delete_marker)

            # 节点球体
            for i, (node_pos, status) in enumerate(
                    zip(self.nodes, self.node_status)):
                m = Marker()
                m.header.frame_id = 'map'
                m.header.stamp = self.get_clock().now().to_msg()
                m.ns = 'topo_nodes'
                m.id = i
                m.type = Marker.SPHERE
                m.action = Marker.ADD
                m.pose.position.x = float(node_pos['x'])
                m.pose.position.y = float(node_pos['y'])
                m.pose.position.z = 0.15
                m.pose.orientation.w = 1.0
                m.scale.x = 0.30
                m.scale.y = 0.30
                m.scale.z = 0.30

                if status == 'reachable':
                    m.color = ColorRGBA(r=0.0, g=0.9, b=0.2, a=0.9)
                elif status == 'unreachable':
                    m.color = ColorRGBA(r=1.0, g=0.0, b=0.0, a=0.7)
                else:  # pending
                    m.color = ColorRGBA(r=1.0, g=0.9, b=0.0, a=0.8)

                markers.markers.append(m)

                # 编号文字
                t = Marker()
                t.header.frame_id = 'map'
                t.header.stamp = self.get_clock().now().to_msg()
                t.ns = 'topo_labels'
                t.id = i
                t.type = Marker.TEXT_VIEW_FACING
                t.action = Marker.ADD
                t.pose.position.x = float(node_pos['x'])
                t.pose.position.y = float(node_pos['y'])
                t.pose.position.z = 0.45
                t.pose.orientation.w = 1.0
                t.scale.z = 0.25
                t.color = ColorRGBA(r=1.0, g=1.0, b=1.0, a=1.0)
                t.text = str(i)
                markers.markers.append(t)

            self.marker_pub.publish(markers)

    # 启动 ROS2
    rclpy.init(args=remaining_args)
    try:
        node = AutoNodePlacerNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except ExternalShutdownException:
        pass
    finally:
        rclpy.shutdown()


# ──────────────────────────────────────────────
# 离线模式
# ──────────────────────────────────────────────

def run_offline(args):
    """离线模式：读取 PGM 文件做几何分析。"""
    if not args.map:
        print('[ERROR] 离线模式需要 --map 参数')
        sys.exit(1)

    print(f'[INFO] 离线模式 - 读取地图: {args.map}')
    map_image, resolution, origin, negate, free_thresh = load_map_from_file(args.map)
    height, width = map_image.shape
    print(f'[INFO] 地图尺寸: {width}x{height} px, 分辨率: {resolution} m/px')
    print(f'[INFO] 实际范围: {width * resolution:.1f} x {height * resolution:.1f} m')

    free_mask = compute_free_mask_from_image(map_image, negate, free_thresh)
    print(f'[INFO] 自由空间: {np.count_nonzero(free_mask)}/{height * width} px')

    safe_mask = erode_mask(free_mask, args.wall_clearance, resolution)
    print(f'[INFO] 安全区域: {np.count_nonzero(safe_mask)} px')

    nodes = grid_sample(safe_mask, args.spacing, resolution,
                        origin[0], origin[1], height)
    print(f'[INFO] 生成节点: {len(nodes)} 个')

    if len(nodes) == 0:
        print('[WARN] 未生成节点! 尝试减小 spacing 或 wall-clearance')
        sys.exit(1)

    for i, n in enumerate(nodes):
        print(f'  Node {i}: ({n["x"]:.2f}, {n["y"]:.2f})')

    output = args.output or os.path.join(
        os.path.dirname(args.map), 'node_positions.json')
    save_json(nodes, output, os.path.abspath(args.map),
              args.spacing, args.wall_clearance, resolution, origin)
    print(f'[INFO] 节点位置已保存: {output}')


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='在栅格地图上自动布局拓扑节点（支持在线/离线模式）')
    parser.add_argument('--spacing', type=float, default=2.0,
                        help='节点间距 (米), 默认 2.0')
    parser.add_argument('--wall-clearance', type=float, default=0.3,
                        help='距障碍物额外安全距离 (米), 默认 0.3')
    parser.add_argument('--output', default=None,
                        help='输出 JSON 路径')
    parser.add_argument('--offline', action='store_true',
                        help='离线模式：读取 PGM 文件（不需要 ROS）')
    parser.add_argument('--map', default=None,
                        help='[离线模式] 地图 YAML 文件路径')
    parser.add_argument('--costmap-topic', default='/global_costmap/costmap',
                        help='[在线模式] 代价地图话题, 默认 /global_costmap/costmap')
    parser.add_argument('--cost-threshold', type=int, default=50,
                        help='[在线模式] 安全代价阈值 (0-252), 默认 50')
    parser.add_argument('--verify-paths', action='store_true',
                        help='[在线模式] 用 Nav2 ComputePathToPose 验证每个节点可达性')

    parsed, remaining = parser.parse_known_args()

    if parsed.offline:
        run_offline(parsed)
    else:
        run_online(parsed, remaining)


if __name__ == '__main__':
    main()
