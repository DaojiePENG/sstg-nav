#!/usr/bin/env python3
"""
WebRTC Camera Bridge — ROS2 双轨道节点

Track 0: RGB 相机画面 (320×240, 15fps)
Track 1: 深度图编码为 RGB (160×120, 10fps) — R=高8位, G=低8位, B=0
信令通道同时推送 camera_info (fx, fy, cx, cy) 供浏览器端 3D 反投影。

依赖:
  pip install aiortc aiohttp av opencv-python-headless

用法:
  ros2 run sstg_system_manager webrtc_camera_bridge
"""

import asyncio
import json
import os
import time
import threading

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CameraInfo

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from av import VideoFrame

# ── 配置 ──

SIGNALING_PORT = 8080

RGB_FPS = 15
RGB_WIDTH = 320
RGB_HEIGHT = 240

DEPTH_FPS = 10
DEPTH_WIDTH = 160
DEPTH_HEIGHT = 120


def ros_image_to_cv2(msg: Image) -> np.ndarray:
    """
    sensor_msgs/Image → OpenCV numpy, 纯 numpy 实现。
    支持 bgr8, rgb8, rgba8, bgra8, mono8, 16uc1 编码。
    """
    dtype = np.uint8
    channels = 3
    encoding = msg.encoding.lower()

    if encoding in ('bgr8', 'rgb8', '8uc3'):
        channels = 3
    elif encoding in ('bgra8', 'rgba8', '8uc4'):
        channels = 4
    elif encoding in ('mono8', '8uc1'):
        channels = 1
    elif encoding in ('16uc1', 'mono16'):
        dtype = np.uint16
        channels = 1
    else:
        channels = 3

    img = np.frombuffer(msg.data, dtype=dtype).reshape(
        msg.height, msg.width, channels)

    if encoding == 'rgb8':
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    elif encoding == 'rgba8':
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    elif encoding == 'bgra8':
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    elif encoding in ('mono8', '8uc1'):
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    return img


def ros_depth_to_16u(msg: Image) -> np.ndarray:
    """sensor_msgs/Image (16UC1 depth) → numpy uint16 数组"""
    encoding = msg.encoding.lower()
    if encoding in ('16uc1', 'mono16'):
        return np.frombuffer(msg.data, dtype=np.uint16).reshape(
            msg.height, msg.width)
    elif encoding in ('32fc1',):
        # 浮点深度(米) → uint16(毫米)
        f32 = np.frombuffer(msg.data, dtype=np.float32).reshape(
            msg.height, msg.width)
        return (f32 * 1000).clip(0, 65535).astype(np.uint16)
    else:
        raise ValueError(f'Unsupported depth encoding: {encoding}')


def encode_depth_as_rgb(depth_16u: np.ndarray, w: int, h: int) -> np.ndarray:
    """
    将 16-bit 深度图编码为 RGB8 伪彩色帧（用于 WebRTC 传输）。
    R = 高 8 位, G = 低 8 位, B = 0
    """
    resized = cv2.resize(depth_16u, (w, h), interpolation=cv2.INTER_NEAREST)
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[:, :, 0] = (resized >> 8).astype(np.uint8)   # R = 高 8 位
    rgb[:, :, 1] = (resized & 0xFF).astype(np.uint8)  # G = 低 8 位
    # B = 0
    return rgb


# ── 帧缓冲 ──

class FrameBuffer:
    """线程安全帧缓冲，供 ROS 回调写入、aiortc track 异步读取。"""

    def __init__(self, fps: int):
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event = asyncio.Event()
        self._last_time = 0.0
        self._interval = 1.0 / fps

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def update(self, frame_rgb: np.ndarray):
        """由 ROS 回调线程调用"""
        now = time.monotonic()
        if now - self._last_time < self._interval:
            return
        self._last_time = now

        with self._lock:
            self._frame = frame_rgb

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._event.set)

    def get(self) -> np.ndarray | None:
        with self._lock:
            return self._frame

    async def wait(self):
        self._event.clear()
        await asyncio.wait_for(self._event.wait(), timeout=2.0)


# ── aiortc VideoStreamTrack ──

class ROSVideoStreamTrack(MediaStreamTrack):
    """从 FrameBuffer 读取帧的 aiortc 视频轨道。"""
    kind = 'video'

    def __init__(self, buf: FrameBuffer, width: int, height: int, label: str):
        super().__init__()
        self._buf = buf
        self._w = width
        self._h = height
        self._label = label
        self._pts = 0

    async def recv(self) -> VideoFrame:
        try:
            await self._buf.wait()
        except asyncio.TimeoutError:
            pass

        frame = self._buf.get()
        if frame is None:
            frame = np.zeros((self._h, self._w, 3), dtype=np.uint8)

        vf = VideoFrame.from_ndarray(frame, format='rgb24')
        vf.pts = self._pts
        vf.time_base = '1/30'
        self._pts += 1
        return vf


# ── ROS2 节点 ──

class CameraBridgeNode(Node):
    """订阅 RGB + Depth + CameraInfo，分别填充帧缓冲。"""

    def __init__(self, rgb_buf: FrameBuffer, depth_buf: FrameBuffer):
        super().__init__('webrtc_camera_bridge')
        self._rgb_buf = rgb_buf
        self._depth_buf = depth_buf

        # 相机内参缓存（只需获取一次）
        self.camera_info: dict | None = None
        self._camera_info_lock = threading.Lock()

        self.create_subscription(
            Image, '/camera/color/image_raw',
            self._rgb_callback, 1)

        self.create_subscription(
            Image, '/camera/depth/image_raw',
            self._depth_callback, 1)

        self.create_subscription(
            CameraInfo, '/camera/depth/camera_info',
            self._camera_info_callback, 1)

        self.get_logger().info(
            f'WebRTC Camera Bridge (dual-track) started on port {SIGNALING_PORT}')

    def _rgb_callback(self, msg: Image):
        try:
            bgr = ros_image_to_cv2(msg)
            if bgr.shape[1] != RGB_WIDTH or bgr.shape[0] != RGB_HEIGHT:
                bgr = cv2.resize(bgr, (RGB_WIDTH, RGB_HEIGHT))
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            self._rgb_buf.update(rgb)
        except Exception as e:
            self.get_logger().warn(
                f'RGB frame error: {e}', throttle_duration_sec=5.0)

    def _depth_callback(self, msg: Image):
        try:
            depth_16u = ros_depth_to_16u(msg)
            depth_rgb = encode_depth_as_rgb(
                depth_16u, DEPTH_WIDTH, DEPTH_HEIGHT)
            self._depth_buf.update(depth_rgb)
        except Exception as e:
            self.get_logger().warn(
                f'Depth frame error: {e}', throttle_duration_sec=5.0)

    def _camera_info_callback(self, msg: CameraInfo):
        with self._camera_info_lock:
            if self.camera_info is not None:
                return  # 只缓存一次
            K = msg.k  # 3×3 内参矩阵 (行优先)
            fx, fy = K[0], K[4]
            cx, cy = K[2], K[5]
            if fx <= 0 or fy <= 0:
                return
            # 缩放到深度帧分辨率
            sx = DEPTH_WIDTH / msg.width
            sy = DEPTH_HEIGHT / msg.height
            self.camera_info = {
                'fx': fx * sx,
                'fy': fy * sy,
                'cx': cx * sx,
                'cy': cy * sy,
                'width': DEPTH_WIDTH,
                'height': DEPTH_HEIGHT,
            }
            self.get_logger().info(
                f'Camera info cached: fx={self.camera_info["fx"]:.1f} '
                f'fy={self.camera_info["fy"]:.1f} '
                f'cx={self.camera_info["cx"]:.1f} '
                f'cy={self.camera_info["cy"]:.1f}')

    def get_camera_info(self) -> dict | None:
        with self._camera_info_lock:
            return self.camera_info


# ── WebRTC 信令 ──

pcs: set[RTCPeerConnection] = set()


async def handle_ws(request):
    """WebSocket 信令 — 双 track + camera_info 推送"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    rgb_buf: FrameBuffer = request.app['rgb_buf']
    depth_buf: FrameBuffer = request.app['depth_buf']
    node: CameraBridgeNode = request.app['node']

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on('connectionstatechange')
    async def on_state():
        state = pc.connectionState
        if state in ('failed', 'closed'):
            await pc.close()
            pcs.discard(pc)
        elif state == 'connected':
            # 连接建立后推送 camera_info
            info = node.get_camera_info()
            if info and ws.closed is False:
                try:
                    await ws.send_json({'type': 'camera_info', **info})
                except Exception:
                    pass

    # 添加两路视频轨道
    rgb_track = ROSVideoStreamTrack(
        rgb_buf, RGB_WIDTH, RGB_HEIGHT, 'rgb')
    depth_track = ROSVideoStreamTrack(
        depth_buf, DEPTH_WIDTH, DEPTH_HEIGHT, 'depth')

    pc.addTrack(rgb_track)
    pc.addTrack(depth_track)

    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            data = json.loads(msg.data)

            if data['type'] == 'offer':
                await pc.setRemoteDescription(
                    RTCSessionDescription(sdp=data['sdp'], type='offer'))
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                await ws.send_json({
                    'type': 'answer',
                    'sdp': pc.localDescription.sdp,
                })

            elif data['type'] == 'get_camera_info':
                # 客户端主动请求 camera_info
                info = node.get_camera_info()
                if info:
                    await ws.send_json({'type': 'camera_info', **info})
                else:
                    await ws.send_json({
                        'type': 'camera_info_pending',
                        'message': 'Waiting for /camera/depth/camera_info',
                    })

            elif data['type'] == 'candidate' and data.get('candidate'):
                pass  # LAN 环境不需要 ICE candidate

        elif msg.type == web.WSMsgType.ERROR:
            break

    await pc.close()
    pcs.discard(pc)
    return ws


async def on_shutdown(app):
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()


def run_ros_spin(node):
    rclpy.spin(node)


def _kill_old_process_on_port(port: int):
    """重启时先杀死占用同一端口的旧进程"""
    import subprocess as _sp
    try:
        result = _sp.run(
            ['fuser', f'{port}/tcp'],
            capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            pids = result.stdout.strip().split()
            my_pid = str(os.getpid())
            for pid in pids:
                if pid != my_pid:
                    try:
                        os.kill(int(pid), 15)
                    except (ProcessLookupError, ValueError):
                        pass
            if pids:
                time.sleep(1.0)
    except Exception:
        pass


def main():
    rclpy.init()

    rgb_buf = FrameBuffer(fps=RGB_FPS)
    depth_buf = FrameBuffer(fps=DEPTH_FPS)
    node = CameraBridgeNode(rgb_buf, depth_buf)

    ros_thread = threading.Thread(
        target=run_ros_spin, args=(node,), daemon=True)
    ros_thread.start()

    _kill_old_process_on_port(SIGNALING_PORT)

    app = web.Application()
    app['rgb_buf'] = rgb_buf
    app['depth_buf'] = depth_buf
    app['node'] = node
    app.router.add_get('/ws', handle_ws)
    app.on_shutdown.append(on_shutdown)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    rgb_buf.set_loop(loop)
    depth_buf.set_loop(loop)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            web.run_app(app, host='0.0.0.0', port=SIGNALING_PORT, loop=loop)
            break
        except OSError as e:
            if 'Address already in use' in str(e) and attempt < max_retries - 1:
                node.get_logger().warn(
                    f'Port {SIGNALING_PORT} busy, retrying in 2s '
                    f'({attempt + 1}/{max_retries})...')
                time.sleep(2.0)
                _kill_old_process_on_port(SIGNALING_PORT)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                rgb_buf.set_loop(loop)
                depth_buf.set_loop(loop)
            else:
                node.get_logger().error(
                    f'Cannot bind port {SIGNALING_PORT}: {e}')
                break
        except KeyboardInterrupt:
            break

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
