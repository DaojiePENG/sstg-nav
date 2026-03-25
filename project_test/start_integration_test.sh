#!/bin/bash
# SSTG Navigation System - Integration Test Launcher
# This script starts all SSTG services for integration testing

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
WORKSPACE_DIR="/home/daojie/yahboomcar_ros2_ws"
SOURCE_CMD="source ${WORKSPACE_DIR}/yahboomcar_ws/install/setup.bash"
LOG_DIR="${WORKSPACE_DIR}/test/logs"
PID_FILE="${WORKSPACE_DIR}/test/processes.pid"

# Create log directory
mkdir -p "$LOG_DIR"
rm -f "$PID_FILE"

echo -e "${BLUE}🚀 SSTG Navigation System Integration Test Launcher${NC}"
echo -e "${BLUE}====================================================${NC}"
echo ""

# Function to start a service in background
start_service() {
    local service_name="$1"
    local command="$2"
    local log_file="$LOG_DIR/${service_name}.log"

    echo -e "${YELLOW}Starting ${service_name}...${NC}"

    # Start service in background
    eval "$command" > "$log_file" 2>&1 &
    local pid=$!

    # Save PID
    echo "$pid:$service_name" >> "$PID_FILE"

    echo -e "${GREEN}✓ ${service_name} started (PID: $pid)${NC}"
    echo -e "  Log: $log_file"

    # Brief wait for service to initialize
    sleep 2
}

# Function to check if service is responding
check_service() {
    local service_name="$1"
    local service_topic="$2"
    local timeout=10

    echo -e "${YELLOW}Checking ${service_name}...${NC}"

    local start_time=$(date +%s)
    while [ $(($(date +%s) - start_time)) -lt $timeout ]; do
        if eval "$SOURCE_CMD && ros2 service list | grep -q '$service_topic'"; then
            echo -e "${GREEN}✓ ${service_name} is responding${NC}"
            return 0
        fi
        sleep 1
    done

    echo -e "${RED}✗ ${service_name} not responding after ${timeout}s${NC}"
    return 1
}

# Function to cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}🧹 Cleaning up...${NC}"

    if [ -f "$PID_FILE" ]; then
        while IFS=: read -r pid name; do
            if kill -0 "$pid" 2>/dev/null; then
                echo -e "${YELLOW}Stopping $name (PID: $pid)...${NC}"
                kill "$pid" 2>/dev/null || true
                sleep 1
                if kill -0 "$pid" 2>/dev/null; then
                    kill -9 "$pid" 2>/dev/null || true
                fi
            fi
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi

    echo -e "${GREEN}✓ Cleanup complete${NC}"
}

# Set trap for cleanup
trap cleanup EXIT INT TERM

# Main script
cd "$WORKSPACE_DIR"

echo -e "${BLUE}📋 Starting SSTG Services...${NC}"
echo ""

# 1. Start Map Manager
start_service "map_manager" "$SOURCE_CMD && ros2 run sstg_map_manager map_manager_node"

# 2. Start NLP Interface
start_service "nlp_interface" "$SOURCE_CMD && ros2 run sstg_nlp_interface nlp_node"

# 3. Start Navigation Planner
start_service "navigation_planner" "$SOURCE_CMD && ros2 run sstg_navigation_planner planning_node"

# 4. Start Navigation Executor
start_service "navigation_executor" "$SOURCE_CMD && ros2 run sstg_navigation_executor executor_node"

# 5. Start Interaction Manager
start_service "interaction_manager" "$SOURCE_CMD && ros2 run sstg_interaction_manager interaction_manager_node"

echo ""
echo -e "${BLUE}🔍 Checking Service Availability...${NC}"
echo ""

# Check all services
services_ok=true

check_service "Map Manager" "get_node_pose" || services_ok=false
check_service "NLP Interface" "process_nlp_query" || services_ok=false
check_service "Navigation Planner" "plan_navigation" || services_ok=false
check_service "Navigation Executor" "execute_navigation" || services_ok=false
check_service "Interaction Manager" "start_task" || services_ok=false

echo ""

if [ "$services_ok" = true ]; then
    echo -e "${GREEN}🎉 All SSTG services started successfully!${NC}"
    echo ""
    echo -e "${BLUE}📊 Service Status:${NC}"
    eval "$SOURCE_CMD && ros2 service list | grep -E '(get_node_pose|process_nlp_query|plan_navigation|execute_navigation|start_task|cancel_task|query_task_status)'"

    echo ""
    echo -e "${BLUE}🧪 Ready to run integration tests!${NC}"
    echo ""
    echo -e "${YELLOW}Commands:${NC}"
    echo -e "  # Run integration tests"
    echo -e "  python test/test_system_integration.py"
    echo ""
    echo -e "  # Manual testing"
    echo -e "  ros2 service call /start_task sstg_msgs/srv/ProcessNLPQuery \"{text_input: 'Go to the living room', context: 'home'}\""
    echo ""
    echo -e "  # Check status"
    echo -e "  ros2 service call /query_task_status std_srvs/srv/Trigger {}"
    echo ""
    echo -e "  # Cancel task"
    echo -e "  ros2 service call /cancel_task std_srvs/srv/Trigger {}"
    echo ""
    echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"

    # Wait for user input or interrupt
    while true; do
        sleep 1
    done
else
    echo -e "${RED}❌ Some services failed to start. Check logs in ${LOG_DIR}${NC}"
    exit 1
fi
