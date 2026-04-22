# SSTG-Nav UI App -- 完整架构文档

> **版本**: v2.5 (Phase 14)
> **技术栈**: React 19 + TypeScript + Zustand + Vite 8 + Three.js + roslib.js
> **定位**: SSTG-Nav 机器人的 Web 控制前端 -- 集成语义地图 3D 可视化、多模态 LLM 对话、任务编排、系统监控
> **可视化架构图**: 打开 `../_WBT_WS_SSTG/architecture_viz/sstg_ui_architecture.html` 查看交互式架构图

---

## 1. 系统架构总览

```
  浏览器 (React SPA)                Vite Dev Server (Node.js)              ROS2 Backend
 ┌───────────────────┐          ┌─────────────────────────┐          ┌──────────────────────┐
 │                   │  HTTP    │  chatSyncPlugin          │          │  rosbridge_websocket  │
 │  ChatView         │ ◄──────►│   ├ REST API (会话/消息)  │          │       :9090           │
 │  MapView          │  SSE    │   ├ SSE 广播              │          │                      │
 │  RobotView        │ ◄──────│   ├ LLM 流式代理          │          │  interaction_manager  │
 │                   │         │   ├ 图片检索引擎          │          │  system_manager       │
 │  Zustand Stores   │         │   └ 图片标注引擎(Sharp)   │          │  nlp_node             │
 │   ├ rosStore      │ WS     │                           │          │  planning_node        │
 │   ├ chatStore ────┼────────►│  llmProxyPlugin           │          │  executor_node        │
 │   └ mapStore      │         │   └ CORS 代理 → LLM API  │          │  perception_node      │
 │                   │ WS      │                           │          │  map_manager_node     │
 │  roslib.js  ──────┼────────►│  backendLauncherPlugin    │  spawn   │  exploration_server   │
 │                   │ :9090   │   └ 进程管理(启停/清杀)────┼────────►│                      │
 │                   │         │                           │          │  Nav2 / AMCL / SLAM   │
 └───────────────────┘         │  Vite Static Server       │          │  底盘 / 雷达 / 相机   │
                               │   └ public/ (地图/全景图) │          └──────────────────────┘
                               └─────────────────────────┘
```

**两条通信通道**:
- **HTTP/SSE**: 浏览器 ↔ Vite Server -- 聊天消息、LLM 流式、图片、后端进程管理
- **WebSocket**: 浏览器 ↔ rosbridge(:9090) -- 机器人位姿、任务状态、系统监控、导航指令

---

## 2. 目录结构

```
sstg_ui_app/
├── index.html                  # 入口 HTML (PWA manifest, 中文 lang)
├── package.json                # 依赖: react 19, three, roslib, zustand, sharp, react-markdown
├── vite.config.ts              # Vite 配置 + 3 个自定义插件 (289 行)
├── tailwind.config.js          # TailwindCSS 3 + @tailwindcss/typography
├── tsconfig.json               # TypeScript 严格模式
├── public/
│   ├── maps/                   # PGM 地图 + YAML + 拓扑 JSON + 全景图
│   │   ├── *.pgm / *.yaml      # ROS2 格式栅格地图
│   │   ├── topological_map_manual.json   # 拓扑语义地图 (节点/物体/别名)
│   │   └── captured_nodes/     # 每个节点 4 方向全景 (000/090/180/270deg_rgb.png)
│   ├── favicon.png / icon-180.png
│   └── manifest.webmanifest    # PWA 配置
├── vite-plugins/
│   └── chatSyncPlugin.ts       # ★ 核心: 聊天服务器 (1493 行) -- 详见 §3.5
├── src/
│   ├── main.tsx                # React 入口
│   ├── App.tsx                 # ★ App Shell: 路由 + 认证 + 电源按钮 (289 行)
│   ├── components/
│   │   ├── ChatView.tsx        # ★ 聊天页面: 流式对话 + 模式切换 + 图片 (1544 行)
│   │   ├── MapView.tsx         # ★ 地图页面: 3D 全息地图 + 节点详情 (707 行)
│   │   ├── RobotView.tsx       # ★ 系统页面: 模式切换 + 硬件 + 监控 (337 行)
│   │   └── UsernameModal.tsx   # 首次访问昵称输入 (43 行)
│   ├── store/
│   │   ├── rosStore.ts         # ROS 连接 + Topic 订阅 + Service 调用 (367 行)
│   │   ├── chatStore.ts        # 会话/消息/LLM 配置 + SSE 同步 (537 行)
│   │   └── mapStore.ts         # 地图元数据 + 校准 + localStorage (123 行)
│   ├── hooks/
│   │   └── useVoiceInput.ts    # 语音输入 (Web Speech API, 104 行)
│   ├── lib/
│   │   ├── pgm3DParser.ts      # PGM 地图 → 3D 挤出网格 (116 行)
│   │   └── utils.ts            # cn() 工具函数 (clsx + tailwind-merge)
│   └── assets/
│       └── LOGO.png            # 应用 Logo
└── ~/sstg-data/chat/           # 运行时数据 (Vite Server 写入)
    ├── index.json              # 会话索引
    ├── messages/*.json         # 每会话消息持久化
    ├── llm-config.json         # LLM 配置 (所有浏览器共享)
    └── images/
        ├── upload/             # 用户上传图片
        └── annotated/          # VLM 标注后图片
```

---

## 3. 核心模块详解

### 3.1 App Shell (`App.tsx`)

**职责**: 全局布局、路由、认证、ROS 连接管理、后端进程控制

**路由表**:
| 路径 | 组件 | 功能 |
|------|------|------|
| `/` | `ChatView` | 多模态对话 + 任务发送 |
| `/map` | `MapView` | 3D 语义地图 + 节点详情 |
| `/robot` | `RobotView` | 系统监控 + 模式切换 |

**认证流程**:
1. `AuthGate` — 共享密钥门禁 (硬编码 `sstg2026`, localStorage 持久化)
2. `UsernameModal` — 首次访问输入昵称 (标记消息发送者, localStorage)

**启动流程** (`useEffect` in `AppLayout`):
```
页面加载 → connect() 连接 rosbridge → initChat() 加载聊天 + SSE
         → 检查 /api/system/backend-status
连接成功 → 推送 LLM 配置到后端 (updateLLMConfig)
         → 如果是电源按钮启动的 → 自动 launchMode("navigation")
```

**电源按钮** (侧边栏底部):
- **短按**: 启动 (`/api/system/start-backend`) 或停止 (`/api/system/stop-backend`)
- **长按 2s**: 强制清杀所有 ROS2 进程 (`/api/system/force-cleanup`)
- 启动后自动跳转到 `/robot` 页面

---

### 3.2 ChatView (`ChatView.tsx`, 1544 行)

**最复杂的组件**, 包含以下子系统:

#### 三种模式

| 模式 | 通道 | 允许的意图 | 典型指令 |
|------|------|-----------|---------|
| `chat` | 流式 HTTP SSE | 纯聊天 | "你好"、"你叫什么" |
| `navigate` | ROS Service | 聊天 + 导航 + 物体搜索 | "去客厅"、"帮我找书包" |
| `explore` | ROS Service | 聊天 + 环境探索 | "探索新家" |

不允许的意图会被前端拦截并返回友好提示 (不发给后端)。

#### 双通道发送逻辑

```
用户输入
  ├── chat 模式 → handleStreamChat() → POST /api/chat/stream → SSE 流式
  ├── navigate/explore + 有图片 → handleStreamChat() → SSE 流式 (图片不走 ROS)
  ├── navigate/explore + 停止关键词 → cancelTask() → ROS /cancel_task
  └── navigate/explore + 文本 → startTask() → ROS /start_task
```

#### LLM 流式渲染优化
- `streamBufferRef` 累积 token, `requestAnimationFrame` 批量刷新
- 每帧最多触发一次 `setState`, 避免高频重渲染
- SSE 连接使用 `Content-Encoding: identity` 禁用压缩

#### 任务队列
- 后端排队时, 前端显示独立的排队指示卡片 (`QueueItem`)
- 后端开始处理时, 从排队区"弹入"聊天区
- 用户可在排队阶段取消 (方案 B: 前端忽略)

#### 图片上传
- 支持拖拽 / 粘贴 / 文件选择, 最多 4 张
- 自动压缩: `MAX_IMAGE_DIM=1280, JPEG_QUALITY=0.8`
- 发送时携带 base64, 服务端保存到 `~/sstg-data/chat/images/upload/`

#### LLM Provider 设置面板
- 内置 5 个 Provider: DashScope, DeepSeek, ZhipuAI, Ollama, OpenAI
- 支持自定义添加/删除 Provider
- 连通性诊断 (测试 TTFT, 超时检测)
- 配置服务端持久化 (`/api/llm-config`), SSE 多端同步

#### 滚动行为
- `autoScrollToBottom(force?)` — 距底部 150px 内自动跟随
- `visibilitychange` 监听 — 后台标签页切回时强制归底
- `prevSessionRef` — 切换会话时强制归底
- `scroll` 事件持续追踪 `wasAtBottomRef`

---

### 3.3 MapView (`MapView.tsx`, 707 行)

#### 3D 全息地图
- **PGM → 3D**: `pgm3DParser.ts` 解析 ROS2 栅格地图 → 生成 color 和 displacement 纹理 → Three.js `planeGeometry` + `displacementMap` 实现 2.5D 挤出
- **拓扑节点**: 八面体晶体 (`octahedronGeometry`) + HTML 标签 (`@react-three/drei Html`)
- **机器人位姿**: 绿色锥体箭头, 实时跟踪 `/navigation_feedback` topic
- **实时地图**: `LiveMapLayer` 渲染 `/map` topic 的 OccupancyGrid (SLAM/探索时叠加)

#### 节点详情侧栏
- 点击节点 → 显示语义信息 (房间类型、置信度、物体别名)
- 360° 全景画廊 (4 方向缩略图, 点击放大, 键盘左右切换)
- "导航前往" 按钮 → 直接调用 `startTask("去{房间名}")`

#### 地图管理器
- 多地图 CRUD (添加/删除/重命名)
- 拓扑节点 JSON 路径可编辑
- 图层校准面板: 地图翻转、节点翻转、XY 平移偏移
- 相机视角持久化 (锁定当前视角 → 刷新自动恢复)

---

### 3.4 RobotView (`RobotView.tsx`, 337 行)

| 区块 | 数据来源 | 功能 |
|------|---------|------|
| 运行模式 | `/system/launch_mode` service | 切换 exploration / navigation / stop |
| 硬件设备 | `/system/status` topic | 底盘 CH340、雷达 RPLidar S2、相机 Gemini 336L 状态 |
| 系统资源 | `/system/status` topic | CPU/RAM 百分比 + 进度条 |
| 活跃节点 | `/system/get_status` service | 展开查看所有运行中 ROS2 节点 |
| 系统日志 | `/system/log` topic | 实时日志流 (自动滚动, 错误/警告高亮) |

---

### 3.5 Vite Server 后端 (最核心部分)

Vite Dev Server 通过 3 个自定义插件承担了"轻量后端"角色:

#### 3.5.1 chatSyncPlugin (`vite-plugins/chatSyncPlugin.ts`, 1493 行)

**这是整个 UI 的核心服务**, 功能包括:

**A) 聊天持久化 + REST API**
- 会话 CRUD (`/api/chat/sessions`)
- 消息读写 (`/api/chat/sessions/:id/messages`)
- 消息更新 (`/api/chat/messages/:id`) — 合并 meta/steps
- 自动标题 (首条用户消息截取 12 字符)
- JSON 文件持久化 (`~/sstg-data/chat/`)
- 防抖写盘 (1s debounce)

**B) SSE 实时广播**
- 所有浏览器共享同一份聊天数据
- 事件类型: `message_added`, `message_updated`, `session_created`, `session_switched`, `session_deleted`, `session_renamed`, `llm_config_updated`
- 30s 心跳保活

**C) LLM 流式代理 (`/api/chat/stream`)**
- 接收用户文本 + 图片 → 构建 OpenAI 兼容请求 → 流式转发
- System Prompt 内置机器人人格 ("小拓")
- 自动读取拓扑地图作为环境上下文
- **Gemini 特殊处理**: system role 遵从度低, 改用 few-shot 锁定角色
- 多模态图片格式适配: OpenAI 格式 vs Qwen-VL 格式

**D) 图片检索引擎**
- 拓扑地图语义搜索 (`searchTopoForObject`)
- 多级匹配: 精确物体名(100分) > 包含匹配(80分) > 别名标签(70分) > 近义词(30分) > 房间类型(10分)
- 内置近义词表 (书包↔背包, 杯子↔水杯, 等)
- 停用词清洗 + 拓扑词典实体提取

**E) 图片标注引擎**
- VLM Grounding: 调用 Gemini/Qwen-VL 获取 bbox
- Gemini: `box_2d [ymin, xmin, ymax, xmax]` 0-1000
- Qwen-VL: `bbox_2d [x1, y1, x2, y2]` 0-1000
- Sharp 绘制: 红色椭圆框 + 标签
- 图片来源优先级: 用户上传 → 检索到的节点图 → 历史图片

**F) LLM 配置管理 (`/api/llm-config`)**
- 服务端 JSON 持久化, 所有浏览器共享
- SSE 广播配置变更

#### 3.5.2 llmProxyPlugin (`vite.config.ts` 内)

- 解决浏览器直调 LLM API 的 CORS 问题
- 前端 → `/api/llm-proxy/chat/completions` + `X-Target-Url` header → 转发到真实 API
- 用于 LLM 连通性诊断

#### 3.5.3 backendLauncherPlugin (`vite.config.ts` 内)

ROS2 后端进程管理, **三层防护**:

| 层级 | 触发时机 | 机制 |
|------|---------|------|
| 第一层 | 停止时 | 优雅关闭链: system_manager 先关 Nav2 → SIGTERM → 等 15s → SIGKILL |
| 第二层 | 启动前 | pkill 清理残留 ROS2 进程 (25+ 进程模式匹配) |
| 第三层 | 长按 2s | 一键清杀所有 ROS2 进程 (`/api/system/force-cleanup`) |

---

### 3.6 状态管理 (Zustand Stores)

#### rosStore (`rosStore.ts`, 367 行)

**连接管理**:
- 自动检测 WebSocket 地址: 本地 → `ws://localhost:9090`, 公网 → `wss://域名/rosbridge`
- 断线 3s 自动重连
- 重连后主动拉取一次当前状态 (`/query_task_status`, `/system/get_status`)

**订阅的 Topics**:
| Topic | 消息类型 | 用途 |
|-------|---------|------|
| `/navigation_feedback` | `NavigationFeedback` | 机器人实时位姿 (四元数→yaw) |
| `/task_status` | `TaskStatus` | 任务进度 (state/message/progress) |
| `/system/status` | `SystemStatus` | CPU/RAM/设备状态 |
| `/system/log` | `std_msgs/String` | 系统日志流 (保留最近 200 条) |
| `/map` | `nav_msgs/OccupancyGrid` | 实时栅格地图 (2s 节流) |

**调用的 Services**:
| Service | 类型 | 用途 |
|---------|------|------|
| `/start_task` | `ProcessNLPQuery` | 发送自然语言任务 |
| `/cancel_task` | `std_srvs/Trigger` | 取消当前任务 |
| `/system/launch_mode` | `LaunchMode` | 切换运行模式 |
| `/system/get_status` | `GetSystemStatus` | 拉取完整系统状态 |
| `/nlp/update_llm_config` | `UpdateLLMConfig` | 推送 LLM 配置到后端 |
| `/nlp/delete_session` | `DeleteChatSession` | 删除聊天会话 |
| `/query_task_status` | `std_srvs/Trigger` | 查询当前任务状态 |

#### chatStore (`chatStore.ts`, 537 行)

- 会话列表 + 当前会话消息 (服务端同步)
- LLM Provider 配置 (服务端持久化 + SSE 多端同步)
- 任务所有权追踪 (`isTaskOwner` / `currentRobotMsgId`)
- 本地消息队列 (`localQueue` / `canceledTaskIds`)
- SSE 事件处理 (`_applySSE`) — 自动去重、会话切换、消息更新

#### mapStore (`mapStore.ts`, 123 行)

- 多地图管理 (CRUD)
- 每地图独立校准参数 (翻转/偏移)
- 相机视角持久化
- 全部 localStorage 持久化

---

## 4. 前后端接口完整清单 (最重要)

### 4.1 Vite Server HTTP API

#### 聊天 API

| Method | Path | 功能 | 请求体 | 响应 |
|--------|------|------|--------|------|
| GET | `/api/chat/sessions` | 获取会话列表 | - | `{ sessions, activeSessionId }` |
| POST | `/api/chat/sessions` | 创建新会话 | `{ title? }` | `ChatSession` |
| PUT | `/api/chat/sessions/active` | 切换活跃会话 | `{ sessionId }` | `{ ok }` |
| PUT | `/api/chat/sessions/:id` | 重命名会话 | `{ title }` | `ChatSession` |
| DELETE | `/api/chat/sessions/:id` | 删除会话 | - | `{ ok }` |
| GET | `/api/chat/sessions/:id/messages` | 获取会话消息 | - | `{ messages }` |
| POST | `/api/chat/sessions/:id/messages` | 添加消息 | `{ role, content, sender?, images?, meta? }` | `ChatMessage` |
| PUT | `/api/chat/messages/:id` | 更新消息 (merge) | `{ sessionId, meta?, content? }` | `ChatMessage` |
| GET | `/api/chat/events` | SSE 实时推送 | - | `text/event-stream` |

#### 流式聊天 API

| Method | Path | 功能 |
|--------|------|------|
| POST | `/api/chat/stream` | LLM 流式聊天 |

**请求体**:
```json
{
  "sessionId": "session-xxx",
  "text": "帮我找书包",
  "senderName": "小明",
  "mapContext": "当前地图: 家...",
  "images": [{ "base64": "...", "mimeType": "image/jpeg", "width": 640, "height": 480 }]
}
```

**响应**: SSE 流
```
X-User-Msg-Id: msg-xxx     (响应头)
X-Robot-Msg-Id: msg-yyy     (响应头)

data: {"event":"token","token":"你"}
data: {"event":"token","token":"好"}
data: {"event":"done","content":"你好！","msgId":"msg-yyy"}
```

**流程**: 保存用户消息 → 创建 robot 占位 → 广播 → LLM 流式 → 完成后自动检测:
- 图片检索意图 → 创建 imgMsg → 拓扑搜索 → 附加节点全景图
- 图片标注意图 → VLM Grounding → Sharp 绘制 → 附加标注图
- 创作意图 → 跳过图片操作

#### LLM 配置 API

| Method | Path | 功能 |
|--------|------|------|
| GET | `/api/llm-config` | 获取 LLM 配置 |
| PUT | `/api/llm-config` | 更新 LLM 配置 (广播到所有客户端) |

#### 图片 API

| Method | Path | 功能 |
|--------|------|------|
| GET | `/api/images/upload/:filename` | 用户上传图片 |
| GET | `/api/images/annotated/:filename` | VLM 标注后图片 |
| GET | `/api/topo/search-images?q=书包` | 拓扑图片搜索 |

#### 系统管理 API

| Method | Path | 功能 |
|--------|------|------|
| POST | `/api/system/start-backend` | 启动 ROS2 后端 |
| POST | `/api/system/stop-backend` | 优雅停止后端 |
| POST | `/api/system/force-cleanup` | 强制清杀所有 ROS2 进程 |
| GET | `/api/system/backend-status` | 查询后端运行状态 |

#### LLM 代理

| Method | Path | 功能 |
|--------|------|------|
| POST | `/api/llm-proxy/*` | CORS 代理 → 真实 LLM API (需 `X-Target-Url` header) |

---

### 4.2 ROS2 WebSocket 接口

通过 `roslib.js` 连接 `rosbridge_websocket` (:9090)

#### 订阅的 Topics

| Topic | 消息类型 | 频率 | UI 消费者 |
|-------|---------|------|----------|
| `/navigation_feedback` | `sstg_msgs/NavigationFeedback` | 实时 | MapView (机器人位姿) |
| `/task_status` | `sstg_msgs/TaskStatus` | 事件驱动 | ChatView (任务进度条) |
| `/system/status` | `sstg_msgs/SystemStatus` | 定时 | RobotView (CPU/RAM/设备) |
| `/system/log` | `std_msgs/String` | 实时 | RobotView (日志终端) |
| `/map` | `nav_msgs/OccupancyGrid` | 2s 节流 | MapView (实时地图叠加) |

#### 调用的 Services

| Service | 类型 | 触发场景 |
|---------|------|---------|
| `/start_task` | `ProcessNLPQuery` | ChatView: navigate/explore 模式发送消息 |
| `/cancel_task` | `std_srvs/Trigger` | ChatView: "停下"/"取消" |
| `/system/launch_mode` | `LaunchMode` | RobotView: 模式切换; App: 启动时自动 |
| `/system/get_status` | `GetSystemStatus` | RobotView: 进入页面 + 5s 轮询 |
| `/nlp/update_llm_config` | `UpdateLLMConfig` | App: ROS 连接成功后推送 |
| `/nlp/delete_session` | `DeleteChatSession` | chatStore: 删除会话时通知后端 |
| `/query_task_status` | `std_srvs/Trigger` | rosStore: 重连后拉取当前状态 |

---

### 4.3 ROS2 消息/服务定义

#### ProcessNLPQuery.srv (核心入口)
```
# Request
string text_input          # 用户自然语言
string context             # 地图上下文
string session_id          # 聊天会话 ID
string sender_name         # 发送者昵称
---
# Response
bool success
string query_json          # 解析结果 JSON
string intent              # 识别意图: navigate_to / locate_object / explore_new_home / chat / queued
float32 confidence
string error_message
```

#### TaskStatus.msg (任务进度)
```
string task_id
string state               # idle / understanding / planning / navigating / exploring / searching / completed / failed / canceled
string current_message     # 人类可读状态描述
string user_query_needed   # 需要用户确认时的问题
float32 progress           # 0.0 ~ 1.0
string history             # 任务历史 JSON
```

#### NavigationFeedback.msg (位姿反馈)
```
int32 node_id
string status
float32 progress
geometry_msgs/Pose current_pose    # 四元数 → UI 转为 yaw
string error_message
float32 distance_to_target
float32 estimated_time_remaining
```

#### SystemStatus.msg (系统监控)
```
string mode                    # idle / navigation / exploration
float32 cpu_percent
float32 memory_percent
string[] device_status         # ["OK:底盘 CH340:/dev/ttyUSB1", ...]
int32 active_node_count
builtin_interfaces/Time stamp
```

#### LaunchMode.srv (模式切换)
```
string mode                    # navigation / exploration / stop
---
bool success
string message
string[] launched_nodes
```

#### UpdateLLMConfig.srv
```
string base_url
string api_key
string model
---
bool success
string message
```

#### ExploreHome.action (探索)
```
# Goal
string session_id
string map_prefix
---
# Result
bool success
string message
string map_yaml
string trace_json
---
# Feedback
string status
int32 frontier_count
float32 progress
```

#### 其他 Services
| Service | 功能 |
|---------|------|
| `GetSystemStatus` | 获取完整系统状态 (active_nodes, device_status, hardware_ok) |
| `DeleteChatSession` | 删除后端聊天会话记录 |
| `GetTopologicalMap` | 获取完整拓扑图 JSON |
| `CheckObjectPresence` | 检查图片中是否存在指定物体 |

---

## 5. 数据流图

### 5.1 聊天消息流

```
[chat 模式]
用户输入 → POST /api/chat/stream → chatSyncPlugin:
  1. 保存 userMsg → 广播 message_added
  2. 创建 robotMsg 占位 → 广播 message_added
  3. 构建 LLM messages (System Prompt + 拓扑上下文 + 历史 + 用户输入)
  4. 流式请求 LLM API → 逐 token SSE 推送给发起者
  5. 完成 → 更新 robotMsg.content → 广播 message_updated
  6. 检测图片意图 → 创建 imgMsg → 拓扑搜索/标注 → 广播

[navigate/explore 模式]
用户输入 → rosStore.startTask() → ROS /start_task:
  1. 前端: addMessage(user) + addMessage(robot 占位)
  2. 后端: NLP 理解 → 规划 → 执行
  3. /task_status topic 推送进度 → ChatView useEffect → updateLastRobotMessage
  4. 终态: finalizeLastRobotMessage 清除 ownership
```

### 5.2 图片检索流

```
用户: "帮我找书包"
  → /api/chat/stream → LLM 流式回复 "好的，帮你找找看~"
  → 检测到 imageReqPattern 且非 isCreative
  → 创建 imgMsg (status: searching)
  → 文本清洗: 去停用词 → 提取关键词 ["书包"]
  → 近义词扩展: ["书包", "背包", "双肩包", "挎包"]
  → 拓扑词典匹配: 扫描所有节点物体名
  → searchTopoForObject: 精确匹配(100) > 包含(80) > 别名(70) > 近义(30)
  → 找到节点 → 加载 4 方向全景图
  → imgMsg.images = [...] → 广播 message_updated
```

### 5.3 系统启动流

```
用户点击电源按钮 (App.tsx)
  → POST /api/system/start-backend
  → backendLauncherPlugin:
      1. 第二层: pkill 清理残留 ROS2 进程
      2. spawn("ros2 launch sstg_interaction_manager sstg_full.launch.py")
  → App: connect() 自动重试连接 rosbridge
  → rosbridge 就绪 → isConnected = true
  → 推送 LLM 配置 → 自动 launchMode("navigation")
  → RobotView 显示运行状态
```

---

## 6. 3.x 后端对接指南

### 6.1 UI 已具备的能力 (2.x 完成)

| 能力 | 实现方式 |
|------|---------|
| 多模态 LLM 对话 | chatSyncPlugin 流式代理 + 多 Provider 适配 |
| 拓扑语义检索 | chatSyncPlugin 内置搜索引擎 |
| VLM 图片标注 | chatSyncPlugin + Sharp |
| 3D 地图可视化 | MapView + Three.js + PGM 解析 |
| 机器人位姿跟踪 | rosStore 订阅 /navigation_feedback |
| 实时地图叠加 | MapView LiveMapLayer 订阅 /map |
| 任务状态跟踪 | ChatView 订阅 /task_status |
| 系统监控 | RobotView 订阅 /system/status + /system/log |
| 硬件模式切换 | RobotView 调用 /system/launch_mode |
| 后端进程管理 | backendLauncherPlugin 三层防护 |
| 用户图片上传 | ChatView 压缩 + base64 + 多模态 VLM |
| 语音输入 | useVoiceInput (Web Speech API) |
| 多端同步 | SSE 广播 + 服务端持久化 |

### 6.2 3.x 需要后端新增/增强的接口

#### 探索功能对接

**UI 已准备**:
- `explore` 模式 (ChatView)
- 实时 OccupancyGrid 渲染 (MapView `LiveMapLayer`)
- `/map` topic 订阅 (rosStore)

**后端需要提供**:
1. **探索进度 Topic** — UI 需要在 `/task_status` 中接收探索进度, `state` 包含 `exploring`
2. **ExploreHome.action 反馈** — `frontier_count` 和 `progress` 字段需要填充
3. **新节点发现通知** — 探索过程中发现新节点时, 拓扑地图 JSON 需要动态更新, 或提供增量 topic

#### 导航路径可视化

**UI 已准备**:
- MapView 中有拓扑边连线 (Line 组件)
- 机器人实时位姿追踪

**后端需要提供**:
1. **导航路径 Topic** — 发布规划路径的点序列, 供 MapView 绘制路径线
2. **NavigationFeedback 增强** — `distance_to_target` 和 `estimated_time_remaining` 字段需要真实值

#### 拓扑地图动态更新

**UI 已准备**:
- MapView 从 `public/maps/topological_map_manual.json` 加载拓扑
- chatSyncPlugin 从同一文件做语义搜索

**后端需要提供**:
1. **GetTopologicalMap service** — UI 可以主动拉取最新拓扑 (替代静态文件)
2. **拓扑变更 Topic** — 节点增删时通知 UI 刷新

#### 物体检索增强

**当前状态**: chatSyncPlugin 内置简单的字符串匹配搜索

**后端可提供**:
1. **CheckObjectPresence service** — VLM 确认物体是否真的在该节点 (减少误报)
2. **语义向量搜索** — 替代前端的关键词匹配

### 6.3 关键交接点

| 交接点 | UI 侧 | 后端侧 |
|--------|--------|--------|
| 任务入口 | `rosStore.startTask()` 调用 `/start_task` | `interaction_manager` 接收 `ProcessNLPQuery` |
| 状态反馈 | `ChatView` 监听 `/task_status` topic | `interaction_manager` 发布 `TaskStatus` |
| LLM 配置 | `chatStore` 管理 + App 启动推送 | `nlp_node` 接收 `UpdateLLMConfig` |
| 模式切换 | `RobotView` 调用 `/system/launch_mode` | `system_manager` 处理 `LaunchMode` |
| 地图数据 | `MapView` 读取 `public/maps/` | ROS2 map_server 或 SLAM 输出 |
| 拓扑数据 | 静态 JSON + chatSyncPlugin 搜索 | `map_manager` 维护 + `GetTopologicalMap` |
| 聊天持久化 | chatSyncPlugin (Vite Server 侧) | `nlp_node` 可选维护 session 上下文 |

---

## 7. 开发与部署

### 本地开发

```bash
cd ~/wbt_ws/sstg-nav/sstg_ui_app
npm install
npm run dev     # http://localhost:5173
```

### 环境依赖

| 依赖 | 用途 |
|------|------|
| Node.js 18+ | Vite Dev Server |
| `rosbridge_websocket` :9090 | ROS2 WebSocket 桥 |
| `~/sstg-data/chat/` | 聊天数据持久化 (自动创建) |
| `public/maps/` | 静态地图文件 |
| LLM API Key | 在 UI 设置面板配置 |

### 端口

| 端口 | 服务 |
|------|------|
| 5173 | Vite Dev Server (HTTP + SSE + WebSocket 代理) |
| 9090 | rosbridge_websocket |

### 公网访问

Vite 配置已启用:
- `server.host: '0.0.0.0'` — 监听所有网卡
- `server.allowedHosts: true` — 允许 Tailscale Funnel 等外部域名
- `/rosbridge` WebSocket 代理 — 公网浏览器通过 `wss://域名/rosbridge` 访问 ROS2
- rosStore 自动检测: 本地 → `ws://localhost:9090`, 公网 → `wss://host/rosbridge`

### 关键命令

```bash
# 构建生产版本
npm run build

# 预览生产版本
npm run preview

# 代码检查
npm run lint
```

---

## 8. 相关文档索引

| 文档 | 路径 | 内容 |
|------|------|------|
| UI 用户指南 | `../SSTG_UI_Guide.md` | 面向用户的操作说明 |
| 设计迭代记录 | `../_WBT_WS_SSTG/doc/2.2_[UI_Image]*.md` | v2.x 全部版本变更记录 |
| 架构可视化 | `../_WBT_WS_SSTG/architecture_viz/sstg_ui_architecture.html` | 交互式架构图 |
| 深度集成方案 | `../_WBT_WS_SSTG/doc/2.1_[UI+]_deep_integration_plan*.md` | 图片交互方案设计 |
| 后端模块文档 | `../sstg_nav_ws/src/sstg_*/doc/MODULE_GUIDE.md` | 各 ROS2 节点详细文档 |
| 项目总体进度 | `../PROJECT_PROGRESS.md` | 全项目进度追踪 |
