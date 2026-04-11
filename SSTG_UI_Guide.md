# SSTG UI 操作指南

本文档面向终端用户，介绍如何通过 Web UI 启动小车、操控导航、语音对话和查看地图。

> **技术栈**: React + TypeScript + Vite + Zustand + React Three Fiber (Three.js) + roslibjs + Tailwind CSS

---

## 1. 启动系统

### 1.1 一键启动（推荐）

UI 侧边栏左下角有一个 **电源按钮**（Power 图标），支持一键启动整个系统：

1. 打开浏览器访问 `http://<MaxTang的IP>:5173`（需先启动 UI，见 1.3）
2. 点击左下角 **电源按钮**（灰色 = 未启动）
3. 按钮变为黄色脉冲 = 后端正在启动，等待 10-15 秒
4. 左下角绿色圆点亮起 = ROS2 后端已连接
5. 系统自动完成以下操作：
   - 启动 SSTG 后端（rosbridge + 所有语义节点）
   - 推送 AI Engine 面板中已保存的 LLM 配置到后端
   - 自动启动导航模式（底盘 + 雷达 + IMU + EKF + SLAM定位 + 相机 + Nav2）
6. 电源按钮变为绿色 = 系统运行中
7. 再次 **短按** 电源按钮 = 优雅停止全部（4 步关闭链：ros2 service stop → SIGTERM → 15s 等待 → SIGKILL + 孤儿进程扫描）
8. **长按 2 秒** 电源按钮 = 强制清杀（SIGKILL 主进程 + pkill 清杀所有 ROS2 残留进程），适用于系统卡死的紧急情况

> 如需切换到探索模式，进入 /robot 页面手动切换。

### 1.2 手动启动（备用方案）

如果一键启动不可用，可通过终端手动启动：

#### 1.2.1 启动后端

在 MaxTang 小电脑上打开终端：

```bash
# source 环境
source /opt/ros/humble/setup.bash
source ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash
source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=28
export DASHSCOPE_API_KEY=<你的API Key>

# 一键启动 SSTG 后端 (rosbridge + 所有节点)
ros2 launch sstg_interaction_manager sstg_full.launch.py
```

> 注意：手动启动时需要通过环境变量设置 `DASHSCOPE_API_KEY`。使用一键启动则不需要，API Key 会从 UI 的 AI Engine 配置自动推送到后端。

### 1.3 启动 UI

另开一个终端：

```bash
cd ~/wbt_ws/sstg-nav/sstg_ui_app
npm run dev
```

### 1.4 打开浏览器

**本地访问（局域网）：**
```
http://<MaxTang的IP>:5173
```

**公网访问（远程协作）：**
```
https://iadc.sstgnav.cc.cd
```

公网访问通过 Cloudflare Tunnel 中转，自动 HTTPS，全球可用。

### 1.5 访问密钥

系统设有前端密钥门禁，首次访问需要输入共享密钥：

| 项目 | 值 |
|------|-----|
| 当前密钥 | `sstg2026` |
| 修改位置 | `sstg_ui_app/src/App.tsx` 第 13 行 `ACCESS_KEY` |

- 输入正确密钥后，浏览器会自动记住（存入 localStorage），下次访问无需重复输入
- 侧边栏底部有 **退出登录按钮**（LogOut 图标），点击后清除记忆，回到密钥输入页
- 不知道密钥的访客（包括爬虫）只能看到登录页面，无法进入系统

> 将密钥告知合作者即可共同使用。修改密钥后所有人需要重新输入。

- 左下角绿色圆点亮起 = ROS2 后端已连接
- 红色 = 未连接，检查 rosbridge 是否在运行
- 电源按钮绿色 = 后端运行中；灰色 = 未启动

---

## 2. 机器人控制中心 (/robot 页面)

点击左侧边栏的 **Activity 图标** (第三个) 进入机器人控制中心。

### 2.1 一键启动硬件

页面顶部有三个按钮：

| 按钮 | 功能 | 启动内容 |
|------|------|---------|
| **探索模式** | 自主建图探索 | 底盘 + 雷达 + IMU + EKF + SLAM + Nav2 + RRT |
| **导航模式** | 在已有地图上导航 | 底盘 + 雷达 + IMU + EKF + SLAM定位 + 相机 + Nav2 |
| **停止** | 关闭所有硬件节点 | 终止当前运行的 launch |

操作流程：
1. 确认硬件设备区域显示三个绿灯（底盘、雷达、相机已连接）
2. 点击 **导航模式** 或 **探索模式**
3. 等待 10-15 秒，系统分阶段启动硬件
4. 系统日志区域会实时显示启动过程
5. 切换模式时会自动停止旧模式，等待串口释放后启动新模式

### 2.2 监控面板

| 区域 | 显示内容 |
|------|---------|
| **硬件设备** | 底盘 CH340、雷达 RPLidar S2、相机 Gemini 336L 的连接状态 (绿灯/红灯) |
| **系统资源** | CPU 使用率、内存使用率、活跃 ROS2 节点数 |
| **节点列表** | 当前运行的所有 ROS2 节点名称 |
| **系统日志** | 实时滚动的 launch 输出日志，错误高亮红色，警告高亮黄色 |

---

## 3. 自然语言对话 (/ 首页)

点击左侧边栏的 **消息图标** (第一个) 进入对话页面。

### 3.1 三模式切换

输入框左侧有三个模式按钮，控制小拓的行为权限：

| 模式 | 图标 | 颜色 | 说明 |
|------|------|------|------|
| **聊天模式** | 💬 | 绿色 | 纯对话，不触发任何导航/探索动作。**无需 ROS 连接即可使用**（纯 HTTP 调 LLM） |
| **导航模式** | 🗺️ | 蓝色 | 全功能：对话 + 导航 + 找物体 + 场景描述 + 停止任务 |
| **探索模式** | 🧭 | 琥珀色 | 对话 + 自主探索 + 场景描述 + 停止任务（不可导航） |

所有模式下 **conversation 意图走流式回复**（逐字打字机效果，首字延迟 100-200ms）。
不允许的意图会被小拓**友好拒绝**，例如聊天模式下说"去客厅"→"我现在是纯聊天模式哦～要导航的话请切换到导航模式~"。

### 3.2 文字输入

在底部输入框输入中文指令，按 Enter 或点击发送按钮：

| 指令示例 | 功能 | 所需模式 |
|---------|------|---------|
| "去客厅" | 语义导航到客厅 | 导航 |
| "帮我探索这个新家" | 启动 RRT 自主探索建图 | 探索 |
| "帮我找书包" | 多节点搜索 + VLM 视觉确认 | 导航 |
| "去有红色沙发的地方" | 基于物体描述的导航 | 导航 |
| "看看前面有什么" | 拍照 + VLM 描述当前场景 | 导航/探索 |
| "停下" / "算了" / "别走了" | 取消当前任务（前端关键词秒取消） | 导航/探索 |
| "你好" / "你叫什么" | 纯对话闲聊 | 任意 |

发送后：
- 气泡正文 = 小拓的自然语言回复（流式逐字输出，带蓝色闪烁光标）
- 气泡下方 = 思考过程轨迹（类似 Claude 的 tool call 折叠行）
  - 🔄 进行中状态带 spinner
  - ✅ 已完成步骤灰色
  - ❌ 失败步骤红色
- 纯对话（conversation 意图）只有正文，无轨迹

### 3.3 语音输入

输入框右侧有一个 **麦克风按钮**：

1. **点击** 麦克风按钮（按钮变红 + 脉冲动画，进入录音状态）
2. 对着麦克风说话，支持连续长句（`continuous = true`）
3. **再次点击** 按钮停止录音，识别的文字自动填入输入框
4. 确认无误后按 Enter 发送

要求：Chrome 或 Edge 浏览器 + 联网环境。不支持的浏览器麦克风按钮不会显示。

### 3.4 取消任务

**方式一（推荐）：自然语言取消**

直接在对话框输入 "停下" / "取消" / "别走了" / "算了" 等关键词，前端秒级响应取消当前任务 + 清空消息队列。

**方式二：终端命令**

```bash
ros2 service call /cancel_task std_srvs/srv/Trigger
```

### 3.5 多人消息队列

多人同时使用时，消息不会报错而是有序排队：

- 后端忙碌时新消息自动入队（FIFO，上限 5 条）
- 输入框上方显示 **琥珀色队列栏**，展示排位序号 + 消息内容 + 取消按钮
- 前一条任务完成后自动处理下一条（匹配 task_id 弹入聊天区）
- 点击 × 可取消单条排队消息

### 3.6 会话管理

- 左侧面板显示历史会话列表
- 点击 **新建导航对话** 创建新会话
- 悬停会话可以重命名或删除
- **所有聊天记录存储在服务端** `~/sstg-data/chat/`（不再依赖浏览器 localStorage）
- 多浏览器 **实时同步** — 任何人发的消息其他人都能看到（SSE 广播）
- 每条消息标注 **发送者昵称 + 彩色首字头像**（djb2 哈希 → 16 色）
- 输入框右侧显示当前用户身份（彩色头像 + 用户名）

---

## 4. AI 引擎配置

点击对话页面顶部的 **AI ENGINE** 按钮，打开大模型配置面板。

### 4.1 选择供应商

支持的 LLM 供应商（内置 + 可自定义增删）：

| 供应商 | 用途 | 是否需要联网 |
|--------|------|-------------|
| DashScope (阿里云) | 默认，qwen-max | 是 |
| DeepSeek (深度求索) | deepseek-chat | 是 |
| ZhipuAI (智谱清言) | glm-4 | 是 |
| Ollama (本地) | llama3/qwen | 否 (本地部署) |
| OpenAI | gpt-4o | 是 |
| 自定义... | 供应商下拉框旁 `+` 按钮添加 | — |

可通过 🗑 按钮删除自定义供应商（至少保留 1 个）。

### 4.2 配置步骤

1. 选择供应商
2. 填入 Base URL（通常自动填好）
3. 填入 API Key
4. 确认模型名称
5. 点击 **保存并启用该配置**

保存后，配置会自动推送到后端 NLP 节点，无需重启后端。切换供应商后立即生效。
保存结果会显示 **三色同步状态**：绿色"已同步到后端" / 黄色"仅保存本地" / 红色"同步失败"。

> LLM 配置存储在服务端 `~/sstg-data/chat/llm-config.json`，所有浏览器共享，SSE 实时同步。换设备/浏览器无需重新输入 API Key。

> 使用一键启动时，每次后端连接成功会自动推送上次保存的配置，无需手动操作。

### 4.3 诊断测试

点击 **基于当前填写诊断** 按钮（采用流式检测 TTFT 首字延迟）：
- 绿色 "连接畅通" + 首字延迟 / 总耗时 = 正常
- 橙色 "连接延迟告警" = 可用但较慢 (首字 >5s)
- 红色 "连接失败" = API Key 错误或网络不通

注意：诊断测试通过 Vite 代理转发，不会有 CORS 问题。

---

## 5. 2.5D 全息地图与导航 (/map 页面)

点击左侧边栏的 **地图图标** (第二个) 进入 2.5D 全息地图。

> **技术栈**: React Three Fiber (`@react-three/fiber` v9.5.0) + Three.js (`three` v0.183.2) + `@react-three/drei`（OrbitControls、Line、Html 等高阶组件）

### 5.1 2.5D 地图原理

地图使用 Three.js 的 **Displacement Map（位移贴图）** 技术实现 2.5D 效果：

```
PGM 地图文件 → Canvas 解析
    ├─ 颜色纹理（colorTex）→ 墙壁=青色，空闲=暗色，未知=透明
    └─ 位移纹理（dispTex） → 占据区域顶点向上偏移（墙壁"凸起来"）
                              空闲区域保持平面
```

本质是一个 **带高度的 Mesh 平面**（meshStandardMaterial + roughness/metalness），不是真正的 3D 模型。

### 5.2 场景结构

| 层 | 说明 |
|----|------|
| 灯光 | AmbientLight + DirectionalLight + 2× PointLight |
| 地面网格 | GridHelper 空间参考 |
| 地图几何体 | 带 Displacement Map 的 2.5D 平面 |
| 实时占据栅格 | 订阅 `/map` topic (OccupancyGrid) 的半透明叠加层 |
| 拓扑节点 | 蓝色八面体 (OctahedronGeometry) + 青色连线 + HTML 标签 |
| 机器人标记 | 绿色锥体 (ConeGeometry)，按 yaw 角实时旋转 |
| 交互控制 | OrbitControls（拖拽旋转 + 滚轮缩放 + 右键平移） |

### 5.3 地图查看

- 鼠标左键拖拽旋转视角
- 滚轮缩放
- 右键拖拽平移
- 蓝色八面体 = 拓扑节点
- 绿色锥形箭头 = 机器人当前位置和朝向（实时更新）
- 青色线条 = 节点间连接

### 5.4 实时地图

当硬件启动后（探索模式或导航模式），`/map` topic 会发布 OccupancyGrid 数据：
- 半透明青色区域 = 已探索的障碍物
- 暗色区域 = 已探索的空闲空间
- 透明区域 = 未探索

地图每 2 秒自动刷新一次。

### 5.5 查看节点详情

点击任意蓝色八面体节点：
- 右侧面板显示节点 ID、房间类型（中文）
- 四方向全景图缩略图（点击可放大浏览）
- 语义标签和置信度

### 5.6 从地图发起导航

1. 点击目标节点
2. 右侧面板底部出现 **导航前往** 按钮
3. 点击按钮，系统自动发送 "去{房间名}" 指令
4. 切换到对话页面可以看到任务状态实时更新

### 5.7 地图校准

左下角齿轮按钮打开校准面板：
- 翻转地图/节点的 X/Y 轴
- 调整节点层偏移量
- 切换地图层和节点层的显示/隐藏
- 修改拓扑 JSON 文件路径

右上角相机按钮可以保存当前视角，下次打开自动恢复。

### 5.8 切换地图

左上角下拉菜单可以切换不同地图：
- 支持导入新地图（需要 PGM + YAML 文件）
- 支持重命名和删除地图

---

## 6. 典型操作流程

### 场景 A：首次探索新环境

```
方式一：一键启动
1. 打开 UI → 点击左下角电源按钮
2. 等待系统自动启动（后端 + 导航模式硬件）
3. 进入 /robot 页面 → 切换为 "探索模式"
4. 切换到 / 对话页面
5. 输入 "帮我探索这个新家"
6. 右侧面板观察探索进度 (前沿点数量、进度百分比)
7. 探索完成后切换到 /map 查看建好的地图

方式二：手动启动
1. 终端启动后端 (见 1.2.1)
2. 打开 UI → /robot 页面
3. 确认三个硬件绿灯亮起
4. 点击 "探索模式" → 等待硬件启动
5. 切换到 / 对话页面
6. 输入 "帮我探索这个新家"
7. 探索完成后切换到 /map 查看建好的地图
```

### 场景 B：语义导航到指定房间

```
1. 确认系统已启动（电源按钮绿色，或手动启动导航模式）
2. 切换到 / 对话页面
3. 输入 "去客厅" 或按住麦克风说 "去客厅"
4. 观察右侧面板: 理解中 → 规划中 → 导航中 → 完成
5. 切换到 /map 页面可以看到机器人箭头在移动
```

### 场景 C：找物体

```
1. 确认已在导航模式
2. 对话页面输入 "帮我找书包"
3. 系统自动: 检索候选节点 → 依次导航 → 拍照 → VLM 确认
4. 右侧面板显示搜索进度:
   "前往走廊查找..." → "拍照检查中..." → "未找到，前往下一个..." → "找到了！"
```

### 场景 D：从地图直接导航

```
1. 打开 /map 页面
2. 点击目标节点（蓝色八面体）
3. 右侧面板查看节点信息和全景图
4. 点击 "导航前往" 按钮
5. 机器人开始移动，绿色箭头实时更新位置
```

---

## 7. 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| 左下角红灯 | rosbridge 未运行 | 点击电源按钮启动，或手动启动后端 |
| 电源按钮点击无反应 | Vite dev server 未运行 | 先在终端执行 `npm run dev` |
| 电源按钮黄色闪烁超过 30 秒 | 后端启动失败 | 检查终端 Vite 日志中 `[backend]` 输出 |
| 点击模式按钮无反应 | ROS2 未连接 | 刷新页面，检查 rosbridge |
| 硬件设备红灯 | USB 设备未连接 | 检查 USB 线缆，重新插拔 |
| 语音按钮不显示 | 浏览器不支持 | 换用 Chrome 或 Edge |
| LLM 诊断失败 | API Key 错误或网络不通 | 检查 Key 和网络连接 |
| 切换 LLM 供应商后无效果 | 配置未推送到后端 | 确认已点击 "保存并启用该配置"，查看三色状态反馈 |
| 地图不更新 | 硬件未启动 | 先在 /robot 页面启动探索或导航模式 |
| 导航前往无反应 | 后端 SSTG 节点未就绪 | 等待 launch 完全启动 (约 15 秒) |
| CPU 占用异常高 (50%+) | 多次开关后 Nav2 孤儿进程叠加 | 长按电源按钮 2s 强制清杀，或终端执行 `pkill -9 -f "nav2\|amcl\|planner\|controller_server"` |
| 多人同时发消息报错 | 后端忙碌 | 消息会自动排队（最多 5 条），无需重发 |

---

## 8. 浏览器要求

| 浏览器 | 支持程度 |
|--------|---------|
| Chrome 90+ | 完全支持 (推荐) |
| Edge 90+ | 完全支持 |
| Firefox 90+ | 基本支持，语音输入不可用 |
| Safari | 3D 地图可能有兼容性问题 |

建议使用 Chrome，以获得语音输入和最佳 3D 渲染性能。

---

## 9. 公网部署（Cloudflare Tunnel）

系统通过 Cloudflare Tunnel 将本地 UI 暴露到公网，供远程合作者访问。

### 9.1 架构

```
合作者浏览器 → https://iadc.sstgnav.cc.cd
                 ↓ (Cloudflare CDN/Tunnel)
              cloudflared (MaxTang 本地)
                 ↓
              Vite Dev Server (localhost:5173)
                 ↓ /rosbridge 代理
              rosbridge (localhost:9090)
```

### 9.2 当前配置

| 项目 | 值 |
|------|-----|
| 域名 | `iadc.sstgnav.cc.cd` |
| Tunnel 名称 | `sstg-nav` |
| Tunnel ID | `c65e6fbe-86c8-49aa-87cc-2b698c5c388e` |
| 配置文件 | `~/.cloudflared/config.yml` |
| cloudflared 路径 | `~/bin/cloudflared` |

### 9.3 启动/停止 Tunnel

```bash
# 通过 systemd 管理（推荐，已配置开机自启）
systemctl --user status sstg-tunnel    # 查看状态
systemctl --user restart sstg-tunnel   # 重启
systemctl --user stop sstg-tunnel      # 停止

# 手动方式（备用）
~/bin/cloudflared tunnel info sstg-nav
```

### 9.4 安全机制

- **前端密钥门禁**：访问者必须输入正确密钥才能进入（见 1.5 节）
- **Cloudflare 层**：自动 HTTPS、DDoS 防护、Bot 管理
- **WebSocket 代理**：rosbridge 不直接暴露，通过 `/rosbridge` 路径走 Vite 反向代理

### 9.5 开机自启

系统配置了两个服务开机自启，MaxTang 通电后无需登录即可自动恢复：

| 服务 | 管理方式 | 说明 |
|------|---------|------|
| Vite UI (port 5173) | PM2 | `pm2 list` 查看，`pm2 restart sstg-ui` 重启 |
| Cloudflare Tunnel | systemd 用户服务 | `systemctl --user status sstg-tunnel` 查看 |

两者均配置了崩溃自动重启。

常用运维命令：
```bash
# 查看两个服务状态
pm2 list
systemctl --user status sstg-tunnel

# Vite 日志
pm2 logs sstg-ui

# Tunnel 日志
journalctl --user -u sstg-tunnel -f

# 全部重启
pm2 restart sstg-ui
systemctl --user restart sstg-tunnel
```

### 9.6 注意事项

- Tunnel 需要 MaxTang 上的 Vite dev server 保持运行
- 公网访问时 WebSocket 自动切换为 `wss://iadc.sstgnav.cc.cd/rosbridge`
- 如需更换域名，修改 `~/.cloudflared/config.yml` 中的 hostname 并重启 tunnel

---

文档版本: 2026-04-11 v2.0 | 适用于 SSTG 2.8 (Phase 13)

---

## 10. 数据存储位置

| 数据 | 存储位置 | 说明 |
|------|---------|------|
| 聊天会话列表 | `~/sstg-data/chat/index.json` | 会话 ID + activeSessionId |
| 聊天消息 | `~/sstg-data/chat/messages/session-*.json` | 每个会话独立文件 |
| LLM 配置 | `~/sstg-data/chat/llm-config.json` | 所有浏览器共享 |
| 后端对话历史 | `~/.sstg_nav/chat_sessions/{session_id}.json` | NLP 节点多轮记忆（标准 messages 格式，4000 token 预算动态截断） |
| 访问密钥记忆 | 浏览器 localStorage | 每浏览器独立 |
| 用户昵称 | 浏览器 localStorage | 每浏览器独立 |

---

## 11. 意图系统总览

小拓（SSTG 机器人助手）支持 6 种意图：

| 意图 | 触发示例 | 处理方式 |
|------|---------|---------|
| `conversation` | "你好" / "这里有什么" | **流式 HTTP SSE**（Vite 直连 LLM，逐 token 推送） |
| `navigate_to` | "去客厅" / "去有沙发的地方" | ROS Service `/start_task` |
| `locate_object` | "帮我找书包" | ROS（精确匹配 → 全局搜索所有节点逐个拍照） |
| `explore_new_home` | "探索这个新家" | ROS（启动 RRT 前沿探索） |
| `describe_scene` | "看看前面有什么" / "拍张照" | ROS（拍照 + VLM 分析） |
| `stop_task` | "停下" / "取消" / "别走了" | 前端关键词秒取消 + 后端 VLM 兜底 |

VLM 分类参数：`temperature=0.3`，优先级：stop_task > describe_scene > navigate_to > locate_object > explore_new_home > conversation

---

## 12. 关键 ROS 接口

```
UI (roslibjs via rosbridge ws://localhost:9090)
│
├── 已有:
│   ├── CALLS: /start_task, /cancel_task
│   └── SUBSCRIBES: /task_status, /navigation_feedback
│
├── Phase 1 新增:
│   ├── CALLS: /system/launch_mode, /system/get_status
│   └── SUBSCRIBES: /system/status, /system/log
│
├── Phase 3 新增:
│   └── SUBSCRIBES: /map (nav_msgs/OccupancyGrid)
│
├── Phase 4 新增:
│   └── CALLS: /nlp/update_llm_config
│
└── Phase 6 新增:
    └── CALLS: /nlp/delete_session
```

---

## 13. 服务端 REST API (Vite chatSyncPlugin)

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/chat/sessions` | 获取会话列表 + 当前活跃 ID |
| `POST` | `/api/chat/sessions` | 创建新会话 |
| `PUT` | `/api/chat/sessions/:id` | 重命名会话 |
| `DELETE` | `/api/chat/sessions/:id` | 删除会话 |
| `PUT` | `/api/chat/sessions/active` | 切换活跃会话 |
| `GET` | `/api/chat/sessions/:id/messages` | 获取会话消息 |
| `POST` | `/api/chat/sessions/:id/messages` | 添加消息 |
| `PUT` | `/api/chat/messages/:id` | 更新消息（robot 步骤累积合并） |
| `POST` | `/api/chat/stream` | 流式对话（SSE 逐 token 推送） |
| `GET` | `/api/llm-config` | 获取 LLM 配置 |
| `PUT` | `/api/llm-config` | 更新 LLM 配置（持久化 + SSE 广播） |
| `GET` | `/api/chat/events` | SSE 实时事件流 |
| `POST` | `/api/system/start-backend` | 一键启动后端 |
| `POST` | `/api/system/stop-backend` | 优雅停止后端 |
| `GET` | `/api/system/backend-status` | 后端进程状态 |
| `POST` | `/api/system/force-cleanup` | 强制清杀所有 ROS2 残留进程 |
