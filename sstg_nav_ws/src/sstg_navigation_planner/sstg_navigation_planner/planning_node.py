"""
导航规划节点 - 主 ROS2 节点
"""

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
import sys
import json
from typing import Optional, Dict

# 导入消息类型
try:
    import sstg_msgs.msg as sstg_msg
    import sstg_msgs.srv as sstg_srv
    from geometry_msgs.msg import Pose
except ImportError:
    class DummyModule:
        pass
    sstg_msg = DummyModule()
    sstg_srv = DummyModule()
    Pose = None

# 导入核心模块
from sstg_navigation_planner.semantic_matcher import SemanticMatcher
from sstg_navigation_planner.candidate_generator import CandidateGenerator
from sstg_navigation_planner.navigation_planner import NavigationPlanner
from sstg_navigation_planner.target_normalizer import normalize_search_target


print("✓ SemanticMatcher initialized")
print("✓ CandidateGenerator initialized")
print("✓ NavigationPlanner initialized")


class PlanningNode(Node):
    """
    导航规划节点
    
    功能：
    - 接收 NLP 查询
    - 获取拓扑图信息
    - 执行语义匹配
    - 生成导航计划
    - 发布规划结果
    """
    
    def __init__(self):
        super().__init__('planning_node')

        self.cb_group = ReentrantCallbackGroup()

        # 参数配置
        self.declare_parameter('max_candidates', 5)
        self.declare_parameter('min_match_score', 0.2)
        self.declare_parameter('map_service_name', 'query_semantic')
        
        self.max_candidates = self.get_parameter('max_candidates').value
        self.min_match_score = self.get_parameter('min_match_score').value
        self.map_service_name = self.get_parameter('map_service_name').value
        
        # 初始化组件
        self.semantic_matcher = SemanticMatcher()
        self.semantic_matcher.set_logger(self.get_logger().info)
        
        self.candidate_generator = CandidateGenerator(max_candidates=self.max_candidates)
        self.candidate_generator.set_logger(self.get_logger().info)
        
        self.navigation_planner = NavigationPlanner()
        self.navigation_planner.set_logger(self.get_logger().info)
        
        # 发布者
        self.plan_pub = self.create_publisher(
            sstg_msg.NavigationPlan,
            'navigation_plans',
            qos_profile=rclpy.qos.QoSProfile(depth=10)
        )
        
        # 服务
        try:
            self.create_service(
                sstg_srv.PlanNavigation,
                'plan_navigation',
                self._plan_navigation_callback,
                callback_group=self.cb_group
            )
            self.get_logger().info("✓ PlanNavigation service registered")
        except Exception as e:
            self.get_logger().warn(f"Could not register PlanNavigation service: {e}")
        
        # 地图管理客户端 (稍后在回调中创建)
        self.map_client = None
        
        self.get_logger().info('✓ Planning Node initialized successfully')
        self.get_logger().info('[Planning][R7++] viewpoint-merge active; OBJECT_TYPE_MAPPING zh-cross enabled')
    
    def _get_topological_map(self) -> Optional[Dict]:
        """
        从地图管理器获取拓扑图
        """
        import time
        try:
            if self.map_client is None:
                # 创建客户端（放入同一 callback group 以支持嵌套调用）
                self.map_client = self.create_client(
                    sstg_srv.GetTopologicalMap,
                    'get_topological_map',
                    callback_group=self.cb_group
                )

                # 等待服务可用
                if not self.map_client.wait_for_service(timeout_sec=5.0):
                    self.get_logger().error("Map service get_topological_map not available")
                    return None

            # 发送请求
            request = sstg_srv.GetTopologicalMap.Request()
            future = self.map_client.call_async(request)

            # 等待响应（MultiThreadedExecutor + ReentrantCallbackGroup 允许嵌套处理）
            deadline = time.monotonic() + 5.0
            while not future.done() and time.monotonic() < deadline:
                time.sleep(0.05)

            if not future.done():
                self.get_logger().error("Map query timeout")
                return None

            result = future.result()
            if not result or not result.success:
                self.get_logger().error(f"Map query failed: {result.message if result else 'no result'}")
                return None

            # 解析 JSON (UI 格式: {nodes: [...], edges: [...], metadata: {...}})
            import json
            raw = json.loads(result.topology_json)

            # 转换 UI 格式到 planner 内部格式: {node_id: {name, room_type, pose, semantic_tags, connections, accessible}}
            topology_dict = self._convert_ui_topology(raw)

            self.get_logger().info(f"✓ Retrieved topological map with {len(topology_dict)} nodes")
            return topology_dict

        except Exception as e:
            self.get_logger().error(f"Error getting topological map: {e}")
            return None
    
    def _convert_ui_topology(self, raw: dict) -> Dict:
        """
        Convert UI-format topology JSON to planner internal format.

        UI format:  {nodes: [{id, name, pose:{x,y,theta}, semantic_info:{room_type, ...}}], edges: [...]}
        Internal:   {node_id: {name, room_type, pose:{x,y,z}, semantic_tags, search_objects, connections, accessible}}
        """
        # Build adjacency from edges
        adjacency: Dict[int, list] = {}
        for edge in raw.get('edges', []):
            src = edge.get('source', edge.get('from'))
            tgt = edge.get('target', edge.get('to'))
            if src is not None and tgt is not None:
                adjacency.setdefault(src, []).append(tgt)
                adjacency.setdefault(tgt, []).append(src)

        result = {}
        for node in raw.get('nodes', []):
            node_id = node.get('id', -1)
            pose = node.get('pose', {})
            sem = node.get('semantic_info') or {}

            semantic_tags = sem.get('semantic_tags', [])
            # Merge object names into semantic_tags for matching
            objects = sem.get('objects', [])
            for obj in objects:
                obj_name = obj.get('name', '') if isinstance(obj, dict) else str(obj)
                if obj_name and obj_name not in semantic_tags:
                    semantic_tags.append(obj_name)
            # 补齐 viewpoint 级 objects（name + name_cn）：聚合层可能基于 salience 阈值过滤掉
            # 某些低显著度但真实存在的物体（例：node 4 的 270° 视角拍到"背包"，
            # 但节点聚合里只剩"耳机/灭火器/门"），导致 planner _match_object 找不到。
            # 直接下沉到 viewpoint 数据，保证凡是被 VLM 看见过的物体都参与匹配。
            for _ang, vp in (node.get('viewpoints', {}) or {}).items():
                vp_sem = vp.get('semantic_info') or {}
                for vp_obj in (vp_sem.get('objects') or []):
                    if not isinstance(vp_obj, dict):
                        continue
                    for key in ('name', 'name_cn'):
                        vp_name = vp_obj.get(key, '')
                        if vp_name and vp_name not in semantic_tags:
                            semantic_tags.append(vp_name)
            room_type = sem.get('room_type', 'unknown')

            result[node_id] = {
                'name': node.get('name', f'Node_{node_id}'),
                'room_type': room_type,
                'pose': {
                    'x': pose.get('x', 0.0),
                    'y': pose.get('y', 0.0),
                    'z': 0.0,
                },
                'semantic_tags': semantic_tags,
                'search_objects': node.get('search_objects', {}),
                'connections': adjacency.get(node_id, []),
                'accessible': True,
            }
            self.get_logger().info(
                f'[Planning][R7++][tags] node={node_id} room={room_type} '
                f'tags={semantic_tags}')

        return result

    def _plan_navigation_callback(self, request, response):
        """
        处理导航规划请求
        """
        try:
            self.get_logger().info(f"[Planning] Received planning request: intent={request.intent}, entities='{request.entities}', confidence={request.confidence}")
            
            # 获取拓扑图
            topological_nodes = self._get_topological_map()
            if not topological_nodes:
                self.get_logger().info("[Planning] Using mock topological map")
                topological_nodes = self._get_mock_topological_map()
            
            self.get_logger().info(f"[Planning] Topological nodes available: {len(topological_nodes)}")
            
            # 解析 NLP 查询
            intent = request.intent if hasattr(request, 'intent') else 'navigate_to'
            
            # 解析实体 - 从SemanticQuery JSON中提取
            entities = []
            original_text = ''
            if hasattr(request, 'entities') and request.entities:
                try:
                    query_data = json.loads(request.entities)
                    if isinstance(query_data, dict):
                        # 如果是SemanticQuery格式，提取entities字段
                        entities = query_data.get('entities', [])
                        original_text = query_data.get('original_text', '')
                        # 优先用 target_objects
                        if query_data.get('target_objects'):
                            entities = query_data.get('target_objects', [])
                        # 如果entities为空，尝试从target_locations提取
                        elif not entities and query_data.get('target_locations'):
                            entities = query_data.get('target_locations', [])
                    elif isinstance(query_data, list):
                        # 如果直接是实体列表
                        entities = query_data
                except json.JSONDecodeError:
                    # 如果不是JSON，当作单个实体处理
                    entities = [request.entities] if request.entities else []

            # 清洗 entities: 过滤停用词，提取核心物体名
            STOP_WORDS = {'找', '去', '到', '帮', '我', '的', '在', '哪', '里', '呢', '吧', '啊', '哦', '嘛', '了', '找到', '寻找', '帮我找', '去找'}
            cleaned = []
            for e in entities:
                e = e.strip()
                if not e or e in STOP_WORDS or len(e) <= 1:
                    continue
                e = normalize_search_target(e) or e
                if e and e not in STOP_WORDS:
                    cleaned.append(e)
            # 如果清洗后为空，尝试从 original_text 提取
            if not cleaned and original_text:
                text = original_text
                for w in STOP_WORDS:
                    text = text.replace(w, '')
                text = text.strip()
                if text:
                    cleaned = [text]
            entities = cleaned if cleaned else entities

            confidence = request.confidence if hasattr(request, 'confidence') else 0.9
            current_node = request.current_node if hasattr(request, 'current_node') else -1
            
            self.get_logger().info(f"[Planning] Parsed: intent={intent}, entities={entities}, confidence={confidence}")
            
            # 执行语义匹配
            matches = self.semantic_matcher.match_query_to_nodes(
                intent=intent,
                entities=entities,
                confidence=confidence,
                topological_nodes=topological_nodes
            )
            
            self.get_logger().info(f"[Planning] Intent: {intent}, Entities: {entities}, Topological nodes: {len(topological_nodes)}")
            
            # 过滤低得分的匹配
            matches = [m for m in matches if m.match_score >= self.min_match_score]
            
            self.get_logger().info(f"[Planning] After filtering (min_score={self.min_match_score}): {len(matches)} matches")
            for match in matches[:3]:  # Log first 3 matches
                self.get_logger().info(f"[Planning] Match: Node {match.node_id} ({match.room_type}) - score: {match.match_score}")
            
            # 生成候选点
            candidates = self.candidate_generator.generate_candidates(
                match_results=matches,
                topological_nodes=topological_nodes
            )
            
            self.get_logger().info(f"[Planning] Generated {len(candidates)} candidates")
            for candidate in candidates[:3]:  # Log first 3 candidates
                self.get_logger().info(f"[Planning] Candidate: Node {candidate.node_id} ({candidate.room_type}) - relevance: {candidate.relevance_score:.3f}")
            self.get_logger().info(
                f'[Planning][R7++][final] entities={entities} '
                f'candidate_node_ids={[c.node_id for c in candidates]}')
            
            # 规划导航
            plan = self.navigation_planner.plan_navigation(
                candidates=candidates,
                topological_nodes=topological_nodes,
                current_node_id=current_node if current_node > 0 else None
            )
            
            self.get_logger().info(f"[Planning] Navigation plan: success={plan.success}, path={plan.path}, reasoning='{plan.reasoning}'")
            
            # 填充响应
            # locate_object: 有候选节点就算成功（不依赖路径规划，interaction_manager 会逐个导航）
            has_candidates = len(candidates) > 0
            response.success = plan.success or (intent == 'locate_object' and has_candidates)
            response.candidate_node_ids = [c.node_id for c in candidates]
            response.reasoning = plan.reasoning if plan.success else (
                f'找到 {len(candidates)} 个候选节点' if has_candidates else plan.reasoning)
            plan_dict = plan.to_dict()
            # 把候选明细（含 distance_hint）附进 plan_json，下游 interaction_manager 用于远距离置信度降权
            plan_dict['candidate_details'] = [c.to_dict() for c in candidates]
            response.plan_json = json.dumps(plan_dict)
            
            # 发布计划
            if plan.success:
                self._publish_navigation_plan(plan, candidates)
            
            self.get_logger().info(f"Navigation planned: {plan.reasoning}")
            
        except Exception as e:
            response.success = False
            response.reasoning = str(e)
            self.get_logger().error(f"Error planning navigation: {e}")
        
        return response
    
    def _publish_navigation_plan(self, plan, candidates):
        """
        发布导航计划
        """
        try:
            msg = sstg_msg.NavigationPlan()
            msg.candidate_node_ids = plan.candidate_indices
            msg.relevance_scores = [c.relevance_score for c in candidates]
            msg.reasoning = plan.reasoning
            msg.recommended_index = 0  # 最优候选总是第一个
            
            # 添加位姿
            for candidate in candidates:
                pose = Pose()
                pose.position.x = candidate.pose_x
                pose.position.y = candidate.pose_y
                pose.position.z = candidate.pose_z
                msg.poses.append(pose)
            
            self.plan_pub.publish(msg)
            self.get_logger().debug("Published navigation plan")
            
        except Exception as e:
            self.get_logger().error(f"Error publishing navigation plan: {e}")
    
    def _get_mock_topological_map(self) -> Dict:
        """
        获取模拟拓扑图（用于测试）
        """
        return {
            0: {
                'name': '客厅',
                'room_type': 'living_room',
                'pose': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                'semantic_tags': ['sofa', 'TV', 'comfortable'],
                'connections': [1, 2],
                'accessible': True
            },
            1: {
                'name': '卧室',
                'room_type': 'bedroom',
                'pose': {'x': 5.0, 'y': 0.0, 'z': 0.0},
                'semantic_tags': ['bed', 'quiet', 'rest'],
                'connections': [0, 2],
                'accessible': True
            },
            2: {
                'name': '厨房',
                'room_type': 'kitchen',
                'pose': {'x': 0.0, 'y': 5.0, 'z': 0.0},
                'semantic_tags': ['cooker', 'sink', 'refrigerator'],
                'connections': [0, 1],
                'accessible': True
            }
        }


def main(args=None):
    """主函数"""
    rclpy.init(args=args)

    try:
        node = PlanningNode()
        executor = MultiThreadedExecutor(num_threads=4)
        executor.add_node(node)
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
