"""
Topological Map management using NetworkX.
"""
import json
import logging
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import networkx as nx
import time
from .topological_node import TopologicalNode, SemanticInfo


logger = logging.getLogger(__name__)


class TopologicalMap:
    """Manages topological graph using NetworkX."""
    
    def __init__(self, map_file: str = None, graph_type: str = 'DiGraph'):
        """
        Initialize topological map.
        
        Args:
            map_file: Path to save/load map JSON
            graph_type: 'DiGraph' or 'Graph'
        """
        self.map_file = map_file
        self.graph_type = graph_type
        
        # Initialize NetworkX graph
        if graph_type == 'DiGraph':
            self.graph = nx.DiGraph()
        else:
            self.graph = nx.Graph()
        
        self.nodes_dict: Dict[int, TopologicalNode] = {}
        self.next_node_id = 0
        
        # Load existing map if file exists
        if map_file and Path(map_file).exists():
            self.load_from_file(map_file)
    
    def create_node(self, x: float, y: float, theta: float) -> TopologicalNode:
        """
        Create and add a new topological node.
        
        Args:
            x, y: Position coordinates
            theta: Orientation angle
            
        Returns:
            Created TopologicalNode
        """
        node_id = self.next_node_id
        self.next_node_id += 1
        
        node = TopologicalNode(
            node_id=node_id,
            x=x,
            y=y,
            theta=theta,
            created_time=time.time(),
            last_updated=time.time(),
        )
        
        self.nodes_dict[node_id] = node
        self.graph.add_node(node_id, data=node)
        
        logger.info(f"Created topological node {node_id} at ({x:.2f}, {y:.2f}, {theta:.2f})")
        return node
    
    def delete_node(self, node_id: int) -> bool:
        """Delete a node and all its edges."""
        if node_id not in self.nodes_dict:
            logger.warning(f"Node {node_id} not found")
            return False
        
        self.graph.remove_node(node_id)
        del self.nodes_dict[node_id]
        
        logger.info(f"Deleted topological node {node_id}")
        return True
    
    def get_node(self, node_id: int) -> Optional[TopologicalNode]:
        """Get a node by ID."""
        return self.nodes_dict.get(node_id)
    
    def add_edge(self, from_id: int, to_id: int, distance: float = 0.0) -> bool:
        """
        Add an edge between two nodes.
        
        Args:
            from_id, to_id: Node IDs
            distance: Euclidean distance between nodes
            
        Returns:
            True if successful
        """
        if from_id not in self.nodes_dict or to_id not in self.nodes_dict:
            logger.warning(f"One or both nodes not found: {from_id}, {to_id}")
            return False
        
        self.graph.add_edge(from_id, to_id, weight=distance)
        logger.info(f"Added edge from node {from_id} to node {to_id}")
        return True
    
    def remove_edge(self, from_id: int, to_id: int) -> bool:
        """Remove an edge between two nodes."""
        if self.graph.has_edge(from_id, to_id):
            self.graph.remove_edge(from_id, to_id)
            logger.info(f"Removed edge from node {from_id} to node {to_id}")
            return True
        
        logger.warning(f"Edge not found: {from_id} -> {to_id}")
        return False
    
    def update_semantic(self, node_id: int, semantic_info: SemanticInfo) -> bool:
        """Update semantic information for a node."""
        if node_id not in self.nodes_dict:
            logger.warning(f"Node {node_id} not found")
            return False
        
        node = self.nodes_dict[node_id]
        node.semantic_info = semantic_info
        node.last_updated = time.time()
        
        logger.info(f"Updated semantic info for node {node_id}: {semantic_info.room_type}")
        return True
    
    def add_panorama_image(self, node_id: int, angle: str, image_path: str) -> bool:
        """Add panorama image path for a specific angle."""
        if node_id not in self.nodes_dict:
            logger.warning(f"Node {node_id} not found")
            return False
        
        node = self.nodes_dict[node_id]
        node.panorama_paths[angle] = image_path
        node.last_updated = time.time()
        
        logger.info(f"Added panorama image for node {node_id} at angle {angle}")
        return True
    
    def query_by_room_type(self, room_type: str) -> List[int]:
        """
        Query nodes by room type.
        
        Args:
            room_type: Target room type (e.g., 'living_room')
            
        Returns:
            List of node IDs matching the room type
        """
        matching_nodes = []
        for node_id, node in self.nodes_dict.items():
            if node.semantic_info and node.semantic_info.room_type == room_type:
                matching_nodes.append(node_id)
        
        return matching_nodes
    
    def query_by_object(self, object_name: str) -> List[int]:
        """
        Query nodes containing a specific object.
        
        Args:
            object_name: Target object name
            
        Returns:
            List of node IDs containing the object
        """
        matching_nodes = []
        for node_id, node in self.nodes_dict.items():
            if node.semantic_info:
                for obj in node.semantic_info.objects:
                    if obj.name.lower() == object_name.lower():
                        matching_nodes.append(node_id)
                        break
        
        return matching_nodes
    
    def query_by_combined(self, room_type: Optional[str] = None, 
                         object_name: Optional[str] = None) -> List[int]:
        """
        Query nodes by combined criteria.
        
        Args:
            room_type: Optional room type filter
            object_name: Optional object name filter
            
        Returns:
            List of node IDs matching all criteria
        """
        matching_nodes = []
        
        for node_id, node in self.nodes_dict.items():
            if not node.semantic_info:
                continue
            
            # Check room type
            if room_type and node.semantic_info.room_type != room_type:
                continue
            
            # Check object
            if object_name:
                found_object = False
                for obj in node.semantic_info.objects:
                    if obj.name.lower() == object_name.lower():
                        found_object = True
                        break
                if not found_object:
                    continue
            
            matching_nodes.append(node_id)
        
        return matching_nodes
    
    def get_shortest_path(self, from_id: int, to_id: int) -> Optional[List[int]]:
        """
        Get shortest path between two nodes.
        
        Args:
            from_id, to_id: Node IDs
            
        Returns:
            List of node IDs representing the path
        """
        try:
            path = nx.shortest_path(self.graph, from_id, to_id)
            return path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            logger.warning(f"No path found from {from_id} to {to_id}")
            return None
    
    def get_all_nodes(self) -> List[TopologicalNode]:
        """Get all nodes."""
        return list(self.nodes_dict.values())
    
    def get_node_count(self) -> int:
        """Get total number of nodes."""
        return len(self.nodes_dict)
    
    def get_edge_count(self) -> int:
        """Get total number of edges."""
        return self.graph.number_of_edges()
    
    def save_to_file(self, file_path: str = None) -> bool:
        """
        Save topological map to JSON file.
        
        Args:
            file_path: Path to save file (uses self.map_file if None)
            
        Returns:
            True if successful
        """
        target_file = file_path or self.map_file
        if not target_file:
            logger.error("No map file path specified")
            return False
        
        try:
            data = {
                'nodes': [node.to_dict() for node in self.nodes_dict.values()],
                'edges': [
                    {'from': u, 'to': v, 'weight': self.graph[u][v].get('weight', 0.0)}
                    for u, v in self.graph.edges()
                ],
            }
            
            Path(target_file).parent.mkdir(parents=True, exist_ok=True)
            with open(target_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Saved topological map to {target_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save map: {e}")
            return False
    
    def load_from_file(self, file_path: str = None) -> bool:
        """
        Load topological map from JSON file.
        
        Args:
            file_path: Path to load file (uses self.map_file if None)
            
        Returns:
            True if successful
        """
        target_file = file_path or self.map_file
        if not target_file or not Path(target_file).exists():
            logger.warning(f"Map file not found: {target_file}")
            return False
        
        try:
            with open(target_file, 'r') as f:
                data = json.load(f)
            
            # Clear existing data
            self.graph.clear()
            self.nodes_dict.clear()
            
            # Load nodes
            max_id = -1
            for node_data in data.get('nodes', []):
                node = TopologicalNode.from_dict(node_data)
                self.nodes_dict[node.node_id] = node
                self.graph.add_node(node.node_id, data=node)
                max_id = max(max_id, node.node_id)
            
            self.next_node_id = max_id + 1
            
            # Load edges
            for edge_data in data.get('edges', []):
                from_id = edge_data['from']
                to_id = edge_data['to']
                weight = edge_data.get('weight', 0.0)
                self.graph.add_edge(from_id, to_id, weight=weight)
            
            logger.info(f"Loaded topological map from {target_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to load map: {e}")
            return False
    
    def to_dict(self) -> Dict:
        """Convert map to dictionary representation."""
        return {
            'nodes': [node.to_dict() for node in self.nodes_dict.values()],
            'edges': [
                {'from': u, 'to': v, 'weight': self.graph[u][v].get('weight', 0.0)}
                for u, v in self.graph.edges()
            ],
            'metadata': {
                'graph_type': self.graph_type,
                'node_count': self.get_node_count(),
                'edge_count': self.get_edge_count(),
            }
        }
