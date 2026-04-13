"""
SSTG 统一后端 Launch 文件
启动所有 SSTG 系统节点 + rosbridge_websocket

启动顺序:
  T=0s: rosbridge_websocket (port 9090) + map_manager_node
  T=2s: nlp_node, planning_node, executor_node, perception_node
  T=5s: interaction_manager_node (等待上游服务就绪)

用法:
  ros2 launch sstg_interaction_manager sstg_full.launch.py
"""

from launch import LaunchDescription
from launch.actions import TimerAction, LogInfo
from launch_ros.actions import Node


def generate_launch_description():

    # --- T=0s: 基础设施 ---

    rosbridge = Node(
        package='rosbridge_server',
        executable='rosbridge_websocket',
        name='rosbridge_websocket',
        parameters=[{
            'port': 9090,
            'address': '',
            'retry_startup_delay': 5.0,
        }],
        output='screen',
    )

    map_manager = Node(
        package='sstg_map_manager',
        executable='map_manager_node',
        name='map_manager_node',
        output='screen',
    )

    system_manager = Node(
        package='sstg_system_manager',
        executable='system_manager_node',
        name='system_manager_node',
        output='screen',
    )

    # --- T=2s: 核心服务节点 ---

    nlp_node = Node(
        package='sstg_nlp_interface',
        executable='nlp_node',
        name='nlp_node',
        output='screen',
    )

    planning_node = Node(
        package='sstg_navigation_planner',
        executable='planning_node',
        name='planning_node',
        output='screen',
    )

    executor_node = Node(
        package='sstg_navigation_executor',
        executable='executor_node',
        name='executor_node',
        output='screen',
    )

    perception_node = Node(
        package='sstg_perception',
        executable='perception_node',
        name='perception_node',
        output='screen',
    )

    exploration_action_server = Node(
        package='sstg_rrt_explorer',
        executable='exploration_action_server.py',
        name='exploration_action_server',
        output='screen',
    )

    webrtc_camera_bridge = Node(
        package='sstg_system_manager',
        executable='webrtc_camera_bridge',
        name='webrtc_camera_bridge',
        output='screen',
    )

    # --- T=5s: 编排层 ---

    interaction_manager = Node(
        package='sstg_interaction_manager',
        executable='interaction_manager_node',
        name='interaction_manager_node',
        output='screen',
    )

    return LaunchDescription([
        # T=0s: rosbridge + map_manager + system_manager 立即启动
        LogInfo(msg='[SSTG] Starting rosbridge_websocket + map_manager + system_manager...'),
        rosbridge,
        map_manager,
        system_manager,

        # T=2s: 核心服务节点
        TimerAction(
            period=2.0,
            actions=[
                LogInfo(msg='[SSTG] Starting NLP, Planner, Executor, Perception...'),
                nlp_node,
                planning_node,
                executor_node,
                perception_node,
                exploration_action_server,
                webrtc_camera_bridge,
            ],
        ),

        # T=5s: 编排中心 (等待上游服务注册)
        TimerAction(
            period=5.0,
            actions=[
                LogInfo(msg='[SSTG] Starting InteractionManager...'),
                interaction_manager,
            ],
        ),
    ])
