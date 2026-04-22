cmake_minimum_required(VERSION 3.8)
project(sstg_rrt_explorer)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(std_srvs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)

include_directories(include)

# C++ executables
add_executable(global_rrt_detector src/global_rrt_detector_ros2.cpp src/functions.cpp src/mtrand.cpp)
ament_target_dependencies(global_rrt_detector rclcpp geometry_msgs nav_msgs visualization_msgs tf2 tf2_ros)

add_executable(local_rrt_detector src/local_rrt_detector_ros2.cpp src/functions.cpp src/mtrand.cpp)
ament_target_dependencies(local_rrt_detector rclcpp geometry_msgs nav_msgs visualization_msgs tf2 tf2_ros)

install(TARGETS
  global_rrt_detector
  local_rrt_detector
  DESTINATION lib/${PROJECT_NAME}
)

# Python scripts
install(PROGRAMS
  scripts/scan_dilute.py
  scripts/topic_relay.py
  scripts/tf_relay.py
  scripts/filter_ros2.py
  scripts/assigner_ros2.py
  scripts/functions_ros2.py
  scripts/getfrontier_ros2.py
  scripts/frontier_opencv_detector_ros2.py
  scripts/rrt_trace_manager.py
  scripts/trace_replay.py
  scripts/auto_node_placer.py
  scripts/collect_clicked_points.py
  scripts/click_and_capture.py
  scripts/visualize_node_positions.py
  scripts/node_semantic_collector.py
  scripts/find_and_navigate.py
  scripts/topo_node_viz.py
  scripts/exploration_action_server.py
  DESTINATION lib/${PROJECT_NAME}
)

# Launch files
install(DIRECTORY
  launch
  DESTINATION share/${PROJECT_NAME}
)

# Config files
install(DIRECTORY
  param
  rviz
  maps
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
