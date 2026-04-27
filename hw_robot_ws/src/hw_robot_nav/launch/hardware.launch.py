import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    sllidar_dir = get_package_share_directory('sllidar_ros2')
    cmd_control_dir = get_package_share_directory('cmd_control')

    start_lidar = LaunchConfiguration('start_lidar')
    start_base = LaunchConfiguration('start_base')
    start_odom = LaunchConfiguration('start_odom')
    publish_laser_tf = LaunchConfiguration('publish_laser_tf')
    publish_odom_tf = LaunchConfiguration('publish_odom_tf')

    base_frame = LaunchConfiguration('base_frame')
    laser_frame = LaunchConfiguration('laser_frame')

    return LaunchDescription([
        DeclareLaunchArgument('start_lidar', default_value='true'),
        DeclareLaunchArgument('start_base', default_value='true'),
        DeclareLaunchArgument('start_odom', default_value='true'),
        DeclareLaunchArgument('publish_laser_tf', default_value='true'),
        DeclareLaunchArgument('publish_odom_tf', default_value='true'),
        DeclareLaunchArgument('base_frame', default_value='base_footprint'),
        DeclareLaunchArgument('odom_frame', default_value='odom'),
        DeclareLaunchArgument('odom_topic', default_value='/odom'),
        DeclareLaunchArgument('laser_frame', default_value='laser'),
        DeclareLaunchArgument('laser_x', default_value='0.0'),
        DeclareLaunchArgument('laser_y', default_value='0.0'),
        DeclareLaunchArgument('laser_z', default_value='0.18'),
        DeclareLaunchArgument('laser_roll', default_value='0.0'),
        DeclareLaunchArgument('laser_pitch', default_value='0.0'),
        DeclareLaunchArgument('laser_yaw', default_value='3.1415926'),
        DeclareLaunchArgument('lidar_serial_port', default_value='/dev/rplidar'),
        DeclareLaunchArgument('lidar_serial_baudrate', default_value='1000000'),
        DeclareLaunchArgument('lidar_scan_mode', default_value='DenseBoost'),
        DeclareLaunchArgument('base_serial_port', default_value='/dev/ttyTHS1'),
        DeclareLaunchArgument('mqtt_broker_ip', default_value='192.168.0.6'),
        DeclareLaunchArgument('mqtt_port', default_value='1883'),
        DeclareLaunchArgument('mqtt_topic', default_value='wifi/car_status'),
        DeclareLaunchArgument('mqtt_yaw_in_degrees', default_value='true'),
        DeclareLaunchArgument('mqtt_yaw_offset', default_value='0.0'),
        DeclareLaunchArgument('mqtt_linear_velocity_scale', default_value='0.01'),
        DeclareLaunchArgument('mqtt_angular_velocity_scale', default_value='1.0'),
        DeclareLaunchArgument('mqtt_data_timeout_sec', default_value='2.0'),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(sllidar_dir, 'launch', 'sllidar_s2_launch.py')
            ),
            condition=IfCondition(start_lidar),
            launch_arguments={
                'serial_port': LaunchConfiguration('lidar_serial_port'),
                'serial_baudrate': LaunchConfiguration('lidar_serial_baudrate'),
                'frame_id': laser_frame,
                'scan_mode': LaunchConfiguration('lidar_scan_mode'),
            }.items(),
        ),

        Node(
            package='cmd_control',
            executable='cmd_vel_to_serial',
            name='cmd_vel_to_serial',
            output='screen',
            condition=IfCondition(start_base),
            parameters=[
                os.path.join(cmd_control_dir, 'config', 'control.yaml'),
                {'serial_port': LaunchConfiguration('base_serial_port')},
            ],
        ),

        Node(
            package='mqtt_bridge_pkg',
            executable='mqtt_to_ros',
            name='mqtt_to_ros_bridge_node',
            output='screen',
            condition=IfCondition(start_odom),
            parameters=[
                os.path.join(
                    get_package_share_directory('hw_robot_nav'),
                    'config',
                    'mqtt_bridge.yaml',
                ),
                {
                    'mqtt_broker_ip': LaunchConfiguration('mqtt_broker_ip'),
                    'mqtt_port': LaunchConfiguration('mqtt_port'),
                    'mqtt_topic': LaunchConfiguration('mqtt_topic'),
                    'odom_topic': LaunchConfiguration('odom_topic'),
                    'odom_frame_id': LaunchConfiguration('odom_frame'),
                    'base_frame_id': base_frame,
                    'yaw_in_degrees': LaunchConfiguration('mqtt_yaw_in_degrees'),
                    'yaw_offset': LaunchConfiguration('mqtt_yaw_offset'),
                    'linear_velocity_scale': LaunchConfiguration(
                        'mqtt_linear_velocity_scale'
                    ),
                    'angular_velocity_scale': LaunchConfiguration(
                        'mqtt_angular_velocity_scale'
                    ),
                    'publish_tf': publish_odom_tf,
                    'data_timeout_sec': LaunchConfiguration('mqtt_data_timeout_sec'),
                },
            ],
        ),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='base_to_laser_tf',
            output='screen',
            condition=IfCondition(publish_laser_tf),
            arguments=[
                '--x', LaunchConfiguration('laser_x'),
                '--y', LaunchConfiguration('laser_y'),
                '--z', LaunchConfiguration('laser_z'),
                '--roll', LaunchConfiguration('laser_roll'),
                '--pitch', LaunchConfiguration('laser_pitch'),
                '--yaw', LaunchConfiguration('laser_yaw'),
                '--frame-id', base_frame,
                '--child-frame-id', laser_frame,
            ],
        ),
    ])
