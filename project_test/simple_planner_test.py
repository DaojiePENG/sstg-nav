#!/usr/bin/env python3
"""
Simple test to call planner service directly
"""

import rclpy
from rclpy.node import Node
import json
from sstg_msgs.srv import PlanNavigation


class SimplePlannerTest(Node):
    def __init__(self):
        super().__init__('simple_planner_test')

        self.client = self.create_client(PlanNavigation, 'plan_navigation')

    def test_planner(self):
        # Wait for service
        if not self.client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('Planner service not available')
            return

        # Create request with the same data as NLP produces
        req = PlanNavigation.Request()
        req.intent = 'navigate_to'
        req.entities = json.dumps({
            "query_type": "navigation_query",
            "intent": "navigate_to",
            "entities": ["客厅"],
            "target_locations": ["客厅"],
            "target_objects": [],
            "context": {},
            "confidence": 0.95,
            "original_text": "去客厅",
            "multimodal_data": None
        })
        req.confidence = 0.95
        req.current_node = -1

        self.get_logger().info('Calling planner service...')
        future = self.client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)

        if not future.done():
            self.get_logger().error('Service call timeout')
            return

        result = future.result()
        self.get_logger().info(f'Planner result: success={result.success}')
        self.get_logger().info(f'Candidate nodes: {result.candidate_node_ids}')
        self.get_logger().info(f'Reasoning: {result.reasoning}')


def main():
    rclpy.init()
    node = SimplePlannerTest()
    node.test_planner()
    rclpy.shutdown()


if __name__ == '__main__':
    main()