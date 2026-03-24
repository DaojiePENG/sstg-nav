"""
NLP Interface Node - SSTG NLP 主节点
处理多模态自然语言输入并构建语义查询
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
import os
from typing import Optional
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
        
        self.get_logger().info('✓ NLP Node initialized successfully')
    
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
                text_query = self.text_processor.process(request.text_input)
                
                # 如果有 VLM，使用 VLM 进行进一步理解
                if self.vlm_client:
                    context = request.context if hasattr(request, 'context') else None
                    vlm_response = self.vlm_client.understand_text(request.text_input, context)
                    
                    if vlm_response.success:
                        intent = vlm_response.intent or text_query.intent
                        entities = vlm_response.entities or text_query.entities
                        confidence = vlm_response.confidence
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
                response.query_json = semantic_query.to_json()
                response.intent = semantic_query.intent
                response.confidence = float(semantic_query.confidence)
                
                if not is_valid:
                    response.error_message = '; '.join(errors)
                
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
                'ask_direction': 'navigation'
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
