import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Quaternion, TransformStamped
from tf2_ros import TransformBroadcaster

import paho.mqtt.client as mqtt
import json
import math
import threading


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def euler_to_quaternion(roll, pitch, yaw) -> Quaternion:
    """将欧拉角转换为四元数"""
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)

    q = Quaternion()
    q.w = cr * cp * cy + sr * sp * sy
    q.x = sr * cp * cy - cr * sp * sy
    q.y = cr * sp * cy + sr * cp * sy
    q.z = cr * cp * sy - sr * sp * cy
    return q


def get_first_float(data, keys, default):
    for key in keys:
        if key not in data:
            continue
        value = data.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default

class MqttToRosBridge(Node):
    def __init__(self):
        """
        初始化节点，设置ROS参数、发布器、MQTT客户端和50Hz定时器。
        """
        super().__init__('mqtt_to_ros_bridge_node')

        # --- ROS 2 参数声明 ---
        self.declare_parameter('mqtt_broker_ip', '192.168.0.6') # 默认IP，可从外部更改
        self.declare_parameter('mqtt_port', 1883)
        self.declare_parameter('mqtt_topic', 'wifi/car_status')
        self.declare_parameter('imu_topic', 'imu')
        self.declare_parameter('odom_topic', 'odom')
        self.declare_parameter('odom_frame_id', 'odom')
        self.declare_parameter('base_frame_id', 'base_footprint')
        self.declare_parameter('publish_rate', 50.0)
        self.declare_parameter('publish_tf', True)
        self.declare_parameter('yaw_in_degrees', True)
        self.declare_parameter('yaw_offset', 0.0)
        self.declare_parameter('linear_velocity_scale', 1.0)
        self.declare_parameter('angular_velocity_scale', 1.0)
        self.declare_parameter('data_timeout_sec', 2.0)

        # --- 获取参数值 ---
        self.broker_address = self.get_parameter('mqtt_broker_ip').get_parameter_value().string_value
        self.port = self.get_parameter('mqtt_port').get_parameter_value().integer_value
        self.mqtt_topic = self.get_parameter('mqtt_topic').get_parameter_value().string_value
        imu_topic = self.get_parameter('imu_topic').get_parameter_value().string_value
        odom_topic = self.get_parameter('odom_topic').get_parameter_value().string_value
        self.odom_frame_id = self.get_parameter('odom_frame_id').get_parameter_value().string_value
        self.base_frame_id = self.get_parameter('base_frame_id').get_parameter_value().string_value
        publish_rate = self.get_parameter('publish_rate').get_parameter_value().double_value
        self.publish_tf = self.get_parameter('publish_tf').get_parameter_value().bool_value
        self.yaw_in_degrees = self.get_parameter('yaw_in_degrees').get_parameter_value().bool_value
        self.yaw_offset = self.get_parameter('yaw_offset').get_parameter_value().double_value
        self.linear_velocity_scale = self.get_parameter(
            'linear_velocity_scale'
        ).get_parameter_value().double_value
        self.angular_velocity_scale = self.get_parameter(
            'angular_velocity_scale'
        ).get_parameter_value().double_value
        self.data_timeout_sec = self.get_parameter(
            'data_timeout_sec'
        ).get_parameter_value().double_value

        self.get_logger().info(f"将连接到 MQTT Broker: {self.broker_address}:{self.port}")
        self.get_logger().info(f"订阅 MQTT 主题: '{self.mqtt_topic}'")

        # --- ROS 2 发布器 ---
        self.imu_publisher = self.create_publisher(Imu, imu_topic, 10)
        self.odom_publisher = self.create_publisher(Odometry, odom_topic, 10)
        self.tf_broadcaster = TransformBroadcaster(self) if self.publish_tf else None

        # --- 存储从MQTT接收到的最新数据 ---
        self.latest_data = {
            "linear_velocity_x": 0.0,
            "angular_velocity_z": 0.0,
            "yaw_angle": 0.0,
            "linear_acceleration_x": 0.0,
        }
        self.last_msg_time = None
        self.stale_warning_active = False
        self.data_lock = threading.Lock() # 线程锁，用于安全地访问 self.latest_data

        # --- 里程计状态变量 ---
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0
        self.last_time = self.get_clock().now()

        # --- 初始化并启动 MQTT 客户端 ---
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect
        self.connect_mqtt()

        # --- 创建一个50Hz的定时器来发布ROS话题 ---
        self.timer = self.create_timer(1.0 / publish_rate, self.timer_callback)

    def connect_mqtt(self):
        """尝试连接到MQTT代理。"""
        try:
            self.get_logger().info("正在连接 MQTT...")
            self.mqtt_client.connect(self.broker_address, self.port, 60)
            self.mqtt_client.loop_start() # 在后台线程中处理网络循环
        except Exception as e:
            self.get_logger().error(f"无法连接到 MQTT Broker: {e}")
            self.get_logger().info("将在5秒后重试...")
            # 使用ROS的定时器进行重连尝试，避免阻塞构造函数
            self.create_timer(5.0, self.reconnect_mqtt)

    def reconnect_mqtt(self):
        """重连函数"""
        # 这是一个一次性定时器，执行后销毁
        # 如果连接再次失败，connect_mqtt 会创建新的重连定时器
        self.connect_mqtt()

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT连接成功时的回调函数。"""
        if rc == 0:
            self.get_logger().info("成功连接到 MQTT Broker!")
            self.mqtt_client.subscribe(self.mqtt_topic)
            self.get_logger().info(f"已订阅主题: {self.mqtt_topic}")
        else:
            self.get_logger().error(f"MQTT 连接失败，返回码: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """MQTT断开连接时的回调函数。"""
        self.get_logger().warn(f"MQTT 断开连接，返回码: {rc}。正在尝试重连...")
        # paho-mqtt 的 loop*() 会自动处理重连，但我们也可以在这里添加额外的逻辑
        # 这里我们简单地记录日志，因为 loop_start() 已经包含了重连逻辑

    def _on_message(self, client, userdata, msg):
        """接收到MQTT消息时的回调函数。"""
        try:
            payload = msg.payload.decode("utf-8")
            data = json.loads(payload)

            # 使用线程锁安全地更新数据
            with self.data_lock:
                self.latest_data["linear_velocity_x"] = get_first_float(
                    data,
                    ("linear_velocity_x", "line_v", "v"),
                    self.latest_data["linear_velocity_x"],
                )
                self.latest_data["angular_velocity_z"] = get_first_float(
                    data,
                    ("angular_velocity_z", "w"),
                    self.latest_data["angular_velocity_z"],
                )
                self.latest_data["yaw_angle"] = get_first_float(
                    data,
                    ("yaw_angle", "Yaw", "yaw"),
                    self.latest_data["yaw_angle"],
                )
                self.latest_data["linear_acceleration_x"] = get_first_float(
                    data,
                    ("linear_acceleration_x", "acc_x"),
                    self.latest_data["linear_acceleration_x"],
                )
                self.last_msg_time = self.get_clock().now()
                self.stale_warning_active = False

            self.get_logger().debug(
                f"MQTT payload mapped: v={self.latest_data['linear_velocity_x']:.3f}, "
                f"w={self.latest_data['angular_velocity_z']:.3f}, "
                f"yaw={self.latest_data['yaw_angle']:.3f}, "
                f"ax={self.latest_data['linear_acceleration_x']:.3f}"
            )

        except json.JSONDecodeError:
            self.get_logger().warn(f"无法解码来自主题 '{msg.topic}' 的JSON消息: {msg.payload.decode('utf-8')}")
        except Exception as e:
            self.get_logger().error(f"处理MQTT消息时发生错误: {e}")

    def timer_callback(self):
        """
        定时器回调函数，以50Hz频率执行。
        负责构建并发布 Imu 和 Odometry 消息。
        """
        current_time = self.get_clock().now()

        # --- 安全地读取最新数据 ---
        with self.data_lock:
            vx = self.latest_data["linear_velocity_x"] * self.linear_velocity_scale
            wz = self.latest_data["angular_velocity_z"] * self.angular_velocity_scale
            yaw = self.latest_data["yaw_angle"]
            ax = self.latest_data["linear_acceleration_x"]
            last_msg_time = self.last_msg_time

        if last_msg_time is None:
            data_age = float('inf')
        else:
            data_age = (current_time - last_msg_time).nanoseconds / 1e9

        if data_age > self.data_timeout_sec:
            vx = 0.0
            wz = 0.0
            ax = 0.0
            if not self.stale_warning_active:
                self.get_logger().warn(
                    f'MQTT odom data stale for {data_age:.2f}s; publishing zero velocity.'
                )
                self.stale_warning_active = True

        if self.yaw_in_degrees:
            yaw = math.radians(yaw)
        yaw = normalize_angle(yaw + self.yaw_offset)

        # --- 发布IMU消息 ---
        imu_msg = Imu()
        imu_msg.header.stamp = current_time.to_msg()
        imu_msg.header.frame_id = self.base_frame_id

        # 方向 (从偏航角转换)
        imu_msg.orientation = euler_to_quaternion(0.0, 0.0, yaw)
        
        # 角速度
        imu_msg.angular_velocity.x = 0.0
        imu_msg.angular_velocity.y = 0.0
        imu_msg.angular_velocity.z = wz

        # 线加速度
        imu_msg.linear_acceleration.x = ax
        imu_msg.linear_acceleration.y = 0.0 # 假设Y轴加速度为0
        imu_msg.linear_acceleration.z = 0.0 # 假设Z轴加速度为0

        # 协方差矩阵（可以根据传感器精度进行调整）
        # 这里使用简化的值，表示我们对测量值有一定的信心
        imu_msg.orientation_covariance[0] = 1.0
        imu_msg.orientation_covariance[4] = 1.0
        imu_msg.orientation_covariance[8] = 0.05
        imu_msg.angular_velocity_covariance[0] = 0.01
        imu_msg.angular_velocity_covariance[4] = 0.01
        imu_msg.angular_velocity_covariance[8] = 0.01
        imu_msg.linear_acceleration_covariance[0] = 0.01
        imu_msg.linear_acceleration_covariance[4] = 0.01
        imu_msg.linear_acceleration_covariance[8] = 0.01

        self.imu_publisher.publish(imu_msg)

        # --- 计算并发布Odometry消息 ---
        dt = (current_time - self.last_time).nanoseconds / 1e9

        # 使用运动学模型进行积分，估算位姿
        # 注意：这里我们使用从IMU/MQTT直接获得的偏航角(yaw)来计算方向，
        # 而不是对角速度(wz)积分。这通常更准确，因为它避免了漂移。
        # 位置则通过对线速度积分得到。
        delta_x = vx * math.cos(self.theta) * dt
        delta_y = vx * math.sin(self.theta) * dt
        
        self.x += delta_x
        self.y += delta_y
        self.theta = yaw # 直接使用最新的偏航角作为方向

        odom_msg = Odometry()
        odom_msg.header.stamp = current_time.to_msg()
        odom_msg.header.frame_id = self.odom_frame_id
        odom_msg.child_frame_id = self.base_frame_id

        # 设置位姿
        odom_msg.pose.pose.position.x = self.x
        odom_msg.pose.pose.position.y = self.y
        odom_msg.pose.pose.position.z = 0.0
        odom_msg.pose.pose.orientation = euler_to_quaternion(0.0, 0.0, self.theta)

        # 设置速度
        odom_msg.twist.twist.linear.x = vx
        odom_msg.twist.twist.linear.y = 0.0
        odom_msg.twist.twist.angular.z = wz

        # 协方差矩阵（同样，可以根据实际情况调整）
        odom_msg.pose.covariance[0] = 0.1 # x
        odom_msg.pose.covariance[7] = 0.1 # y
        odom_msg.pose.covariance[35] = 0.2 # yaw
        odom_msg.twist.covariance[0] = 0.1 # vx
        odom_msg.twist.covariance[35] = 0.2 # wz

        self.odom_publisher.publish(odom_msg)
        
        if self.tf_broadcaster is not None:
            t = TransformStamped()
            t.header.stamp = current_time.to_msg()
            t.header.frame_id = self.odom_frame_id
            t.child_frame_id = self.base_frame_id
            t.transform.translation.x = self.x
            t.transform.translation.y = self.y
            t.transform.translation.z = 0.0
            t.transform.rotation = odom_msg.pose.pose.orientation
            self.tf_broadcaster.sendTransform(t)

        self.last_time = current_time

    def destroy_node(self):
        """节点销毁时，断开MQTT连接。"""
        self.get_logger().info("正在关闭 MQTT 客户端...")
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = MqttToRosBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
