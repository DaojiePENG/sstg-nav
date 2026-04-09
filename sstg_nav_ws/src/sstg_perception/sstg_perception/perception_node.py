"""
SSTG Perception Node - 感知和语义标注 ROS2 节点
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
import os
from pathlib import Path
import math

from tf2_ros import Buffer, TransformListener, TransformException

try:
    import sstg_msgs.msg as sstg_msg
    import sstg_msgs.srv as sstg_srv
except ImportError:
    # 如果直接运行，使用空模块代替
    class DummyModule:
        pass
    sstg_msg = DummyModule()
    sstg_srv = DummyModule()

from sstg_perception.camera_subscriber import CameraSubscriber
from sstg_perception.panorama_capture import PanoramaCapture
from sstg_perception.vlm_client import VLMClientWithRetry
from sstg_perception.semantic_extractor import SemanticExtractor, SemanticInfo

DEFAULT_PANORAMA_STORAGE_PATH = (
    '/home/jetson/wbt_ws/sstg-nav/sstg_nav_ws/src/'
    'sstg_rrt_explorer/captured_nodes'
)


class PerceptionNode(Node):
    """
    SSTG 感知节点
    
    功能：
    - RGB-D 图像采集
    - 四方向全景图采集
    - VLM 语义标注
    - 结果发布
    """
    
    def __init__(self):
        super().__init__('perception_node')
        
        # 参数配置 - API Key 优先从环境变量读取
        api_key_from_env = os.getenv('DASHSCOPE_API_KEY', '')
        self.declare_parameter('api_key', api_key_from_env)
        self.declare_parameter('api_base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.declare_parameter('vlm_model', 'qwen-vl-plus')
        self.declare_parameter('panorama_storage_path', DEFAULT_PANORAMA_STORAGE_PATH)
        self.declare_parameter('rgb_topic', '/camera/color/image_raw')
        self.declare_parameter('depth_topic', '/camera/depth/image_raw')
        self.declare_parameter('confidence_threshold', 0.5)
        self.declare_parameter('max_retries', 3)
        
        # 从参数获取 API Key（环境变量已设置为默认值）
        self.api_key = self.get_parameter('api_key').value
        self.api_base_url = self.get_parameter('api_base_url').value
        self.vlm_model = self.get_parameter('vlm_model').value
        self.panorama_storage_path = self.get_parameter('panorama_storage_path').value
        self.rgb_topic = self.get_parameter('rgb_topic').value
        self.depth_topic = self.get_parameter('depth_topic').value
        self.confidence_threshold = self.get_parameter('confidence_threshold').value
        self.max_retries = self.get_parameter('max_retries').value
        
        # 验证 API Key
        if not self.api_key:
            self.get_logger().warn('API Key not configured. VLM annotation will be disabled.')
        
        # 初始化相机订阅器
        self.camera_subscriber = CameraSubscriber(
            rgb_topic=self.rgb_topic,
            depth_topic=self.depth_topic
        )
        self.camera_subscriber.start_background_spin()

        # TF 查询：用于读取当前真实朝向，避免仅依赖请求里的目标 yaw
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # 初始化全景图采集器（传入相机订阅器）
        self.panorama_capture = PanoramaCapture(
            camera_subscriber=self.camera_subscriber,
            storage_path=self.panorama_storage_path,
            enable_navigation=True,  # 启用自动导航
            heading_provider=self._lookup_current_heading_deg,
        )
        self.panorama_capture.set_logger(self.get_logger().info)
        
        # 初始化 VLM 客户端
        if self.api_key:
            self.vlm_client = VLMClientWithRetry(
                api_key=self.api_key,
                base_url=self.api_base_url,
                model=self.vlm_model,
                max_retries=self.max_retries
            )
            self.vlm_client.set_logger(self.get_logger().info)
        else:
            self.vlm_client = None
        
        # 初始化语义提取器
        self.extractor = SemanticExtractor(confidence_threshold=self.confidence_threshold)
        self.extractor.set_logger(self.get_logger().info)
        
        # 发布器
        self.semantic_pub = self.create_publisher(
            sstg_msg.SemanticAnnotation,
            'semantic_annotations',
            qos_profile=QoSProfile(depth=10)
        )
        
        # 服务
        self.create_service(
            sstg_srv.CaptureImage,
            'capture_panorama',
            self._capture_panorama_callback
        )
        
        self.create_service(
            sstg_srv.AnnotateSemantic,
            'annotate_semantic',
            self._annotate_semantic_callback
        )

        self.create_service(
            sstg_srv.CheckObjectPresence,
            'check_object_presence',
            self._check_object_presence_callback
        )

        self.get_logger().info('Perception Node initialized successfully')
    
    def _capture_panorama_callback(self, request, response):
        """
        全景图采集服务回调

        自动完成：导航到目标位姿 → 旋转采集四个方向 → 返回结果
        """
        try:
            node_id = request.node_id

            # 解析位姿
            pose_stamped = request.pose
            pose = {
                'x': float(pose_stamped.pose.position.x),
                'y': float(pose_stamped.pose.position.y),
                'theta': self._quaternion_to_yaw(pose_stamped.pose.orientation)
            }
            frame_id = pose_stamped.header.frame_id or 'map'

            self.get_logger().info(
                f'📸 Panorama capture request: node={node_id}, '
                f'pose=({pose["x"]:.2f}, {pose["y"]:.2f}, {pose["theta"]:.1f}°)'
            )

            if not self.camera_subscriber.has_publishers():
                response.success = False
                response.error_message = (
                    f'Camera driver not publishing: {self.rgb_topic}, {self.depth_topic}'
                )
                self.get_logger().error(response.error_message)
                return response

            # 检查相机就绪
            if not self.camera_subscriber.is_ready():
                self.get_logger().warn('Camera not ready, waiting...')
                if not self.camera_subscriber.wait_for_images(timeout=5.0):
                    response.success = False
                    response.error_message = 'Camera not responding'
                    return response

            # 调用新的采集方法（自动导航+旋转+采集）
            panorama_data = self.panorama_capture.capture_at_pose(
                node_id=node_id,
                pose=pose,
                frame_id=frame_id,
                navigate=True,  # 启用导航
                wait_after_rotation=4.0
            )

            if panorama_data is None:
                response.success = False
                response.error_message = 'Panorama capture failed'
                return response

            # 构造响应
            images_dict = panorama_data.get('images', {})
            response.success = bool(panorama_data.get('complete', False))
            response.error_message = panorama_data.get('error_message', '')
            images_dict = panorama_data['images']
            response.image_paths = [
                f"{angle}:{path}" for angle, path in sorted(images_dict.items())
            ]

            if response.success:
                self.get_logger().info(
                    f'✅ Panorama captured successfully: {len(images_dict)} images'
                )
            else:
                self.get_logger().warn(
                    f'⚠️  Panorama incomplete: {len(images_dict)} images, '
                    f'error={response.error_message}'
                )

        except Exception as e:
            response.success = False
            response.error_message = str(e)
            self.get_logger().error(f'❌ Capture error: {e}')
            import traceback
            self.get_logger().error(traceback.format_exc())

        return response

    def _quaternion_to_yaw(self, q) -> float:
        """将四元数转换为yaw角度（度）"""
        # yaw = atan2(2*(w*z + x*y), 1 - 2*(y^2 + z^2))
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw_rad = math.atan2(siny_cosp, cosy_cosp)
        return math.degrees(yaw_rad)

    def _lookup_current_heading_deg(self, frame_id: str = 'map') -> float | None:
        """查询机器人当前在目标坐标系下的真实朝向。"""
        try:
            transform = self.tf_buffer.lookup_transform(
                frame_id,
                'base_footprint',
                rclpy.time.Time(),
                timeout=rclpy.duration.Duration(seconds=0.3),
            )
        except TransformException as exc:
            self.get_logger().warn(
                f'Cannot lookup heading transform {frame_id} -> base_footprint: {exc}'
            )
            return None

        return self._quaternion_to_yaw(transform.transform.rotation)
    
    def _annotate_semantic_callback(self, request, response):
        """
        语义标注服务回调
        
        参数: image_path, node_id (可选)
        """
        try:
            image_path = request.image_path
            node_id = request.node_id
            
            self.get_logger().info(f'Annotating semantic for: {image_path}')
            
            if not Path(image_path).exists():
                response.success = False
                response.error_message = f'Image not found: {image_path}'
                return response
            
            # 调用 VLM
            if not self.vlm_client:
                response.success = False
                response.error_message = 'VLM client not configured'
                return response
            
            vlm_response = self.vlm_client.call_semantic_annotation(image_path)
            
            if not vlm_response.success:
                response.success = False
                response.error_message = vlm_response.error
                return response
            
            # 提取语义信息
            success, semantic_info, error = self.extractor.extract_semantic_info(
                vlm_response.content
            )
            
            if not success:
                response.success = False
                response.error_message = f'Failed to extract semantic: {error}'
                return response
            
            # 构建响应
            response.success = True
            response.room_type = semantic_info.room_type
            response.description = semantic_info.description
            response.confidence = semantic_info.confidence
            
            for obj in semantic_info.objects:
                semantic_obj = sstg_msg.SemanticObject()
                semantic_obj.name = obj.name
                semantic_obj.position = obj.position
                semantic_obj.quantity = obj.quantity
                semantic_obj.confidence = obj.confidence
                response.objects.append(semantic_obj)
            
            # 发布标注结果
            self._publish_semantic_annotation(
                node_id, image_path, semantic_info
            )
            
            self.get_logger().info(
                f'✓ Semantic annotation complete: room={semantic_info.room_type}, '
                f'objects={len(semantic_info.objects)}'
            )
            
        except Exception as e:
            response.success = False
            response.error_message = str(e)
            self.get_logger().error(f'Annotation error: {e}')
        
        return response

    def _check_object_presence_callback(self, request, response):
        """
        VLM 物体存在性确认服务回调

        给定一张图和目标物体名，用 VLM 判断图中是否存在该物体。
        """
        try:
            image_path = request.image_path
            target_object = request.target_object

            self.get_logger().info(
                f'Checking object presence: "{target_object}" in {image_path}')

            if not Path(image_path).exists():
                response.found = False
                response.confidence = 0.0
                response.description = ''
                response.error_message = f'Image not found: {image_path}'
                return response

            if not self.vlm_client:
                response.found = False
                response.confidence = 0.0
                response.description = ''
                response.error_message = 'VLM client not configured'
                return response

            prompt = (
                f'请仔细观察这张图片，判断图中是否有"{target_object}"。\n'
                f'请用以下 JSON 格式回复：\n'
                f'{{"found": true/false, "confidence": 0.0-1.0, '
                f'"description": "简短描述物体位置和状态"}}\n'
                f'只回复 JSON，不要其他内容。'
            )

            vlm_response = self.vlm_client.call_semantic_annotation(
                image_path, prompt=prompt)

            if not vlm_response.success:
                response.found = False
                response.confidence = 0.0
                response.description = ''
                response.error_message = f'VLM call failed: {vlm_response.error}'
                return response

            # 解析 VLM 返回的 JSON
            import json
            try:
                content = vlm_response.content.strip()
                # 处理可能的 markdown 代码块
                if content.startswith('```'):
                    content = content.split('\n', 1)[1]
                    content = content.rsplit('```', 1)[0]
                result = json.loads(content)
                response.found = bool(result.get('found', False))
                response.confidence = float(result.get('confidence', 0.0))
                response.description = str(result.get('description', ''))
                response.error_message = ''
            except (json.JSONDecodeError, ValueError) as e:
                # VLM 返回非标准 JSON，尝试从文本推断
                text = vlm_response.content.lower()
                response.found = '是' in text or 'true' in text or '有' in text
                response.confidence = 0.5 if response.found else 0.3
                response.description = vlm_response.content[:200]
                response.error_message = ''

            self.get_logger().info(
                f'Object check result: found={response.found}, '
                f'confidence={response.confidence:.2f}')

        except Exception as e:
            response.found = False
            response.confidence = 0.0
            response.description = ''
            response.error_message = str(e)
            self.get_logger().error(f'Object check error: {e}')

        return response

    def _publish_semantic_annotation(self, node_id: int, image_path: str,
                                    semantic_info: SemanticInfo) -> None:
        """发布语义标注消息"""
        from geometry_msgs.msg import Pose
        
        msg = sstg_msg.SemanticAnnotation()
        msg.node_id = node_id
        msg.image_path = image_path
        msg.timestamp = self.get_clock().now().to_msg()
        msg.pose = Pose()  # 默认姿态
        
        # 创建 SemanticData
        semantic_data = sstg_msg.SemanticData()
        semantic_data.room_type = semantic_info.room_type
        semantic_data.description = semantic_info.description
        semantic_data.confidence = semantic_info.confidence
        
        for obj in semantic_info.objects:
            semantic_obj = sstg_msg.SemanticObject()
            semantic_obj.name = obj.name
            semantic_obj.position = obj.position
            semantic_obj.quantity = obj.quantity
            semantic_obj.confidence = obj.confidence
            semantic_data.objects.append(semantic_obj)
        
        msg.semantic_data = semantic_data
        self.semantic_pub.publish(msg)
    
    def destroy_node(self):
        """清理资源"""
        if self.panorama_capture:
            self.panorama_capture.shutdown()
        if self.camera_subscriber:
            self.camera_subscriber.destroy_node()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print('\nShutting down...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
