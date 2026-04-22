"""
NLP Interface Node - SSTG NLP 主节点
处理多模态自然语言输入并构建语义查询
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
import os
from typing import Optional, List, Dict
import json

try:
    import sstg_msgs.msg as sstg_msg
    import sstg_msgs.srv as sstg_srv
except ImportError:
    class DummyModule:
        pass
    sstg_msg = DummyModule()
    sstg_srv = DummyModule()

from sstg_nlp_interface.text_processor import TextProcessor
from sstg_nlp_interface.multimodal_input import MultimodalInputHandler, InputModality
from sstg_nlp_interface.vlm_client import VLMClientWithRetry
from sstg_nlp_interface.query_builder import QueryBuilder, QueryValidator


class NLPNode(Node):
    """
    NLP 接口节点
    
    功能：
    - 接收多模态输入（文本、音频、图片）
    - 使用 VLM 进行理解
    - 构建语义查询
    - 发布查询结果
    """
    
    def __init__(self):
        super().__init__('nlp_node')
        
        # 参数配置 - API Key 优先从环境变量读取
        api_key_from_env = os.getenv('DASHSCOPE_API_KEY', '')
        self.declare_parameter('api_key', api_key_from_env)
        self.declare_parameter('api_base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.declare_parameter('vlm_model', 'qwen-vl-plus')
        self.declare_parameter('confidence_threshold', 0.3)
        self.declare_parameter('max_retries', 3)
        self.declare_parameter('language', 'zh')
        
        # 从参数获取配置
        self.api_key = self.get_parameter('api_key').value
        self.api_base_url = self.get_parameter('api_base_url').value
        self.vlm_model = self.get_parameter('vlm_model').value
        self.confidence_threshold = self.get_parameter('confidence_threshold').value
        self.max_retries = self.get_parameter('max_retries').value
        self.language = self.get_parameter('language').value
        
        # 验证 API Key
        if not self.api_key:
            self.get_logger().warn('API Key not configured. VLM features will be disabled.')
        
        # 初始化处理器
        self.text_processor = TextProcessor()
        self.text_processor.set_logger(self.get_logger().info)
        
        self.multimodal_handler = MultimodalInputHandler()
        self.multimodal_handler.set_logger(self.get_logger().info)
        
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
        
        # 初始化查询构建器
        self.query_builder = QueryBuilder()
        self.query_builder.set_logger(self.get_logger().info)
        
        # 初始化查询验证器
        self.query_validator = QueryValidator()
        self.query_validator.set_logger(self.get_logger().info)

        # 对话会话持久化：每个 session_id 一个 JSON 文件
        self._map_context_cache = ''
        self._sessions_dir = os.path.expanduser('~/.sstg_nav/chat_sessions')
        os.makedirs(self._sessions_dir, exist_ok=True)
        self._session_cache = {}  # {session_id: [messages]}
        self._MAX_HISTORY_TOKENS = 4000

        # 地图服务客户端（用于获取拓扑图摘要）
        try:
            self._map_client = self.create_client(
                sstg_srv.GetTopologicalMap,
                'get_topological_map'
            )
        except Exception:
            self._map_client = None
        
        # 发布器
        self.semantic_query_pub = self.create_publisher(
            sstg_msg.SemanticData,
            'semantic_queries',
            qos_profile=QoSProfile(depth=10)
        )
        
        # 服务
        try:
            self.create_service(
                sstg_srv.ProcessNLPQuery,
                'process_nlp_query',
                self._process_nlp_query_callback
            )
            self.get_logger().info("✓ ProcessNLPQuery service registered")
        except Exception as e:
            self.get_logger().warn(f"Could not register ProcessNLPQuery service: {e}")

        # 动态 LLM 配置服务
        try:
            self.create_service(
                sstg_srv.UpdateLLMConfig,
                'nlp/update_llm_config',
                self._update_llm_config_callback
            )
            self.get_logger().info("✓ UpdateLLMConfig service registered")
        except Exception as e:
            self.get_logger().warn(f"Could not register UpdateLLMConfig service: {e}")

        # 删除会话服务
        try:
            self.create_service(
                sstg_srv.DeleteChatSession,
                'nlp/delete_session',
                self._delete_session_callback
            )
            self.get_logger().info("✓ DeleteChatSession service registered")
        except Exception as e:
            self.get_logger().warn(f"Could not register DeleteChatSession service: {e}")
        
        self.get_logger().info('✓ NLP Node initialized successfully')
    
    def _update_llm_config_callback(self, request, response):
        """动态更新 LLM 配置"""
        try:
            self.api_key = request.api_key
            self.api_base_url = request.base_url or self.api_base_url
            self.vlm_model = request.model or self.vlm_model

            if self.api_key:
                self.vlm_client = VLMClientWithRetry(
                    api_key=self.api_key,
                    base_url=self.api_base_url,
                    model=self.vlm_model,
                    max_retries=self.max_retries
                )
                self.vlm_client.set_logger(self.get_logger().info)
                self.get_logger().info(
                    f"✓ LLM config updated: base_url={self.api_base_url}, model={self.vlm_model}"
                )
            else:
                self.vlm_client = None
                self.get_logger().warn("LLM config updated: API key empty, VLM disabled")

            response.success = True
            response.message = f"Config updated: model={self.vlm_model}"
        except Exception as e:
            response.success = False
            response.message = str(e)
            self.get_logger().error(f"Error updating LLM config: {e}")
        return response

    def _get_map_context_summary(self) -> str:
        """获取拓扑地图摘要，缓存结果"""
        if self._map_context_cache:
            return self._map_context_cache

        if not self._map_client or not self._map_client.wait_for_service(timeout_sec=1.0):
            return ''

        try:
            future = self._map_client.call_async(sstg_srv.GetTopologicalMap.Request())
            rclpy.spin_until_future_complete(self, future, timeout_sec=3.0)
            result = future.result()
            if not result or not result.success:
                return ''

            topo = json.loads(result.topological_map_json)
            nodes = topo.get('nodes', [])

            rooms = []
            objects_by_room = {}
            for n in nodes:
                si = n.get('semantic_info', {})
                room = si.get('room_type_cn', si.get('room_type', f"节点{n.get('id')}"))
                rooms.append(f"{room}(节点{n.get('id')})")
                objs = [o.get('name', '') for o in si.get('objects', [])[:5]]
                if objs:
                    objects_by_room[room] = objs

            summary = f"可用位置: {', '.join(rooms)}"
            obj_parts = []
            for room, objs in objects_by_room.items():
                obj_parts.append(f"{room}: {', '.join(objs)}")
            if obj_parts:
                summary += f"\n已知物体: {'; '.join(obj_parts)}"

            self._map_context_cache = summary
            self.get_logger().info(f"Map context cached: {len(nodes)} nodes")
            return summary
        except Exception as e:
            self.get_logger().warn(f"Failed to get map context: {e}")
            return ''

    # ── 会话持久化 ──

    def _session_path(self, session_id: str) -> str:
        safe_id = session_id.replace('/', '_').replace('..', '_')
        return os.path.join(self._sessions_dir, f'{safe_id}.json')

    def _load_session(self, session_id: str) -> List[Dict[str, str]]:
        if session_id in self._session_cache:
            return self._session_cache[session_id]
        path = self._session_path(session_id)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
                self._session_cache[session_id] = messages
                return messages
            except Exception:
                pass
        self._session_cache[session_id] = []
        return self._session_cache[session_id]

    def _save_session(self, session_id: str):
        messages = self._session_cache.get(session_id, [])
        path = self._session_path(session_id)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(messages, f, ensure_ascii=False, indent=1)
        except Exception as e:
            self.get_logger().warn(f"Failed to save session {session_id}: {e}")

    def _delete_session_callback(self, request, response):
        sid = request.session_id
        self._session_cache.pop(sid, None)
        path = self._session_path(sid)
        try:
            if os.path.exists(path):
                os.remove(path)
            response.success = True
            response.message = f"Session {sid} deleted"
        except Exception as e:
            response.success = False
            response.message = str(e)
        return response

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        rest = len(text) - cn_chars
        return int(cn_chars * 1.5 + rest * 0.4)

    def _get_chat_history(self, session_id: str) -> List[Dict[str, str]]:
        """按 token 预算从最新往回保留尽可能多的历史"""
        messages = self._load_session(session_id) if session_id else []
        if not messages:
            return []
        budget = self._MAX_HISTORY_TOKENS
        result = []
        for msg in reversed(messages):
            cost = self._estimate_tokens(msg['content'])
            if budget - cost < 0 and result:
                break
            budget -= cost
            result.append(msg)
        result.reverse()
        return result

    def _append_to_session(self, session_id: str, user_text: str, assistant_text: str):
        messages = self._load_session(session_id)
        messages.append({'role': 'user', 'content': user_text})
        messages.append({'role': 'assistant', 'content': assistant_text})
        self._save_session(session_id)

    def _process_nlp_query_callback(self, request, response):
        """
        处理 NLP 查询服务回调
        
        Args:
            request: 请求对象
            response: 响应对象
        """
        try:
            # 初始化响应对象所有字段
            response.success = False
            response.query_json = ""
            response.intent = ""
            response.confidence = 0.0
            response.error_message = ""
            
            # 处理文本输入
            if hasattr(request, 'text_input') and request.text_input:
                session_id = getattr(request, 'session_id', '') or ''
                sender_name = getattr(request, 'sender_name', '') or ''
                text_query = self.text_processor.process(request.text_input)

                # 如果有 VLM，使用 VLM 进行进一步理解
                chat_response = ''
                if self.vlm_client:
                    context = request.context if hasattr(request, 'context') else None
                    # 如果前端传了地图上下文（非默认 "home"），直接使用，跳过 ROS service 调用
                    if context and context != 'home' and len(context) > 20:
                        map_ctx = context
                    else:
                        map_ctx = self._get_map_context_summary()
                    history = self._get_chat_history(session_id)
                    vlm_response = self.vlm_client.understand_text(
                        request.text_input, context,
                        map_context=map_ctx, chat_history=history,
                        sender_name=sender_name)

                    if vlm_response.success:
                        intent = vlm_response.intent or text_query.intent
                        entities = vlm_response.entities or text_query.entities
                        confidence = vlm_response.confidence
                        chat_response = vlm_response.response or ''
                        # 如果 response 为空但 VLM 成功了，尝试从原始 content 中提取
                        if not chat_response and vlm_response.content:
                            try:
                                raw = json.loads(vlm_response.content.strip().strip('`').removeprefix('json'))
                                chat_response = raw.get('response', '')
                            except Exception:
                                pass
                    else:
                        intent = text_query.intent
                        entities = text_query.entities
                        confidence = text_query.confidence
                else:
                    intent = text_query.intent
                    entities = text_query.entities
                    confidence = text_query.confidence
                
                # 构建查询
                semantic_query = self.query_builder.build_query(
                    intent=intent,
                    entities=entities,
                    original_text=request.text_input,
                    confidence=confidence
                )
                
                # 验证查询
                is_valid, errors = self.query_validator.validate(semantic_query)
                
                # 填充响应
                response.success = is_valid
                # 嵌入 chat_response 到 query_json
                query_data = json.loads(semantic_query.to_json())
                if chat_response:
                    query_data['chat_response'] = chat_response
                response.query_json = json.dumps(query_data, ensure_ascii=False)
                response.intent = semantic_query.intent
                response.confidence = float(semantic_query.confidence)

                if not is_valid:
                    response.error_message = '; '.join(errors)

                # 记录对话历史到会话文件
                if chat_response and session_id:
                    user_content = f"[{sender_name}] {request.text_input}" if sender_name else request.text_input
                    self._append_to_session(session_id, user_content, chat_response)
                
                # 发布查询
                if is_valid and confidence >= self.confidence_threshold:
                    self._publish_semantic_query(semantic_query)
                
                self.get_logger().info(f"NLP Query processed: intent={semantic_query.intent}, conf={confidence:.2f}")
            
            else:
                response.success = False
                response.error_message = "No valid input provided"
        
        except Exception as e:
            response.success = False
            response.error_message = str(e)
            self.get_logger().error(f"Error processing NLP query: {e}")
        
        return response
    
    def _publish_semantic_query(self, semantic_query):
        """
        发布语义查询
        
        Args:
            semantic_query: 语义查询对象
        """
        try:
            msg = sstg_msg.SemanticData()
            
            # 映射查询类型到房间类型
            room_type_map = {
                'navigate_to': 'room',
                'locate_object': 'room',
                'query_info': 'context',
                'ask_direction': 'navigation',
                'explore_new_home': 'exploration',
            }
            msg.room_type = room_type_map.get(semantic_query.query_type, 'unknown')
            msg.confidence = semantic_query.confidence
            msg.description = semantic_query.original_text or ''
            
            # 构建 SemanticObject 数组
            msg.objects = []
            if semantic_query.entities:
                for entity in semantic_query.entities:
                    obj = sstg_msg.SemanticObject()
                    obj.name = entity
                    obj.position = "unknown"
                    obj.quantity = 1
                    obj.confidence = semantic_query.confidence
                    msg.objects.append(obj)
            
            self.semantic_query_pub.publish(msg)
            self.get_logger().debug(f"Published semantic query: {semantic_query.query_type}")
        
        except Exception as e:
            self.get_logger().error(f"Error publishing semantic query: {e}")


def main(args=None):
    """主函数"""
    rclpy.init(args=args)
    
    try:
        node = NLPNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
