"""
SSTG Perception Node - ROS2 Launch File
仅启动 perception_node，不重复启动相机驱动
"""

import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.substitutions import LaunchConfiguration
from launch.actions import DeclareLaunchArgument

import os

DEFAULT_PANORAMA_STORAGE_PATH = (
    os.path.expanduser('~/wbt_ws/sstg-nav/sstg_nav_ws/src/')
    + 'sstg_rrt_explorer/captured_nodes'
)


def generate_launch_description():
    """生成启动配置"""
    
    # ======================== Perception 参数声明 ========================
    declare_panorama_path = DeclareLaunchArgument(
        'panorama_storage_path',
        default_value=DEFAULT_PANORAMA_STORAGE_PATH,
        description='Path to store panorama images'
    )
    
    declare_confidence_threshold = DeclareLaunchArgument(
        'confidence_threshold',
        default_value='0.5',
        description='Semantic confidence threshold'
    )
    
    # ======================== Perception Node ========================
    perception_node = Node(
        package='sstg_perception',
        executable='perception_node',
        name='perception_node',
        output='screen',
        parameters=[
            {
                'api_base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                'api_key': os.getenv('DASHSCOPE_API_KEY', 'sk-942e8661f10f492280744a26fe7b953b'),
                'vlm_model': 'qwen-vl-plus',
                'panorama_storage_path': LaunchConfiguration('panorama_storage_path'),
                'rgb_topic': '/camera/color/image_raw',
                'depth_topic': '/camera/depth/image_raw',
                'confidence_threshold': LaunchConfiguration('confidence_threshold'),
                'max_retries': 3,
            }
        ]
    )
    
    # ======================== 组装启动项 ========================
    ld = LaunchDescription()
    
    # Perception 参数
    ld.add_action(declare_panorama_path)
    ld.add_action(declare_confidence_threshold)
    
    # 启动 Perception 节点
    ld.add_action(perception_node)
    
    return ld
