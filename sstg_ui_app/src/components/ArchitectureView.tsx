import { useState } from "react";
import { BookOpen, Network } from "lucide-react";
import { cn } from "../lib/utils";

const TABS = [
  { key: "core", label: "Core Hub", icon: Network, src: "/interaction-core-embed.html", accent: true },
  { key: "ui", label: "UI 架构", icon: BookOpen, src: "/architecture-embed.html", accent: false },
] as const;

export default function ArchitectureView() {
  const [tab, setTab] = useState<string>("core");
  const active = TABS.find(t => t.key === tab) ?? TABS[0];

  return (
    <div className="flex h-full w-full bg-slate-950 text-slate-200 overflow-hidden flex-col">
      {/* Header */}
      <div className="px-6 py-3 border-b border-slate-800 bg-slate-950 flex-shrink-0">
        <div className="flex items-center gap-4">
          <div className={cn(
            "w-10 h-10 rounded-2xl flex items-center justify-center transition-colors",
            tab === "core" ? "bg-orange-500/20 text-orange-400" : "bg-indigo-600/20 text-indigo-400"
          )}>
            {tab === "core" ? <Network size={24} /> : <BookOpen size={24} />}
          </div>
          <div>
            <h1 className="text-lg font-bold text-slate-100 tracking-wide">系统架构</h1>
            <p className="text-[11px] text-slate-500">
              {tab === "core" ? "Interaction Manager — 编排核心 / 任务链路 / 状态机" : "UI 模块 / 数据流 / 后端接口 / 3.x 对接"}
            </p>
          </div>
        </div>

        {/* Tab switcher */}
        <div className="flex bg-slate-900 border border-slate-800 rounded-xl p-1 gap-0.5 mt-3 w-fit">
          {TABS.map(t => {
            const Icon = t.icon;
            const isActive = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all",
                  isActive && t.accent
                    ? "bg-orange-500 text-white shadow-lg shadow-orange-500/20"
                    : isActive
                    ? "bg-blue-600 text-white shadow"
                    : t.accent
                    ? "text-orange-400 hover:text-orange-300 hover:bg-orange-500/10"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                )}
              >
                <Icon size={14} />
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Embedded visualization */}
      <iframe
        key={active.key}
        src={active.src}
        className="flex-1 w-full border-0"
        title={active.label}
      />
    </div>
  );
}
