"""
slam_toolbox_localization.launch.py - AMCL 定位 + map_server

架构：
  - AMCL: 粒子滤波定位 → map→odom TF
  - map_server: 加载 PGM 地图 → /map（给 Nav2 global_costmap + AMCL）
  - lifecycle_manager: 管理 map_server + amcl 生命周期

用法：
  ros2 launch sstg_rrt_explorer slam_toolbox_localization.launch.py

  # 指定地图：
  ros2 launch sstg_rrt_explorer slam_toolbox_localization.launch.py \\
    map_yaml:=/path/to/map.yaml

注意：
  之前使用 slam_toolbox localization 模式，但在 MaxTang (AMD GPU) 上
  slam_toolbox 2.6.10 存在内部死锁 bug（Ceres solver 阻塞 TF 更新），
  改用 Nav2 AMCL 粒子滤波定位，更轻量稳定。
  RViz 2D Pose Estimate 可正常使用（AMCL 原生支持）。
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_dir = get_package_share_directory('sstg_rrt_explorer')
    default_map_yaml = os.path.join(pkg_dir, 'maps', '20260402_083419.yaml')

    map_yaml_arg = DeclareLaunchArgument('map_yaml', default_value=default_map_yaml)

    # ── AMCL 粒子滤波定位 ──
    amcl_node = Node(
        package='nav2_amcl',
        executable='amcl',
        name='amcl',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            # ── 坐标系 ──
            'base_frame_id': 'base_footprint',
            'odom_frame_id': 'odom',
            'global_frame_id': 'map',
            # ── 激光参数 ──
            'scan_topic': '/scan',
            'laser_model_type': 'likelihood_field',
            'max_beams': 90,
            'laser_max_range': 12.0,
            'laser_min_range': 0.1,
            # ── 粒子滤波参数 ──
            'min_particles': 500,
            'max_particles': 3000,
            # ── 运动模型（差速/全向） ──
            'robot_model_type': 'nav2_amcl::OmniMotionModel',
            'alpha1': 0.3,   # 旋转→旋转噪声（麦轮旋转打滑较大）
            'alpha2': 0.3,   # 平移→旋转噪声
            'alpha3': 0.3,   # 平移→平移噪声
            'alpha4': 0.3,   # 旋转→平移噪声
            'alpha5': 0.2,   # 侧向平移噪声（全向）
            # ── 更新阈值 ──
            'update_min_d': 0.05,   # 移动 0.05m 即更新（更灵敏）
            'update_min_a': 0.1,    # 旋转 0.1rad 即更新
            'resample_interval': 1,
            # ── 初始位姿（地图原点附近） ──
            'set_initial_pose': True,
            'initial_pose.x': 0.0,
            'initial_pose.y': 0.0,
            'initial_pose.z': 0.0,
            'initial_pose.yaw': 0.0,
            # ── 似然场参数 ──
            'z_hit': 0.7,
            'z_rand': 0.3,
            'sigma_hit': 0.1,
            'laser_likelihood_max_dist': 2.0,
            # ── TF ──
            'tf_broadcast': True,
            'transform_tolerance': 0.5,
        }],
    )

    # ── map_server: 加载预建 PGM 地图 → /map ──
    map_server_node = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'yaml_filename': LaunchConfiguration('map_yaml'),
        }],
    )

    # ── lifecycle_manager: 管理 map_server + amcl ──
    lifecycle_manager = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_map',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'autostart': True,
            'node_names': ['map_server', 'amcl'],
        }],
    )

    return LaunchDescription([
        map_yaml_arg,
        amcl_node,
        map_server_node,
        lifecycle_manager,
    ])
