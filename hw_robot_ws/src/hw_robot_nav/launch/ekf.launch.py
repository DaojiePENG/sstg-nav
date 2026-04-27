import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('hw_robot_nav')

    return LaunchDescription([
        DeclareLaunchArgument(
            'ekf_params_file',
            default_value=os.path.join(pkg_dir, 'config', 'ekf.yaml'),
        ),
        Node(
            package='robot_localization',
            executable='ekf_node',
            name='ekf_filter_node',
            output='screen',
            parameters=[LaunchConfiguration('ekf_params_file')],
            remappings=[
                ('odometry/filtered', '/odom'),
            ],
        ),
    ])
