#!/bin/bash
# Phase 0 验收测试脚本

echo "=========================================="
echo "Phase 0 验收测试"
echo "=========================================="

source install/setup.bash

echo ""
echo "1. 测试 map_manager 的 get_topological_map 服务..."
timeout 5 ros2 service call /get_topological_map sstg_msgs/srv/GetTopologicalMap || echo "服务未运行（需要先启动 map_manager）"

echo ""
echo "2. 检查 planning_node 是否能连接到正确的服务..."
echo "   预期：planning_node 应该尝试连接 get_topological_map 而不是 /manage_map"

echo ""
echo "=========================================="
echo "手动验证步骤："
echo "=========================================="
echo "1. 启动所有节点："
echo "   ./start_tmux.sh"
echo ""
echo "2. 在另一个终端发送导航任务："
echo "   source install/setup.bash"
echo "   ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery \"{text_input: '去客厅'}\""
echo ""
echo "3. 检查 planning_node 日志："
echo "   应该看到 '✓ Retrieved topological map with X nodes'"
echo "   而不是 'using mock map'"
echo ""
echo "=========================================="
