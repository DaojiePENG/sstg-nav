import { defineConfig, Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import http from 'http'
import https from 'https'
import { spawn, execSync, ChildProcess } from 'child_process'
import chatSyncPlugin from './vite-plugins/chatSyncPlugin'

/**
 * LLM Proxy Plugin - 解决浏览器直调 LLM API 时的 CORS 问题
 *
 * 前端请求 /api/llm-proxy/chat/completions
 * header 中带 X-Target-Url (真实 API base URL) 和 Authorization
 * 插件将请求转发到真实 API，返回结果
 */
function llmProxyPlugin(): Plugin {
  return {
    name: 'llm-proxy',
    configureServer(server) {
      server.middlewares.use('/api/llm-proxy', (req, res) => {
        const targetUrl = req.headers['x-target-url'] as string;
        if (!targetUrl) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Missing X-Target-Url header' }));
          return;
        }

        // 拼接完整 URL
        const subPath = req.url || '';
        const fullUrl = targetUrl.replace(/\/$/, '') + subPath;

        // 收集请求 body
        const chunks: Buffer[] = [];
        req.on('data', (chunk: Buffer) => chunks.push(chunk));
        req.on('end', () => {
          const body = Buffer.concat(chunks);

          let parsedUrl: URL;
          try {
            parsedUrl = new URL(fullUrl);
          } catch {
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: `Invalid URL: ${fullUrl}` }));
            return;
          }

          const isHttps = parsedUrl.protocol === 'https:';
          const lib = isHttps ? https : http;

          const options: http.RequestOptions = {
            hostname: parsedUrl.hostname,
            port: parsedUrl.port || (isHttps ? 443 : 80),
            path: parsedUrl.pathname + parsedUrl.search,
            method: req.method || 'POST',
            headers: {
              'Content-Type': req.headers['content-type'] || 'application/json',
              'Authorization': req.headers['authorization'] || '',
              'Content-Length': body.length,
            },
            timeout: 60000,
          };

          const proxyReq = lib.request(options, (proxyRes) => {
            // 回传状态码和 headers
            res.writeHead(proxyRes.statusCode || 500, {
              'Content-Type': proxyRes.headers['content-type'] || 'application/json',
              'Access-Control-Allow-Origin': '*',
            });
            proxyRes.pipe(res);
          });

          proxyReq.on('error', (err) => {
            res.writeHead(502, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: `Proxy error: ${err.message}` }));
          });

          proxyReq.on('timeout', () => {
            proxyReq.destroy();
            res.writeHead(504, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Proxy timeout (60s)' }));
          });

          proxyReq.write(body);
          proxyReq.end();
        });
      });
    },
  };
}

/**
 * Backend Launcher Plugin - 通过 HTTP 端点管理 SSTG ROS2 后端进程
 *
 * 三层防护机制：
 *   1. 关闭链修正：stop 时先让 system_manager 关闭 Nav2，再杀主进程组，超时 20s
 *   2. 启动前清理：start 时自动 pkill 残留 ROS2 节点
 *   3. 一键清杀端点：/api/system/force-cleanup 应急清理所有 ROS2 进程
 */
function backendLauncherPlugin(): Plugin {
  let backendProcess: ChildProcess | null = null;

  const ROS_ENV = [
    'source /opt/ros/humble/setup.bash',
    'source ~/wbt_ws/sstg-nav/yahboomcar_ws/install/setup.bash',
    'source ~/wbt_ws/sstg-nav/sstg_nav_ws/install/setup.bash',
    'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp',
    'export ROS_DOMAIN_ID=28',
  ].join(' && ');

  const LAUNCH_CMD = ROS_ENV + ' && ros2 launch sstg_interaction_manager sstg_full.launch.py';

  // 已知的 ROS2 节点进程关键字（用于清理残留）
  const ROS2_PROCESS_PATTERNS = [
    'controller_server', 'planner_server', 'bt_navigator', 'behavior_server',
    'nav2_amcl/amcl', 'map_server', 'lifecycle_manager', 'ekf_node',
    'Mcnamu_driver', 'sllidar_node', 'joint_state_publisher', 'robot_state_publisher',
    'rosbridge_websocket', 'interaction_manager_node', 'nlp_node', 'perception_node',
    'planning_node', 'executor_node', 'map_manager_node', 'system_manager_node',
    'exploration_action_server',
  ];

  function isRunning(): boolean {
    if (!backendProcess || backendProcess.exitCode !== null) {
      backendProcess = null;
      return false;
    }
    return true;
  }

  /** 第二层：清杀所有残留 ROS2 进程 */
  function killOrphanedProcesses(): number {
    let killed = 0;
    for (const pat of ROS2_PROCESS_PATTERNS) {
      try {
        execSync(`pkill -9 -f "${pat}" 2>/dev/null`, { timeout: 3000 });
        killed++;
      } catch {
        // pkill returns non-zero if no processes matched — safe to ignore
      }
    }
    return killed;
  }

  /** 第一层：优雅关闭链 —— 先让 system_manager 关 Nav2，再杀主进程组 */
  function stopBackend(): Promise<{ stopped: boolean; detail: string }> {
    return new Promise(async (resolve) => {
      if (!isRunning() || !backendProcess) {
        resolve({ stopped: true, detail: 'No active process' });
        return;
      }

      const pid = backendProcess.pid!;

      // Step 1: 通过 ROS2 CLI 让 system_manager 先关闭 Nav2 子进程
      console.log('[backend] Step 1: Requesting system_manager to stop Nav2...');
      try {
        execSync(
          `bash -c '${ROS_ENV} && ros2 service call /system/launch_mode sstg_msgs/srv/LaunchMode "{mode: stop}" --timeout 5'`,
          { timeout: 12000, stdio: 'pipe' },
        );
        console.log('[backend] Step 1 done: system_manager stopped Nav2');
      } catch {
        console.log('[backend] Step 1 skipped: system_manager unreachable (will force-kill)');
      }

      // Step 2: SIGTERM 到主进程组
      console.log('[backend] Step 2: SIGTERM to process group...');
      try { process.kill(-pid, 'SIGTERM'); } catch {}

      // Step 3: 等待最多 15s
      const forceKillTimer = setTimeout(() => {
        console.log('[backend] Step 3: SIGTERM timeout (15s), sending SIGKILL...');
        try { process.kill(-pid, 'SIGKILL'); } catch {}
        // Step 4: 兜底扫描残留
        setTimeout(() => {
          const orphans = killOrphanedProcesses();
          console.log(`[backend] Step 4: Orphan cleanup killed ${orphans} patterns`);
          backendProcess = null;
          resolve({ stopped: true, detail: `Force-killed after timeout, cleaned ${orphans} orphans` });
        }, 2000);
      }, 15000);

      // 正常退出时取消强杀定时器
      backendProcess.on('exit', (code) => {
        clearTimeout(forceKillTimer);
        console.log(`[backend] Process exited with code ${code}`);
        // 仍然扫描一次残留（以防子进程逃逸）
        const orphans = killOrphanedProcesses();
        if (orphans > 0) console.log(`[backend] Post-exit orphan cleanup: ${orphans} patterns`);
        backendProcess = null;
        resolve({ stopped: true, detail: `Exited gracefully (code=${code}), cleaned ${orphans} orphans` });
      });
    });
  }

  return {
    name: 'backend-launcher',
    configureServer(server) {
      server.middlewares.use('/api/system', async (req, res) => {
        const url = req.url || '';
        res.setHeader('Content-Type', 'application/json');

        if (url.startsWith('/start-backend') && req.method === 'POST') {
          if (isRunning()) {
            res.writeHead(409);
            res.end(JSON.stringify({ error: 'Backend already running', pid: backendProcess!.pid }));
            return;
          }

          // 第二层：启动前清理残留进程
          console.log('[backend] Pre-start: cleaning orphaned processes...');
          const orphans = killOrphanedProcesses();
          if (orphans > 0) {
            console.log(`[backend] Pre-start: cleaned ${orphans} orphan patterns, waiting 2s...`);
            await new Promise(r => setTimeout(r, 2000));  // 等待端口/串口释放
          }

          backendProcess = spawn('bash', ['-c', LAUNCH_CMD], {
            detached: true,
            stdio: ['ignore', 'pipe', 'pipe'],
          });
          backendProcess.stdout?.on('data', (d: Buffer) => process.stdout.write(`[backend] ${d}`));
          backendProcess.stderr?.on('data', (d: Buffer) => process.stderr.write(`[backend] ${d}`));
          backendProcess.on('exit', (code) => {
            console.log(`[backend] exited with code ${code}`);
            backendProcess = null;
          });
          res.writeHead(200);
          res.end(JSON.stringify({ success: true, pid: backendProcess.pid, orphansCleaned: orphans }));

        } else if (url.startsWith('/stop-backend') && req.method === 'POST') {
          const result = await stopBackend();
          res.writeHead(200);
          res.end(JSON.stringify({ success: true, ...result }));

        } else if (url.startsWith('/force-cleanup') && req.method === 'POST') {
          // 第三层：一键清杀所有 ROS2 进程
          console.log('[backend] Force cleanup requested!');
          if (isRunning() && backendProcess) {
            try { process.kill(-backendProcess.pid!, 'SIGKILL'); } catch {}
            backendProcess = null;
          }
          const cleaned = killOrphanedProcesses();
          console.log(`[backend] Force cleanup done: ${cleaned} patterns killed`);
          res.writeHead(200);
          res.end(JSON.stringify({ success: true, patternsKilled: cleaned }));

        } else if (url.startsWith('/backend-status')) {
          res.writeHead(200);
          res.end(JSON.stringify({ running: isRunning(), pid: backendProcess?.pid ?? null }));

        } else {
          res.writeHead(404);
          res.end(JSON.stringify({ error: 'Not found' }));
        }
      });

      // Vite 关闭时清理后端进程
      server.httpServer?.on('close', () => { stopBackend(); });
    },
  };
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), llmProxyPlugin(), backendLauncherPlugin(), chatSyncPlugin()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,  // 允许 Tailscale Funnel 等外部域名访问
    proxy: {
      // rosbridge WebSocket 代理 — 公网访问时走同一端口
      '/rosbridge': {
        target: 'ws://localhost:9090',
        ws: true,
        rewriteWsOrigin: true,
        rewrite: (path) => path.replace(/^\/rosbridge/, ''),
      },
    },
  },
})
