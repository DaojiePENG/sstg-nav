from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """Generate launch description for SSTG Map Manager."""
    
    map_manager_node = Node(
        package='sstg_map_manager',
        executable='map_manager_node',
        name='map_manager_node',
        output='screen',
        parameters=[
            {'map_file': '/tmp/topological_map.json'},
            {'frame_id': 'map'},
        ]
    )
    
    webui_node = Node(
        package='sstg_map_manager',
        executable='map_webui',
        name='map_webui_node',
        output='screen',
        parameters=[
            {'host': '0.0.0.0'},
            {'port': 8000},
        ]
    )
    
    ld = LaunchDescription()
    ld.add_action(map_manager_node)
    ld.add_action(webui_node)
    
    return ld
