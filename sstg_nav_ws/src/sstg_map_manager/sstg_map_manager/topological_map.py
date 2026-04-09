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
            name=f"拓扑点{node_id}",
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
        if not node.name or node.name.startswith('拓扑点'):
            node.name = semantic_info.room_type_cn or node.name
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
        room_type_lower = room_type.strip().lower()
        for node_id, node in self.nodes_dict.items():
            if not node.semantic_info:
                continue

            semantic = node.semantic_info
            candidates = [semantic.room_type, semantic.room_type_cn, *semantic.aliases]
            for candidate in candidates:
                candidate_lower = candidate.lower()
                if room_type_lower in candidate_lower or candidate_lower in room_type_lower:
                    matching_nodes.append(node_id)
                    break
        
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
        object_lower = object_name.strip().lower()
        for node_id, node in self.nodes_dict.items():
            if node.semantic_info:
                for obj in node.semantic_info.objects:
                    names = [obj.name, obj.name_cn]
                    if any(
                        object_lower in name.lower() or name.lower() in object_lower
                        for name in names if name
                    ):
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
            if room_type and node_id not in self.query_by_room_type(room_type):
                continue
            
            # Check object
            if object_name:
                if node_id not in self.query_by_object(object_name):
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
            data = self.to_dict()
            
            Path(target_file).parent.mkdir(parents=True, exist_ok=True)
            with open(target_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
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
            with open(target_file, 'r', encoding='utf-8') as f:
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
                from_id = edge_data.get('from', edge_data.get('source'))
                to_id = edge_data.get('to', edge_data.get('target'))
                if from_id is None or to_id is None:
                    continue
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
            'nodes': [
                node.to_dict() for node in sorted(
                    self.nodes_dict.values(), key=lambda item: item.node_id)
            ],
            'edges': [
                {
                    'source': u,
                    'target': v,
                    'weight': self.graph[u][v].get('weight', 0.0),
                }
                for u, v in self.graph.edges()
            ],
            'metadata': {
                'graph_type': self.graph_type,
                'node_count': self.get_node_count(),
                'edge_count': self.get_edge_count(),
            }
        }
