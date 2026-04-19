"""
SSTG Perception Node - 感知和语义标注 ROS2 节点
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from rclpy.callback_groups import ReentrantCallbackGroup, MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
import json
import os
import time
from pathlib import Path
import math

from tf2_ros import Buffer, TransformListener, TransformException
from geometry_msgs.msg import Twist

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
from sstg_perception.search_trace import search_trace as _search_trace_raw

DEFAULT_PANORAMA_STORAGE_PATH = (
    os.path.expanduser('~/wbt_ws/sstg-nav/sstg_nav_ws/src/')
    + 'sstg_rrt_explorer/captured_nodes'
)

# UI AI 引擎配置 single-source-of-truth（与 vite-plugins/chatSyncPlugin.ts 对齐）
LLM_CONFIG_PATH = os.path.expanduser('~/sstg-data/chat/llm-config.json')


def _load_llm_config_from_ui() -> dict:
    """
    从 UI 持久化的 llm-config.json 读取当前激活 provider。

    返回 {api_key, base_url, model, provider, source}；全部字段可能为空。
    只有 llm-config.json 存在且 activeProvider 有 apiKey 时才返回有内容的 dict。
    """
    try:
        with open(LLM_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    active = cfg.get('activeProvider', '')
    providers = cfg.get('providers', {})
    if not active or active not in providers:
        return {}

    p = providers[active] or {}
    return {
        'api_key': (p.get('apiKey') or '').strip(),
        'base_url': (p.get('baseUrl') or '').strip(),
        'model': (p.get('model') or '').strip(),
        'provider': active,
        'source': 'llm-config.json',
    }


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

        # cmd_vel 直驱旋转参数（Round 4：替代 Nav2 spin BT）
        self.declare_parameter('cmd_vel_topic', 'cmd_vel')
        self.declare_parameter('rotation_max_angular_vel', 0.5)
        self.declare_parameter('rotation_tolerance_deg', 2.0)
        self.declare_parameter('rotation_timeout_s', 8.0)
        self.declare_parameter('rotation_kp', 1.5)
        
        # 从参数获取 API Key（环境变量已设置为默认值）
        self.api_key = self.get_parameter('api_key').value
        self.api_base_url = self.get_parameter('api_base_url').value
        self.vlm_model = self.get_parameter('vlm_model').value
        self.panorama_storage_path = self.get_parameter('panorama_storage_path').value
        self.rgb_topic = self.get_parameter('rgb_topic').value
        self.depth_topic = self.get_parameter('depth_topic').value
        self.confidence_threshold = self.get_parameter('confidence_threshold').value
        self.max_retries = self.get_parameter('max_retries').value

        # L1 兜底：param 和 env 都没给 key 时，读 UI 的 llm-config.json
        # 来源优先级：ROS param > 环境变量 > UI 配置文件
        key_source = 'param' if self.api_key else ('env' if api_key_from_env else '')
        llm_provider = ''
        if not self.api_key:
            ui_cfg = _load_llm_config_from_ui()
            if ui_cfg.get('api_key'):
                self.api_key = ui_cfg['api_key']
                # base_url/model 仅在 UI 有值且当前字段是默认空/未覆盖时才使用
                if ui_cfg.get('base_url'):
                    self.api_base_url = ui_cfg['base_url']
                if ui_cfg.get('model'):
                    self.vlm_model = ui_cfg['model']
                llm_provider = ui_cfg.get('provider', '')
                key_source = 'llm-config.json'

        # 验证 API Key
        if not self.api_key:
            self.get_logger().error(
                'API Key not configured (param/env/llm-config.json 均为空)。'
                'VLM 检查将全部返回 found=false！'
            )
        
        # 初始化相机订阅器
        self.camera_subscriber = CameraSubscriber(
            rgb_topic=self.rgb_topic,
            depth_topic=self.depth_topic
        )
        self.camera_subscriber.start_background_spin()

        # TF 查询：用于读取当前真实朝向，避免仅依赖请求里的目标 yaw
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # cmd_vel 直驱 publisher（Round 4：TF 闭环替代 Nav2 spin）
        cmd_vel_topic = self.get_parameter('cmd_vel_topic').value
        self.cmd_vel_pub = self.create_publisher(Twist, cmd_vel_topic, 1)
        self.get_logger().info(
            f'cmd_vel publisher ready: topic={cmd_vel_topic}, '
            f'max_w={self.get_parameter("rotation_max_angular_vel").value} rad/s'
        )

        # 回调组：capture 独占（长时间运行），annotate/check 可并行
        self._capture_cbg = MutuallyExclusiveCallbackGroup()
        self._parallel_cbg = ReentrantCallbackGroup()
        
        # 初始化全景图采集器（传入相机订阅器）
        self.panorama_capture = PanoramaCapture(
            camera_subscriber=self.camera_subscriber,
            storage_path=self.panorama_storage_path,
            enable_navigation=True,  # 启用自动导航
            heading_provider=self._lookup_current_heading_deg,
            cmd_vel_publisher=self.cmd_vel_pub,
            rotation_max_angular_vel=self.get_parameter('rotation_max_angular_vel').value,
            rotation_tolerance_deg=self.get_parameter('rotation_tolerance_deg').value,
            rotation_timeout_s=self.get_parameter('rotation_timeout_s').value,
            rotation_kp=self.get_parameter('rotation_kp').value,
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

        # 启动 trace：VLM 配置来源一目了然，后续 search_trace.log 可直接定位
        _search_trace_raw(
            'perception',
            f'[SEARCH-TRACE] perception.boot '
            f'vlm_client={"OK" if self.vlm_client else "None"} '
            f'key_source={key_source or "none"} '
            f'provider="{llm_provider}" '
            f'model="{self.vlm_model}" '
            f'base_url="{self.api_base_url}"',
            None,
        )
        
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
            self._capture_panorama_callback,
            callback_group=self._capture_cbg
        )

        self.create_service(
            sstg_srv.AnnotateSemantic,
            'annotate_semantic',
            self._annotate_semantic_callback,
            callback_group=self._parallel_cbg
        )

        self.create_service(
            sstg_srv.CheckObjectPresence,
            'check_object_presence',
            self._check_object_presence_callback,
            callback_group=self._parallel_cbg
        )

        # P2：与 nlp_node 对称，允许 UI 连接后热推送 LLM 配置到 perception
        try:
            self.create_service(
                sstg_srv.UpdateLLMConfig,
                'perception/update_llm_config',
                self._update_llm_config_callback,
                callback_group=self._parallel_cbg,
            )
            self.get_logger().info('✓ UpdateLLMConfig service registered (perception)')
        except Exception as e:
            self.get_logger().warn(f'Could not register UpdateLLMConfig: {e}')

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

            self.get_logger().info(
                f'[SEARCH-TRACE] capture_svc.response node={node_id} '
                f'success={response.success} count={len(images_dict)} '
                f'paths={response.image_paths} error="{response.error_message}"'
            )
            _search_trace_raw(
                'perception',
                f'[SEARCH-TRACE] capture_svc.response node={node_id} '
                f'success={response.success} count={len(images_dict)} '
                f'paths={response.image_paths} error="{response.error_message}"',
                None,
            )

        except Exception as e:
            response.success = False
            response.error_message = str(e)
            self.get_logger().error(f'❌ Capture error: {e}')
            self.get_logger().error(
                f'[SEARCH-TRACE] capture_svc.exception node={node_id} exc="{e!r}"'
            )
            _search_trace_raw(
                'perception',
                f'[SEARCH-TRACE] capture_svc.exception node={node_id} exc="{e!r}"',
                None,
            )
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
                semantic_obj.name_cn = obj.name_cn
                semantic_obj.position = obj.position
                semantic_obj.quantity = obj.quantity
                semantic_obj.confidence = obj.confidence
                semantic_obj.distance_hint = obj.distance_hint
                semantic_obj.salience = obj.salience
                semantic_obj.visibility = obj.visibility
                semantic_obj.image_region = obj.image_region
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
        image_path = ''
        target_object = ''
        t_start = time.time()
        try:
            image_path = request.image_path
            target_object = request.target_object

            self.get_logger().info(
                f'Checking object presence: "{target_object}" in {image_path}')
            _search_trace_raw(
                'perception',
                f'[SEARCH-TRACE] check_object.enter target="{target_object}" '
                f'image="{Path(image_path).name}" '
                f'vlm_ready={self.vlm_client is not None}',
                None,
            )

            if not Path(image_path).exists():
                response.found = False
                response.confidence = 0.0
                response.description = ''
                response.error_message = f'Image not found: {image_path}'
                _search_trace_raw(
                    'perception',
                    f'[SEARCH-TRACE] check_object.reject target="{target_object}" '
                    f'reason="image_not_found" path="{image_path}"',
                    None,
                )
                return response

            if not self.vlm_client:
                response.found = False
                response.confidence = 0.0
                response.description = ''
                response.error_message = 'VLM client not configured'
                _search_trace_raw(
                    'perception',
                    f'[SEARCH-TRACE] check_object.reject target="{target_object}" '
                    f'reason="vlm_client_none" (检查 llm-config.json / env / launch param)',
                    None,
                )
                return response

            prompt = (
                f'请严格判断这张图片中是否真的存在"{target_object}"。\n\n'
                f'判定流程（必须按顺序，认真执行）：\n'
                f'步骤 1：先在脑中列出你能在图中清楚看到的 3-5 件物体（椅子、墙、门、书包等真实存在、不是你推测的）。\n'
                f'步骤 2：检查你列出的物体里是否有 "{target_object}" 或完全等同的物体。不是"看起来像"、不是"可能是"、不是"包装盒"、不是"类似物"。\n'
                f'步骤 3：得出结论。若"{target_object}"真的就在图中清晰可见 → found=true；否则一律 found=false。\n\n'
                f'严格规则（违反任何一条都要改为 found=false）：\n'
                f'- 不得基于"推测"、"可能"、"看起来像"给出 found=true。\n'
                f'- 不得仅凭周围环境（例如"有书桌所以可能有电脑"）推断物体存在。\n'
                f'- 若目标被严重遮挡、只露一小角且无法确认，found=false。\n'
                f'- 若你只看到 "{target_object}" 的包装盒/附件/类似物（如耳机盒不是耳机），found=false。\n'
                f'- found=true 时 description 必须说出 "{target_object}" 在图里的具体位置（如"左下角地面上"、"画面中央桌上"）；讲不出位置说明你其实没看到——改 found=false。\n'
                f'- confidence：非常确定（亲眼看到且能指出位置）才能 ≥0.8；犹豫/不确定一律 <0.4。\n'
                f'- 宁可漏报（found=false）不要误报（found=true）。误报会让机器人白跑一趟。\n\n'
                f'请用以下 JSON 格式回复（visible_objects 字段用于自我核对，必须如实列出你真正看到的）：\n'
                f'{{"visible_objects": ["物体1", "物体2", ...], '
                f'"found": true/false, "confidence": 0.0-1.0, '
                f'"description": "若 found=true 必须写出位置；若 found=false 简述图中实际看到的东西"}}\n'
                f'只回复 JSON，不要其他内容。'
            )

            vlm_t0 = time.time()
            vlm_response = self.vlm_client.call_semantic_annotation(
                image_path, prompt=prompt)
            vlm_elapsed = time.time() - vlm_t0

            if not vlm_response.success:
                response.found = False
                response.confidence = 0.0
                response.description = ''
                response.error_message = f'VLM call failed: {vlm_response.error}'
                _search_trace_raw(
                    'perception',
                    f'[SEARCH-TRACE] check_object.vlm_fail target="{target_object}" '
                    f'image="{Path(image_path).name}" elapsed={vlm_elapsed:.2f}s '
                    f'err="{vlm_response.error}"',
                    None,
                )
                return response

            # 解析 VLM 返回的 JSON
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
                parse_mode = 'json'
            except (json.JSONDecodeError, ValueError):
                # VLM 返回非标准 JSON，尝试从文本推断
                text = vlm_response.content.lower()
                response.found = '是' in text or 'true' in text or '有' in text
                response.confidence = 0.5 if response.found else 0.3
                response.description = vlm_response.content[:200]
                response.error_message = ''
                parse_mode = 'fallback'

            raw_snippet = vlm_response.content.replace('\n', ' ')[:120]
            _search_trace_raw(
                'perception',
                f'[SEARCH-TRACE] check_object.result target="{target_object}" '
                f'image="{Path(image_path).name}" found={response.found} '
                f'conf={response.confidence:.2f} mode={parse_mode} '
                f'elapsed={vlm_elapsed:.2f}s '
                f'desc="{response.description[:80]}" raw="{raw_snippet}"',
                None,
            )

            self.get_logger().info(
                f'Object check result: found={response.found}, '
                f'confidence={response.confidence:.2f}')

        except Exception as e:
            response.found = False
            response.confidence = 0.0
            response.description = ''
            response.error_message = str(e)
            self.get_logger().error(f'Object check error: {e}')
            _search_trace_raw(
                'perception',
                f'[SEARCH-TRACE] check_object.exception target="{target_object}" '
                f'image="{Path(image_path).name}" exc="{e!r}" '
                f'elapsed={time.time() - t_start:.2f}s',
                None,
            )

        return response

    def _update_llm_config_callback(self, request, response):
        """P2：UI 一键启动/保存配置时热更新 perception 的 VLM 客户端，无需重启节点"""
        try:
            new_key = (request.api_key or '').strip()
            new_base = (request.base_url or '').strip()
            new_model = (request.model or '').strip()

            self.api_key = new_key or self.api_key
            self.api_base_url = new_base or self.api_base_url
            self.vlm_model = new_model or self.vlm_model

            if self.api_key:
                self.vlm_client = VLMClientWithRetry(
                    api_key=self.api_key,
                    base_url=self.api_base_url,
                    model=self.vlm_model,
                    max_retries=self.max_retries,
                )
                self.vlm_client.set_logger(self.get_logger().info)
                self.get_logger().info(
                    f'✓ perception LLM config updated: '
                    f'base_url={self.api_base_url}, model={self.vlm_model}'
                )
                status = 'OK'
            else:
                self.vlm_client = None
                self.get_logger().warn('perception LLM config updated: API key empty, VLM disabled')
                status = 'None'

            _search_trace_raw(
                'perception',
                f'[SEARCH-TRACE] perception.vlm.update vlm_client={status} '
                f'model="{self.vlm_model}" base_url="{self.api_base_url}" key_len={len(self.api_key)}',
                None,
            )

            response.success = True
            response.message = f'Config updated: model={self.vlm_model}'
        except Exception as e:
            response.success = False
            response.message = str(e)
            self.get_logger().error(f'Error updating perception LLM config: {e}')
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
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        print('\nShutting down...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
