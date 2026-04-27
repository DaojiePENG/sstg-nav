import time
import struct
import threading
import serial

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from geometry_msgs.msg import Twist


SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUD = 115200

current_v = 0.0
current_w = 0.0
last_cmd_time = 0.0
timeout_sec = 0.5

lock = threading.Lock()


def float_to_be_bytes(val: float) -> bytes:
    return struct.pack(">f", float(val))


def build_cmd(line_v: float, ang_v: float, third: float = 0.0, cmd_id: int = 1) -> bytes:
    """
    STM32控制帧
    55 55 + 3 float + id + CK1 CK2
    """
    payload = bytearray()
    payload.extend(float_to_be_bytes(line_v))
    payload.extend(float_to_be_bytes(ang_v))
    payload.extend(float_to_be_bytes(third))
    payload.append(cmd_id & 0xFF)

    ck1 = 0
    ck2 = 0
    for b in payload:
        ck1 = (ck1 + b) & 0xFF
        ck2 = (ck2 + ck1) & 0xFF

    frame = bytearray([0x55, 0x55])
    frame.extend(payload)
    frame.append(ck1)
    frame.append(ck2)

    return bytes(frame)


class CmdVelToSerial(Node):

    def __init__(self):
        super().__init__('cmd_vel_to_serial')
        global timeout_sec

        self.declare_parameter("serial_port", SERIAL_PORT)
        self.declare_parameter("serial_baud", SERIAL_BAUD)
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("linear_scale", 200.0)
        self.declare_parameter("angular_scale", 1.0)
        self.declare_parameter("cmd_timeout_sec", timeout_sec)

        self.serial_port = self.get_parameter("serial_port").value
        self.serial_baud = self.get_parameter("serial_baud").value
        self.cmd_vel_topic = self.get_parameter("cmd_vel_topic").value
        self.linear_scale = self.get_parameter("linear_scale").value
        self.angular_scale = self.get_parameter("angular_scale").value
        timeout_sec = float(self.get_parameter("cmd_timeout_sec").value)

        self.get_logger().info(f"Serial target: {self.serial_port} @ {self.serial_baud}")
        self.get_logger().info(f"Subscribe topic: {self.cmd_vel_topic}")
        self.get_logger().info(
            f"Scale: linear={self.linear_scale}, angular={self.angular_scale}, timeout={timeout_sec}s")

        # 初始串口对象为 None，将在发送线程中打开
        self.ser = None
        self.ser_lock = threading.Lock()

        self.create_subscription(
            Twist,
            self.cmd_vel_topic,
            self.cmd_callback,
            10
        )

        self.tx_thread = threading.Thread(target=self.serial_sender, daemon=True)
        self.tx_thread.start()

    def cmd_callback(self, msg: Twist):
        global current_v, current_w, last_cmd_time

        v = msg.linear.x * self.linear_scale
        w = msg.angular.z * self.angular_scale

        with lock:
            current_v = v
            current_w = w
            last_cmd_time = time.time()

        self.get_logger().debug(f'cmd_vel -> v:{v:.2f} w:{w:.2f}')

    def open_serial(self):
        """
        尝试打开串口，成功返回 True，失败返回 False
        """
        try:
            ser = serial.Serial(
                self.serial_port,
                self.serial_baud,
                timeout=0.1,
                rtscts=False,
                dsrdtr=False,
                xonxoff=False,
            )
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            with self.ser_lock:
                self.ser = ser
            self.get_logger().info(f"Serial port {self.serial_port} opened successfully")
            return True
        except Exception as e:
            self.get_logger().error(f"Failed to open serial port {self.serial_port}: {e}")
            return False

    def close_serial(self):
        with self.ser_lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except:
                    pass
            self.ser = None

    def write_serial(self, data: bytes) -> bool:
        """
        线程安全地写数据，返回是否成功
        """
        with self.ser_lock:
            ser = self.ser
        if ser is None or not ser.is_open:
            return False
        try:
            ser.write(data)
            return True
        except (serial.SerialException, OSError, IOError) as e:
            self.get_logger().warn(f"Serial write error: {e}")
            self.close_serial()
            return False

    def serial_sender(self):
        self.get_logger().info("Serial TX thread started")

        # 循环等待串口打开
        while rclpy.ok():
            # 如果串口未打开，尝试打开
            if not self.write_serial(b""): # 简单测试是否可用
                # 先关闭可能残留的连接
                self.close_serial()
                # 尝试打开串口
                if self.open_serial():
                    # 打开成功，继续循环发送数据
                    pass
                else:
                    # 打开失败，等待1秒后重试
                    time.sleep(1.0)
                    continue

            # 获取当前速度指令
            with lock:
                v = current_v
                w = current_w
                t = last_cmd_time

            if time.time() - t > timeout_sec:
                v = 0.0
                w = 0.0

            frame = build_cmd(v, w, 0.0, 1)

            # 发送数据（内部已经处理错误和重述）
            success = self.write_serial(frame)
            if not success:
                # 发送失败，等待一小段时间后重试打开
                time.sleep(0.1)
                continue

            # 控制发送频率10Hz
            time.sleep(0.1)

    def destroy_node(self):
        self.close_serial()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CmdVelToSerial()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
