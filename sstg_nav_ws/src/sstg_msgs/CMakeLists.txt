cmake_minimum_required(VERSION 3.8)
project(sstg_msgs)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(action_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/SemanticObject.msg"
  "msg/SemanticData.msg"
  "msg/Command.msg"
  "msg/NavigationPlan.msg"
  "msg/NavigationFeedback.msg"
  "msg/TaskStatus.msg"
  "msg/SemanticAnnotation.msg"
  "srv/CreateNode.srv"
  "srv/QuerySemantic.srv"
  "srv/UpdateSemantic.srv"
  "srv/GetNodePose.srv"
  "srv/CaptureImage.srv"
  "srv/AnnotateSemantic.srv"
  "srv/ProcessNLPQuery.srv"
  "srv/PlanNavigation.srv"
  "srv/ExecuteNavigation.srv"
  "srv/GetTopologicalMap.srv"
  "msg/PointArray.msg"
  "msg/GoalTraceEvent.msg"
  "srv/SaveRrtSession.srv"
  "srv/CheckObjectPresence.srv"
  "srv/LaunchMode.srv"
  "srv/GetSystemStatus.srv"
  "srv/UpdateLLMConfig.srv"
  "srv/DeleteChatSession.srv"
  "srv/RestartNode.srv"
  "msg/SystemStatus.msg"
  "action/ExploreHome.action"
  DEPENDENCIES
    builtin_interfaces
    geometry_msgs
    std_msgs
    sensor_msgs
    action_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()