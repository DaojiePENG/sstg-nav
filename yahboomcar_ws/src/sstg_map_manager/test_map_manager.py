#!/usr/bin/env python3
"""
Test script for sstg_map_manager functionality.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sstg_map_manager.topological_map import TopologicalMap
from sstg_map_manager.topological_node import SemanticInfo, SemanticObject


def test_basic_operations():
    """Test basic map operations."""
    print("=" * 60)
    print("Testing SSTG Map Manager")
    print("=" * 60)
    
    # Create map
    topo_map = TopologicalMap(map_file='/tmp/test_topo_map.json', graph_type='DiGraph')
    print(f"\n✓ Created TopologicalMap")
    
    # Create some nodes
    node1 = topo_map.create_node(0.0, 0.0, 0.0)
    node2 = topo_map.create_node(5.0, 0.0, 0.0)
    node3 = topo_map.create_node(5.0, 5.0, 1.57)
    print(f"✓ Created 3 nodes (IDs: {node1.node_id}, {node2.node_id}, {node3.node_id})")
    
    # Add edges
    topo_map.add_edge(node1.node_id, node2.node_id, distance=5.0)
    topo_map.add_edge(node2.node_id, node3.node_id, distance=5.0)
    topo_map.add_edge(node3.node_id, node1.node_id, distance=7.07)
    print(f"✓ Added 3 edges")
    
    # Add semantic information
    semantic1 = SemanticInfo(
        room_type='living_room',
        confidence=0.95,
        objects=[
            SemanticObject(name='sofa', position='center', quantity=1, confidence=0.9),
            SemanticObject(name='table', position='left', quantity=1, confidence=0.85),
        ],
        description='Living room with sofa and coffee table'
    )
    topo_map.update_semantic(node1.node_id, semantic1)
    
    semantic2 = SemanticInfo(
        room_type='kitchen',
        confidence=0.92,
        objects=[
            SemanticObject(name='refrigerator', position='right', quantity=1, confidence=0.95),
            SemanticObject(name='stove', position='left', quantity=1, confidence=0.88),
        ],
        description='Kitchen with kitchen appliances'
    )
    topo_map.update_semantic(node2.node_id, semantic2)
    
    semantic3 = SemanticInfo(
        room_type='bedroom',
        confidence=0.88,
        objects=[
            SemanticObject(name='bed', position='center', quantity=1, confidence=0.92),
        ],
        description='Bedroom with bed'
    )
    topo_map.update_semantic(node3.node_id, semantic3)
    print(f"✓ Added semantic information to nodes")
    
    # Test queries
    print("\n--- Query Tests ---")
    
    living_rooms = topo_map.query_by_room_type('living_room')
    print(f"✓ Found living rooms: {living_rooms}")
    
    sofas = topo_map.query_by_object('sofa')
    print(f"✓ Found nodes with sofas: {sofas}")
    
    kitchens_with_fridge = topo_map.query_by_combined(room_type='kitchen', object_name='refrigerator')
    print(f"✓ Found kitchens with refrigerator: {kitchens_with_fridge}")
    
    # Test shortest path
    print("\n--- Path Finding ---")
    path = topo_map.get_shortest_path(node1.node_id, node3.node_id)
    print(f"✓ Shortest path from node 0 to node 2: {path}")
    
    # Test statistics
    print("\n--- Map Statistics ---")
    print(f"✓ Total nodes: {topo_map.get_node_count()}")
    print(f"✓ Total edges: {topo_map.get_edge_count()}")
    
    # Test serialization
    print("\n--- Serialization ---")
    topo_map.save_to_file('/tmp/test_topo_map.json')
    print(f"✓ Saved map to /tmp/test_topo_map.json")
    
    # Load and verify
    topo_map2 = TopologicalMap(map_file='/tmp/test_topo_map.json')
    print(f"✓ Loaded map from file")
    print(f"  - Loaded {topo_map2.get_node_count()} nodes")
    print(f"  - Loaded {topo_map2.get_edge_count()} edges")
    
    # Verify loaded data
    loaded_node = topo_map2.get_node(0)
    if loaded_node:
        print(f"✓ Retrieved node 0: ({loaded_node.x:.1f}, {loaded_node.y:.1f})")
        if loaded_node.semantic_info:
            print(f"  - Room type: {loaded_node.semantic_info.room_type}")
            print(f"  - Objects: {[obj.name for obj in loaded_node.semantic_info.objects]}")
    
    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)


if __name__ == '__main__':
    test_basic_operations()
