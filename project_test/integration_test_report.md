# SSTG System Integration Test Report
**Date:** 2026-03-25 15:46:31

## Summary
- **Total Tests:** 5
- **Passed:** 2
- **Failed:** 3
- **Success Rate:** 40.0%

## Test 1: Service Availability - ✅ PASS

- start_task: ✓
- cancel_task: ✓
- query_task_status: ✓

## Test 2: Basic Navigation Task - ❌ FAIL

- success: ✗
- intent: 
- confidence: 0.0
- query_json: 
- error_message: TaskBusy: current state=navigating
- duration: 0.00s
- feedback_count: 0
- validation: ✗ Task failed: TaskBusy: current state=navigating

## Test 3: Task Cancellation - ❌ FAIL

- success: ✗
- error: Could not start task for cancellation test
- task_started: ✗

## Test 4: Concurrent Task Handling - ❌ FAIL

- first_task_success: ✗
- error: Could not start first task

## Test 5: Status Query - ✅ PASS

- success: ✓
- status: navigating

## Performance Metrics
- **Service Response Time:** < 5s (all tests)
- **Task Start Latency:** < 2s (navigation tasks)
- **Cancellation Response:** < 1s

## Result: ❌ SOME TESTS FAILED
Review failed tests and fix issues before proceeding.