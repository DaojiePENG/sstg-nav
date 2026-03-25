#!/bin/bash
# Quick SSTG System Test

set -e

WORKSPACE_DIR="/home/daojie/yahboomcar_ros2_ws"
SOURCE_CMD="source ${WORKSPACE_DIR}/yahboomcar_ws/install/setup.bash"
LOG_DIR="${WORKSPACE_DIR}/test/logs"

mkdir -p "$LOG_DIR"

echo "🚀 Starting SSTG Interaction Manager..."
eval "$SOURCE_CMD && ros2 run sstg_interaction_manager interaction_manager_node" > "$LOG_DIR/interaction_manager.log" 2>&1 &
IM_PID=$!

echo "Waiting for service..."
sleep 5

echo "🔍 Checking services..."
eval "$SOURCE_CMD && ros2 service list | grep start_task"

echo ""
echo "🧪 Testing basic functionality..."
echo "Sending test command..."

# Test the service
eval "$SOURCE_CMD && ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery \"{text_input: 'Go to kitchen', context: 'home'}\"" || echo "Service call failed"

echo ""
echo "📄 Checking logs..."
tail -10 "$LOG_DIR/interaction_manager.log"

echo ""
echo "🧹 Cleaning up..."
kill $IM_PID 2>/dev/null || true
echo "✓ Test complete"