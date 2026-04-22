#!/usr/bin/env python3
"""
rrt_exploration_full.launch.py - 一键启动 RRT 自主探索全流程

启动顺序 (通过 TimerAction 分阶段):
  0s   硬件层: URDF, 底盘驱动, IMU, EKF, 雷达, TF
  3s   SLAM:   slam_toolbox (async)
  6s   Nav2:   navigation_launch (controller, planner, behavior, bt_navigator)
  10s  RRT:    global/local detector, filter, assigner, trace_manager

用法:
  ros2 launch sstg_rrt_explorer rrt_exploration_full.launch.py

前提:
  source /opt/ros/humble/setup.bash
  source ~/yahboomcar_ros2_ws/software/library_ws/install/setup.bash
  source ~/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash
  source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
"""

import os
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
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

    # ── 阶段 2: SLAM (3s) ──
    slam = TimerAction(
        period=3.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(pkg_share, 'launch', 'library', 'slam_toolbox.launch.py')
                )
            ),
        ],
    )

    # ── 阶段 3: Nav2 (6s) ──
    nav2 = TimerAction(
        period=6.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(
                        get_package_share_directory('nav2_bringup'),
                        'launch', 'navigation_launch.py',
                    )
                ),
                launch_arguments={
                    'params_file': nav2_params,
                    'use_sim_time': 'false',
                }.items(),
            ),
        ],
    )

    # ── 阶段 4: RRT 探索 (10s) ──
    rrt = TimerAction(
        period=10.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(pkg_share, 'launch', 'rrt_exploration_ros2.launch.py')
                )
            ),
        ],
    )

    return LaunchDescription([
        hardware,
        slam,
        nav2,
        rrt,
    ])
