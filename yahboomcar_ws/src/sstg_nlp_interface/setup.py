from setuptools import find_packages, setup
import glob
import os

package_name = 'sstg_nlp_interface'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        # ROS2 package index
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        # Package manifest
        ('share/' + package_name, ['package.xml']),
        # Launch and config files
        (os.path.join('share', package_name, 'launch'), glob.glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob.glob('config/*.yaml')),
    ],
    install_requires=[
        'setuptools',
        'rclpy',
        'std_msgs',
        'geometry_msgs',
        'requests>=2.28.0',
    ],
    zip_safe=True,
    maintainer='daojie',
    maintainer_email='Daojie.PENG@qq.com',
    description='SSTG NLP Interface - Multimodal Natural Language Understanding',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'nlp_node = sstg_nlp_interface.nlp_node:main',
            'sstg_nlp_interface = sstg_nlp_interface.nlp_node:main'
        ],
    },
)
