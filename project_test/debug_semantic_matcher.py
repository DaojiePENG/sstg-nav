#!/usr/bin/env python3
"""
Test semantic matcher directly
"""

import sys
import os
sys.path.append('/home/daojie/yahboomcar_ros2_ws/yahboomcar_ws/install/sstg_navigation_planner/lib/python3.10/site-packages')

from sstg_navigation_planner.semantic_matcher import SemanticMatcher

def test_semantic_matcher():
    """Test the semantic matcher with mock data"""

    # Mock topological data (same as in planning_node.py)
    topological_nodes = {
        0: {
            'name': '客厅',
            'room_type': 'living_room',
            'pose': {'x': 0.0, 'y': 0.0, 'z': 0.0},
            'semantic_tags': ['sofa', 'TV', 'comfortable'],
            'connections': [1, 2],
            'accessible': True
        },
        1: {
            'name': '卧室',
            'room_type': 'bedroom',
            'pose': {'x': 5.0, 'y': 0.0, 'z': 0.0},
            'semantic_tags': ['bed', 'quiet', 'rest'],
            'connections': [0, 2],
            'accessible': True
        },
        2: {
            'name': '厨房',
            'room_type': 'kitchen',
            'pose': {'x': 0.0, 'y': 5.0, 'z': 0.0},
            'semantic_tags': ['cooker', 'sink', 'refrigerator'],
            'connections': [0, 1],
            'accessible': True
        }
    }

    matcher = SemanticMatcher()
    matcher.set_logger(print)

    print("Testing semantic matcher...")
    print(f"Available nodes: {list(topological_nodes.keys())}")
    print(f"Room types: {[n['room_type'] for n in topological_nodes.values()]}")

    # Test with Chinese "客厅" (living room)
    entities = ["客厅"]
    intent = "navigate_to"
    confidence = 0.95

    print(f"\nTesting with intent='{intent}', entities={entities}")

    matches = matcher.match_query_to_nodes(
        intent=intent,
        entities=entities,
        confidence=confidence,
        topological_nodes=topological_nodes
    )

    print(f"Found {len(matches)} matches:")
    for match in matches:
        print(f"  - Node {match.node_id}: {match.node_name} ({match.room_type}) - score: {match.match_score}")
        print(f"    Reason: {match.match_reason}")

    # Also test with "living_room" directly
    print(f"\nTesting with entities=['living_room']")
    matches2 = matcher.match_query_to_nodes(
        intent=intent,
        entities=["living_room"],
        confidence=confidence,
        topological_nodes=topological_nodes
    )

    print(f"Found {len(matches2)} matches:")
    for match in matches2:
        print(f"  - Node {match.node_id}: {match.node_name} ({match.room_type}) - score: {match.match_score}")
        print(f"    Reason: {match.match_reason}")

if __name__ == "__main__":
    test_semantic_matcher()