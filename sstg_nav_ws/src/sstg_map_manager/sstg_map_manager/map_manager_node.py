"""
ROS2 Node for topological map management.
"""
import logging
import os
import yaml
from pathlib import Path

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, Pose

from sstg_msgs.srv import CreateNode, QuerySemantic, UpdateSemantic, GetNodePose, GetTopologicalMap
from sstg_msgs.msg import SemanticData

from .topological_map import TopologicalMap
from .topological_node import SemanticInfo, SemanticObject


logger = logging.getLogger(__name__)


class MapManagerNode(Node):
    """ROS2 Node for topological map management."""

    def __init__(self):
        super().__init__('map_manager_node')

        # Resolve package share directory (ROS2 standard) for maps/config
        try:
            from ament_index_python.packages import get_package_share_directory
            share_dir = get_package_share_directory('sstg_map_manager')
        except Exception:
            share_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Load config file to get defaults
        config_path = os.path.join(share_dir, 'config', 'map_config.yaml')
        cfg_defaults = {}
        cfg = {}
        if os.path.exists(config_path):
            import yaml
            with open(config_path, 'r') as f:
                cfg = yaml.safe_load(f) or {}
            cfg_defaults = cfg.get('general', {})

        # Declare parameters (config file values override hardcoded defaults)
        self.declare_parameter('maps_root', os.path.join(share_dir, 'maps'))
        self.declare_parameter('active_map', cfg_defaults.get('active_map', 'default'))
        self.declare_parameter('frame_id', cfg_defaults.get('frame_id', 'map'))
        self.declare_parameter('graph_type', cfg.get('network', {}).get('graph_type', 'DiGraph'))

        # Get parameters
        self.maps_root = self.get_parameter('maps_root').value
        self.active_map = self.get_parameter('active_map').value
        self.frame_id = self.get_parameter('frame_id').value
        self.graph_type = self.get_parameter('graph_type').value

        # Resolve map session paths
        self.session_dir = os.path.join(self.maps_root, self.active_map)
        self.map_file = os.path.join(self.session_dir, 'topological_map.json')
        self.capture_root = os.path.join(self.session_dir, 'captured_nodes')

        # Ensure directories exist
        os.makedirs(self.session_dir, exist_ok=True)
        os.makedirs(self.capture_root, exist_ok=True)
        
        # Initialize topological map
        self.topo_map = TopologicalMap(
            map_file=self.map_file,
            graph_type=self.graph_type
        )
        
        # Create ROS2 services
        self.create_service(
            CreateNode,
            'create_node',
            self._handle_create_node
        )
        
        self.create_service(
            QuerySemantic,
            'query_semantic',
            self._handle_query_semantic
        )
        
        self.create_service(
            UpdateSemantic,
            'update_semantic',
            self._handle_update_semantic
        )
        
        self.create_service(
            GetNodePose,
            'get_node_pose',
            self._handle_get_node_pose
        )

        self.create_service(
            GetTopologicalMap,
            'get_topological_map',
            self._handle_get_topological_map
        )
        
        # Create publisher for visualization
        self.marker_publisher = self.create_publisher(
            Pose,  # Simplified - would use MarkerArray in practice
            'topological_nodes',
            10
        )
        
        self.get_logger().info(
            f"Map Manager Node initialized. Session: {self.active_map}, "
            f"Map file: {self.map_file}, "
            f"Nodes: {self.topo_map.get_node_count()}"
        )
    
    def _handle_create_node(self, request: CreateNode.Request, 
                           response: CreateNode.Response) -> CreateNode.Response:
        """Handle create node service request."""
        try:
            pose = request.pose.pose
            node = self.topo_map.create_node(
                x=pose.position.x,
                y=pose.position.y,
                theta=0.0  # Extract from pose orientation if needed
            )
            
            response.node_id = node.node_id
            response.success = True
            response.message = f"Created node {node.node_id}"
            
            self.get_logger().info(f"Created node {node.node_id}")
            self.save_map()
            
        except Exception as e:
            response.success = False
            response.message = f"Error creating node: {str(e)}"
            self.get_logger().error(response.message)
        
        return response
    
    def _handle_query_semantic(self, request: QuerySemantic.Request,
                              response: QuerySemantic.Response) -> QuerySemantic.Response:
        """Handle query semantic service request. Returns matched angles per node."""
        try:
            query = request.query.strip()
            node_ids = []
            matched_angles = []

            if query.startswith('room_type:'):
                room_type = query.replace('room_type:', '')
                node_ids = self.topo_map.query_by_room_type(room_type)
                matched_angles = [-1] * len(node_ids)  # room_type is node-level
            elif query.startswith('object:'):
                object_name = query.replace('object:', '')
                results = self.topo_map.query_by_object_with_angles(object_name)
                for nid, angles in results:
                    node_ids.append(nid)
                    # Use first matching angle, or -1 if node-level only
                    matched_angles.append(angles[0] if angles else -1)

            # Convert nodes to semantic data
            semantic_data_list = []
            for node_id in node_ids:
                node = self.topo_map.get_node(node_id)
                if node and node.semantic_info:
                    sem_msg = SemanticData()
                    sem_msg.room_type = node.semantic_info.room_type
                    sem_msg.confidence = node.semantic_info.confidence
                    sem_msg.description = node.semantic_info.description
                    semantic_data_list.append(sem_msg)

            response.node_ids = node_ids
            response.semantics = semantic_data_list
            response.matched_angles = matched_angles
            response.success = True
            response.message = f"Found {len(node_ids)} matching nodes"

        except Exception as e:
            response.success = False
            response.message = f"Error querying semantic: {str(e)}"
            self.get_logger().error(response.message)

        return response
    
    def _handle_update_semantic(self, request: UpdateSemantic.Request,
                               response: UpdateSemantic.Response) -> UpdateSemantic.Response:
        """Handle update semantic service request. Supports per-viewpoint updates."""
        try:
            node_id = request.node_id
            sem_data = request.semantic_data
            angle = request.angle  # -1 = node-level, 0/90/180/270 = viewpoint-level

            # Convert ROS message to SemanticInfo
            objects = [
                SemanticObject(
                    name=obj.name,
                    name_cn=getattr(obj, 'name_cn', ''),
                    position=obj.position,
                    quantity=obj.quantity,
                    confidence=obj.confidence,
                    distance_hint=getattr(obj, 'distance_hint', 'unknown'),
                    salience=getattr(obj, 'salience', 0.5),
                    visibility=getattr(obj, 'visibility', 'unknown'),
                    image_region=getattr(obj, 'image_region', 'mixed'),
                )
                for obj in sem_data.objects
            ]

            semantic_info = SemanticInfo(
                room_type=sem_data.room_type,
                confidence=sem_data.confidence,
                objects=objects,
                description=sem_data.description
            )

            node = self.topo_map.get_node(node_id)
            if not node:
                response.success = False
                response.message = f"Node {node_id} not found"
                return response

            if angle >= 0:
                # Per-viewpoint update
                from .topological_node import Viewpoint
                if angle not in node.viewpoints:
                    node.viewpoints[angle] = Viewpoint(angle=angle)
                node.viewpoints[angle].semantic_info = semantic_info
                import time
                node.viewpoints[angle].capture_time = time.time()
                # Re-aggregate node-level semantic
                node.aggregate_semantic()
                # Ensure unique name after aggregation
                node.name = self.topo_map._unique_name(node.name, node_id)
                node.last_updated = time.time()
                response.message = f"Updated viewpoint {angle}° for node {node_id}, aggregated"
            else:
                # Node-level update (backward compat)
                success = self.topo_map.update_semantic(node_id, semantic_info)
                response.message = f"Updated semantic for node {node_id}" if success else "Update failed"

            response.success = True
            self.get_logger().info(response.message)
            self.save_map()

        except Exception as e:
            response.success = False
            response.message = f"Error updating semantic: {str(e)}"
            self.get_logger().error(response.message)

        return response
    
    def _handle_get_node_pose(self, request: GetNodePose.Request,
                             response: GetNodePose.Response) -> GetNodePose.Response:
        """Handle get node pose service request."""
        try:
            node_id = request.node_id
            node = self.topo_map.get_node(node_id)
            
            if node:
                response.pose.header.frame_id = self.frame_id
                response.pose.header.stamp = self.get_clock().now().to_msg()
                response.pose.pose.position.x = node.x
                response.pose.pose.position.y = node.y
                response.pose.pose.position.z = 0.0
                
                # Set orientation based on theta (simplified)
                response.pose.pose.orientation.z = node.theta
                response.pose.pose.orientation.w = 1.0
                
                response.success = True
                response.message = f"Found node {node_id}"
            else:
                response.success = False
                response.message = f"Node {node_id} not found"
            
        except Exception as e:
            response.success = False
            response.message = f"Error getting node pose: {str(e)}"
            self.get_logger().error(response.message)
        
        return response
    
    def save_map(self):
        """Save current map to file."""
        success = self.topo_map.save_to_file()
        if success:
            self.get_logger().info("Map saved successfully")
        else:
            self.get_logger().error("Failed to save map")
        return success

    def _handle_get_topological_map(self, request: GetTopologicalMap.Request,
                                    response: GetTopologicalMap.Response) -> GetTopologicalMap.Response:
        """Handle get topological map service request."""
        try:
            import json
            topology_dict = self.topo_map.to_dict()
            response.topology_json = json.dumps(topology_dict, ensure_ascii=False)
            response.success = True
            node_count = topology_dict.get('metadata', {}).get('node_count', len(topology_dict.get('nodes', [])))
            response.message = f"Retrieved {node_count} nodes"
            self.get_logger().info(f"Returned topological map with {node_count} nodes")
        except Exception as e:
            response.success = False
            response.message = f"Error getting topological map: {str(e)}"
            response.topology_json = "{}"
            self.get_logger().error(response.message)

        return response


def main(args=None):
    rclpy.init(args=args)
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    node = MapManagerNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Shutting down...")
        node.save_map()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
