# SSTG Navigation System 安装指南

详细的分步安装和配置说明。

## 📋 系统要求

### 硬件要求
- **CPU**: 双核处理器或更高（建议4核以上）
- **RAM**: 最少4GB（建议8GB以上）
- **存储**: 最少2GB可用空间
- **网络**: 建议有网络连接以下载依赖包

### 操作系统
- **推荐**: Ubuntu 22.04 LTS
- **其他**: 任何支持ROS2 Humble的Linux发行版

### 依赖软件
- **ROS2**: Humble Hawksbill
- **Python**: 3.10+
- **Git**: 版本管理

## 🚀 详细安装步骤

### 第1步：安装ROS2 Humble

如果尚未安装ROS2，请按以下步骤安装：

```bash
# 1. 设置ROS2源
locale  # 检查locale支持UTF-8
sudo apt update && sudo apt install locales
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8

# 2. 添加ROS2仓库
sudo apt install software-properties-common
sudo add-apt-repository universe
sudo apt update && sudo apt install curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

# 3. 安装ROS2 Humble
sudo apt update
sudo apt install ros-humble-desktop
sudo apt install ros-humble-dev-tools

# 4. Source ROS2 setup脚本
source /opt/ros/humble/setup.bash

# 5. 添加到bashrc以便每次自动加载
echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
```

### 第2步：安装colcon构建工具

```bash
# 安装colcon
sudo apt install python3-colcon-common-extensions

# 验证安装
colcon --version
```

**⚠️ 重要**: 确保setuptools版本兼容
setuptools版本过新（≥70）可能与ROS2 colcon构建系统不兼容。请确保使用兼容版本：

```bash
# 查看当前setuptools版本
pip show setuptools | grep Version

# 如果版本 >= 70，需要降级到兼容版本（推荐 < 70）
pip install 'setuptools<70'

# 如果在conda环境中构建（推荐方式），确保环境中的setuptools版本正确
conda run -n <your_env> pip install 'setuptools<70'
```

### 第3步：安装Nav2

```bash
# 安装Nav2框架
sudo apt install ros-humble-nav2 ros-humble-nav2-bringup

# 验证安装
ros2 pkg list | grep nav2
```

### 第4步：克隆或定位项目

如果你已经有项目目录：

```bash
# 进入项目目录
cd ~/sstg_nav/sstg_nav_ws
```

如果需要克隆项目：

```bash
# 根据实际URL进行克隆
git clone <repository_url> ~/sstg_nav
cd ~/sstg_nav/sstg_nav_ws
```

### 第5步：安装Python依赖

```bash
# 方法1：通过pip安装
python3 -m pip install --upgrade pip
python3 -m pip install fastapi uvicorn networkx pydantic

# 方法2：通过requirements文件（如果项目提供）
if [ -f "requirements.txt" ]; then
    python3 -m pip install -r requirements.txt
fi

# 验证安装
python3 -c "import fastapi, uvicorn, networkx; print('✓ All dependencies installed')"
```

### 第6步：构建SSTG工作空间

```bash
# 进入工作空间
cd ~/sstg_nav/sstg_nav_ws

# 创建符号链接安装（便于开发）
colcon build --symlink-install

# 或者，如果只想执行标准安装（如用于部署）
# colcon build
```

**构建时间**: 通常需要5-15分钟，具体取决于CPU

### 第7步：配置Shell环境

```bash
# Source新构建的工作空间
source ~/sstg_nav/sstg_nav_ws/install/setup.bash

# 添加到bashrc自动加载
echo "source ~/sstg_nav/sstg_nav_ws/install/setup.bash" >> ~/.bashrc
```

### 第8步：验证安装

```bash
# 验证ROS2环境
echo $ROS_DISTRO  # 应显示 "humble"
ros2 --version   # 显示ROS2版本

# 验证SSTG包
ros2 pkg list | grep sstg
# 应该列出这7个包:
# sstg_interaction_manager
# sstg_map_manager
# sstg_msgs
# sstg_navigation_executor
# sstg_navigation_planner
# sstg_nlp_interface
# sstg_perception

# 验证依赖包
python3 -c "import rclpy; print(f'rclpy version: {rclpy.__version__}')"
```

## 🔍 故障排除

### 问题1：找不到ROS2命令

**症状**: `command not found: ros2`

**解决**:
```bash
# 检查ROS2是否source
echo $ROS_DISTRO

# 如果为空，手动source
source /opt/ros/humble/setup.bash

# 或添加到bashrc
echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
source ~/.bashrc
```

### 问题2：colcon build失败 - setuptools版本错误

**症状**: 构建时出现 `error: option --editable not recognized` 或 `error: option --build-directory not recognized`

**原因**: setuptools版本过新（≥70）不支持ROS2 colcon构建系统传递的选项

**解决**:
```bash
# 1. 查看当前setuptools版本
pip show setuptools | grep Version

# 2. 如果版本 >= 70，需要降级
pip install 'setuptools<70'

# 3. 如果使用conda环境（推荐），确保环境中的setuptools正确
conda run -n hw_nav pip install 'setuptools<70'

# 4. 清理构建并重试
rm -rf build/ install/ log/
colcon build --symlink-install
```

**验证修复**:
```bash
# 查看当前setuptools版本应该 < 70
pip show setuptools | grep Version
# 应该显示类似: Version: 69.5.1

# 确保colcon能识别
python3 -c "import setuptools; print(f'setuptools version: {setuptools.__version__}')"
```

### 问题3：colcon build失败 - 其他构建错误

**症状**: 构建时出现其他错误

**解决**:
```bash
# 1. 清理之前的构建
rm -rf build/ install/ log/

# 2. 重新尝试
colcon build --symlink-install

# 3. 如果仍然失败，查看详细日志
colcon build --symlink-install --executor sequential --event-handlers console_direct=

# 4. 检查依赖是否都已安装
rosdep install --from-paths src --ignore-src -y
```

### 问题4：找不到Python包

**症状**: `ModuleNotFoundError: No module named 'fastapi'`

**解决**:
```bash
# 检查Python版本
python3 --version  # 应为3.10或更高

# 安装缺失的包
python3 -m pip install fastapi uvicorn networkx

# 或使用system包管理器
sudo apt install python3-fastapi python3-uvicorn python3-networkx
```

### 问题4：权限问题

**症状**: 安装时出现权限错误

**解决**:
```bash
# 方案1：使用pip的--user选项
python3 -m pip install --user fastapi uvicorn networkx

# 方案2：修复权限
sudo chown -R $USER ~/.local

# 方案3：使用虚拟环境（推荐用于多项目）
python3 -m venv ~/SSTG_env
source ~/SSTG_env/bin/activate
python3 -m pip install fastapi uvicorn networkx
```

### 问题5：源代码路径不存在

**症状**: `colcon build` 时提示找不到包

**解决**:
```bash
# 检查src目录是否包含SSTG包
ls -la ~/sstg_nav/sstg_nav_ws/src

# 应该看到这7个目录:
# sstg_interaction_manager/
# sstg_map_manager/
# sstg_msgs/
# sstg_navigation_executor/
# sstg_navigation_planner/
# sstg_nlp_interface/
# sstg_perception/

# 如果缺失，请确保包已正确复制到此目录
```

## 🧪 验证和测试

### 构建前的关键检查清单

在运行 `colcon build` 之前，建议先运行自动检查脚本：

```bash
# 运行环境检查脚本
bash check_environment.sh
```

这个脚本会自动检查以下内容：
- Python版本（需要3.10+）
- ROS2环境（需要Humble）
- colcon工具
- **setuptools版本（需要 < 70）** ⚠️ 最关键
- 项目结构和依赖包

如果所有检查通过，脚本会提示你可以开始构建。

### 手动检查清单

如果不使用脚本，请手动检查以下几点：

```bash
# 1. 检查setuptools版本（最关键）
pip show setuptools | grep Version
# ✓ 应该显示 Version < 70（推荐 69.x）
# ✗ 如果 >= 70，运行: pip install 'setuptools<70'

# 2. 如果使用conda环境，检查该环境中的setuptools
conda run -n hw_nav pip show setuptools | grep Version
# ✓ 应该 < 70

# 3. 检查colcon是否正确安装
colcon --help | head -5
# ✓ 应该显示colcon帮助信息

# 4. 检查ROS2是否正确source
echo $ROS_DISTRO
# ✓ 应该显示 "humble"

# 5. 检查Python版本
python3 --version
# ✓ 应该是3.10或更高

# 6. 检查源代码目录
ls -la ~/sstg_nav/sstg_nav_ws/src
# ✓ 应该包含7个SSTG包目录
```

如果所有检查都通过，现在可以继续构建了。

### 快速测试

```bash
# 1. 打开新终端
# 2. Source工作空间
source ~/sstg_nav/sstg_nav_ws/install/setup.bash

# 3. 运行单个节点测试
ros2 run sstg_map_manager map_manager_node

# 在另一个终端检查节点是否运行
ros2 node list | grep map_manager
```

### 完整系统测试

```bash
# 从项目根目录运行完整集成测试
cd ~/sstg_nav
./project_test/run_tests.sh

# 查看测试结果
cat project_test/integration_test_report.md
```

## 📚 下一步

安装完成后：

1. **阅读快速开始**: [QUICK_START.md](src/sstg_map_manager/doc/QUICK_START.md)
2. **启动系统**: 按照快速开始指南启动各个节点
3. **访问Web界面**: 启动后访问 http://localhost:8000
4. **查看完整文档**: [../README.md](../README.md)

## 📦 可选：安装附加工具

### 用于可视化的RViz2

```bash
sudo apt install ros-humble-rviz2
```

### 用于监控的rqt

```bash
sudo apt install ros-humble-rqt-common-plugins
```

### 用于开发的IDE支持

```bash
# VS Code的ROS2扩展
# 在VS Code扩展市场搜索 "ROS"

# Python开发工具
python3 -m pip install autopep8 pylint flake8
```

## 🔄 更新系统

如果需要更新SSTG系统到最新版本：

```bash
# 进入项目目录
cd ~/sstg_nav

# 更新代码
git pull origin main

# 进入工作空间
cd sstg_nav_ws

# 重新构建
colcon build --symlink-install

# 更新环境
source install/setup.bash
```

## 💾 卸载

如果需要完全卸载SSTG系统：

```bash
# 删除工作空间
rm -rf ~/sstg_nav/sstg_nav_ws/build
rm -rf ~/sstg_nav/sstg_nav_ws/install
rm -rf ~/sstg_nav/sstg_nav_ws/log

# 移除bashrc中的source行（可选）
# 手动编辑 ~/.bashrc，删除相关行
```

## 📞 获取帮助

遇到问题？

1. **查看日志**: `cat ~/sstg_nav/sstg_nav_ws/log/latest/*.log`
2. **检查ROS2**: `ros2 doctor`
3. **查阅文档**: 参考 [README.md](README.md)
4. **运行诊断**: `./project_test/run_tests.sh`

---

**安装指南最后更新**: 2026-03-29
