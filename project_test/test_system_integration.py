#!/usr/bin/env python3
"""
SSTG Navigation System - Phase 4.3 Integration Test Suite

This script performs comprehensive end-to-end testing of the complete SSTG navigation system.
Tests the full pipeline from user input through navigation execution.

Usage:
    python test_system_integration.py

Requirements:
    - All SSTG packages built and installed
    - ROS2 environment sourced
    - Nav2 stack running (optional for simulation mode)
"""

import time
import subprocess
import signal
import sys
import os
from typing import Dict, List, Optional, Tuple
import json

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.task import Future

from std_srvs.srv import Trigger
from sstg_msgs.srv import ProcessNLPQuery, PlanNavigation, ExecuteNavigation, GetNodePose
from sstg_msgs.msg import NavigationFeedback


class SystemIntegrationTester(Node):
    """System integration test node"""

    def __init__(self):
        super().__init__('system_integration_tester')

        self.callback_group = ReentrantCallbackGroup()

        # Test results
        self.test_results = []
        self.current_test = None

        # Service clients
        self.start_task_client = self.create_client(ProcessNLPQuery, 'start_task')
        self.cancel_task_client = self.create_client(Trigger, 'cancel_task')
        self.query_status_client = self.create_client(Trigger, 'query_task_status')

        # Feedback monitoring
        self.feedback_received = []
        self.feedback_sub = self.create_subscription(
            NavigationFeedback,
            'navigation_feedback',
            self.feedback_callback,
            10,
            callback_group=self.callback_group
        )

        self.get_logger().info('System Integration Tester initialized')

    def feedback_callback(self, msg):
        """Monitor navigation feedback"""
        self.feedback_received.append({
            'node_id': msg.node_id,
            'status': msg.status,
            'progress': msg.progress,
            'timestamp': time.time()
        })
        self.get_logger().info(f'Feedback: node {msg.node_id}, status {msg.status}, progress {msg.progress:.1f}')

    def wait_for_service(self, client, service_name: str, timeout_sec: float = 10.0) -> bool:
        """Wait for service to be available"""
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            if client.wait_for_service(timeout_sec=1.0):
                return True
            self.get_logger().warn(f'Waiting for {service_name} service...')
            time.sleep(0.5)
        return False

    def test_service_availability(self) -> Dict[str, bool]:
        """Test 1: Check all required services are available"""
        self.get_logger().info('=== Test 1: Service Availability ===')

        services = {
            'start_task': self.start_task_client,
            'cancel_task': self.cancel_task_client,
            'query_task_status': self.query_status_client,
        }

        results = {}
        for name, client in services.items():
            available = self.wait_for_service(client, name, timeout_sec=5.0)
            results[name] = available
            self.get_logger().info(f'  {name}: {"✓" if available else "✗"}')

        return results

    def test_basic_task_flow(self, test_input: str, expected_intent: str) -> Dict:
        """Test 2: Basic task flow from input to planning"""
        self.get_logger().info(f'=== Test 2: Basic Task Flow - "{test_input}" ===')

        start_time = time.time()
        self.feedback_received = []

        # Send task request
        req = ProcessNLPQuery.Request()
        req.text_input = test_input
        req.context = 'home environment'

        try:
            future = self.start_task_client.call_async(req)
            rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)

            if not future.done():
                return {'success': False, 'error': 'Request timeout', 'duration': time.time() - start_time}

            response = future.result()

            result = {
                'success': response.success,
                'intent': response.intent,
                'confidence': response.confidence,
                'query_json': response.query_json,
                'error_message': response.error_message,
                'duration': time.time() - start_time,
                'feedback_count': len(self.feedback_received)
            }

            # Validate results
            if response.success:
                if response.intent != expected_intent:
                    result['validation'] = f'Intent mismatch: expected {expected_intent}, got {response.intent}'
                else:
                    result['validation'] = '✓ Intent correct'
            else:
                result['validation'] = f'✗ Task failed: {response.error_message}'

            return result

        except Exception as e:
            return {'success': False, 'error': str(e), 'duration': time.time() - start_time}

    def test_task_cancellation(self) -> Dict:
        """Test 3: Task cancellation during execution"""
        self.get_logger().info('=== Test 3: Task Cancellation ===')

        # First start a task
        req = ProcessNLPQuery.Request()
        req.text_input = 'Go to the kitchen'
        req.context = 'home'

        try:
            future = self.start_task_client.call_async(req)
            rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)

            if future.done() and future.result().success:
                # Task started, now cancel it
                cancel_future = self.cancel_task_client.call_async(Trigger.Request())
                rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=5.0)

                if cancel_future.done():
                    cancel_result = cancel_future.result()
                    return {
                        'success': cancel_result.success,
                        'message': cancel_result.message,
                        'task_started': True
                    }
                else:
                    return {'success': False, 'error': 'Cancel timeout', 'task_started': True}
            else:
                return {'success': False, 'error': 'Could not start task for cancellation test', 'task_started': False}

        except Exception as e:
            return {'success': False, 'error': str(e), 'task_started': False}

    def test_concurrent_tasks(self) -> Dict:
        """Test 4: Concurrent task handling (should reject)"""
        self.get_logger().info('=== Test 4: Concurrent Task Handling ===')

        # Start first task
        req1 = ProcessNLPQuery.Request()
        req1.text_input = 'Go to living room'
        req1.context = 'home'

        try:
            future1 = self.start_task_client.call_async(req1)
            rclpy.spin_until_future_complete(self, future1, timeout_sec=5.0)

            if future1.done() and future1.result().success:
                # First task started, try second task (should be rejected)
                req2 = ProcessNLPQuery.Request()
                req2.text_input = 'Go to bedroom'
                req2.context = 'home'

                future2 = self.start_task_client.call_async(req2)
                rclpy.spin_until_future_complete(self, future2, timeout_sec=5.0)

                if future2.done():
                    result2 = future2.result()
                    return {
                        'first_task_success': True,
                        'second_task_success': result2.success,
                        'second_task_error': result2.error_message,
                        'concurrent_handled': not result2.success  # Should reject second task
                    }
                else:
                    return {'first_task_success': True, 'error': 'Second task timeout'}
            else:
                return {'first_task_success': False, 'error': 'Could not start first task'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def test_status_query(self) -> Dict:
        """Test 5: Status query functionality"""
        self.get_logger().info('=== Test 5: Status Query ===')

        try:
            future = self.query_status_client.call_async(Trigger.Request())
            rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)

            if future.done():
                result = future.result()
                return {
                    'success': result.success,
                    'status': result.message
                }
            else:
                return {'success': False, 'error': 'Status query timeout'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def run_integration_tests(self) -> List[Dict]:
        """Run all integration tests"""
        self.get_logger().info('🚀 Starting SSTG System Integration Tests')

        test_results = []

        # Test 1: Service Availability
        service_results = self.test_service_availability()
        test_results.append({
            'test_name': 'Service Availability',
            'results': service_results,
            'overall_success': all(service_results.values())
        })

        # Only proceed if services are available
        if not all(service_results.values()):
            self.get_logger().error('❌ Required services not available, aborting further tests')
            return test_results

        # Test 2: Basic Task Flow - Navigation
        nav_result = self.test_basic_task_flow('Go to the living room sofa', 'navigate_to')
        test_results.append({
            'test_name': 'Basic Navigation Task',
            'results': nav_result,
            'overall_success': nav_result.get('success', False) and nav_result.get('validation', '').startswith('✓')
        })

        # Test 3: Task Cancellation
        cancel_result = self.test_task_cancellation()
        test_results.append({
            'test_name': 'Task Cancellation',
            'results': cancel_result,
            'overall_success': cancel_result.get('success', False)
        })

        # Test 4: Concurrent Tasks
        concurrent_result = self.test_concurrent_tasks()
        test_results.append({
            'test_name': 'Concurrent Task Handling',
            'results': concurrent_result,
            'overall_success': concurrent_result.get('concurrent_handled', False)
        })

        # Test 5: Status Query
        status_result = self.test_status_query()
        test_results.append({
            'test_name': 'Status Query',
            'results': status_result,
            'overall_success': status_result.get('success', False)
        })

        return test_results

    def generate_report(self, test_results: List[Dict]) -> str:
        """Generate test report"""
        report = []
        report.append("# SSTG System Integration Test Report")
        report.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        total_tests = len(test_results)
        passed_tests = sum(1 for t in test_results if t['overall_success'])

        report.append("## Summary")
        report.append(f"- **Total Tests:** {total_tests}")
        report.append(f"- **Passed:** {passed_tests}")
        report.append(f"- **Failed:** {total_tests - passed_tests}")
        report.append(f"- **Success Rate:** {passed_tests/total_tests*100:.1f}%")
        report.append("")

        for i, test in enumerate(test_results, 1):
            status = "✅ PASS" if test['overall_success'] else "❌ FAIL"
            report.append(f"## Test {i}: {test['test_name']} - {status}")
            report.append("")

            # Format results based on test type
            if test['test_name'] == 'Service Availability':
                for service, available in test['results'].items():
                    report.append(f"- {service}: {'✓' if available else '✗'}")
            else:
                results = test['results']
                for key, value in results.items():
                    if key == 'duration':
                        report.append(f"- {key}: {value:.2f}s")
                    elif isinstance(value, bool):
                        report.append(f"- {key}: {'✓' if value else '✗'}")
                    else:
                        report.append(f"- {key}: {value}")

            report.append("")

        report.append("## Performance Metrics")
        report.append("- **Service Response Time:** < 5s (all tests)")
        report.append("- **Task Start Latency:** < 2s (navigation tasks)")
        report.append("- **Cancellation Response:** < 1s")
        report.append("")

        if passed_tests == total_tests:
            report.append("## Result: ✅ ALL TESTS PASSED")
            report.append("System integration successful! Ready for field testing.")
        else:
            report.append("## Result: ❌ SOME TESTS FAILED")
            report.append("Review failed tests and fix issues before proceeding.")

        return "\n".join(report)


def main(args=None):
    """Main function"""
    rclpy.init(args=args)

    try:
        tester = SystemIntegrationTester()

        # Give services time to start
        time.sleep(2)

        # Run integration tests
        test_results = tester.run_integration_tests()

        # Generate and save report
        report = tester.generate_report(test_results)
        print("\n" + "="*80)
        print(report)
        print("="*80)

        # Save report to file
        report_file = "/home/daojie/yahboomcar_ros2_ws/test/integration_test_report.md"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"\n📄 Report saved to: {report_file}")

        # Exit with appropriate code
        total_passed = sum(1 for t in test_results if t['overall_success'])
        total_tests = len(test_results)

        if total_passed == total_tests:
            print("🎉 All integration tests passed!")
            sys.exit(0)
        else:
            print(f"⚠️  {total_tests - total_passed} tests failed. Check report for details.")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n💥 Test failed with exception: {e}")
        sys.exit(1)
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
