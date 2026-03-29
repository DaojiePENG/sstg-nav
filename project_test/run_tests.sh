#!/bin/bash
# SSTG System Integration Test Runner
# 完整的系统集成测试：初始化→启动→测试

set -e

WORKSPACE_DIR="/home/daojie/sstg_nav"
PROJECT_TEST="${WORKSPACE_DIR}/project_test"
SOURCE_CMD="source ${WORKSPACE_DIR}/yahboomcar_ws/install/setup.bash"
LOG_DIR="${PROJECT_TEST}/logs"

mkdir -p "$LOG_DIR"

echo "================================================================================"
echo "🧪 SSTG System Integration Test"
echo "================================================================================"
echo ""

# 初始化测试地图
echo "📍 Phase 1: Initialize test map..."
python3 "${PROJECT_TEST}/init_test_map.py"
echo ""

# 启动所有 ROS2 节点
echo "📍 Phase 2: Start all ROS2 nodes..."

eval "$SOURCE_CMD && ros2 run sstg_map_manager map_manager_node" > "$LOG_DIR/map_manager.log" 2>&1 &
MM_PID=$!
sleep 2

eval "$SOURCE_CMD && ros2 run sstg_nlp_interface nlp_node" > "$LOG_DIR/nlp_node.log" 2>&1 &
NLP_PID=$!
sleep 2

eval "$SOURCE_CMD && ros2 run sstg_navigation_planner planning_node" > "$LOG_DIR/planning_node.log" 2>&1 &
PLAN_PID=$!
sleep 2

eval "$SOURCE_CMD && ros2 run sstg_navigation_executor executor_node" > "$LOG_DIR/executor_node.log" 2>&1 &
EXEC_PID=$!
sleep 2

eval "$SOURCE_CMD && ros2 run sstg_interaction_manager interaction_manager_node" > "$LOG_DIR/interaction_manager.log" 2>&1 &
IM_PID=$!
sleep 3

echo "✓ All nodes started"
echo ""

# 清理函数
cleanup() {
    echo ""
    echo "🧹 Cleaning up..."
    kill $MM_PID $NLP_PID $PLAN_PID $EXEC_PID $IM_PID 2>/dev/null || true
    sleep 1
    echo "✓ All nodes stopped"
}

trap cleanup EXIT

# 运行集成测试
echo "📍 Phase 3: Run integration tests..."
echo ""
cd "$WORKSPACE_DIR"
eval "$SOURCE_CMD && python3 ${PROJECT_TEST}/test_system_integration.py"

echo ""
echo "================================================================================"
echo "✅ Integration test completed"
echo "================================================================================"
