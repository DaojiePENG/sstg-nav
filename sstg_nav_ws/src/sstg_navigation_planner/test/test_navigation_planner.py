"""
导航规划器单元测试
"""

import unittest
import sys
from pathlib import Path

# 测试导入
from sstg_navigation_planner.semantic_matcher import SemanticMatcher, MatchResult
from sstg_navigation_planner.candidate_generator import CandidateGenerator
from sstg_navigation_planner.navigation_planner import NavigationPlanner
from sstg_navigation_planner.target_normalizer import normalize_search_target


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

    def test_object_match_prefers_search_objects(self):
        """locate_object 优先利用增强后的 search_objects"""
        topological_nodes = {
            2: {
                'name': '走廊3',
                'room_type': 'corridor',
                'semantic_tags': ['bag'],
                'search_objects': {
                    '包': {
                        'supporting_angles': [0, 270],
                        'best_view_angle': 270,
                        'best_view_score': 0.955,
                        'best_confidence': 0.95,
                        'distance_hint': 'near',
                        'salience': 0.9,
                        'visibility': 'full',
                        'name': 'bag',
                        'name_cn': '包',
                    }
                },
            },
            3: {
                'name': '走廊4',
                'room_type': 'corridor',
                'semantic_tags': ['backpack'],
                'search_objects': {
                    '背包': {
                        'supporting_angles': [0],
                        'best_view_angle': 0,
                        'best_view_score': 0.865,
                        'best_confidence': 0.9,
                        'distance_hint': 'near',
                        'salience': 0.8,
                        'visibility': 'partial',
                        'name': 'backpack',
                        'name_cn': '背包',
                    }
                },
            },
        }

        matches = self.matcher.match_query_to_nodes(
            intent='locate_object',
            entities=['书包'],
            confidence=0.95,
            topological_nodes=topological_nodes
        )

        self.assertGreater(len(matches), 1)
        self.assertEqual(matches[0].node_id, 2)
        self.assertGreater(len(matches[0].search_meta.get('supporting_angles', [])), len(matches[1].search_meta.get('supporting_angles', [])))


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
            match_reason='高相似度匹配',
            search_meta={},
        )
        
        candidates = self.generator.generate_candidates(
            match_results=[match_result],
            topological_nodes=self.topological_nodes
        )
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].node_id, 0)
        self.assertGreater(candidates[0].relevance_score, 0)

    def test_candidate_generation_prefers_evidence(self):
        """增强字段应拉开 locate_object 候选优先级"""
        self.topological_nodes[0]['search_objects'] = {
            '包': {
                'supporting_angles': [0, 90],
                'best_view_angle': 90,
                'best_view_score': 0.95,
                'best_confidence': 0.95,
                'distance_hint': 'near',
                'salience': 0.9,
                'visibility': 'full',
            }
        }
        self.topological_nodes[1]['search_objects'] = {
            '包': {
                'supporting_angles': [0],
                'best_view_angle': 0,
                'best_view_score': 0.75,
                'best_confidence': 0.85,
                'distance_hint': 'mid',
                'salience': 0.6,
                'visibility': 'partial',
            }
        }

        match_results = [
            MatchResult(
                node_id=0,
                node_name='客厅',
                room_type='living_room',
                semantic_tags=['bag'],
                match_score=0.92,
                match_reason='命中包',
                search_meta=self.topological_nodes[0]['search_objects']['包'],
            ),
            MatchResult(
                node_id=1,
                node_name='卧室',
                room_type='bedroom',
                semantic_tags=['bag'],
                match_score=0.88,
                match_reason='命中包',
                search_meta=self.topological_nodes[1]['search_objects']['包'],
            ),
        ]

        candidates = self.generator.generate_candidates(
            match_results=match_results,
            topological_nodes=self.topological_nodes
        )

        self.assertEqual(candidates[0].node_id, 0)
        self.assertGreater(candidates[0].evidence_score, candidates[1].evidence_score)


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


class TestTargetNormalizer(unittest.TestCase):
    """目标词规范化测试 - 保证 canonical form 全链路一致"""

    CASES = [
        ('书包', '书包'),
        ('我的书包', '书包'),
        ('找我的书包', '书包'),
        ('帮我找书包', '书包'),
        ('到我的书包', '书包'),
        ('给我找书包', '书包'),
        ('我的耳机', '耳机'),
        ('耳机呢', '耳机'),
        ('找书包', '书包'),
        ('书包在哪', '书包'),
        ('我的书包在哪里', '书包'),
        ('书包的位置', '书包'),
        ('背包', '背包'),
        ('我的', ''),
        ('', ''),
        ('   ', ''),
        ('我的充电宝', '充电宝'),
    ]

    def test_normalize_search_target(self):
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_search_target(raw), expected)

    def test_normalize_search_target_cross_package(self):
        """两个包必须持有字节级相同的 target_normalizer.py。"""
        pkg_root = Path(__file__).resolve().parents[2]
        a = pkg_root / 'sstg_navigation_planner' / 'sstg_navigation_planner' / 'target_normalizer.py'
        b = pkg_root / 'sstg_interaction_manager' / 'sstg_interaction_manager' / 'target_normalizer.py'
        if not (a.exists() and b.exists()):
            self.skipTest(f'cross-package files not both present: {a}, {b}')
        self.assertEqual(
            a.read_bytes(), b.read_bytes(),
            msg=f'target_normalizer.py drift between packages: {a} vs {b}',
        )


if __name__ == '__main__':
    print("Running Navigation Planner Tests...\n")
    unittest.main(verbosity=2)
