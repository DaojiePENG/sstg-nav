#!/usr/bin/env python3
"""
Debug script to test NLP to Planner data flow
"""

import rclpy
from rclpy.node import Node
import json
from sstg_msgs.srv import ProcessNLPQuery, PlanNavigation


class DebugNLPPlanner(Node):
    def __init__(self):
        super().__init__('debug_nlp_planner')

        self.nlp_client = self.create_client(ProcessNLPQuery, 'process_nlp_query')
        self.plan_client = self.create_client(PlanNavigation, 'plan_navigation')

        self.get_logger().info('Debug NLP-Planner node initialized')

    def test_data_flow(self, text_input):
        """Test the data flow from NLP to Planner"""

        self.get_logger().info(f'Testing with input: {text_input}')

        # Step 1: Call NLP service
        if not self.nlp_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('NLP service not available')
            return False

        nlp_req = ProcessNLPQuery.Request()
        nlp_req.text_input = text_input
        nlp_req.context = ''

        self.get_logger().info('Calling NLP service...')
        nlp_future = self.nlp_client.call_async(nlp_req)
        rclpy.spin_until_future_complete(self, nlp_future, timeout_sec=10.0)

        if not nlp_future.done():
            self.get_logger().error('NLP service call timeout')
            return False

        nlp_result = nlp_future.result()
        if not nlp_result.success:
            self.get_logger().error(f'NLP failed: {nlp_result.error_message}')
            return False

        self.get_logger().info(f'NLP result: intent={nlp_result.intent}, confidence={nlp_result.confidence}')
        self.get_logger().info(f'NLP query_json: {nlp_result.query_json}')

        # Step 2: Parse the JSON to see what Planner will receive
        try:
            semantic_query = json.loads(nlp_result.query_json)
            self.get_logger().info(f'Parsed semantic_query: {semantic_query}')
        except json.JSONDecodeError as e:
            self.get_logger().error(f'Failed to parse NLP query_json: {e}')
            return False

        # Step 3: Call Planner service with the same data
        if not self.plan_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('Planner service not available')
            return False

        plan_req = PlanNavigation.Request()
        plan_req.intent = nlp_result.intent
        plan_req.entities = nlp_result.query_json  # This is what Interaction Manager sends
        plan_req.confidence = nlp_result.confidence
        plan_req.current_node = -1

        self.get_logger().info('Calling Planner service...')
        plan_future = self.plan_client.call_async(plan_req)
        rclpy.spin_until_future_complete(self, plan_future, timeout_sec=10.0)

        if not plan_future.done():
            self.get_logger().error('Planner service call timeout')
            return False

        plan_result = plan_future.result()
        self.get_logger().info(f'Planner result: success={plan_result.success}, candidates={plan_result.candidate_node_ids}')
        if not plan_result.success:
            self.get_logger().error(f'Planner error: {plan_result.error_message}')

        return plan_result.success


def main():
    rclpy.init()
    node = DebugNLPPlanner()

    # Test with the same input that fails in integration test
    test_input = "去客厅"  # "Go to living room"

    success = node.test_data_flow(test_input)

    if success:
        node.get_logger().info('Data flow test PASSED')
    else:
        node.get_logger().error('Data flow test FAILED')

    rclpy.shutdown()


if __name__ == '__main__':
    main()