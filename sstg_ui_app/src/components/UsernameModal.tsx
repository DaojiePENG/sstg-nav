import { useState } from "react";
import { getUsername, setUsername } from "../store/chatStore";
import { User } from "lucide-react";

/**
 * 首次访问时弹出昵称输入框。
 * 昵称存储在浏览器 localStorage，用于标记消息发送者。
 */
export default function UsernameModal({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState(getUsername());

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim() || `用户${Math.random().toString(36).slice(2, 5)}`;
    setUsername(trimmed);
    onDone();
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[9998]">
      <form onSubmit={handleSubmit} className="bg-slate-900 border border-slate-700 rounded-2xl p-8 w-80 shadow-2xl flex flex-col items-center gap-5">
        <div className="w-14 h-14 rounded-full bg-blue-600/20 flex items-center justify-center">
          <User size={28} className="text-blue-400" />
        </div>
        <div className="text-center">
          <h2 className="text-lg font-semibold text-slate-100">设置昵称</h2>
          <p className="text-sm text-slate-400 mt-1">其他协作者可以看到你的昵称</p>
        </div>
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="输入你的昵称"
          autoFocus
          className="w-full px-4 py-2.5 rounded-lg bg-slate-800 border border-slate-600 text-slate-100 text-center placeholder:text-slate-500 outline-none focus:border-blue-500 transition-colors"
        />
        <button type="submit" className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors">
          确认
        </button>
      </form>
    </div>
  );
}
