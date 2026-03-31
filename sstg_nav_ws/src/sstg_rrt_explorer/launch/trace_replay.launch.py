#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('trace_file', default_value=''),
        DeclareLaunchArgument('global_frame', default_value='map'),
        DeclareLaunchArgument('navigate_action', default_value='navigate_to_pose'),
        DeclareLaunchArgument('compute_path_action', default_value='compute_path_to_pose'),
        DeclareLaunchArgument('map_topic', default_value='/map'),
        DeclareLaunchArgument('costmap_topic', default_value='/global_costmap/costmap'),
        DeclareLaunchArgument('amcl_pose_topic', default_value='/amcl_pose'),
        DeclareLaunchArgument('min_goal_separation', default_value='0.45'),
        DeclareLaunchArgument('skip_goal_distance', default_value='0.35'),
        DeclareLaunchArgument('safety_radius', default_value='0.30'),
        DeclareLaunchArgument('blocked_cost_threshold', default_value='70'),
        DeclareLaunchArgument('max_goal_retries', default_value='1'),
        DeclareLaunchArgument('max_consecutive_failures', default_value='2'),
        Node(
            package='sstg_rrt_explorer',
            executable='trace_replay.py',
            name='trace_replay',
            parameters=[{
                'trace_file': LaunchConfiguration('trace_file'),
                'global_frame': LaunchConfiguration('global_frame'),
                'navigate_action': LaunchConfiguration('navigate_action'),
                'compute_path_action': LaunchConfiguration('compute_path_action'),
                'map_topic': LaunchConfiguration('map_topic'),
                'costmap_topic': LaunchConfiguration('costmap_topic'),
                'amcl_pose_topic': LaunchConfiguration('amcl_pose_topic'),
                'min_goal_separation': LaunchConfiguration('min_goal_separation'),
                'skip_goal_distance': LaunchConfiguration('skip_goal_distance'),
                'safety_radius': LaunchConfiguration('safety_radius'),
                'blocked_cost_threshold': LaunchConfiguration('blocked_cost_threshold'),
                'max_goal_retries': LaunchConfiguration('max_goal_retries'),
                'max_consecutive_failures': LaunchConfiguration('max_consecutive_failures'),
            }],
            output='screen',
        ),
    ])
