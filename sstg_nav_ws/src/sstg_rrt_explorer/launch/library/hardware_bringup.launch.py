"""
hardware_bringup.launch.py - Yahboom X3 麦轮车硬件启动

启动内容：
  - Mcnamu_driver_X3   底盘电机驱动
  - base_node_X3       里程计 + IMU 原始数据
  - imu_filter_madgwick  IMU 滤波
  - robot_localization (EKF)  融合里程计 + IMU
  - sllidar_node       RPLidar A1 雷达
  - robot_state_publisher  URDF TF 树
  - base_link → laser 静态 TF

注意：
  Yahboom 出厂默认桌面自启动 rosmaster_main.py（手机/Web 遥控模式），
  它与 ROS2 的 Mcnamu_driver_X3 共用底盘串口 /dev/myserial，
  两者属于互斥的使用模式，不能同时运行。
  本 launch 启动时会自动检测并停掉 rosmaster_main.py 以切换到 ROS2 模式。

前提：
  source /opt/ros/humble/setup.bash
  source ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash
  source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
"""

import os
import subprocess
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, LogInfo, TimerAction
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory, get_package_share_path


def generate_launch_description():
    # ── 切换到 ROS2 模式：停掉 Yahboom 遥控主程序（如果在运行） ──
    try:
        result = subprocess.run(
            ['pkill', '-f', 'rosmaster_main.py'],
            capture_output=True, timeout=3,
        )
        if result.returncode == 0:
            import time
            time.sleep(1)  # 等待串口释放
            print('[hardware_bringup] 已停掉 rosmaster_main.py，切换到 ROS2 模式')
        else:
            print('[hardware_bringup] rosmaster_main.py 未运行，直接进入 ROS2 模式')
    except Exception as e:
        print(f'[hardware_bringup] 检测 rosmaster_main.py 时出错: {e}')

    # ── URDF ──
    urdf_path = get_package_share_path('yahboomcar_description')
    default_model = str(urdf_path / 'urdf/yahboomcar_X3.urdf')

    model_arg = DeclareLaunchArgument('model', default_value=default_model)

    robot_description = ParameterValue(
        Command(['xacro ', LaunchConfiguration('model')]), value_type=str)

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{'robot_description': robot_description}],
    )

    joint_state_publisher = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
    )

    # ── 底盘驱动 ──
    driver_node = Node(
        package='yahboomcar_bringup',
        executable='Mcnamu_driver_X3',
    )

    base_node = Node(
        package='yahboomcar_base_node',
        executable='base_node_X3',
        # 参数与 Yahboom 官方 yahboomcar_bringup_X3_launch.py 保持一致
        # 当使用 EKF 融合时，odom→base_footprint TF 由 EKF 发布
        parameters=[{
            'pub_odom_tf': False,
            'linear_scale_x': 1.0,
            'linear_scale_y': 1.0,
            'angular_scale': 1.0,
        }],
    )

    # ── IMU 滤波 ──
    imu_filter_config = os.path.join(
        get_package_share_directory('yahboomcar_bringup'),
        'param', 'imu_filter_param.yaml')

    imu_filter = Node(
        package='imu_filter_madgwick',
        executable='imu_filter_madgwick_node',
        parameters=[imu_filter_config],
    )

    # ── EKF 融合 ──
    ekf_config = os.path.join(
        get_package_share_directory('sstg_rrt_explorer'),
        'param', 'common', 'ekf_x3_override.yaml')

    ekf_node = Node(
        package='robot_localization',
        executable='ekf_node',
        name='ekf_filter_node',
        output='screen',
        parameters=[ekf_config],
        remappings=[('/odometry/filtered', '/odom')],
    )

    # ── 雷达 (RPLidar S2) ──
    lidar_node = Node(
        package='sllidar_ros2',
        executable='sllidar_node',
        name='sllidar_node',
        parameters=[{
            'channel_type': 'serial',
            'serial_port': '/dev/rplidar',
            'serial_baudrate': 1000000,
            'frame_id': 'laser',
            'inverted': False,
            'angle_compensate': True,
        }],
        output='screen',
    )

    # ── base_link → laser 静态 TF ──
    tf_base_to_laser = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        arguments=[
            '0.0435', '5.258E-05', '0.11',
            '3.14', '0', '0',
            'base_link', 'laser',
        ],
    )

    return LaunchDescription([
        model_arg,
        robot_state_publisher,
        joint_state_publisher,
        driver_node,
        base_node,
        imu_filter,
        ekf_node,
        lidar_node,
        tf_base_to_laser,
    ])
