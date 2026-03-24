from setuptools import find_packages, setup
import glob
import os

package_name = 'sstg_map_manager'

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
        # 安装launch和config目录（保持你的文件结构）
        (os.path.join('share', package_name, 'launch'), glob.glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob.glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='daojie',
    maintainer_email='Daojie.PENG@qq.com',
    description='TODO: Package description',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'map_manager_node = sstg_map_manager.map_manager_node:main',
            'map_webui = sstg_map_manager.map_webui:main',
        ],
    },
)
