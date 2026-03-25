#!/usr/bin/env python3
"""
Initialize test topological map for SSTG system testing
"""

import json
import time
from pathlib import Path

def create_test_map():
    """Create a test topological map with semantic information"""

    # Test map data with semantic information
    test_map = {
        "nodes": [
            {
                "id": 0,
                "pose": {
                    "x": 0.0,
                    "y": 0.0,
                    "theta": 0.0
                },
                "panorama_paths": {},
                "semantic_info": {
                    "room_type": "living_room",
                    "confidence": 0.9,
                    "objects": [
                        {"name": "sofa", "position": "center", "quantity": 1, "confidence": 0.8},
                        {"name": "tv", "position": "north_wall", "quantity": 1, "confidence": 0.9},
                        {"name": "table", "position": "center", "quantity": 1, "confidence": 0.7}
                    ],
                    "description": "主客厅区域，包含沙发、电视和桌子"
                },
                "created_time": time.time(),
                "last_updated": time.time()
            },
            {
                "id": 1,
                "pose": {
                    "x": 3.0,
                    "y": 0.0,
                    "theta": 0.0
                },
                "panorama_paths": {},
                "semantic_info": {
                    "room_type": "kitchen",
                    "confidence": 0.95,
                    "objects": [
                        {"name": "stove", "position": "east_wall", "quantity": 1, "confidence": 0.9},
                        {"name": "fridge", "position": "north_wall", "quantity": 1, "confidence": 0.95},
                        {"name": "table", "position": "center", "quantity": 1, "confidence": 0.8}
                    ],
                    "description": "厨房区域，包含炉灶、冰箱和餐桌"
                },
                "created_time": time.time(),
                "last_updated": time.time()
            },
            {
                "id": 2,
                "pose": {
                    "x": 0.0,
                    "y": 3.0,
                    "theta": 1.57
                },
                "panorama_paths": {},
                "semantic_info": {
                    "room_type": "bedroom",
                    "confidence": 0.9,
                    "objects": [
                        {"name": "bed", "position": "center", "quantity": 1, "confidence": 0.95},
                        {"name": "wardrobe", "position": "west_wall", "quantity": 1, "confidence": 0.8},
                        {"name": "desk", "position": "south_wall", "quantity": 1, "confidence": 0.7}
                    ],
                    "description": "卧室区域，包含床、衣柜和书桌"
                },
                "created_time": time.time(),
                "last_updated": time.time()
            },
            {
                "id": 3,
                "pose": {
                    "x": -2.0,
                    "y": 1.0,
                    "theta": -0.78
                },
                "panorama_paths": {},
                "semantic_info": {
                    "room_type": "bathroom",
                    "confidence": 0.85,
                    "objects": [
                        {"name": "toilet", "position": "north_wall", "quantity": 1, "confidence": 0.9},
                        {"name": "sink", "position": "east_wall", "quantity": 1, "confidence": 0.8},
                        {"name": "shower", "position": "west_wall", "quantity": 1, "confidence": 0.7}
                    ],
                    "description": "卫生间区域，包含马桶、水槽和淋浴"
                },
                "created_time": time.time(),
                "last_updated": time.time()
            }
        ],
        "edges": [
            {"source": 0, "target": 1, "weight": 3.0},
            {"source": 0, "target": 2, "weight": 3.0},
            {"source": 0, "target": 3, "weight": 2.5},
            {"source": 1, "target": 2, "weight": 4.2},
            {"source": 2, "target": 3, "weight": 3.5}
        ]
    }

    return test_map

def main():
    """Main function"""
    map_file = "/tmp/topological_map.json"

    # Create test map
    test_map = create_test_map()

    # Save to file
    with open(map_file, 'w', encoding='utf-8') as f:
        json.dump(test_map, f, indent=2, ensure_ascii=False)

    print(f"✅ Test topological map created: {map_file}")
    print(f"   - {len(test_map['nodes'])} nodes with semantic information")
    print(f"   - {len(test_map['edges'])} edges connecting nodes")
    print("\nNodes:")
    for node in test_map['nodes']:
        semantic = node['semantic_info']
        print(f"  - Node {node['id']}: {semantic['room_type']} - {semantic['description']}")

if __name__ == "__main__":
    main()