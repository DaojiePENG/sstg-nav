#!/bin/bash
# =============================================================================
# SSTG Perception 服务完整测试脚本
# =============================================================================
# 功能：
#   1. 编译 sstg_perception 包
#   2. 启动 perception_node
#   3. 验证节点和服务
#   4. 测试服务调用
#   5. 显示结果和日志
#
# 使用方法：
#   cd ~/sstg_nav/yahboomcar_ws/src/sstg_perception
#   bash scripts/test_perception_services.sh
# =============================================================================

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo "=============================================================="
echo "    SSTG Perception 服务测试"
echo "=============================================================="
echo ""

# =============================================================================
# 步骤 1: 切换到工作空间目录
# =============================================================================
log_info "步骤 1/6: 切换到工作空间目录..."
cd /home/daojie/sstg_nav/yahboomcar_ws
log_success "当前目录: $(pwd)"
echo ""

# =============================================================================
# 步骤 2: 编译包
# =============================================================================
log_info "步骤 2/6: 编译 sstg_perception 包..."
if colcon build --packages-select sstg_perception 2>&1 | tee /tmp/colcon_build.log | tail -5; then
    log_success "编译成功"
else
    log_error "编译失败，请检查日志: /tmp/colcon_build.log"
    exit 1
fi
echo ""

# =============================================================================
# 步骤 3: Source 环境
# =============================================================================
log_info "步骤 3/6: 加载环境..."
source /opt/ros/humble/setup.bash
source install/setup.bash

# 设置 API Key
if [ -z "$DASHSCOPE_API_KEY" ]; then
    export DASHSCOPE_API_KEY="sk-942e8661f10f492280744a26fe7b953b"
    log_success "DASHSCOPE_API_KEY 已设置"
else
    log_success "DASHSCOPE_API_KEY 已存在"
fi
echo ""

# =============================================================================
# 步骤 4: 启动 perception_node
# =============================================================================
log_info "步骤 4/6: 启动 perception_node..."

# 检查是否已有节点在运行
if ros2 node list 2>/dev/null | grep -q "/perception_node"; then
    log_warn "检测到已运行的 perception_node，停止旧节点..."
    pkill -f "ros2 run sstg_perception perception_node" || true
    sleep 2
fi

# 启动新节点（后台）
LOG_FILE="/tmp/perception_node_test.log"
ros2 run sstg_perception perception_node > "$LOG_FILE" 2>&1 &
PERCEPTION_PID=$!
log_success "Perception Node 已启动 (PID: $PERCEPTION_PID)"
log_info "日志文件: $LOG_FILE"

# 等待节点启动
log_info "等待节点初始化（5秒）..."
sleep 5
echo ""

# =============================================================================
# 步骤 5: 验证节点和服务
# =============================================================================
log_info "步骤 5/6: 验证节点和服务..."

# 检查节点
log_info "检查运行中的节点:"
if ros2 node list 2>/dev/null | grep -E "perception_node|camera_subscriber"; then
    log_success "节点正常运行"
else
    log_error "未找到 perception_node，请检查日志: $LOG_FILE"
    cat "$LOG_FILE"
    exit 1
fi
echo ""

# 检查服务
log_info "检查可用的服务:"
SERVICES=$(ros2 service list 2>/dev/null | grep -E "(annotate_semantic|capture_panorama)" || true)
if [ -z "$SERVICES" ]; then
    log_error "未找到感知服务，请检查日志: $LOG_FILE"
    cat "$LOG_FILE"
    exit 1
fi

echo "$SERVICES"
log_success "服务已就绪"
echo ""

# =============================================================================
# 步骤 6: 测试服务调用
# =============================================================================
log_info "步骤 6/6: 测试服务调用..."
echo ""

# 测试图像路径
TEST_IMAGE="/home/daojie/Pictures/kitchen.png"

# 检查测试图像是否存在
if [ ! -f "$TEST_IMAGE" ]; then
    log_warn "测试图像不存在: $TEST_IMAGE"
    log_info "尝试使用其他图像..."

    # 查找其他可用图像
    TEST_IMAGE=$(find /home/daojie/Pictures -name "*.png" -o -name "*.jpg" 2>/dev/null | head -1)

    if [ -z "$TEST_IMAGE" ]; then
        log_error "未找到测试图像，跳过服务调用测试"
        TEST_IMAGE=""
    else
        log_success "找到测试图像: $TEST_IMAGE"
    fi
fi

# 测试 1: 语义标注服务
if [ -n "$TEST_IMAGE" ]; then
    log_info "测试 1: 语义标注服务"
    echo "----------------------------------------"
    log_info "调用: /annotate_semantic"
    log_info "图像: $TEST_IMAGE"
    echo ""

    if timeout 30 ros2 service call /annotate_semantic sstg_msgs/srv/AnnotateSemantic \
        "{image_path: '$TEST_IMAGE', node_id: 0}" 2>&1 | tee /tmp/annotate_result.log; then
        log_success "✓ 语义标注服务调用成功"
    else
        log_error "✗ 语义标注服务调用失败"
        log_info "请查看日志: /tmp/annotate_result.log"
    fi
    echo ""
fi

# 测试 2: 全景采集服务（如果相机可用）
log_info "测试 2: 全景采集服务"
echo "----------------------------------------"

# 检查相机话题是否可用
if ros2 topic list 2>/dev/null | grep -q "/camera/color/image_raw"; then
    log_info "调用: /capture_panorama"
    echo ""

    if timeout 30 ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
        "{node_id: 0, pose: {position: {x: 1.0, y: 2.0, z: 0.0}, orientation: {w: 1.0}}}" \
        2>&1 | tee /tmp/capture_result.log; then
        log_success "✓ 全景采集服务调用成功"
    else
        log_error "✗ 全景采集服务调用失败"
        log_info "请查看日志: /tmp/capture_result.log"
    fi
else
    log_warn "相机话题不可用，跳过全景采集测试"
    log_info "如需测试全景采集，请先启动相机："
    log_info "  ros2 launch orbbec_camera gemini_330_series.launch.py"
fi
echo ""

# =============================================================================
# 总结
# =============================================================================
echo "=============================================================="
echo "    测试完成"
echo "=============================================================="
echo ""

log_info "节点信息："
echo "  PID: $PERCEPTION_PID"
echo "  日志: $LOG_FILE"
echo ""

log_info "有用的命令："
echo "  查看实时日志: tail -f $LOG_FILE"
echo "  停止节点:     kill $PERCEPTION_PID"
echo "  查看节点列表: ros2 node list"
echo "  查看服务列表: ros2 service list | grep -E '(annotate|capture)'"
echo ""

log_info "手动测试服务："
echo "  # 语义标注"
echo "  ros2 service call /annotate_semantic sstg_msgs/srv/AnnotateSemantic \\"
echo "    \"{image_path: '$TEST_IMAGE', node_id: 0}\""
echo ""
echo "  # 全景采集"
echo "  ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \\"
echo "    \"{node_id: 0, pose: {position: {x: 1.0, y: 2.0, z: 0.0}, orientation: {w: 1.0}}}\""
echo ""

log_success "测试脚本执行完毕！"

# 提示用户是否保持节点运行
echo ""
read -p "是否保持 perception_node 运行？[Y/n] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_info "停止 perception_node..."
    kill $PERCEPTION_PID
    log_success "节点已停止"
else
    log_success "节点继续运行 (PID: $PERCEPTION_PID)"
fi
