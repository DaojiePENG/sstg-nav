import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from tf2_ros import Buffer, TransformListener
from numpy import array
from nav2_msgs.action import NavigateToPose
from nav_msgs.srv import GetPlan
from geometry_msgs.msg import PoseStamped
from action_msgs.msg import GoalStatus
from numpy import floor
from numpy.linalg import norm
from numpy import inf
# ________________________________________________________________________________


class robot:
    start = PoseStamped()
    end = PoseStamped()

    def __init__(self, node, name):
        self.node = node
        self.assigned_point = []
        self.name = name

        if node.has_parameter('global_frame'):
            self.global_frame = node.get_parameter('global_frame').value
        else:
            self.global_frame = 'map'

        if node.has_parameter('robot_frame'):
            self.robot_frame = node.get_parameter('robot_frame').value
        else:
            self.robot_frame = 'base_link'

        if node.has_parameter('plan_service'):
            self.plan_service = node.get_parameter('plan_service').value
        else:
            self.plan_service = '/plan'

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, node)

        # Wait for transform
        self.node.get_logger().info('Waiting for the robot transform')
        while rclpy.ok():
            try:
                frame_id = self.name + '/' + self.robot_frame if self.name else self.robot_frame
                trans = self.tf_buffer.lookup_transform(
                    self.global_frame,
                    frame_id,
                    rclpy.time.Time())
                break
            except Exception as e:
                rclpy.spin_once(self.node, timeout_sec=0.1)

        self.position = array([trans.transform.translation.x, trans.transform.translation.y])
        self.assigned_point = self.position

        action_name = self.name + '/navigate_to_pose' if self.name else 'navigate_to_pose'
        self.client = ActionClient(self.node, NavigateToPose, action_name)
        self.client.wait_for_server()

        self.goal_handle = None
        self.goal_status = 0  # 0: idle, 1: busy
        self.goal_event_callback = None
        self.active_goal_id = None

        self.make_plan_client = self.node.create_client(GetPlan, self.name+self.plan_service)
        robot.start.header.frame_id = self.global_frame
        robot.end.header.frame_id = self.global_frame

    def set_goal_event_callback(self, callback):
        self.goal_event_callback = callback

    def _emit_goal_event(self, event_type, goal_id, point, nav_status=0):
        if self.goal_event_callback is None or point is None:
            return
        self.goal_event_callback(
            robot_name=self.name,
            goal_id=goal_id,
            event_type=event_type,
            point=array(point, dtype=float),
            nav_status=int(nav_status),
        )

    def getPosition(self):
        try:
            frame_id = self.name + '/' + self.robot_frame if self.name else self.robot_frame
            trans = self.tf_buffer.lookup_transform(
                self.global_frame,
                frame_id,
                rclpy.time.Time())
            self.position = array([trans.transform.translation.x, trans.transform.translation.y])
        except Exception as e:
            self.node.get_logger().warn(f'Transform lookup failed: {e}')
        return self.position

    def sendGoal(self, point, goal_id=None):
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = self.global_frame
        goal_msg.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = float(point[0])
        goal_msg.pose.pose.position.y = float(point[1])
        goal_msg.pose.pose.orientation.w = 1.0

        self.goal_status = 1  # busy
        point_array = array(point, dtype=float)
        context = {
            'goal_id': goal_id if goal_id is not None else -1,
            'point': point_array,
        }
        self.active_goal_id = context['goal_id']
        future = self.client.send_goal_async(goal_msg)
        future.add_done_callback(lambda fut, ctx=context: self._goal_response_callback(fut, ctx))
        self.assigned_point = point_array
        self._emit_goal_event('assigned', context['goal_id'], point_array, GoalStatus.STATUS_ACCEPTED)

    def _goal_response_callback(self, future, context):
        self.goal_handle = future.result()
        if self.goal_handle.accepted:
            result_future = self.goal_handle.get_result_async()
            result_future.add_done_callback(lambda fut, ctx=context: self._goal_result_callback(fut, ctx))
            return

        if context['goal_id'] == self.active_goal_id:
            self.goal_status = 0
        self._emit_goal_event('failed', context['goal_id'], context['point'], GoalStatus.STATUS_ABORTED)

    def _goal_result_callback(self, future, context):
        status = future.result().status
        if context['goal_id'] == self.active_goal_id:
            self.goal_status = 0  # idle
            self.active_goal_id = None

        if status == GoalStatus.STATUS_SUCCEEDED:
            event_type = 'reached'
        elif status == GoalStatus.STATUS_CANCELED:
            event_type = 'canceled'
        else:
            event_type = 'failed'
        self._emit_goal_event(event_type, context['goal_id'], context['point'], status)

    def getState(self):
        return self.goal_status

    def cancelGoal(self):
        if self.goal_handle:
            self.goal_handle.cancel_goal_async()
        self.goal_status = 0
        self.active_goal_id = None
        self.assigned_point = self.getPosition()
# ________________________________________________________________________________


def index_of_point(mapData, Xp):
    resolution = mapData.info.resolution
    Xstartx = mapData.info.origin.position.x
    Xstarty = mapData.info.origin.position.y
    width = mapData.info.width
    height = mapData.info.height
    col = int(floor((Xp[0] - Xstartx) / resolution))
    row = int(floor((Xp[1] - Xstarty) / resolution))
    if col < 0 or col >= width or row < 0 or row >= height:
        return -1
    index = int((floor((Xp[1]-Xstarty)/resolution) * width) +
                (floor((Xp[0]-Xstartx)/resolution)))
    return index


def point_of_index(mapData, i):
    row = i // mapData.info.width
    col = i % mapData.info.width
    y = mapData.info.origin.position.y + row * mapData.info.resolution
    x = mapData.info.origin.position.x + col * mapData.info.resolution
    return array([x, y])
# ________________________________________________________________________________


def point_in_map(mapData, Xp):
    return index_of_point(mapData, Xp) >= 0
# ________________________________________________________________________________


def informationGain(mapData, point, r):
    infoGain = 0
    index = index_of_point(mapData, point)
    if index < 0:
        return 0.0
    r_region = int(r/mapData.info.resolution)
    init_index = index-r_region*(mapData.info.width+1)
    for n in range(0, 2*r_region+1):
        start = n*mapData.info.width+init_index
        end = start+2*r_region
        limit = ((start // mapData.info.width)+2)*mapData.info.width
        for i in range(start, end+1):
            if (i >= 0 and i < limit and i < len(mapData.data)):
                if(mapData.data[i] == -1 and norm(array(point)-point_of_index(mapData, i)) <= r):
                    infoGain += 1
    return infoGain*(mapData.info.resolution**2)
# ________________________________________________________________________________


def discount(mapData, assigned_pt, centroids, infoGain, r):
    index = index_of_point(mapData, assigned_pt)
    if index < 0:
        return infoGain
    r_region = int(r/mapData.info.resolution)
    init_index = index-r_region*(mapData.info.width+1)
    for n in range(0, 2*r_region+1):
        start = n*mapData.info.width+init_index
        end = start+2*r_region
        limit = ((start // mapData.info.width)+2)*mapData.info.width
        for i in range(start, end+1):
            if (i >= 0 and i < limit and i < len(mapData.data)):
                for j in range(0, len(centroids)):
                    current_pt = centroids[j]
                    if(mapData.data[i] == -1 and norm(point_of_index(mapData, i)-current_pt) <= r and norm(point_of_index(mapData, i)-assigned_pt) <= r):
                        infoGain[j] -= 1
    return infoGain
# ________________________________________________________________________________


def pathCost(path):
    if (len(path) > 0):
        i = len(path)//2
        p1 = array([path[i-1].pose.position.x, path[i-1].pose.position.y])
        p2 = array([path[i].pose.position.x, path[i].pose.position.y])
        return norm(p1-p2)*(len(path)-1)
    else:
        return inf
# ________________________________________________________________________________


def unvalid(mapData, pt):
    index = index_of_point(mapData, pt)
    if index < 0:
        return True
    r_region = 5
    init_index = index-r_region*(mapData.info.width+1)
    for n in range(0, 2*r_region+1):
        start = n*mapData.info.width+init_index
        end = start+2*r_region
        limit = ((start // mapData.info.width)+2)*mapData.info.width
        for i in range(start, end+1):
            if (i >= 0 and i < limit and i < len(mapData.data)):
                if(mapData.data[i] == 1):
                    return True
    return False
# ________________________________________________________________________________


def Nearest(V, x):
    n = inf
    result = 0
    for i in range(0, V.shape[0]):
        n1 = norm(V[i, :]-x)
        if (n1 < n):
            n = n1
            result = i
    return result
# ________________________________________________________________________________


def Nearest2(V, x):
    n = inf
    result = 0
    for i in range(0, len(V)):
        n1 = norm(V[i]-x)
        if (n1 < n):
            n = n1
            result = i
    return result
# ________________________________________________________________________________


def gridValue(mapData, Xp):
    Data = mapData.data
    index = index_of_point(mapData, Xp)
    if index < 0 or index >= len(Data):
        return 100
    return Data[index]
