"""
Test NLP Interface Module
"""

import sys
import os
import tempfile
import json
import unittest

# 添加源路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sstg_nlp_interface.text_processor import TextProcessor, TextQuery
from sstg_nlp_interface.multimodal_input import MultimodalInputHandler, InputModality
from sstg_nlp_interface.query_builder import QueryBuilder, QueryValidator, SemanticQuery
from sstg_nlp_interface.vlm_client import VLMClient


class TestTextProcessor(unittest.TestCase):
    """文本处理器测试"""
    
    def setUp(self):
        self.processor = TextProcessor()
    
    def test_text_processing(self):
        """测试文本处理"""
        text = "请带我去客厅"
        query = self.processor.process(text)
        
        self.assertIsNotNone(query)
        self.assertEqual(query.text, text)
        self.assertIsNotNone(query.intent)
        self.assertIn(query.intent, ['navigate_to', 'query_info'])
    
    def test_entity_extraction(self):
        """测试实体提取"""
        text = "我想要找到卧室里的椅子"
        query = self.processor.process(text)
        
        self.assertIsNotNone(query.entities)
        self.assertGreater(len(query.entities), 0)
    
    def test_intent_recognition(self):
        """测试意图识别"""
        test_cases = [
            ("找一下沙发", "locate_object"),
            ("怎么走到厨房", "ask_direction"),
            ("这是什么", "query_info"),
        ]
        
        for text, expected_intent in test_cases:
            query = self.processor.process(text)
            print(f"Text: {text} -> Intent: {query.intent}")
            self.assertIsNotNone(query.intent)
    
    def test_text_cleaning(self):
        """测试文本清理"""
        dirty_text = "  你好   ，这是   一个测试  ！@#$%  "
        cleaned = self.processor._clean_text(dirty_text)
        
        self.assertNotIn("@#$%", cleaned)
        self.assertNotIn("  ", cleaned)


class TestMultimodalInputHandler(unittest.TestCase):
    """多模态输入处理器测试"""
    
    def setUp(self):
        self.handler = MultimodalInputHandler()
    
    def test_text_input(self):
        """测试文本输入处理"""
        text = "我想找一下电灯"
        input_data = self.handler.process_text(text)
        
        self.assertEqual(input_data.modality, InputModality.TEXT)
        self.assertEqual(input_data.text, text)
        self.assertTrue(self.handler.validate_input(input_data))
    
    def test_multimodal_mixed(self):
        """测试混合模态处理"""
        input_data = self.handler.process_mixed(
            text="这里有什么吗？",
            language='zh'
        )
        
        self.assertEqual(input_data.modality, InputModality.MIXED)
        self.assertEqual(input_data.text, "这里有什么吗？")
        self.assertTrue(self.handler.validate_input(input_data))
    
    def test_context_merging(self):
        """测试上下文合并"""
        input_data = self.handler.process_text("找椅子")
        context = {'current_location': 'living_room', 'user_id': 123}
        input_data = self.handler.merge_context(input_data, context)
        
        self.assertIsNotNone(input_data.context)
        self.assertEqual(input_data.context.get('current_location'), 'living_room')


class TestQueryBuilder(unittest.TestCase):
    """查询构建器测试"""
    
    def setUp(self):
        self.builder = QueryBuilder()
        self.validator = QueryValidator()
    
    def test_query_building(self):
        """测试查询构建"""
        query = self.builder.build_query(
            intent='navigate_to',
            entities=['客厅'],
            original_text='去客厅',
            confidence=0.85
        )
        
        self.assertIsNotNone(query)
        self.assertEqual(query.intent, 'navigate_to')
        self.assertEqual(query.query_type, 'navigation_query')
        self.assertIn('客厅', query.target_locations or [])
    
    def test_query_validation(self):
        """测试查询验证"""
        valid_query = SemanticQuery(
            query_type='navigation_query',
            intent='navigate_to',
            entities=['客厅'],
            confidence=0.8
        )
        
        is_valid, errors = self.validator.validate(valid_query)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_invalid_query_validation(self):
        """测试无效查询验证"""
        invalid_query = SemanticQuery(
            query_type='test',
            intent='',
            entities=[],
            confidence=0.1
        )
        
        is_valid, errors = self.validator.validate(invalid_query)
        self.assertFalse(is_valid)
        self.assertGreater(len(errors), 0)
    
    def test_query_serialization(self):
        """测试查询序列化"""
        query = self.builder.build_query(
            intent='locate_object',
            entities=['灯', '客厅'],
            original_text='找客厅里的灯',
            confidence=0.75
        )
        
        json_str = query.to_json()
        self.assertIsNotNone(json_str)
        
        parsed = json.loads(json_str)
        self.assertEqual(parsed['intent'], 'locate_object')
        self.assertIn('灯', parsed['entities'])


class TestVLMClient(unittest.TestCase):
    """VLM 客户端测试"""
    
    def test_client_initialization(self):
        """测试客户端初始化"""
        client = VLMClient(
            api_key='test_key',
            base_url='https://test.com',
            model='test-model'
        )
        
        self.assertEqual(client.api_key, 'test_key')
        self.assertEqual(client.model, 'test-model')
    
    def test_prompt_building(self):
        """测试提示构建"""
        client = VLMClient(api_key='test_key')
        
        prompt = client._build_text_prompt("找椅子", context={'room': 'kitchen'})
        self.assertIn("找椅子", prompt)
        self.assertIn("kitchen", prompt)
    
    def test_json_parsing(self):
        """测试JSON解析"""
        client = VLMClient(api_key='test_key')
        
        response_text = '''```json
{
  "intent": "locate_object",
  "entities": ["椅子"],
  "confidence": 0.9
}
```'''
        
        parsed = json.loads(response_text.split('```')[1][4:].strip())
        self.assertEqual(parsed['intent'], 'locate_object')
        self.assertIn('椅子', parsed['entities'])


def run_tests():
    """运行所有测试"""
    print("=" * 70)
    print("🧪 NLP Interface Module Tests")
    print("=" * 70)
    print()
    
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestTextProcessor))
    suite.addTests(loader.loadTestsFromTestCase(TestMultimodalInputHandler))
    suite.addTests(loader.loadTestsFromTestCase(TestQueryBuilder))
    suite.addTests(loader.loadTestsFromTestCase(TestVLMClient))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print()
    print("=" * 70)
    if result.wasSuccessful():
        print(f"✅ ALL TESTS PASSED ({result.testsRun} tests)")
    else:
        print(f"❌ SOME TESTS FAILED")
        print(f"   Failures: {len(result.failures)}")
        print(f"   Errors: {len(result.errors)}")
    print("=" * 70)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
