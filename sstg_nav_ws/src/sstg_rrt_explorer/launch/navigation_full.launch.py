#!/usr/bin/env python3
"""
navigation_full.launch.py - 一键启动导航全栈（第三次启动）

前提：已完成 RRT 探索建图 + 拓扑节点采集，拥有：
  - PGM 栅格地图 + slam_toolbox 序列化地图
  - topological_map_manual.json（已含语义标注的拓扑节点）

启动顺序 (通过 TimerAction 分阶段):
  0s   硬件层: URDF, 底盘驱动, IMU, EKF, 雷达, TF
  3s   SLAM:   slam_toolbox localization + map_server
  3s   相机:   Orbbec Gemini 336L (与 SLAM 并行)
  6s   Nav2:   navigation (controller, planner, behavior, bt_navigator)
  8s   拓扑:   map_manager_node + topo_node_viz

用法:
  # 一键启动（1 个终端）
  ros2 launch sstg_rrt_explorer navigation_full.launch.py

  # RViz（另一个桌面终端）
  rviz2 -d ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/rviz/rrt_ros2.rviz

  # 自然语言导航（再一个终端，需 source + export 环境变量）
  python3 ~/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/scripts/find_and_navigate.py \\
    --query "我要找我的书包"

前提:
  source /opt/ros/humble/setup.bash
  source ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash
  source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export ROS_DOMAIN_ID=28
"""

import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('sstg_rrt_explorer')
    nav2_params = os.path.join(pkg_share, 'param', 'common', 'nav2_params.yaml')

    # ── 阶段 1: 硬件 (0s) ──
    hardware = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_share, 'launch', 'library', 'hardware_bringup.launch.py')
        )
    )

    # ── 阶段 2: SLAM 定位 + map_server (3s) ──
    slam_localization = TimerAction(
        period=3.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(pkg_share, 'launch', 'library',
                                'slam_toolbox_localization.launch.py')
                )
            ),
        ],
    )

    # ── 阶段 2: 相机 (3s, 与 SLAM 并行) ──
    camera = TimerAction(
        period=3.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(pkg_share, 'launch', 'library', 'orbbec_stable.launch.py')
                )
            ),
        ],
    )

    # ── 阶段 3: Nav2 (12s, 用自己的 nav2.launch.py 避免嵌套问题) ──
    nav2 = TimerAction(
        period=12.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(pkg_share, 'launch', 'library', 'nav2.launch.py')
                )
            ),
        ],
    )

    # ── 阶段 4: 拓扑管理 + 可视化 (15s) ──
    topo_map_file = os.path.join(
        pkg_share, 'maps', 'topological_map_manual.json')

    map_manager = TimerAction(
        period=15.0,
        actions=[
            Node(
                package='sstg_map_manager',
                executable='map_manager_node',
                name='map_manager_node',
                output='screen',
            ),
        ],
    )

    topo_viz = TimerAction(
        period=15.0,
        actions=[
            Node(
                package='sstg_rrt_explorer',
                executable='topo_node_viz.py',
                name='topo_node_viz',
                output='screen',
                parameters=[{'map_file': topo_map_file}],
            ),
        ],
    )

    return LaunchDescription([
        hardware,
        slam_localization,
        camera,
        nav2,
        map_manager,
        topo_viz,
    ])
