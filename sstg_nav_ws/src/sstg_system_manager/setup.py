from setuptools import setup

package_name = 'sstg_system_manager'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='WBT',
    maintainer_email='wbt@example.com',
    description='SSTG System Manager - hardware launch and system status monitoring',
    license='MIT',
    entry_points={
        'console_scripts': [
            'system_manager_node = sstg_system_manager.system_manager_node:main',
            'webrtc_camera_bridge = sstg_system_manager.webrtc_camera_bridge:main',
        ],
    },
)
