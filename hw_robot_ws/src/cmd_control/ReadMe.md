### 构建并 source `nav2_code`

```bash
cd /home/nx/daojie/hw_robot_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

### 静态检查

```bash
colcon list
```


### 悬空轮 `/cmd_vel` 安全测试

先不要启动 Nav2，只测试串口桥。

```bash
cd /home/nx/daojie/hw_robot_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run cmd_control cmd_vel_to_serial \
  --ros-args --params-file /home/nx/SSTG_WS/sstg-nav/hw_robot_ws/src/nav2_code/cmd_control/control.yaml
```

另一个终端低速发布：

```bash
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.3, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"

ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 1.0}}"


```

### 编译和启动雷达来提供 /scan

```bash

cd /home/nx/daojie/hw_robot_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash

# 启动雷达
ros2 launch sllidar_ros2 sllidar_s2_launch.py 

# 在另一个终端查看topic信息，应该有 /scan
ros2 topic list


# 启动奥比中光相机
ros2 launch sllidar_ros2 camera_gemini_336l.launch.py 

# 在另一个终端查看topic信息，应该有 /camera/color/* 等话题
ros2 topic list

```

