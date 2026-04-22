#!/usr/bin/env python3
"""
orbbec_stable.launch.py - 更稳的 Gemini 330 启动配置

目标：
  - 降低相机驱动内存占用
  - 避免默认高负载配置导致的 frame buffer 分配失败
  - 为拓扑采集提供稳定的 RGB/Depth 话题
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    orbbec_share = get_package_share_directory('orbbec_camera')
    stable_launch = os.path.join(
        orbbec_share,
        'launch',
        'gemini_330_series_low_cpu.launch.py',
    )

    camera = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(stable_launch),
        launch_arguments={
            'camera_name': 'camera',
            'uvc_backend': 'v4l2',
            'enable_point_cloud': 'false',
            'enable_colored_point_cloud': 'false',
            'enable_left_ir': 'false',
            'enable_right_ir': 'false',
            'enable_accel': 'false',
            'enable_gyro': 'false',
            'color_width': '640',
            'color_height': '480',
            'color_fps': '15',
            'depth_width': '640',
            'depth_height': '480',
            'depth_fps': '15',
            'enable_hardware_noise_removal_filter': 'true',
            'enable_noise_removal_filter': 'false',
            'diagnostic_period': '1.0',
        }.items(),
    )

    return LaunchDescription([camera])
