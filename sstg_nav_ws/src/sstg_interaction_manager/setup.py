from setuptools import find_packages, setup

package_name = 'sstg_interaction_manager'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/docs', [
            'docs/MODULE_GUIDE.md',
            'docs/INTERACTION_QuickRef.md',
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='daojie',
    maintainer_email='Daojie.PENG@qq.com',
    description='Task Orchestration and Interaction Manager for SSTG System - Phase 4.2',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'interaction_manager_node = sstg_interaction_manager.interaction_manager_node:main'
        ],
    },
)
