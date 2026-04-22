"""
slam_toolbox.launch.py - slam_toolbox async 建图模式（用于 RRT 探索）

RRT 探索阶段使用：从零建图 + 发布 map→odom TF
探索完成后调用 /slam_toolbox/serialize_map 保存序列化地图
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    scan_topic_arg = DeclareLaunchArgument('scan_topic', default_value='scan')

    slam_toolbox_node = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'base_frame': 'base_footprint',
            'odom_frame': 'odom',
            'map_frame': 'map',
            'scan_topic': LaunchConfiguration('scan_topic'),
            'map_update_interval': 0.5,
            'max_laser_range': 12.0,
            'min_laser_range': 0.1,
            'link_scan_maximum_distance': 3.0,
            'scan_buffer_maximum_scan_distance': 12.0,
            'minimum_score': 0.3,
            'link_match_minimum_response_fine': 0.1,
            'loop_search_maximum_distance': 4.0,
        }]
    )

    return LaunchDescription([
        scan_topic_arg,
        slam_toolbox_node,
    ])
