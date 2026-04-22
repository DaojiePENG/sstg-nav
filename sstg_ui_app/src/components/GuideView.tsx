import {
  MessageCircle, Route, Compass, MapPin, Brain, Network,
  Camera, ChevronRight, Sparkles, Search, Eye, Layers,
  HelpCircle, BookOpen, Zap,
} from "lucide-react";
import appLogo from "../assets/LOGO.png";
import { cn } from "../lib/utils";

/* ── Mode Cards ── */
const MODES = [
  {
    key: "chat",
    label: "聊天模式",
    icon: MessageCircle,
    color: "green",
    gradient: "from-green-500/20 to-emerald-600/10",
    border: "border-green-500/30",
    glow: "shadow-green-500/10",
    iconBg: "bg-green-500/20 text-green-400",
    desc: "和小拓自由对话，提问、闲聊、查询知识",
    examples: [
      "你好呀，介绍一下你自己",
      "客厅里有什么家具？",
      "帮我看看这张图片是什么",
    ],
    features: ["多模态 LLM 对话", "图片上传识别", "语音输入", "多 Provider 切换"],
  },
  {
    key: "navigate",
    label: "导航模式",
    icon: Route,
    color: "blue",
    gradient: "from-blue-500/20 to-indigo-600/10",
    border: "border-blue-500/30",
    glow: "shadow-blue-500/10",
    iconBg: "bg-blue-500/20 text-blue-400",
    desc: "用自然语言指挥机器人导航或寻找物品",
    examples: [
      "带我去客厅",
      "帮我找一下书包在哪",
      "去厨房看看有没有水杯",
    ],
    features: ["语义目标理解", "拓扑路径规划", "实时位姿反馈", "物体语义搜索"],
  },
  {
    key: "explore",
    label: "探索模式",
    icon: Compass,
    color: "amber",
    gradient: "from-amber-500/20 to-orange-600/10",
    border: "border-amber-500/30",
    glow: "shadow-amber-500/10",
    iconBg: "bg-amber-500/20 text-amber-400",
    desc: "让机器人自主探索未知环境，同步建图",
    examples: [
      "开始探索这个房间",
      "看看周围有什么",
      "帮我建一张新的地图",
    ],
    features: ["RRT 前沿探索", "实时 SLAM 建图", "拓扑节点自动创建", "全景语义采集"],
  },
] as const;

/* ── SSTG Pipeline Steps ── */
const PIPELINE = [
  { icon: MessageCircle, label: "自然语言输入", desc: "用户说出意图", color: "text-green-400" },
  { icon: Brain, label: "NLP 语义理解", desc: "VLM 解析意图", color: "text-purple-400" },
  { icon: Network, label: "拓扑图匹配", desc: "语义节点寻路", color: "text-blue-400" },
  { icon: MapPin, label: "路径规划", desc: "拓扑 → 坐标", color: "text-cyan-400" },
  { icon: Route, label: "Nav2 执行", desc: "实时导航", color: "text-amber-400" },
  { icon: Eye, label: "视觉感知", desc: "到达后确认", color: "text-rose-400" },
] as const;

/* ── Quick Start Steps ── */
const QUICK_START = [
  { step: "1", title: "启动系统", desc: "点击侧边栏底部的电源按钮，等待 ROS2 后端启动（绿灯亮起表示已连接）" },
  { step: "2", title: "选择模式", desc: "在聊天界面顶部切换三种模式：聊天 / 导航 / 探索" },
  { step: "3", title: "开始交互", desc: "直接用自然语言输入你的需求，小拓会理解并执行" },
  { step: "4", title: "查看地图", desc: "切换到地图页面，实时查看机器人位置、拓扑节点和全景照片" },
] as const;

export default function GuideView() {
  return (
    <div className="flex h-full w-full bg-slate-950 text-slate-200 overflow-hidden">
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-6 py-8 space-y-10">

          {/* ── Hero ── */}
          <section className="text-center space-y-4">
            <div className="w-20 h-20 mx-auto rounded-3xl overflow-hidden shadow-xl ring-1 ring-slate-700/60 bg-slate-900">
              <img src={appLogo} alt="SSTG" className="w-full h-full object-cover scale-110" />
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-50">
              SSTG-Nav
            </h1>
            <p className="text-base text-slate-400 max-w-2xl mx-auto leading-relaxed">
              <span className="text-slate-200 font-semibold">空间语义拓扑图</span>驱动的智能导航系统 ——
              用自然语言与机器人对话，实现语义导航、物体搜索和自主探索
            </p>
            <div className="flex items-center justify-center gap-3 pt-2">
              {[
                { icon: Layers, label: "拓扑语义地图" },
                { icon: Brain, label: "VLM 理解" },
                { icon: Camera, label: "全景感知" },
                { icon: Sparkles, label: "自然语言交互" },
              ].map(({ icon: Icon, label }) => (
                <span key={label} className="flex items-center gap-1.5 text-[11px] text-slate-400 bg-slate-900 border border-slate-800 rounded-full px-3 py-1.5">
                  <Icon size={13} className="text-blue-400" />
                  {label}
                </span>
              ))}
            </div>
          </section>

          {/* ── Three Modes ── */}
          <section>
            <div className="flex items-center gap-2 mb-5">
              <Zap size={18} className="text-amber-400" />
              <h2 className="text-lg font-bold text-slate-100">三种交互模式</h2>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {MODES.map((m) => {
                const Icon = m.icon;
                return (
                  <div
                    key={m.key}
                    className={cn(
                      "rounded-2xl border p-5 bg-gradient-to-br transition-all hover:scale-[1.02] hover:shadow-xl",
                      m.gradient, m.border, m.glow
                    )}
                  >
                    {/* Header */}
                    <div className="flex items-center gap-3 mb-3">
                      <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", m.iconBg)}>
                        <Icon size={22} />
                      </div>
                      <div>
                        <h3 className="font-bold text-slate-100">{m.label}</h3>
                        <p className="text-[11px] text-slate-400">{m.desc}</p>
                      </div>
                    </div>

                    {/* Example prompts */}
                    <div className="space-y-1.5 mb-4">
                      {m.examples.map((ex, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs text-slate-300">
                          <ChevronRight size={12} className="text-slate-500 mt-0.5 shrink-0" />
                          <span>"{ex}"</span>
                        </div>
                      ))}
                    </div>

                    {/* Features */}
                    <div className="flex flex-wrap gap-1.5">
                      {m.features.map((f) => (
                        <span key={f} className="text-[10px] font-medium bg-slate-900/60 border border-slate-700/50 text-slate-400 rounded-md px-2 py-0.5">
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* ── SSTG Pipeline ── */}
          <section className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
            <div className="flex items-center gap-2 mb-2">
              <Network size={18} className="text-blue-400" />
              <h2 className="text-lg font-bold text-slate-100">SSTG 语义导航流程</h2>
            </div>
            <p className="text-xs text-slate-500 mb-5">
              Spatial Semantic Topological Graph — 从自然语言到机器人行动的完整链路
            </p>

            {/* Pipeline flow */}
            <div className="flex items-center gap-1 overflow-x-auto pb-2">
              {PIPELINE.map((step, i) => {
                const Icon = step.icon;
                return (
                  <div key={i} className="flex items-center shrink-0">
                    <div className="flex flex-col items-center text-center w-[120px]">
                      <div className="w-12 h-12 rounded-xl bg-slate-800 border border-slate-700/50 flex items-center justify-center mb-2">
                        <Icon size={22} className={step.color} />
                      </div>
                      <span className="text-xs font-bold text-slate-200">{step.label}</span>
                      <span className="text-[10px] text-slate-500">{step.desc}</span>
                    </div>
                    {i < PIPELINE.length - 1 && (
                      <ChevronRight size={16} className="text-slate-600 mx-1 shrink-0" />
                    )}
                  </div>
                );
              })}
            </div>

            {/* Concept cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-6">
              <div className="bg-slate-950 rounded-xl border border-slate-800/50 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Layers size={14} className="text-emerald-400" />
                  <span className="text-xs font-bold text-slate-300">拓扑语义地图</span>
                </div>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  每个房间/地点是一个拓扑节点，节点包含语义标签（房间名、物品清单）和 360° 全景照片。通过节点间的边连接构成拓扑图，支持语义级别的路径搜索。
                </p>
              </div>
              <div className="bg-slate-950 rounded-xl border border-slate-800/50 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Search size={14} className="text-blue-400" />
                  <span className="text-xs font-bold text-slate-300">语义物体搜索</span>
                </div>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  "帮我找书包" → 系统搜索所有节点的语义标签，通过关键词匹配 + 近义词扩展找到最可能的位置，引导机器人前往并用 VLM 视觉确认。
                </p>
              </div>
              <div className="bg-slate-950 rounded-xl border border-slate-800/50 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Camera size={14} className="text-amber-400" />
                  <span className="text-xs font-bold text-slate-300">VLM 视觉感知</span>
                </div>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  机器人到达节点后拍摄 4 方向 RGB+Depth 全景。VLM (Gemini/Qwen-VL) 自动识别并标注物品，生成带定位框的标注图片。
                </p>
              </div>
            </div>
          </section>

          {/* ── Quick Start ── */}
          <section>
            <div className="flex items-center gap-2 mb-5">
              <HelpCircle size={18} className="text-cyan-400" />
              <h2 className="text-lg font-bold text-slate-100">快速上手</h2>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {QUICK_START.map((s) => (
                <div key={s.step} className="flex gap-4 bg-slate-900 border border-slate-800 rounded-xl p-4">
                  <div className="w-9 h-9 rounded-lg bg-blue-500/15 border border-blue-500/30 flex items-center justify-center text-blue-400 font-bold text-sm shrink-0">
                    {s.step}
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-200">{s.title}</h3>
                    <p className="text-[11px] text-slate-400 leading-relaxed mt-1">{s.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* ── Pages Overview ── */}
          <section>
            <div className="flex items-center gap-2 mb-5">
              <BookOpen size={18} className="text-indigo-400" />
              <h2 className="text-lg font-bold text-slate-100">页面导览</h2>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                {
                  icon: MessageCircle,
                  iconColor: "text-green-400",
                  iconBg: "bg-green-500/15",
                  title: "聊天",
                  path: "侧边栏第 1 个图标",
                  desc: "三模式聊天 + LLM 设置 + 任务队列。支持文本/图片/语音输入。导航和探索指令也在这里发出。",
                },
                {
                  icon: MapPin,
                  iconColor: "text-blue-400",
                  iconBg: "bg-blue-500/15",
                  title: "地图",
                  path: "侧边栏第 2 个图标",
                  desc: "3D 全息拓扑地图。查看机器人实时位置、拓扑节点详情、全景照片和实时 SLAM 地图叠加。",
                },
                {
                  icon: Zap,
                  iconColor: "text-amber-400",
                  iconBg: "bg-amber-500/15",
                  title: "系统",
                  path: "侧边栏第 3 个图标",
                  desc: "机器人控制中心。切换探索/导航模式、查看硬件状态、CPU/RAM、活跃节点和系统日志。",
                },
                {
                  icon: BookOpen,
                  iconColor: "text-indigo-400",
                  iconBg: "bg-indigo-500/15",
                  title: "架构",
                  path: "侧边栏第 4 个图标",
                  desc: "系统架构全景图（本页下方）。交互式查看 UI 模块、数据流、HTTP/ROS2 接口和后端对接清单。",
                },
              ].map((p) => {
                const Icon = p.icon;
                return (
                  <div key={p.title} className="flex gap-3 bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center shrink-0", p.iconBg)}>
                      <Icon size={20} className={p.iconColor} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-bold text-slate-200">{p.title}</h3>
                        <span className="text-[10px] text-slate-500 bg-slate-800 rounded px-1.5 py-0.5">{p.path}</span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed mt-1">{p.desc}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* ── Tips ── */}
          <section className="bg-gradient-to-r from-blue-500/5 to-indigo-500/5 border border-blue-500/15 rounded-2xl p-5 mb-4">
            <h3 className="text-sm font-bold text-slate-200 mb-3">小贴士</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-[11px] text-slate-400">
              <div className="flex items-start gap-2">
                <span className="text-blue-400 font-bold shrink-0">*</span>
                <span>侧边栏底部<b className="text-slate-300">电源按钮</b>：短按启停后端，<b className="text-slate-300">长按 2 秒</b>强制清理所有进程</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-blue-400 font-bold shrink-0">*</span>
                <span>底部<b className="text-slate-300">绿/红灯</b>指示 ROS2 连接状态，断线会自动 3 秒重连</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-blue-400 font-bold shrink-0">*</span>
                <span>聊天界面点击<b className="text-slate-300">齿轮图标</b>可配置 LLM Provider (OpenAI/Gemini/DashScope/Deepseek/自定义)</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-blue-400 font-bold shrink-0">*</span>
                <span>地图页面支持<b className="text-slate-300">多地图管理</b>和图层校准，点击拓扑节点查看全景照片</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-blue-400 font-bold shrink-0">*</span>
                <span>多端同步：多个浏览器同时打开，聊天消息和 LLM 配置实时同步</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="text-blue-400 font-bold shrink-0">*</span>
                <span>支持<b className="text-slate-300">图片上传</b>（直接粘贴或点击附件图标），VLM 会识别图中内容</span>
              </div>
            </div>
          </section>

          <footer className="text-center text-[10px] text-slate-600 pb-6">
            SSTG-Nav v2.5 — Spatial Semantic Topological Graph Navigation
          </footer>
        </div>
      </div>
    </div>
  );
}
