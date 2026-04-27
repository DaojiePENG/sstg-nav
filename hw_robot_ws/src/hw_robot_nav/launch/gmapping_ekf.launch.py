import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('hw_robot_nav')

    include_hardware = LaunchConfiguration('include_hardware')
    scan_topic = LaunchConfiguration('scan_topic')
    base_frame = LaunchConfiguration('base_frame')
    odom_frame = LaunchConfiguration('odom_frame')
    map_frame = LaunchConfiguration('map_frame')
    use_scan_downsampler = LaunchConfiguration('use_scan_downsampler')
    use_rviz = LaunchConfiguration('use_rviz')

    return LaunchDescription([
        DeclareLaunchArgument('include_hardware', default_value='true'),
        DeclareLaunchArgument('use_rviz', default_value='true'),
        DeclareLaunchArgument(
            'rviz_config',
            default_value=os.path.join(pkg_dir, 'rviz', 'gmapping.rviz'),
        ),
        DeclareLaunchArgument('use_scan_downsampler', default_value='true'),
        DeclareLaunchArgument('raw_scan_topic', default_value='/scan'),
        DeclareLaunchArgument('scan_topic', default_value='/scan_gmapping'),
        DeclareLaunchArgument('max_scan_beams', default_value='1800'),
        DeclareLaunchArgument('base_frame', default_value='base_footprint'),
        DeclareLaunchArgument('odom_frame', default_value='odom'),
        DeclareLaunchArgument('odom_topic', default_value='/odom_raw'),
        DeclareLaunchArgument('map_frame', default_value='map'),
        DeclareLaunchArgument('start_lidar', default_value='true'),
        DeclareLaunchArgument('start_base', default_value='true'),
        DeclareLaunchArgument('start_odom', default_value='true'),
        DeclareLaunchArgument('publish_laser_tf', default_value='true'),
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
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(pkg_dir, 'config', 'slam_gmapping.yaml'),
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg_dir, 'launch', 'hardware.launch.py')
            ),
            condition=IfCondition(include_hardware),
            launch_arguments={
                'start_lidar': LaunchConfiguration('start_lidar'),
                'start_base': LaunchConfiguration('start_base'),
                'start_odom': LaunchConfiguration('start_odom'),
                'publish_laser_tf': LaunchConfiguration('publish_laser_tf'),
                'publish_odom_tf': 'false',
                'base_frame': base_frame,
                'odom_frame': odom_frame,
                'odom_topic': LaunchConfiguration('odom_topic'),
                'laser_frame': LaunchConfiguration('laser_frame'),
                'laser_x': LaunchConfiguration('laser_x'),
                'laser_y': LaunchConfiguration('laser_y'),
                'laser_z': LaunchConfiguration('laser_z'),
                'laser_roll': LaunchConfiguration('laser_roll'),
                'laser_pitch': LaunchConfiguration('laser_pitch'),
                'laser_yaw': LaunchConfiguration('laser_yaw'),
                'lidar_serial_port': LaunchConfiguration('lidar_serial_port'),
                'lidar_serial_baudrate': LaunchConfiguration('lidar_serial_baudrate'),
                'lidar_scan_mode': LaunchConfiguration('lidar_scan_mode'),
                'base_serial_port': LaunchConfiguration('base_serial_port'),
                'mqtt_broker_ip': LaunchConfiguration('mqtt_broker_ip'),
                'mqtt_port': LaunchConfiguration('mqtt_port'),
                'mqtt_topic': LaunchConfiguration('mqtt_topic'),
                'mqtt_yaw_in_degrees': LaunchConfiguration('mqtt_yaw_in_degrees'),
                'mqtt_yaw_offset': LaunchConfiguration('mqtt_yaw_offset'),
                'mqtt_linear_velocity_scale': LaunchConfiguration(
                    'mqtt_linear_velocity_scale'
                ),
                'mqtt_angular_velocity_scale': LaunchConfiguration(
                    'mqtt_angular_velocity_scale'
                ),
                'mqtt_data_timeout_sec': LaunchConfiguration('mqtt_data_timeout_sec'),
            }.items(),
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg_dir, 'launch', 'ekf.launch.py')
            ),
            launch_arguments={
                'ekf_params_file': os.path.join(pkg_dir, 'config', 'ekf.yaml'),
            }.items(),
        ),

        Node(
            package='hw_robot_nav',
            executable='scan_downsampler',
            name='scan_downsampler',
            output='screen',
            condition=IfCondition(use_scan_downsampler),
            parameters=[
                {
                    'input_scan_topic': LaunchConfiguration('raw_scan_topic'),
                    'output_scan_topic': scan_topic,
                    'max_beams': LaunchConfiguration('max_scan_beams'),
                },
            ],
        ),

        Node(
            package='slam_gmapping',
            executable='slam_gmapping',
            name='slam_gmapping',
            output='screen',
            parameters=[
                LaunchConfiguration('params_file'),
                {
                    'base_frame': base_frame,
                    'odom_frame': odom_frame,
                    'map_frame': map_frame,
                },
            ],
            remappings=[
                ('scan', scan_topic),
            ],
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(
                    get_package_share_directory('nav2_bringup'),
                    'launch',
                    'rviz_launch.py',
                )
            ),
            condition=IfCondition(use_rviz),
            launch_arguments={
                'namespace': '',
                'use_namespace': 'False',
                'rviz_config': LaunchConfiguration('rviz_config'),
            }.items(),
        ),
    ])
