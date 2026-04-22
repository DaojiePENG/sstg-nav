import { useEffect } from "react";
import { useVisionStore } from "../../store/visionStore";
import CompressedImageFallback from "./CompressedImageFallback";

/**
 * 相机面板：统一走 rosbridge compressed JPEG
 * 公网局域网都走同一条通路，稳定可靠
 */

export default function CameraStreamPanel() {
  const cameraEnabled = useVisionStore((s) => s.cameraEnabled);
  const setCameraEnabled = useVisionStore((s) => s.setCameraEnabled);

  useEffect(() => { setCameraEnabled(true); }, [setCameraEnabled]);

  if (!cameraEnabled) {
    return (
      <div className="w-full h-full flex items-center justify-center text-slate-500 text-sm">
        相机未启用
      </div>
    );
  }

  return <CompressedImageFallback />;
}
