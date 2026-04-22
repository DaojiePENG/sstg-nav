import { createPortal } from "react-dom";
import { useVisionStore } from "../../store/visionStore";
import FloatingPiPWindow from "./FloatingPiPWindow";

/**
 * Portal 挂载点 — 放在 App.tsx 的 <AuthGate> 内，<BrowserRouter> 旁。
 * 使用 createPortal 渲染到 document.body，这样路由切换不会卸载 PiP 窗口。
 */
export default function FloatingPiPManager() {
  const isPiPVisible = useVisionStore((s) => s.isPiPVisible);

  if (!isPiPVisible) return null;

  return createPortal(<FloatingPiPWindow />, document.body);
}
