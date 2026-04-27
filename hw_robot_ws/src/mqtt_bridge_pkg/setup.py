from setuptools import setup

package_name = 'mqtt_bridge_pkg'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=[
        'setuptools',
        'paho-mqtt'  # 添加 paho-mqtt 作为依赖
    ],
    zip_safe=True,
    maintainer='Daojie PENG', # 修改为你的名字
    maintainer_email='Daojie.PENG@qq.com', # 修改为你的邮箱
    description='A ROS 2 node to bridge MQTT messages to IMU and Odometry topics.',
    license='Apache License 2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # 格式: '可执行文件名 = 包名.模块名:main函数'
            'mqtt_to_ros = mqtt_bridge_pkg.mqtt_to_ros_node:main',
        ],
    },
)
