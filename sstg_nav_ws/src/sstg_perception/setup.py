from setuptools import find_packages, setup
import glob
import os

package_name = 'sstg_perception'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        # 让ROS2索引到这个包（关键）
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        # 安装package.xml
        ('share/' + package_name, ['package.xml']),
        # 安装launch和config目录
        (os.path.join('share', package_name, 'launch'), glob.glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob.glob('config/*.yaml')),
    ],
    install_requires=[
        'setuptools',
        'rclpy',
        'std_msgs',
        'geometry_msgs',
        'sensor_msgs',
        'opencv-python>=4.5.0',
        'numpy>=1.20.0',
        'requests>=2.28.0',
        'pillow>=8.0.0',
    ],
    zip_safe=True,
    maintainer='daojie',
    maintainer_email='Daojie.PENG@qq.com',
    description='SSTG Perception Module - RGB-D Image Capture and VLM Semantic Annotation',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'perception_node = sstg_perception.perception_node:main',
            'sstg_perception = sstg_perception.perception_node:main'
        ],
    },
)
