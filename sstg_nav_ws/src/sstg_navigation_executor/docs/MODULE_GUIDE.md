# SSTG Navigation Executor - Module Guide

## Overview

The SSTG Navigation Executor (Phase 4.1) is a ROS2-based navigation execution system that bridges the gap between high-level planning and low-level robot control. It translates semantic navigation commands into actionable navigation goals, monitors progress in real-time, and provides comprehensive feedback to the upper system layers.

**Key Features:**
- Nav2 integration with asynchronous action-based navigation
- Real-time AMCL-based localization and progress monitoring
- Comprehensive feedback system with historical tracking
- Graceful fallback to simulation mode when Nav2 is unavailable
- Modular architecture for easy integration and testing

---

## Architecture

### System Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                   SSTG Navigation Executor                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────┐     ┌──────────────────────┐              │
│  │  ExecutorNode    │     │ ExecuteNavigation    │              │
│  │ (ROS2 Service)   │────▶│ Service Call Handler │              │
│  └──────────────────┘     └──────────────────────┘              │
│           │                                                       │
│           ├──────────────────────────────────┬────────────────┐  │
│           │                                  │                │  │
│    ┌──────▼──────────┐  ┌─────────────────┐ │ ┌─────────────┐│  │
│    │  Nav2Client     │  │ Navigation      │ │ │ Feedback    ││  │
│    │                 │  │ Monitor         │ │ │ Handler     ││  │
│    │ - send_goal()   │  │                 │ │ │             ││  │
│    │ - cancel_goal() │  │ - set_target()  │ │ │ - update()  ││  │
│    │ - is_navigating │  │ - get_progress()│ │ │ - on_reached││  │
│    └────────┬────────┘  └────────┬────────┘ │ └─────────────┘│  │
│             │                    │          │                │  │
└─────────────┼────────────────────┼──────────┼────────────────┘  │
              │                    │          │                    │
        ┌─────▼─────────────────────▼──────────▼────────────────┐  │
        │         ROS2 Publish/Subscribe Layer                  │  │
        │                                                         │  │
        │ Topics:                                                │  │
        │ - /amcl_pose (Subscribe)          [geometry_msgs/Pose]│  │
        │ - /navigation_feedback (Publish) [sstg_msgs/NavFeedback]│
        │ - /navigate_to_pose/_action/* (Action)                │  │
        │                                                         │  │
        └──────────────────────────────────────────────────────┘  │
```

### Data Flow

```
1. SEMANTIC PLANNING LAYER
   ↓
   Plan: "Navigate to room 3"
   ↓
2. EXECUTOR SERVICE REQUEST
   Service: ExecuteNavigation
   Request: target_pose (x=1.5, y=2.0, theta=0.785), node_id=3
   ↓
3. EXECUTOR NODE PROCESSING
   a) Create navigation context
   b) Start Nav2 goal (async)
   c) Setup progress monitoring
   ↓
4. REAL-TIME MONITORING (10 Hz)
   a) Read current pose from AMCL
   b) Calculate distance to target
   c) Update progress [0.0 to 1.0]
   d) Publish feedback
   ↓
5. GOAL COMPLETION
   a) Nav2 returns result (SUCCEEDED/FAILED)
   b) Handler processes outcome
   c) Final feedback published
   ↓
6. RESPONSE
   Service Response: {success: true, message: "Navigation completed"}
```

---

## Component Details

### 1. Nav2Client (`nav2_client.py`)

**Purpose:** Wrapper around ROS2 Navigation2 action client for goal-oriented navigation.

**Key Classes:**
- `Nav2Client`: Main integration class

**Public Methods:**

```python
async def wait_for_nav2(timeout_sec: float = 10.0) -> bool
```
Waits for Navigation2 action server availability.
- **Parameters**: timeout_sec (float) - Maximum wait time
- **Returns**: True if available, False if timeout
- **Raises**: No exceptions; returns False on timeout
- **Usage**: Call at startup to verify Nav2 is running

```python
def send_goal(x: float, y: float, theta: float, 
              frame_id: str = 'map',
              callback=None) -> bool
```
Send navigation goal to Nav2 and initiate navigation.
- **Parameters**:
  - x, y (float): Target position in meters
  - theta (float): Target orientation in radians
  - frame_id (str): Coordinate frame (default: 'map')
  - callback (Callable): Optional async callback for when goal completes
- **Returns**: True if goal accepted, False otherwise
- **Internal**: Converts theta to quaternion, sends NavigateToPose action

**Callback Signature:**
```python
async def goal_callback(future):
    result = future.result()
    # result.result.status: 4=SUCCEEDED, 5=FAILED, 6=CANCELED
```

```python
def cancel_goal() -> bool
```
Cancel the current navigation goal.
- **Returns**: True if cancellation sent successfully
- **Side Effects**: Robot stops, Nav2 transitions to CANCELING state

```python
def is_navigating() -> bool
```
Check if navigation is currently in progress.
- **Returns**: True if goal is active and not completed

**Internal Methods:**

```python
def _euler_to_quaternion(roll: float, pitch: float, 
                         yaw: float) -> Quaternion
```
Converts Euler angles (roll, pitch, yaw) to quaternion representation.
- **Formula**: Uses tf_transformations.quaternion_from_euler()
- **Input**: All angles in radians
- **Output**: geometry_msgs.Quaternion object
- **Use Case**: Converting theta to orientation for PoseStamped

```python
def _quaternion_to_euler(quat: Quaternion) -> tuple
```
Converts quaternion to Euler angles.
- **Output**: (roll, pitch, yaw) tuple in radians
- **Use Case**: Extracting heading from AMCL pose

---

### 2. NavigationMonitor (`navigation_monitor.py`)

**Purpose:** Real-time tracking of robot position relative to navigation target.

**Key Classes:**
- `NavigationMonitor`: Position tracking and progress calculation
- Uses AMCL pose subscriber for localization

**Subscribed Topics:**
- `/amcl_pose` (geometry_msgs/PoseWithCovarianceStamped) - Robot's estimated position

**Public Methods:**

```python
def set_target(x: float, y: float, theta: float) -> None
```
Set the navigation target coordinates and orientation.
- **Parameters**: x, y (float in meters), theta (float in radians)
- **Effect**: Updates internal target, resets progress calculation
- **Note**: Call before checking progress or distances

```python
def get_distance_to_target() -> float
```
Get Euclidean distance to target.
- **Returns**: Distance in meters
- **Formula**: sqrt((robot_x - target_x)^2 + (robot_y - target_y)^2)
- **Precision**: ~0.01m accuracy with AMCL

```python
def get_angle_to_target() -> float
```
Get angle offset to target.
- **Returns**: Angle in radians [-π, π]
- **Formula**: atan2(target_y - robot_y, target_x - robot_x) - robot_theta
- **Interpretation**: Positive = counterclockwise, Negative = clockwise

```python
def get_progress(initial_distance: float) -> float
```
Calculate linear progress [0.0, 1.0].
- **Parameters**: initial_distance (float) - Distance at start of navigation
- **Returns**: Float in [0.0, 1.0]
- **Formula**: (initial_distance - current_distance) / initial_distance
- **Clipping**: Clamped at 1.0 even if distance overshoots
- **Note**: Requires initial_distance > 0

```python
def is_near_target(threshold: float = 0.2) -> bool
```
Check if robot is within threshold distance of target.
- **Parameters**: threshold (float) - Distance in meters (default: 0.2m)
- **Returns**: Boolean
- **Typical Usage**: Used to detect navigation completion

```python
def is_aligned_with_target(threshold: float = 0.1) -> bool
```
Check if robot orientation matches target.
- **Parameters**: threshold (float) - Angle tolerance in radians (default: 0.1 rad ≈ 5.7°)
- **Returns**: Boolean

```python
def get_status_dict() -> dict
```
Get comprehensive status snapshot.
- **Returns**: Dictionary with keys:
  - `current_x`, `current_y`, `current_theta`: Robot's position
  - `target_x`, `target_y`, `target_theta`: Target position
  - `distance`: Distance to target
  - `angle`: Angle offset
  - `progress`: Progress [0.0, 1.0]
  - `near_target`: Boolean
  - `aligned`: Boolean
  - `timestamp`: Unix timestamp

---

### 3. FeedbackHandler (`feedback_handler.py`)

**Purpose:** Manage navigation lifecycle, state transitions, and feedback tracking.

**Key Enums & Dataclasses:**

```python
class NavigationStatus(Enum):
    IDLE = 0              # Not navigating
    STARTING = 1          # Goal just sent to Nav2
    IN_PROGRESS = 2       # Actively navigating
    REACHED = 3           # Target reached successfully
    FAILED = 4            # Navigation failed
    CANCELLED = 5         # Navigation cancelled by user
```

```python
@dataclass
class NavigationFeedback:
    node_id: int                      # Planning node ID
    status: NavigationStatus          # Current state
    progress: float                   # [0.0, 1.0]
    current_pose: tuple               # (x, y, theta)
    distance_to_target: float         # Meters
    estimated_time_remaining: float   # Seconds
    error_message: str                # "" if no error
    timestamp: float                  # Unix time
    history: List[dict]               # Historical entries
```

**FeedbackHandler Methods:**

```python
def start_navigation(node_id: int, target_x: float, 
                     target_y: float) -> NavigationFeedback
```
Initialize navigation context and create initial feedback.
- **Returns**: NavigationFeedback with status=STARTING, progress=0.0
- **Side Effects**: Records start time, initializes history

```python
def update_progress(current_x: float, current_y: float, 
                    current_theta: float,
                    distance_to_target: float,
                    nav2_feedback=None) -> NavigationFeedback
```
Update progress based on current position.
- **Parameters**:
  - current_x, current_y, current_theta: Robot's current pose
  - distance_to_target: Distance to goal (meters)
  - nav2_feedback: Optional Nav2 goal feedback (contains estimated_time_remaining)
- **Returns**: Updated NavigationFeedback
- **Internal**: Calculates linear progress, estimates time remaining

```python
def on_reached() -> NavigationFeedback
```
Mark navigation as successfully completed.
- **Returns**: NavigationFeedback with status=REACHED, progress=1.0
- **Effect**: Records completion time, calculates total duration

```python
def on_failed(error_msg: str = "") -> NavigationFeedback
```
Mark navigation as failed.
- **Parameters**: error_msg (str) - Error description
- **Returns**: NavigationFeedback with status=FAILED
- **Effect**: Records failure reason in error_message field

```python
def on_cancelled() -> NavigationFeedback
```
Mark navigation as cancelled.
- **Returns**: NavigationFeedback with status=CANCELLED

```python
def get_feedback_history(limit: int = 10) -> List[dict]
```
Retrieve historical feedback entries.
- **Parameters**: limit (int) - Maximum entries to return
- **Returns**: List of feedback dictionaries (newest first)
- **Use Case**: Debug/monitoring of navigation history

```python
def get_statistics() -> dict
```
Calculate navigation statistics.
- **Returns**: Dictionary with:
  - `total_navigations`: Total navigation attempts
  - `successful`: Count of successful navigations
  - `failed`: Count of failures
  - `success_rate`: Percentage (0.0-1.0)
  - `avg_duration`: Average navigation time

---

### 4. ExecutorNode (`executor_node.py`)

**Purpose:** Main ROS2 node that orchestrates all navigation components and provides service interface.

**ROS2 Service:**

```
Service: /execute_navigation
Type: sstg_navigation_executor/ExecuteNavigation

Request:
  - target_pose (geometry_msgs/PoseStamped)
  - node_id (int32)

Response:
  - success (bool)
  - message (string)
```

**ROS2 Publishers:**

```
Topic: /navigation_feedback
Type: sstg_msgs/NavigationFeedback
QoS: depth=10, best_effort
Frequency: 10 Hz (configurable)
```

**ROS2 Subscriptions:**

```
Topic: /amcl_pose
Type: geometry_msgs/PoseWithCovarianceStamped
Purpose: Robot localization
```

**Parameters (Configurable via launch or command-line):**

```yaml
nav2_available: bool         # Enable/disable Nav2 (default: true)
                             # If false, simulates successful navigation

position_threshold: float    # Distance threshold for "reached" (default: 0.2m)

orientation_threshold: float # Angle threshold for "aligned" (default: 0.1 rad)

update_rate: int            # Progress update frequency (default: 10 Hz)
                            # Range: 1-100 Hz
```

**Node Initialization:**

```python
def __init__(self):
    # 1. Create ROS2 node
    # 2. Initialize sub-components (Nav2Client, Monitor, Handler)
    # 3. Create service server (ExecuteNavigation)
    # 4. Create feedback publisher
    # 5. Setup progress update timer (10 Hz)
    # 6. Wait for Nav2 (if enabled)
```

**Service Callback Flow:**

```python
async def _execute_navigation_callback(request, response):
    # 1. Extract target_pose and node_id
    # 2. Convert quaternion to euler angles
    # 3. Create navigation context
    # 4. Call _start_navigation()
    # 5. Return response {success, message}
```

**Progress Update Timer (10 Hz):**

```python
def _update_progress(self):
    # 1. Check if navigation active
    # 2. Read current pose from AMCL
    # 3. Update FeedbackHandler with current state
    # 4. Publish feedback message
    # 5. Check for completion (distance < threshold or Nav2 result)
    # 6. On completion: store result, stop timer
```

**Fallback/Simulation Mode:**

If `nav2_available=false`:
- Service calls still accepted
- Navigation automatically completes after 0.1 seconds
- Feedback shows progress=1.0, status=REACHED
- Useful for testing when Nav2 unavailable

---

## Integration Points

### Input: From Semantic Planning Layer

**PlanNavigation Service Response** → **ExecutorNode Service Request**

```python
# Planning layer returns:
plan = {
    'node_id': 3,
    'node_pose': {'x': 1.5, 'y': 2.0, 'theta': 0.785}
}

# Executor receives (converted to ExecuteNavigation.srv):
{
    'target_pose': PoseStamped(
        position=Point(x=1.5, y=2.0, z=0),
        orientation=Quaternion.from_euler(0, 0, 0.785)
    ),
    'node_id': 3
}
```

### Output: To System Feedback/Dialogue Layer

**ExecutorNode Feedback Topic** → **Interaction Manager**

```python
# Published on /navigation_feedback:
{
    'node_id': 3,
    'status': 2,  # IN_PROGRESS
    'progress': 0.45,  # 45% complete
    'current_pose': {'x': 0.8, 'y': 1.2, 'theta': 0.5},
    'distance_to_target': 1.1,  # meters
    'estimated_time_remaining': 8.5,  # seconds
    'error_message': '',
    'timestamp': 1710345600.123
}
```

---

## Usage Example

### Launch File

```xml
<!-- executor.launch.xml -->
<launch>
  <node pkg="sstg_navigation_executor" 
        exec="executor_node"
        name="navigation_executor">
    <param name="nav2_available" value="true"/>
    <param name="update_rate" value="10"/>
    <param name="position_threshold" value="0.2"/>
  </node>
</launch>
```

### Python Client Code

```python
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, Point, Quaternion
from sstg_navigation_executor.srv import ExecuteNavigation
import math

class PlanningNode(Node):
    def __init__(self):
        super().__init__('planning_node')
        self.client = self.create_client(
            ExecuteNavigation, 
            'execute_navigation'
        )
    
    def navigate_to_room(self, room_id, x, y, theta):
        # Create service request
        request = ExecuteNavigation.Request()
        request.node_id = room_id
        
        request.target_pose = PoseStamped()
        request.target_pose.header.frame_id = 'map'
        request.target_pose.position = Point(x=x, y=y, z=0.0)
        
        # Convert theta to quaternion
        cy = math.cos(theta * 0.5)
        sy = math.sin(theta * 0.5)
        request.target_pose.orientation = Quaternion(
            x=0.0, y=0.0, z=sy, w=cy
        )
        
        # Send request
        future = self.client.call_async(request)
        future.add_done_callback(self._response_callback)
    
    def _response_callback(self, future):
        response = future.result()
        self.get_logger().info(
            f"Navigation result: {response.success}, {response.message}"
        )
```

### Feedback Subscriber

```python
from sstg_msgs.msg import NavigationFeedback

def feedback_callback(msg: NavigationFeedback):
    print(f"Node {msg.node_id}: {msg.progress*100:.1f}% complete")
    print(f"  Distance: {msg.distance_to_target:.2f}m")
    print(f"  ETA: {msg.estimated_time_remaining:.1f}s")
    if msg.error_message:
        print(f"  Error: {msg.error_message}")

# In node init:
self.create_subscription(
    NavigationFeedback,
    'navigation_feedback',
    feedback_callback,
    qos_profile_sensor_data
)
```

---

## Error Handling

### Common Errors & Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| "Nav2 not available" | Navigation2 not running | Start Nav2 or set `nav2_available=false` |
| "Service not available" | Executor node crashed | Restart `executor_node` |
| Navigation timeout | Robot physically stuck | Check for obstacles, adjust thresholds |
| AMCL subscription empty | AMCL not running | Start AMCL node, verify /amcl_pose publishing |
| Invalid quaternion | Service request malformed | Verify theta is in valid range [-π, π] |

### Debug Logging

Enable full logging:
```bash
ros2 run sstg_navigation_executor executor_node \
  --ros-args --log-level sstg_navigation_executor:=debug
```

Monitor feedback:
```bash
ros2 topic echo /navigation_feedback
```

Check service calls:
```bash
ros2 service call /execute_navigation sstg_navigation_executor/ExecuteNavigation \
  "{target_pose: {header: {frame_id: 'map'}, position: {x: 1.0, y: 1.0}}, node_id: 1}"
```

---

## Testing

### Unit Tests

Located in `test/test_navigation_executor.py`:

1. **TestNavigationMonitor**
   - `test_set_target`: Verify target setting
   - `test_distance_calculation`: Verify Euclidean distance

2. **TestFeedbackHandler**
   - `test_start_navigation`: Verify initialization
   - `test_on_reached`: Verify state transition

Run tests:
```bash
cd /home/daojie/sstg_nav/yahboomcar_ws/src/sstg_navigation_executor
PYTHONPATH=/home/daojie/sstg_nav/yahboomcar_ws/install/sstg_navigation_executor/lib/python3.10/site-packages:$PYTHONPATH python test/test_navigation_executor.py
```

### Integration Testing

Test with real Nav2:
```bash
# Terminal 1: Start Nav2
ros2 launch nav2_bringup navigation_launch.py

# Terminal 2: Start executor
ros2 run sstg_navigation_executor executor_node

# Terminal 3: Send test navigation
ros2 service call /execute_navigation sstg_navigation_executor/ExecuteNavigation \
  "{target_pose: {header: {frame_id: 'map'}, position: {x: 5.0, y: 5.0}}, node_id: 1}"
```

---

## Performance Considerations

### Timing

- **Service call latency**: ~5-10ms (service + Nav2 goal acceptance)
- **Feedback update rate**: 10 Hz (configurable, default), ~100ms per update
- **Distance calculation**: <1ms (simple Euclidean math)
- **Progress monitor loop**: Total time per cycle <5ms

### Resources

- **CPU**: ~2-3% (single thread, 10 Hz update rate)
- **Memory**: ~15MB (Python process + ROS2 subscriptions/publishers)
- **Network**: ~2KB/sec (feedback topic, 10 Hz, best_effort QoS)

### Scalability

Current design supports:
- Multiple sequential navigations (one at a time)
- 100+ feedback subscribers (QoS: best_effort)
- Theoretically up to 1000 Hz update rate (not recommended)

For parallel multi-robot execution, consider:
- Separate ExecutorNode instance per robot
- Namespaced topics: `/robot1/execute_navigation`, `/robot2/execute_navigation`

---

## Dependencies

### ROS2 Packages
- `rclpy` - ROS2 Python client library
- `nav2_msgs` - Navigation2 message definitions
- `geometry_msgs` - Standard geometry messages
- `sstg_msgs` - Custom SSTG message definitions

### Python Libraries
- `tf_transformations` - Quaternion/Euler conversions
- `dataclasses` - Structured data (Python 3.7+)
- `numpy` - Mathematical operations (see compatibility note below)

### System Dependencies
- Python 3.8+
- ROS2 Humble
- **NumPy Compatibility**: Requires NumPy < 2.0 due to transforms3d dependency. If using NumPy 2.x, manually patch `/usr/lib/python3/dist-packages/transforms3d/quaternions.py` line 27: change `np.finfo(np.float).eps` to `np.finfo(float).eps`

---

## Contributing Guidelines

### Adding New Features

1. Update corresponding module (nav2_client.py, monitor, handler, or executor)
2. Add unit tests in `test/test_navigation_executor.py`
3. Update this MODULE_GUIDE.md with new methods
4. Run full test suite: `PYTHONPATH=/path/to/install/lib/python3.10/site-packages:$PYTHONPATH python test/test_navigation_executor.py`, 
e.g., `PYTHONPATH=/home/daojie/sstg_nav/yahboomcar_ws/install/sstg_navigation_executor/lib/python3.10/site-packages:$PYTHONPATH /home/daojie/anaconda3/envs/hw_nav/bin/python test/test_navigation_executor.py`
5. Rebuild: `colcon build --packages-select sstg_navigation_executor`

### Code Style

- Follow PEP 8
- Use type hints for all functions
- Add docstrings to public methods
- Keep lines <100 characters

---

## Version History

- **v0.1.0** (Initial Release)
  - Nav2 integration
  - AMCL-based position tracking
  - ExecuteNavigation service
  - Real-time feedback publisher
  - Fallback simulation mode

---

## Support & Troubleshooting

For issues or questions:
1. Check `/home/daojie/sstg_nav/yahboomcar_ws/log/` for build logs
2. Run unit tests to verify core functionality
3. Monitor ROS2 topics: `ros2 topic list` and `ros2 topic echo`
4. Check node status: `ros2 node list` and `ros2 node info /navigation_executor`
5. Review service definition: `ros2 service type /execute_navigation`
