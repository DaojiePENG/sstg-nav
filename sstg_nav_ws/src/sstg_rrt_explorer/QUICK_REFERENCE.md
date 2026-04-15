# SSTG RRT Explorer - Quick Reference Guide

## Key Files Checklist

### Must Know Files
- **CMakeLists.txt** - Build config (2 C++ executables + 15 Python scripts)
- **package.xml** - Dependencies (nav2_msgs, sstg_msgs, etc.)
- **launch/rrt_exploration_ros2.launch.py** - Core RRT pipeline (5 nodes)
- **launch/rrt_exploration_full.launch.py** - Full stack (Hardware→SLAM→Nav2→RRT)
- **launch/navigation_full.launch.py** - Navigation on pre-built map

### C++ Sources
- **src/global_rrt_detector_ros2.cpp** - Global RRT sampling
- **src/local_rrt_detector_ros2.cpp** - Local RRT sampling
- **src/functions.cpp** - RRT + geometry utilities
- **include/functions.h** - C++ headers

### Core Python Nodes
- **scripts/filter_ros2.py** - Frontier filtering (MeanShift clustering)
- **scripts/assigner_ros2.py** - Goal assignment (information gain)
- **scripts/rrt_trace_manager.py** - Trajectory recording + completion detection
- **scripts/functions_ros2.py** - Shared Python utilities

### Topology & Navigation
- **scripts/auto_node_placer.py** - Auto-place topological nodes
- **scripts/find_and_navigate.py** - NLP-based navigation
- **scripts/node_semantic_collector.py** - Semantic labeling
- **scripts/click_and_capture.py** - Interactive node creation
- **scripts/topo_node_viz.py** - Visualization

### Configuration
- **param/common/nav2_params.yaml** - Nav2 controller/planner config
- **param/common/ekf_x3_override.yaml** - EKF odometry fusion
- **maps/topological_map_manual.json** - Topological graph (post-exploration)

---

## Node Count & Types

| Type | Count | Examples |
|------|-------|----------|
| **C++ Nodes** | 2 | global_rrt_detector, local_rrt_detector |
| **Python ROS2 Nodes** | 5 core | filter, assigner, rrt_trace_manager + helpers |
| **Topological/NLP** | 6+ | auto_node_placer, find_and_navigate, etc. |
| **Utilities** | 4+ | topic_relay, tf_relay, scan_dilute, etc. |
| **Total Scripts** | 18 | All listed in CMakeLists.txt |

---

## Critical Topics & Frames

### Must-Have Topics
| Topic | Type | Direction | Source |
|-------|------|-----------|--------|
| `/map` | OccupancyGrid | ← | SLAM |
| `/odom` | Odometry | ← | EKF filter |
| `/scan` | LaserScan | ← | Lidar |
| `/detected_points` | PointStamped | → | RRT detectors |
| `/filtered_points` | PointArray | → | Filter |
| `/move_base_simple/goal` | PoseStamped | → | Assigner → Nav2 |
| `/cmd_vel` | Twist | ← | Nav2 → Motors |
| `/rrt_exploration_status` | String | → | Trace manager |

### TF Frames (Critical)
```
map
└── odom (from SLAM)
    └── base_footprint
        └── base_link (required for local RRT)
            └── laser (hardcoded: 0.0435, 5.258E-05, 0.11 + π rotation)
```

**Critical Frames:**
- `base_link` - Robot body frame (required for TF lookups)
- `map` - Global reference frame
- `laser` - LiDAR sensor frame

---

## Launch Files at a Glance

### rrt_exploration_ros2.launch.py
**When to use:** Just RRT pipeline (SLAM + Nav2 already running)  
**Nodes:** global_rrt_detector, local_rrt_detector, filter, assigner, rrt_trace_manager  
**Key params:** local_eta=1.5, global_eta=4.0, info_radius=1.5  
**Delay:** 8 seconds before starting

### rrt_exploration_full.launch.py
**When to use:** First-time exploration (everything from scratch)  
**Timeline:**
```
t=0s:  Hardware (motors, IMU, EKF, lidar, TF)
t=3s:  SLAM (async map building)
t=6s:  Nav2 (navigation stack)
t=10s: RRT (exploration)
```
**Rationale:** Stages prevent resource conflicts; dependencies initialize first

### navigation_full.launch.py
**When to use:** Navigate using pre-built map + topological nodes  
**Timeline:**
```
t=0s:  Hardware
t=3s:  SLAM localization + map_server + camera (parallel)
t=6s:  Nav2
t=15s: Topological visualization
```

---

## Key Parameters to Tune

### RRT Exploration (rrt_exploration_ros2.launch.py)

| Param | Type | Default | Effect |
|-------|------|---------|--------|
| `local_eta` | float | 1.5 | Local RRT step distance (smaller = denser sampling) |
| `global_eta` | float | 4.0 | Global RRT step distance |
| `local_range` | float | 8.0m | Radius for local detector |
| `info_radius` | float | 1.5m | Radius for evaluating information gain |
| `filter_cluster_bandwidth` | float | 0.45 | MeanShift kernel size |
| `filter_min_frontier_separation` | float | 0.20m | Minimum distance between cluster centers |
| `assignment_period` | float | 0.2s | How often assigner recomputes goal |
| `completion_patience` | float | 10.0s | Timeout to declare exploration done |

### Thresholds for Completion Detection

| Param | Default | Meaning |
|-------|---------|---------|
| `trajectory_distance_threshold` | 0.05m | Movement below this = stationarity |
| `trajectory_time_threshold` | 0.5s | How long stationarity lasts |

---

## Common Workflows

### Workflow 1: Full Exploration + Topological Mapping
```bash
# Terminal 1: Full exploration
ros2 launch sstg_rrt_explorer rrt_exploration_full.launch.py

# Wait for exploration to complete, then in Terminal 2:
ros2 run sstg_rrt_explorer auto_node_placer.py --spacing 2.0

# Terminal 3: Semantic labeling (interactive in RViz)
ros2 run sstg_rrt_explorer node_semantic_collector.py --interactive

# Results: topological_map_manual.json saved to maps/
```

### Workflow 2: Navigate on Pre-Built Map
```bash
# Terminal 1: Full navigation stack
ros2 launch sstg_rrt_explorer navigation_full.launch.py

# Terminal 2: RViz
rviz2 -d ~/wbt_ws/.../sstg_rrt_explorer/rviz/rrt_ros2.rviz

# Terminal 3: NLP-based navigation
ros2 run sstg_rrt_explorer find_and_navigate.py --query "我要找我的书包"
```

### Workflow 3: Just RRT (SLAM + Nav2 already running)
```bash
# Terminal 1: RRT exploration only
ros2 launch sstg_rrt_explorer rrt_exploration_ros2.launch.py

# Exploration runs independently
```

### Workflow 4: Replay Exploration
```bash
ros2 launch sstg_rrt_explorer trace_replay.launch.py \
  trace_file:=maps/trace_20260413.json
```

---

## Debugging Checklist

### Node Not Starting?
```bash
# Check if build is up-to-date
colcon build --packages-select sstg_rrt_explorer

# Check source
source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash

# Check dependencies
rosdep install --from-paths src --ignore-src -r -y
```

### Missing Topics?
```bash
# List all topics
ros2 topic list

# Check specific topic
ros2 topic echo /detected_points

# Monitor node activity
ros2 node list
ros2 node info /global_rrt_detector
```

### TF Issues?
```bash
# Check TF tree
ros2 run tf2_tools view_frames.py
# Output: frames.pdf

# Echo specific TF
ros2 run tf2_ros tf2_echo map base_link
```

### Parameter Issues?
```bash
# List all params for a node
ros2 param list /filter

# Get specific param
ros2 param get /filter cluster_bandwidth

# Set param (if node supports dynamic reconfigure)
ros2 param set /filter cluster_bandwidth 0.5
```

---

## Integration with Other Packages

### Data Flow from sstg_rrt_explorer

| Output | Consumed By | Purpose |
|--------|------------|---------|
| `/move_base_simple/goal` | Nav2 | Navigation goals |
| `/rrt_exploration_status` | sstg_interaction_manager | Progress tracking |
| `/save_rrt_session` service | sstg_interaction_manager | Save exploration results |
| `topological_map_manual.json` | sstg_map_manager | Topological graph storage |
| Semantic node images | sstg_perception | VLM re-annotation |

### Dependencies on Other Packages
- **sstg_msgs** - Custom messages (PointArray, GoalTraceEvent, ExploreHome action, SaveRrtSession)
- **nav2_bringup** - Navigation stack (controller, planner, BT navigator)
- **slam_toolbox** - SLAM (async mapping + localization)
- **yahboomcar_bringup/description** - Hardware (Yahboom X3 drivers, URDF)
- **robot_localization** - EKF fusion for odometry

---

## Quick Troubleshooting

### "Global_rrt_detector waiting for clicked point"
**Fix:** Click a point near robot in RViz to seed the RRT  
**Why:** RRT needs a seed point; click near robot start position

### "No frontiers detected"
**Check:** 
- Is SLAM running? `/map` should exist
- Is `/detected_points` being published?
- Is costmap clearing threshold correct? (70.0 default)

### "Exploration never completes"
**Check:**
- Does `completion_patience` timeout happen? (10.0s default)
- Are there persistent frontiers? Check with `ros2 topic echo /detected_points`
- Try increasing `completion_patience` parameter

### "Nav2 fails to reach goal"
**Check:**
- Is `/map` consistent? Publish from single source
- Are costmap inflation radius settings correct?
- Is robot stuck in recovery behaviors?

---

## File Locations Summary

| What | Where |
|------|-------|
| Package root | `/home/daojie/wbt_ws/sstg-nav/sstg_nav_ws/src/sstg_rrt_explorer/` |
| Build files | `src/`, `include/`, `CMakeLists.txt` |
| Launch files | `launch/` and `launch/library/` |
| Scripts | `scripts/` (18 Python executables) |
| Config | `param/common/` (2 YAML files) |
| Maps | `maps/` (PGM + topological JSON) |
| RViz config | `rviz/rrt_ros2.rviz` |
| Captured nodes | `captured_nodes/` (post-exploration data) |
| Documentation | `PACKAGE_ANALYSIS.md` (comprehensive guide) |
| Architecture | `NODE_ARCHITECTURE.txt` (visual diagram) |

---

## Useful Commands

```bash
# Build
colcon build --packages-select sstg_rrt_explorer

# Run full exploration
ros2 launch sstg_rrt_explorer rrt_exploration_full.launch.py

# List active nodes
ros2 node list

# Check node details
ros2 node info /global_rrt_detector

# Visualize TF
ros2 run tf2_tools view_frames.py

# Record bag
ros2 bag record /map /tf /detected_points /filtered_points

# Echo topic
ros2 topic echo /filtered_points

# Check parameter
ros2 param get /filter cluster_bandwidth
```

---

**Last Updated:** April 13, 2026  
**For detailed information:** See `PACKAGE_ANALYSIS.md` and `NODE_ARCHITECTURE.txt`
