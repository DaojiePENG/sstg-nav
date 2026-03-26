#!/usr/bin/env python3
"""
测试相机订阅器
"""

import rclpy
from sstg_perception.camera_subscriber import CameraSubscriber


def main():
    # ✓ 关键步骤1：初始化 ROS2
    rclpy.init()

    try:
        # ✓ 关键步骤2：创建订阅器节点
        camera = CameraSubscriber(
            rgb_topic='/camera/color/image_raw',
            depth_topic='/camera/depth/image_raw'
        )

        print("等待相机图像...")

        # ✓ 关键步骤3：等待图像（现在会自动 spin）
        if camera.wait_for_images(timeout=5):
            rgb, depth = camera.get_latest_pair()
            print(f"✓ 成功接收图像!")
            print(f"  RGB shape: {rgb.shape}")
            print(f"  Depth shape: {depth.shape}")
        else:
            print("✗ 超时：未接收到图像")
            print("\n请检查：")
            print("1. 相机节点是否运行？")
            print("2. 话题名称是否正确？")
            print("   运行: ros2 topic list")
            print("   运行: ros2 topic hz /camera/color/image_raw")

    except KeyboardInterrupt:
        print("\n中断...")
    finally:
        # ✓ 关键步骤4：清理
        camera.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
