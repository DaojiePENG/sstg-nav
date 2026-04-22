"""
导航规划器单元测试
"""

import unittest
import sys

# 测试导入
from sstg_navigation_planner.semantic_matcher import SemanticMatcher, MatchResult
from sstg_navigation_planner.candidate_generator import CandidateGenerator
from sstg_navigation_planner.navigation_planner import NavigationPlanner


class TestSemanticMatcher(unittest.TestCase):
    """语义匹配器测试"""
    
    def setUp(self):
        self.matcher = SemanticMatcher()
    
    def test_room_match(self):
        """测试房间匹配"""
        topological_nodes = {
            0: {
                'name': '客厅',
                'room_type': 'living_room',
                'semantic_tags': ['sofa', 'TV']
            },
            1: {
                'name': '卧室',
                'room_type': 'bedroom',
                'semantic_tags': ['bed', 'quiet']
            }
        }
        
        matches = self.matcher.match_query_to_nodes(
            intent='navigate_to',
            entities=['客厅'],
            confidence=0.9,
            topological_nodes=topological_nodes
        )
        
        self.assertGreater(len(matches), 0)
        self.assertEqual(matches[0].node_name, '客厅')
    
    def test_object_match(self):
        """测试物体匹配"""
        topological_nodes = {
            0: {
                'name': '客厅',
                'room_type': 'living_room',
                'semantic_tags': ['sofa', 'TV', 'comfortable']
            }
        }
        
        matches = self.matcher.match_query_to_nodes(
            intent='locate_object',
            entities=['sofa'],
            confidence=0.8,
            topological_nodes=topological_nodes
        )
        
        self.assertGreater(len(matches), 0)


class TestCandidateGenerator(unittest.TestCase):
    """候选点生成器测试"""
    
    def setUp(self):
        self.generator = CandidateGenerator(max_candidates=5)
        self.topological_nodes = {
            0: {
                'name': '客厅',
                'room_type': 'living_room',
                'pose': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                'semantic_tags': ['sofa', 'TV'],
                'connections': [1, 2],
                'accessible': True
            },
            1: {
                'name': '卧室',
                'room_type': 'bedroom',
                'pose': {'x': 5.0, 'y': 0.0, 'z': 0.0},
                'semantic_tags': ['bed'],
                'connections': [0],
                'accessible': True
            }
        }
    
    def test_candidate_generation(self):
        """测试候选点生成"""
        match_result = MatchResult(
            node_id=0,
            node_name='客厅',
            room_type='living_room',
            semantic_tags=['sofa', 'TV'],
            match_score=0.9,
            match_reason='高相似度匹配'
        )
        
        candidates = self.generator.generate_candidates(
            match_results=[match_result],
            topological_nodes=self.topological_nodes
        )
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].node_id, 0)
        self.assertGreater(candidates[0].relevance_score, 0)


class TestNavigationPlanner(unittest.TestCase):
    """导航规划器测试"""
    
    def setUp(self):
        self.planner = NavigationPlanner()
        self.topological_nodes = {
            0: {
                'name': '客厅',
                'room_type': 'living_room',
                'pose': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                'connections': [1, 2]
            },
            1: {
                'name': '卧室',
                'room_type': 'bedroom',
                'pose': {'x': 5.0, 'y': 0.0, 'z': 0.0},
                'connections': [0, 2]
            },
            2: {
                'name': '厨房',
                'room_type': 'kitchen',
                'pose': {'x': 0.0, 'y': 5.0, 'z': 0.0},
                'connections': [0, 1]
            }
        }
    
    def test_path_planning(self):
        """测试路径规划"""
        from sstg_navigation_planner.candidate_generator import CandidatePoint
        
        candidate = CandidatePoint(
            node_id=2,
            node_name='厨房',
            pose_x=0.0,
            pose_y=5.0,
            pose_z=0.0,
            room_type='kitchen',
            relevance_score=0.9,
            semantic_score=0.9,
            distance_score=0.5,
            accessibility_score=1.0,
            match_reason='完美匹配'
        )
        
        plan = self.planner.plan_navigation(
            candidates=[candidate],
            topological_nodes=self.topological_nodes,
            current_node_id=0
        )
        
        self.assertTrue(plan.success)
        self.assertGreater(len(plan.path), 0)
        self.assertEqual(plan.start_node_id, 0)
        self.assertEqual(plan.goal_node_id, 2)


if __name__ == '__main__':
    print("Running Navigation Planner Tests...\n")
    unittest.main(verbosity=2)
