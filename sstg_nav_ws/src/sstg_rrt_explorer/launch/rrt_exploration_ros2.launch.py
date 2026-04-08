#!/usr/bin/env python3

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('local_eta', default_value='1.5'),
        DeclareLaunchArgument('global_eta', default_value='4.0'),
        DeclareLaunchArgument('local_range', default_value='8.0'),
        DeclareLaunchArgument('map_topic', default_value='/map'),
        DeclareLaunchArgument('info_radius', default_value='1.5'),
        DeclareLaunchArgument('global_costmap_topic', default_value='/global_costmap/costmap'),
        DeclareLaunchArgument('frontiers_topic', default_value='/filtered_points'),
        DeclareLaunchArgument('robot_frame', default_value='base_link'),
        DeclareLaunchArgument('global_frame', default_value='map'),
        DeclareLaunchArgument('filter_rate', default_value='2.0'),
        DeclareLaunchArgument('assignment_period', default_value='0.2'),
        DeclareLaunchArgument('filter_cluster_bandwidth', default_value='0.45'),
        DeclareLaunchArgument('filter_min_frontier_separation', default_value='0.20'),
        DeclareLaunchArgument('filter_max_frontier_samples', default_value='150'),
        DeclareLaunchArgument(
            'trace_output_dir',
            default_value=os.path.join(
                get_package_share_directory('sstg_rrt_explorer'), 'maps'),
        ),
        DeclareLaunchArgument('completion_patience', default_value='10.0'),
        DeclareLaunchArgument('trajectory_distance_threshold', default_value='0.05'),
        DeclareLaunchArgument('trajectory_time_threshold', default_value='0.5'),

        TimerAction(
            period=8.0,
            actions=[
                Node(
                    package='sstg_rrt_explorer',
                    executable='global_rrt_detector',
                    name='global_rrt_detector',
                    parameters=[{
                        'eta': LaunchConfiguration('global_eta'),
                        'map_topic': LaunchConfiguration('map_topic'),
                    }],
                    output='screen'
                ),
                Node(
                    package='sstg_rrt_explorer',
                    executable='local_rrt_detector',
                    name='local_rrt_detector',
                    parameters=[{
                        'eta': LaunchConfiguration('local_eta'),
                        'range': LaunchConfiguration('local_range'),
                        'map_topic': LaunchConfiguration('map_topic'),
                        'robot_frame': LaunchConfiguration('robot_frame'),
                    }],
                    output='screen'
                ),
                Node(
                    package='sstg_rrt_explorer',
                    executable='filter_ros2.py',
                    name='filter',
                    parameters=[{
                        'map_topic': LaunchConfiguration('map_topic'),
                        'info_radius': LaunchConfiguration('info_radius'),
                        'global_costmap_topic': LaunchConfiguration('global_costmap_topic'),
                        'rate': LaunchConfiguration('filter_rate'),
                        'cluster_bandwidth': LaunchConfiguration('filter_cluster_bandwidth'),
                        'min_frontier_separation': LaunchConfiguration('filter_min_frontier_separation'),
                        'max_frontier_samples': LaunchConfiguration('filter_max_frontier_samples'),
                    }],
                    output='screen'
                ),
                Node(
                    package='sstg_rrt_explorer',
                    executable='assigner_ros2.py',
                    name='assigner',
                    parameters=[{
                        'map_topic': LaunchConfiguration('map_topic'),
                        'info_radius': LaunchConfiguration('info_radius'),
                        'frontiers_topic': LaunchConfiguration('frontiers_topic'),
                        'global_frame': LaunchConfiguration('global_frame'),
                        'robot_frame': LaunchConfiguration('robot_frame'),
                        'assignment_period': LaunchConfiguration('assignment_period'),
                    }],
                    output='screen'
                ),
                Node(
                    package='sstg_rrt_explorer',
                    executable='rrt_trace_manager.py',
                    name='rrt_trace_manager',
                    parameters=[{
                        'map_topic': LaunchConfiguration('map_topic'),
                        'filtered_points_topic': LaunchConfiguration('frontiers_topic'),
                        'global_frame': LaunchConfiguration('global_frame'),
                        'robot_frame': LaunchConfiguration('robot_frame'),
                        'trace_output_dir': LaunchConfiguration('trace_output_dir'),
                        'completion_patience': LaunchConfiguration('completion_patience'),
                        'trajectory_distance_threshold': LaunchConfiguration('trajectory_distance_threshold'),
                        'trajectory_time_threshold': LaunchConfiguration('trajectory_time_threshold'),
                    }],
                    output='screen'
                ),
            ]
        ),
    ])
