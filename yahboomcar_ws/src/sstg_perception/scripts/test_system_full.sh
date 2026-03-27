#!/bin/bash
# SSTG Perception v0.2.0 - 完整测试脚本

set -e

echo "=========================================="
echo "  SSTG Perception v0.2.0 系统测试"
echo "=========================================="
echo

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查函数
check_node() {
    if ros2 node list | grep -q "$1"; then
        echo -e "${GREEN}✓${NC} $2 运行中"
        return 0
    else
        echo -e "${RED}✗${NC} $2 未运行"
        return 1
    fi
}

check_topic() {
    if ros2 topic list | grep -q "$1"; then
        echo -e "${GREEN}✓${NC} $2 存在"
        return 0
    else
        echo -e "${RED}✗${NC} $2 不存在"
        return 1
    fi
}

check_service() {
    if ros2 service list | grep -q "$1"; then
        echo -e "${GREEN}✓${NC} $2 可用"
        return 0
    else
        echo -e "${RED}✗${NC} $2 不可用"
        return 1
    fi
}

# 步骤1: 检查系统状态
echo "[步骤 1/4] 检查系统状态..."
echo

all_ok=true

# 检查关键节点
echo "检查ROS2节点:"
check_node "camera" "相机节点" || all_ok=false
check_node "amcl" "AMCL定位" || all_ok=false
check_node "bt_navigator" "导航节点" || all_ok=false
check_node "perception_node" "Perception节点" || all_ok=false
echo

# 检查话题
echo "检查ROS2话题:"
check_topic "/camera/color/image_raw" "相机RGB话题" || all_ok=false
check_topic "/camera/depth/image_raw" "相机深度话题" || all_ok=false
check_topic "/amcl_pose" "定位话题" || all_ok=false
echo

# 检查服务
echo "检查ROS2服务:"
check_service "/capture_panorama" "全景采集服务" || all_ok=false
check_service "/annotate_semantic" "语义标注服务" || all_ok=false
echo

if [ "$all_ok" = false ]; then
    echo -e "${RED}✗ 系统检查失败！${NC}"
    echo
    echo "请确保所有服务已启动:"
    echo "  1. ros2 launch yahboomcar_nav camera_gemini_336l.launch.py"
    echo "  2. ros2 launch yahboomcar_nav laser_bringup_launch.py"
    echo "  3. ros2 launch yahboomcar_nav navigation_dwa_launch.py"
    echo "  4. ros2 run sstg_perception perception_node"
    exit 1
fi

echo -e "${GREEN}✓ 系统状态正常${NC}"
echo

# 步骤2: 检查相机数据
echo "[步骤 2/4] 检查相机数据..."
echo

if timeout 2 ros2 topic hz /camera/color/image_raw --once > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} 相机正在发布图像"
else
    echo -e "${YELLOW}⚠${NC} 无法获取相机数据频率（可能太慢）"
fi

# 检查能否收到一帧图像
if timeout 5 ros2 topic echo /camera/color/image_raw --once > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} 成功接收相机图像"
else
    echo -e "${RED}✗${NC} 无法接收相机图像"
    exit 1
fi
echo

# 步骤3: 检查定位
echo "[步骤 3/4] 检查机器人定位..."
echo

if timeout 2 ros2 topic echo /amcl_pose --once > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} 机器人已定位"

    # 获取当前位置
    pose_info=$(timeout 2 ros2 topic echo /amcl_pose --once 2>/dev/null | grep -A 3 "position:")
    echo "当前位置:"
    echo "$pose_info" | head -4
else
    echo -e "${RED}✗${NC} 机器人未定位"
    echo "请在RViz中使用'2D Pose Estimate'设置初始位姿"
    exit 1
fi
echo

# 步骤4: 测试全景采集服务
echo "[步骤 4/4] 测试全景采集服务..."
echo

echo -e "${YELLOW}准备调用全景采集服务...${NC}"
echo "目标: node_id=999 (测试), 位置=(0.5, 0.0)"
echo

read -p "按Enter开始测试，或Ctrl+C取消... "

echo "调用服务（预计耗时 1-2 分钟）..."
echo

# 调用服务
if timeout 150 ros2 service call /capture_panorama sstg_msgs/srv/CaptureImage \
  "{node_id: 999, pose: {header: {frame_id: 'map'}, pose: {position: {x: 0.5, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}" \
  > /tmp/panorama_test_result.txt 2>&1; then

    # 检查结果
    if grep -q "success: true" /tmp/panorama_test_result.txt; then
        echo -e "${GREEN}✓${NC} 全景采集成功!"
        echo

        # 显示保存的图像
        if [ -d "/tmp/sstg_perception/node_999" ]; then
            echo "保存的文件:"
            ls -lh /tmp/sstg_perception/node_999/ | grep -v "^total" | awk '{print "  " $9 " (" $5 ")"}'
            echo

            # 验证图像数量
            img_count=$(ls /tmp/sstg_perception/node_999/*.png 2>/dev/null | wc -l)
            if [ "$img_count" -eq 8 ]; then
                echo -e "${GREEN}✓${NC} 8张图像（4个方向 x RGB+深度）全部保存"
            else
                echo -e "${YELLOW}⚠${NC} 图像数量: $img_count (期望: 8)"
            fi

            # 显示元数据
            if [ -f "/tmp/sstg_perception/node_999/panorama_metadata.json" ]; then
                echo
                echo "元数据内容:"
                cat /tmp/sstg_perception/node_999/panorama_metadata.json
            fi
        fi
    else
        echo -e "${RED}✗${NC} 全景采集失败"
        echo
        echo "错误信息:"
        grep "error_message" /tmp/panorama_test_result.txt || echo "无详细错误信息"
        exit 1
    fi
else
    echo -e "${RED}✗${NC} 服务调用超时或失败"
    echo
    echo "可能原因:"
    echo "  1. 导航失败（目标点不可达）"
    echo "  2. 机器人未定位"
    echo "  3. 系统响应太慢"
    exit 1
fi

echo
echo "=========================================="
echo -e "${GREEN}✅ 测试完成！所有功能正常${NC}"
echo "=========================================="
echo
echo "测试图像位置: /tmp/sstg_perception/node_999/"
echo
echo "下一步:"
echo "  1. 在实际位置测试全景采集"
echo "  2. 测试语义标注服务 /annotate_semantic"
echo "  3. 集成到拓扑地图构建流程"
echo
