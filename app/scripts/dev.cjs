#!/usr/bin/env node
/* 同时启动 FastAPI 后端(8100) 与 Vite 前端，CLI 参数原样转发给 vite。
 * Kimi Work 打开预览卡片时会以 `npm run dev -- --host ... --port ...` 调用，
 * 这些参数最终落到 vite 上。
 *
 * 健壮性：
 * - 显式解析可用的 python（须能 import 后端依赖；跳过 Microsoft Store 占位符）；
 * - 后端输出落盘 server/api_last_run.log 便于诊断；
 * - 后端失败只警告并自动重启一次，绝不拖垮前端。 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const appDir = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const isWin = process.platform === 'win32';

// ---------- 解析 python ----------
const PY_PROBE = 'import fastapi,uvicorn,pymysql,openpyxl';

function pythonWorks(c) {
  try {
    const real = fs.realpathSync(c);
    if (real.includes('WindowsApps')) return false;   // 商店占位符
  } catch { /* 裸名字继续探测 */ }
  try {
    execSync(`"${c}" -c "${PY_PROBE}"`, { stdio: 'pipe', timeout: 15000, shell: isWin ? true : undefined });
    return true;
  } catch {
    return false;
  }
}

function resolvePython() {
  const candidates = [];
  if (process.env.PYTHON) candidates.push(process.env.PYTHON);
  candidates.push('python', 'python3');
  // Kimi Work 托管运行时兜底（PATH 不全时仍可用）
  candidates.push('E:\\KimiData\\daimon-share\\daimon\\runtime\\python\\python.exe');
  return candidates.find(pythonWorks) || null;
}

// ---------- 启动后端 ----------
const API_LOG = path.join(__dirname, '..', 'server', 'api_last_run.log');
let api = null;
let apiRetries = 0;
function startApi() {
  const py = resolvePython();
  if (!py) {
    fs.writeFileSync(API_LOG, '[dev] 未找到同时满足 fastapi/uvicorn/pymysql/openpyxl 的 python，后端未启动\n');
    console.error('[dev] 未找到可用 python（缺依赖），后端未启动，详见 server/api_last_run.log');
    return;
  }
  console.error(`[dev] 后端解释器: ${py}`);
  const logFd = fs.openSync(API_LOG, 'w');
  api = spawn(py, [path.join('server', 'api.py')], { stdio: ['ignore', logFd, logFd], cwd: appDir, shell: isWin });
  api.on('error', (e) => console.error('[dev] API 启动失败:', e.message));
  api.on('exit', (code) => {
    console.error(`[dev] API 服务退出(code=${code})，详见 server/api_last_run.log`);
    if (apiRetries < 3) {
      apiRetries += 1;
      console.error(`[dev] 3 秒后自动重启 API（第 ${apiRetries} 次）…`);
      setTimeout(startApi, 3000);
    }
  });
}

// ---------- 启动前端 ----------
startApi();
const vite = spawn('npx', ['vite', ...args], { stdio: 'inherit', cwd: appDir, shell: isWin });
vite.on('error', (e) => console.error('[dev] vite 启动失败:', e.message));

function shutdown(code) {
  try {
    if (api) {
      if (isWin) spawn('taskkill', ['/F', '/T', '/PID', String(api.pid)], { stdio: 'ignore' });
      else api.kill();
    }
    if (isWin) spawn('taskkill', ['/F', '/T', '/PID', String(vite.pid)], { stdio: 'ignore' });
    else vite.kill();
  } catch { /* ignore */ }
  process.exit(code ?? 0);
}
process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));
vite.on('exit', (code) => shutdown(code));
