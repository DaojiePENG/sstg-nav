# SSTG Navigation System - Visual UI Architecture & Development Guide

**最后更新时间**: 2026-04-09
**当前 UI 版本**: v1.1.0 (Phase 3 完成，交互闭环就绪)

## 1. 项目简介与核心定位

本项目 (`sstg_ui_app`) 是为 SSTG (Spatial Semantic Topological Graph) 机器人导航系统量身定制的**跨平台 Linux 桌面应用**前端。
它**不是**一个通用大模型聊天套壳（如 LobeChat/OpenWebUI），而是一个以**“语义地图可视化 + 任务对话 + 机器人状态编排”**为核心的专业级工业控制软件。

- **技术栈**: Vite + React 18 + TypeScript + TailwindCSS 3 + Shadcn UI (Lucide Icons)
- **3D 引擎**: Three.js + `@react-three/fiber` + `@react-three/drei`
- **状态与缓存**: `zustand` (带有 `localStorage` 持久化)
- **ROS 通信**: `roslib` (WebSocket 直连后端 `rosbridge_server`)
- **打包套件**: Tauri (计划中，用于打包 `.deb` / `.AppImage`)

## 2. 目录结构与核心代码导航

如果下一个 Agent 需要接手或修改 UI，请重点关注以下文件分布：

```text
sstg_ui_app/
├── public/
│   └── maps/                  # ⚠️ 极其重要！所有本地的 .pgm, .yaml, .json 拓扑图和实景全景图都存在这里。UI 会通过 Fetch 加载它们。
├── src/
│   ├── components/            # 核心页面视图组件 (业务逻辑最重的地方)
│   │   ├── ChatView.tsx       # 聊天与任务编排页 (包含大模型诊断、历史会话、导航指令下发)
│   │   └── MapView.tsx        # 3D 全息语义地图页 (包含 Three.js 渲染、图层对齐校准、实景画廊漫游)
│   ├── lib/
│   │   ├── pgm3DParser.ts     # ⚠️ 核心自研算法：将 ROS 的 2D .pgm 灰度图解析并拔高成 2.5D 的 Three.js 深度贴图矩阵。
│   │   └── utils.ts           # Tailwind 类名合并工具 (cn)
│   ├── store/                 # Zustand 全局状态管理 (系统的“大脑”与“记忆”)
│   │   ├── chatStore.ts       # 负责存储聊天记录、多会话 (Sessions)、大模型 API 配置。
│   │   ├── mapStore.ts        # 负责存储每张地图的 3D 视角、X/Y 偏移量、翻转状态、关联的 JSON 文件路径。
│   │   └── rosStore.ts        # 负责维护 roslibjs WebSocket 连接、机器人实时位姿和任务执行进度条。
│   ├── App.tsx                # 应用的根路由和极简左侧边栏导航。
│   ├── index.css              # 全局深色模式 (Dark Theme) 和字体设定。
│   └── main.tsx               # React 挂载入口。
```

## 3. 架构设计与状态流转机理

- **状态持久化 (Persistence)**:
  `chatStore` 和 `mapStore` 都自己实现了简单的 `localStorage` 劫持。用户修改的任何大模型 API 密钥、任何一张地图的 X/Y 偏移量和翻转配置，只要修改过一次，**永久生效**。
- **地图渲染解耦**:
  地图的 2D 栅格图片 (`.pgm`) 和它的拓扑节点 (`.json`) 的坐标系往往是不一致的。因此我们在 `MapView.tsx` 的 **[3D 校准]** 面板中，将 Map 和 Nodes 彻底拆分，允许用户独立对它们进行 X/Y 轴的翻转 (Flip) 和偏移 (Offset) 并单独保存。
- **ROS 桥接闭环**:
  所有跟机器人打交道的操作全在 `rosStore.ts`。`startTask` 封装了 `sstg_msgs/srv/ProcessNLPQuery`；状态栏的数据来源于订阅 `/navigation_feedback`。

## 4. ⚠️ 历史踩坑记录与警告 (给下一个 Agent 的避雷针)

如果你要修改复杂的 React JSX 代码，请**务必**注意以下血泪教训：

1. **白屏/全无界面的致命原因 (React Syntax / DOM Nesting)**:
   - 曾因为将一个全屏遮罩 `Modal` 从代码末尾强行挪进 `<header>` 内部，且丢失了闭合标签 `</div>`，导致 Vite/esbuild 抛出 `[PARSE_ERROR]`，从而让整个页面瞬间变白屏。
   - **Agent 必读**: 在做大段 JSX 的正则表达式替换或字符串注入时，**必须确保闭合标签完好**。如果出现页面变白，立刻 `npm run dev` 看终端的语法报错，或者在浏览器打开 F12 控制台，大概率是 `SyntaxError` 或者是未引入的 Component（如未引入某个 Icon）。
2. **TypeScript 类型导出报错**:
   - 不要轻易修改 `export interface` 后又在别的地方使用 `as any`，曾导致 Vite 的 HMR (热更新) 崩溃报 `does not provide an export named xxx`。最好把 Interface 都清晰地写在对应文件顶部。
3. **MapCalibration 解构 undefined 报错**:
   - `zustand` 初始化的持久化数据中，老旧版本的缓存可能缺少新加的字段（比如后来加的 `nodeOffsetX`）。在从 `Store` 解构数据时，**必须要有 Fallback 回退机制**，否则极易抛出 `Cannot destructure property 'x' of 'undefined'` 导致组件渲染炸毁：
     ```typescript
     // ❌ 错误示范 (极易炸裂)
     const { flipMapX } = calibration; 
     // ✅ 正确示范 (防御性编程)
     const { flipMapX = false } = (calibration || {}) as any;
     ```

## 5. 下一步行动计划 (Next Steps)

当前 UI 已经完成了前端静态交互、大模型联调闭环和 3D 地图可视化。接下来的待办事项：

- [ ] **Phase 4: Tauri 桌面端套壳与 Linux 打包部署**
  - 当前是用浏览器访问 Vite 的 5173 端口。下一步需要通过 `npm install @tauri-apps/api @tauri-apps/cli`，在项目中初始化 Rust 环境。
  - 配置 `tauri.conf.json`，并将打包目标设定为 `.deb` 或 `.AppImage`。
  - 这样可以直接在机器人主机（比如车载 NUC 或 Jetson）上双击打开这个极其美观的独立软件，而不需要再开浏览器。
- [ ] **完善 ROS 真实联调**
  - 启动后端的 `rosbridge_server`。
  - 测试小车在行驶时，`rosStore` 收到的 `/navigation_feedback` 进度条和 X/Y 坐标能否流畅地在 UI 面板上跳动更新。
- [ ] **动态获取地图列表**
  - 目前 `mapStore.ts` 里的 `DEFAULT_MAPS` 列表是写死的。后续可以通过编写一个后端小脚本（或通过 Tauri 的文件系统 API），在应用启动时自动遍历 `/maps` 文件夹，生成下拉菜单选项。
## 6. 🤝 跨 Agent 协作协议 (SSTG 后端交互与接口契约)

本节专为负责编写 SSTG **后端 ROS 节点代码 (如 Claude)** 的智能体提供。前端 UI 的所有交互都强依赖以下接口与文件系统约定，请在修改后端时**严格遵守以下契约**，否则前端将无法正常工作：

### 6.1 文件系统约定 (File System Contracts)
前端 UI 会直接通过 HTTP Fetch 读取静态资源。请确保后端建图和保存节点时，输出的文件路径和格式符合以下规范：

*   **二维栅格地图保存**:
    *   存放位置: `/sstg_nav_ws/src/sstg_rrt_explorer/maps/`
    *   格式要求: 必须成对保存 `.pgm` (P5格式，不能是P2) 和 `.yaml` 文件。
    *   **⚠️ 注意**: UI 是使用自研 `pgm3DParser.ts` 直接解析 `.pgm` 的二进制数据并根据 `.yaml` 中的 `occupied_thresh` 和 `resolution` 拉伸 3D 墙壁的，请勿改变标准的 ROS `map_server` 输出格式。
*   **拓扑图数据保存**:
    *   格式要求: 必须是 `.json` 格式，结构需包含 `nodes` 数组，每个 Node 必须有 `id`, `name`, `pose: {x, y, theta}`, `semantic_info: { room_type_cn, aliases, confidence }`。
    *   UI 的地图选取面板支持**为每张 pgm 地图独立绑定一个对应的 topo_json 文件**。
*   **全景实景快照 (Panorama Captures)**:
    *   存放位置: `/sstg_nav_ws/src/sstg_rrt_explorer/captured_nodes/node_{id}/`
    *   命名规范: UI 写死了通过轮播角度加载图片，必须命名为 `000deg_rgb.png`, `090deg_rgb.png`, `180deg_rgb.png`, `270deg_rgb.png`。如果节点缺少图片，UI 会自动容错隐藏。

### 6.2 ROS 2 通信接口约定 (ROS Bridge Contracts)
前端通过 `roslibjs` 经由 `rosbridge_server` (默认 `ws://localhost:9090`) 与 ROS 2 后端通信。前端 `rosStore.ts` 强依赖以下服务和话题：

#### 1. 下发自然语言任务 (Service Client)
*   **Service Name**: `/start_task`
*   **Service Type**: `sstg_msgs/srv/ProcessNLPQuery`
*   **Request**: `text_input` (string, 用户的原话), `context` (string, 默认 "home")
*   **Response**: `success` (bool), `intent` (string, 解析的意图，用于气泡展示), `confidence` (float32), `error_message` (string)
*   **UI 行为**: 用户点击发送后，UI 会立即转为 Loading 动画，等待该 Service 的 Response。

#### 2. 终止当前任务 (Service Client)
*   **Service Name**: `/cancel_task`
*   **Service Type**: `std_srvs/srv/Trigger`

#### 3. 监听任务进度与状态 (Topic Subscriber)
*   **Topic Name**: `/navigation_feedback`
*   **Message Type**: `sstg_msgs/msg/NavigationFeedback`
*   **Fields Required by UI**:
    *   `status` (string): 驱动 UI 右侧面板的状态指示器 (如 "completed", "failed", "executing")。
    *   `progress` (float32, 0.0 ~ 1.0): 驱动 UI 的任务总进度条。
    *   `current_pose` (geometry_msgs/Pose): 驱动 UI 右侧的实时坐标遥测面板 (提取 `position.x` 和 `position.y`)。
    *   `error_message` (string): 如果任务失败，会在这里抓取报错信息并在 UI 弹红框。

> **💡 致后端开发 Agent**: 
> 目前的 UI **不直接订阅高频的 `/map` 话题实时建图**，而是通过长轮询或刷新重新加载静态 PGM 文件。如果后续要实现 RRT 探索过程中的“地图实时扩张渲染”，请通知负责 UI 的 Agent 引入 `nav_msgs/OccupancyGrid` 的实时重绘逻辑。

## 7. 🧠 设计理念与产品初衷 (Design Philosophy & Origins)

为了防止后续接手的开发者或智能体“走弯路”或“过度重构”，特此说明本 UI 诞生时的核心产品决策：

### 7.1 为什么不直接套壳 LobeChat / OpenWebUI？
在项目初期，我们评估过直接使用市面上流行的通用大模型平台（如 LobeChat、OpenWebUI、AnythingLLM）作为底座。但最终**坚决放弃了这条路线**。
*   **原因**：通用平台的中心是“对话”，而 SSTG 系统的中心是**“语义地图可视化 + 机器人控制编排”**。如果套用通用平台，地图页面会沦为一个被边缘化的“插件”，且我们要花 80% 的时间去删减那些与机器人毫不相干的冗余功能（如知识库、多租户等）。
*   **最终形态**：我们选择从零搭建，完全掌握页面骨架，将应用定调为**“带有自然语言入口的机器人控制中枢 (Robot Control Center)”**。

### 7.2 UI 美学基调：暗黑玻璃拟物风 (Dark Glassmorphism)
*   为了突显工业级与科技感，抛弃了花哨的渐变色和高亮亮色，全量采用 `Slate-900/950` 作为底色。
*   引入了大量的毛玻璃特效 (`backdrop-blur`) 和半透明的边框，以模仿高端车载系统或科幻电影中的全息控制台（如发光的蓝色 3D 墙壁、绿色呼吸灯、橙/红色警告状态框）。后续开发请**务必保持这一极简、暗黑的美学基调**，不要轻易引入高饱和度的大面积色块。

### 7.3 关键开源项目借鉴参考 (References)
如果你需要扩充组件，可以优先参考以下我们在设计时借鉴过的开源思想：
*   **Foxglove Studio**：行业顶级的 ROS 可视化平台。我们的 3D 地图渲染思路（Canvas 贴图与坐标系对齐）深受其启发。
*   **assistant-ui**：我们在构建左侧聊天气泡、历史会话列表、以及意图识别标签 (Intent/Confidence Badge) 时，参考了其流式对话组件的最佳实践。

## 8. ⚙️ 核心复杂图层机理解析 (Deep Dive into Core Mechanics)

这是给下一个负责维护 `MapView.tsx` 和 3D 引擎的 Agent 的“解密手册”：

### 8.1 惊艳的 2.5D 全息沙盘是怎么做出来的？
在 `lib/pgm3DParser.ts` 中，我们没有使用沉重的点云或网格模型，而是使用了一种极具性价比的**深度置换贴图 (Displacement Mapping)** 技术：
1.  **二进制解码**：读取 `.pgm` 图像的字节流（P5格式）。
2.  **双通道 Canvas 绘制**：
    *   `Color Canvas`：把黑色的墙画成深蓝色（`#38bdf8`），空白走廊画成深灰色。
    *   `Displacement (高度) Canvas`：把黑色的墙画成纯白色 (值为 255)，空白画成纯黑色 (值为 0)。
3.  **Three.js 挤出**：在 `<meshStandardMaterial>` 中，我们将 `Displacement Canvas` 传入，引擎会根据白色像素自动把平面网格“拔高”，瞬间形成 3D 墙壁的立体效果！

### 8.2 让人头疼的坐标系对齐魔法
ROS 中的 `Map` (通常 X 向右，Y 向上) 和 DOM/Three.js 中的坐标系 (Y向下，Z向深) 是冲突的。我们在 `MapView.tsx` 中做了一套**终极解耦变换矩阵**：
*   用户在左下角点击“水平翻转 Map”，实际上是在调整 `<group scale={[-1, 1, 1]}>`。
*   所有的拓扑节点都经过 `toLocal()` 和 `toCanvasCoord()` 的双重转换计算。
*   **鼠标拾取 (Raycasting/Hit Test)**：因为我们在 3D 和 2D 之间做了大量的 `scale(-1)`，所以传统的 `clientX/clientY` 是算不准的。在代码中，我们巧妙利用了 `e.nativeEvent.offsetX / offsetY` 结合数学反算，保证了无论地图怎么 3D 翻转，鼠标点击节点始终 100% 精准。**修改坐标逻辑时请极其谨慎！**

## 9. 🛠️ 开发、调试与打包部署指南

### 9.1 前端独立开发模式 (Mocking)
如果后端 ROS 环境没有开启，你依然可以开发 UI。
*   `useRosStore` 中有默认的降级处理。
*   静态的 `pgm` 地图和 `json` 都会从 `/public/maps/` 读取。如果需要测试新地图，直接把文件扔进这个文件夹并在 `mapStore.ts` 的 `DEFAULT_MAPS` 数组里加一条记录即可。

### 9.2 未来部署：Linux 桌面级 App (Tauri)
本应用的最终宿命是打包成一个可以通过双击运行的独立 Linux 软件放在你的 MaxTang 车载主机上。
交给下一个 Agent 的部署任务清单：
1.  在项目中运行 `npx tauri init`。
2.  修改 `src-tauri/tauri.conf.json`，把 `build.beforeBuildCommand` 设置为 `npm run build`，把 `build.distDir` 设置为 `../dist`。
3.  如果有跨域问题，配置 tauri 的网络权限放行对 `http://localhost:9090` (rosbridge) 和各个大模型 API 的 Fetch 请求。
4.  运行 `npm run tauri build`，它将在 `src-tauri/target/release/bundle/deb/` 下生成一个完美封装的 `.deb` 安装包！

---
**🚀 致下一个 Agent**: 
你现在已经掌握了 SSTG 前端宇宙的全部拼图。请在这个极其强健、美观的骨架上，继续为人类创造令人惊叹的智能交互体验吧！
