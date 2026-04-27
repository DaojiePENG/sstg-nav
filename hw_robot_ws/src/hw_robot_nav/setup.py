import os
from glob import glob

from setuptools import find_packages, setup


package_name = 'hw_robot_nav'


def data_files(pattern, destination):
    return (os.path.join('share', package_name, destination), glob(pattern))


setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'README.md']),
        data_files('config/*.yaml', 'config'),
        data_files('launch/*.py', 'launch'),
        data_files('maps/*', 'maps'),
        data_files('rviz/*.rviz', 'rviz'),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Daojie PENG',
    maintainer_email='Daojie.PENG@qq.com',
    description='hw_robot gmapping and Nav2 bringup package',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'check_system = hw_robot_nav.check_system:main',
            'scan_downsampler = hw_robot_nav.scan_downsampler:main',
        ],
    },
)
