# SSTG Navigation Executor - Quick Reference

## Overview

Single-document reference for quick lookup of ExecutorNode features, parameters, and common operations.

---

## Startup

### Launch ExecutorNode

```bash
# Default configuration
ros2 run sstg_navigation_executor executor_node

# With debug logging
ros2 run sstg_navigation_executor executor_node \
  --ros-args --log-level debug

# With custom parameters
ros2 run sstg_navigation_executor executor_node \
  --ros-args -p nav2_available:=false -p update_rate:=5
```

### Via Launch File

```bash
# Using the provided launch file
ros2 launch sstg_navigation_executor executor.launch.py

# Or directly with ros2 run
ros2 run sstg_navigation_executor executor_node
```

---

## Service Call

### ExecuteNavigation Service

```python
# Python client
from geometry_msgs.msg import PoseStamped, Point, Quaternion
from sstg_navigation_executor.srv import ExecuteNavigation
import math

client = node.create_client(ExecuteNavigation, 'execute_navigation')

# Build request
request = ExecuteNavigation.Request()
request.node_id = 3
request.target_pose = PoseStamped()
request.target_pose.header.frame_id = 'map'
request.target_pose.position = Point(x=1.5, y=2.0, z=0.0)

# Convert theta to quaternion: theta (rad) -> quat
theta = 0.785  # 45 degrees
cy = math.cos(theta * 0.5)
sy = math.sin(theta * 0.5)
request.target_pose.orientation = Quaternion(x=0, y=0, z=sy, w=cy)

# Call service
future = client.call_async(request)
response = future.result()  # blocks until response
print(f"Success: {response.success}, Message: {response.message}")
```

### Via Command Line

```bash
# Simple call (orientation defaults to identity)
ros2 service call /execute_navigation \
  sstg_msgs/srv/ExecuteNavigation \
  "{target_pose: {header: {frame_id: 'map'}, pose: {position: {x: 1.5, y: 2.0, z: 0.0}}}, node_id: 3}"

# With orientation (45 degrees)
ros2 service call /execute_navigation \
  sstg_msgs/srv/ExecuteNavigation \
  "{target_pose: {
      header: {frame_id: 'map'}, 
      pose: {
        position: {x: 1.5, y: 2.0, z: 0.0},
        orientation: {x: 0.0, y: 0.0, z: 0.383, w: 0.924}
      }
    }, 
    node_id: 3}"
```

---

## Topics

### Subscribe to Feedback

```python
from sstg_msgs.msg import NavigationFeedback
from rclpy.qos import QoSProfile, QoSReliabilityPolicy

def feedback_callback(msg: NavigationFeedback):
    print(f"Progress: {msg.progress*100:.1f}%")
    print(f"Distance: {msg.distance_to_target:.2f}m")
    print(f"ETA: {msg.estimated_time_remaining:.1f}s")
    if msg.error_message:
        print(f"Error: {msg.error_message}")

qos = QoSProfile(reliability=QoSReliabilityPolicy.BEST_EFFORT, depth=10)
subscription = node.create_subscription(
    NavigationFeedback,
    'navigation_feedback',
    feedback_callback,
    qos
)
```

### Monitor via CLI

```bash
# Show messages as they arrive
ros2 topic echo /navigation_feedback

# Show at 2Hz (every 0.5s)
ros2 topic echo /navigation_feedback --rate 2

# Show only specific fields
ros2 topic echo /navigation_feedback --field progress,distance_to_target
```

---

## Parameters

### Available Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `nav2_available` | bool | true | - | Enable/disable Nav2; if false, simulates completion |
| `update_rate` | int | 10 | 1-100 | Progress update frequency (Hz) |
| `position_threshold` | float | 0.2 | 0.01-1.0 | Distance threshold for "reached" (m) |
| `orientation_threshold` | float | 0.1 | 0.01-π | Angle threshold for "aligned" (rad) |

### Set Parameters at Runtime

```bash
# View current parameters
ros2 param list
ros2 param get /navigation_executor update_rate

# Set parameter (node must support dynamic reconfiguration)
ros2 param set /navigation_executor update_rate 5
```

---

## API Reference

### Nav2Client

```python
from sstg_navigation_executor import Nav2Client

nav2 = Nav2Client(node)

# Wait for Nav2 to be available
available = await nav2.wait_for_nav2(timeout_sec=10.0)

# Send navigation goal
success = nav2.send_goal(x=1.5, y=2.0, theta=0.785, frame_id='map')

# Check if navigating
is_active = nav2.is_navigating()

# Cancel goal
cancelled = nav2.cancel_goal()
```

### NavigationMonitor

```python
from sstg_navigation_executor import NavigationMonitor

monitor = NavigationMonitor(node)

# Set target
monitor.set_target(x=1.5, y=2.0, theta=0.785)

# Get metrics
distance = monitor.get_distance_to_target()        # meters
angle = monitor.get_angle_to_target()              # radians
progress = monitor.get_progress(initial_dist=3.0) # [0.0, 1.0]
near = monitor.is_near_target(threshold=0.2)      # bool
aligned = monitor.is_aligned_with_target(threshold=0.1)  # bool

# Get full status
status = monitor.get_status_dict()
# Returns: {current_x, current_y, current_theta, target_x, target_y, 
#           target_theta, distance, angle, progress, near_target, aligned, timestamp}
```

### FeedbackHandler

```python
from sstg_navigation_executor import FeedbackHandler, NavigationStatus

handler = FeedbackHandler()

# Start navigation
feedback = handler.start_navigation(node_id=3, target_x=1.5, target_y=2.0)
# -> status=STARTING, progress=0.0

# Update during navigation
feedback = handler.update_progress(
    current_x=0.8, current_y=1.0, current_theta=0.5,
    distance_to_target=1.5, nav2_feedback=None
)
# -> status=IN_PROGRESS, progress=0.45

# Mark as reached
feedback = handler.on_reached()
# -> status=REACHED, progress=1.0

# Or mark as failed
feedback = handler.on_failed("Collision detected")
# -> status=FAILED, error_message="Collision detected"

# Get history (last 10 updates)
history = handler.get_feedback_history(limit=10)

# Get statistics
stats = handler.get_statistics()
# Returns: {total_navigations, successful, failed, success_rate, avg_duration}
```

---

## Common Operations

### Initialize ExecutorNode in Python

```python
from rclpy.node import Node
from sstg_navigation_executor import ExecutorNode

class MyRobot(Node):
    def __init__(self):
        super().__init__('my_robot')
        self.executor = ExecutorNode()
        # Now use self.executor.nav2_client, monitor, handler
```

### Send Navigation Goal

```python
# Method 1: Direct service call
future = client.call_async(request)
response = future.result()

# Method 2: Async callback
def done_callback(f):
    response = f.result()
    self.get_logger().info(f"Got response: {response.success}")

future = client.call_async(request)
future.add_done_callback(done_callback)
```

### Convert Between Theta and Quaternion

```python
import math
from geometry_msgs.msg import Quaternion

# Theta (radians) to Quaternion
def theta_to_quat(theta):
    cy = math.cos(theta * 0.5)
    sy = math.sin(theta * 0.5)
    return Quaternion(x=0, y=0, z=sy, w=cy)

# Quaternion to Theta
def quat_to_theta(quat):
    import math
    theta = 2.0 * math.atan2(quat.z, quat.w)
    return theta

# Examples
print(theta_to_quat(0.785))        # 45 degrees -> Quaternion
print(quat_to_theta(Quaternion(x=0, y=0, z=0.383, w=0.924)))  # -> 0.785
```

### Monitor Navigation Progress

```python
import time

def monitor_navigation():
    # After service call is sent
    start_time = time.time()
    
    while time.time() - start_time < 60:  # 60 second timeout
        # Check latest feedback (via subscription callback)
        if latest_feedback.progress >= 1.0:
            print("Navigation complete!")
            break
        
        print(f"Progress: {latest_feedback.progress*100:.1f}%, " +
              f"Distance: {latest_feedback.distance_to_target:.2f}m")
        
        time.sleep(0.5)  # Update every 500ms
```

---

## Troubleshooting

### ExecutorNode Won't Start

**Symptom:** Process exits immediately
```bash
# Check logs
tail -f ~/.ros/log/latest/executor_node/*.log

# Likely causes:
# 1. Missing dependency
# 2. Nav2 not available (and nav2_available=true)
# 3. AMCL not publishing /amcl_pose
```

**Solutions:**
```bash
# Install missing packages
pip install tf_transformations

# Start Nav2 first
ros2 launch nav2_bringup navigation_launch.py

# Or disable Nav2 requirement
ros2 run sstg_navigation_executor executor_node \
  --ros-args -p nav2_available:=false
```

### Service Calls Fail

**Symptom:** "Service not available" or timeout
```bash
# Check if executor is running
ros2 node list
# Should show: /navigation_executor

# Check service availability
ros2 service list | grep execute_navigation
# Should show: /execute_navigation

# Verify service definition
ros2 service type /execute_navigation
# Should show: sstg_navigation_executor/ExecuteNavigation
```

### No Feedback Messages

**Symptom:** Topic echo shows nothing
```bash
# Check topic is publishing
ros2 topic list | grep navigation_feedback

# Check frequency
ros2 topic hz /navigation_feedback
# Should show ~10 Hz

# Check data
ros2 topic echo /navigation_feedback --once

# If empty: navigation not active; send service call first
```

### Incorrect Distance/Progress Calculations

**Likely Cause:** AMCL not initialized or /amcl_pose not publishing

```bash
# Verify AMCL is running
ros2 node list | grep amcl

# Check amcl_pose topic
ros2 topic echo /amcl_pose --once

# If no output: AMCL not initialized; run localization first
```

### Navigation Never Completes

**Causes & Solutions:**
1. **Robot stuck**: Check for obstacles in path
   - Solution: Manually drive robot, re-plan path
2. **Threshold too strict**: Distance/angle thresholds unreachable
   - Solution: Increase thresholds (ros2 param set)
3. **Nav2 failure**: Navigation2 failed silently
   - Solution: Check Nav2 logs, verify map/costmap

```bash
# Increase tolerance
ros2 param set /navigation_executor position_threshold 0.5
ros2 param set /navigation_executor orientation_threshold 0.3

# Check Nav2 status
ros2 lifecycle get /navigate_to_pose
```

### NumPy Compatibility Error

**Symptom:** ImportError with `np.float` or `np.maximum_sctype` removed
```bash
AttributeError: module 'numpy' has no attribute 'float'.
`np.float` was a deprecated alias for the builtin `float`.
```

**Root Cause:** NumPy 1.20+ removed deprecated aliases, but ROS2's transforms3d package still uses them.

**Solution:** Fix transforms3d source code
```bash
# Edit the transforms3d quaternions.py file
sudo nano /usr/lib/python3/dist-packages/transforms3d/quaternions.py

# Change line 27 from:
_FLOAT_EPS = np.finfo(np.float).eps
# To:
_FLOAT_EPS = np.finfo(float).eps

# Save and restart executor_node
ros2 run sstg_navigation_executor executor_node
```

**Alternative:** Downgrade NumPy (not recommended)
```bash
pip install 'numpy<2.0'
# Note: May break other packages requiring NumPy 2.x
```

---

## Debug Commands

### View ROS2 Graph

```bash
# All nodes and topics
ros2 node list
ros2 topic list

# Specific node details
ros2 node info /navigation_executor

# Topic details
ros2 topic info /navigation_feedback
```

### Monitor Performance

```bash
# Topic message rate
ros2 topic hz /navigation_feedback

# Topic bandwidth
ros2 topic bw /navigation_feedback

# Node CPU/memory (requires rqt)
rqt_graph
rqt_console (for logging)
```

### Manual Service Testing

```bash
# Inspect service definition
ros2 service type /execute_navigation
ros2 srv show sstg_navigation_executor/ExecuteNavigation

# Test with valid request
ros2 service call /execute_navigation \
  sstg_navigation_executor/ExecuteNavigation \
  "{target_pose: {header: {frame_id: 'map'}, position: {x: 0, y: 0}}, node_id: 1}"

# Result should be:
# response:
#   message: 'Navigation goal accepted'
#   success: true
```

---

## Performance Tips

### Reduce CPU Usage

```bash
# Decrease update rate (default 10 Hz)
ros2 param set /navigation_executor update_rate 5

# Use best_effort QoS (not reliable)
# Already configured in module
```

### Improve Feedback Latency

```bash
# Increase update rate (up to 50 Hz max)
ros2 param set /navigation_executor update_rate 20

# Note: May increase CPU usage
```

### Handle Multiple Robots

For multi-robot setup:
```bash
# Robot 1
ros2 run sstg_navigation_executor executor_node \
  --ros-args -n /robot1/navigation_executor

# Robot 2
ros2 run sstg_navigation_executor executor_node \
  --ros-args -n /robot2/navigation_executor
```

---

## Version Info

```bash
# Check version from package.xml
grep '<version>' /home/daojie/sstg_nav/yahboomcar_ws/src/sstg_navigation_executor/package.xml

# Current: 0.1.0

# Check ROS2 version
ros2 --version
# Required: Humble or later
```

---

## Examples

### Complete Navigation Cycle

```python
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, Point, Quaternion
from sstg_navigation_executor.srv import ExecuteNavigation
from sstg_msgs.msg import NavigationFeedback
import math

class NavigationDemo(Node):
    def __init__(self):
        super().__init__('nav_demo')
        
        # Create service client
        self.client = self.create_client(ExecuteNavigation, 'execute_navigation')
        while not self.client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('Service not available, waiting...')
        
        # Subscribe to feedback
        self.create_subscription(
            NavigationFeedback,
            'navigation_feedback',
            self.feedback_callback,
            qos_profile_sensor_data
        )
        
        self.latest_feedback = None
    
    def navigate(self, x, y, theta, node_id):
        # Build request
        request = ExecuteNavigation.Request()
        request.node_id = node_id
        request.target_pose = PoseStamped()
        request.target_pose.header.frame_id = 'map'
        request.target_pose.position = Point(x=float(x), y=float(y), z=0.0)
        
        cy = math.cos(float(theta) * 0.5)
        sy = math.sin(float(theta) * 0.5)
        request.target_pose.orientation = Quaternion(x=0.0, y=0.0, z=sy, w=cy)
        
        # Send request
        future = self.client.call_async(request)
        future.add_done_callback(self.response_callback)
    
    def response_callback(self, future):
        response = future.result()
        self.get_logger().info(
            f"Service response: success={response.success}, msg={response.message}"
        )
    
    def feedback_callback(self, msg: NavigationFeedback):
        self.latest_feedback = msg
        self.get_logger().info(
            f"Node {msg.node_id}: {msg.progress*100:.0f}% | "
            f"Distance: {msg.distance_to_target:.2f}m"
        )

if __name__ == '__main__':
    rclpy.init()
    demo = NavigationDemo()
    
    # Navigate to position (1.5, 2.0) with 45 degree heading, node_id=3
    demo.navigate(1.5, 2.0, 0.785, 3)
    
    rclpy.spin(demo)
```

---

## File Locations

| File | Location |
|------|----------|
| Package root | `/home/daojie/sstg_nav/yahboomcar_ws/src/sstg_navigation_executor/` |
| Main node | `sstg_navigation_executor/executor_node.py` |
| Nav2 client | `sstg_navigation_executor/nav2_client.py` |
| Monitor | `sstg_navigation_executor/navigation_monitor.py` |
| Feedback | `sstg_navigation_executor/feedback_handler.py` |
| Tests | `test/test_navigation_executor.py` |
| Full docs | `docs/MODULE_GUIDE.md` |
| Service def | `srv/ExecuteNavigation.srv` (in sstg_msgs) |
| Launch files | `launch/executor.launch.py` |

---

## Related Packages

- **sstg_msgs**: Message definitions (NavigationFeedback, ExecuteNavigation service)
- **nav2_msgs**: Navigation2 action definitions (NavigateToPose)
- **geometry_msgs**: Pose, Point, Quaternion messages
- **sstg_planning_node**: Upstream planner that sends ExecuteNavigation requests
- **sstg_interaction_manager**: Downstream manager that processes feedback

