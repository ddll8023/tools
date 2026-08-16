const { spawn, execSync } = require('child_process')
const os = require('os')
const path = require('path')
const http = require('http')

const APP_DATA_DIR_NAME = '工具盒子'

function getUnifiedDataDir() {
  const home = os.homedir()
  let base
  if (process.platform === 'win32') {
    base = process.env.APPDATA || path.join(home, 'AppData', 'Roaming')
  } else if (process.platform === 'darwin') {
    base = path.join(home, 'Library', 'Application Support')
  } else {
    base = process.env.XDG_CONFIG_HOME || path.join(home, '.config')
  }
  return path.resolve(path.join(base, APP_DATA_DIR_NAME))
}

const ROOT_DIR = path.resolve(__dirname, '..')
const FRONTEND_DIR = path.join(ROOT_DIR, 'frontend')
const BACKEND_DIR = path.join(ROOT_DIR, 'backend')
const VITE_PORT = 5173
const BACKEND_PORT = 4740
const TOOLBOX_DATA_DIR = process.env.TOOLBOX_DATA_DIR || getUnifiedDataDir()

function waitForBackendReady(maxWait = 60000) {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = () => {
      const postData = JSON.stringify({})
      const req = http.request(`http://127.0.0.1:${BACKEND_PORT}/api/v1/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        timeout: 3000
      }, (res) => {
        let body = ''
        res.on('data', (chunk) => body += chunk)
        res.on('end', () => {
          try {
            const json = JSON.parse(body)
            if (json.code === 0) return resolve()   // 确认后端真正就绪
          } catch {}
          if (Date.now() - start > maxWait) return reject(new Error('后端未返回正常状态'))
          setTimeout(check, 500)
        })
      })
      req.on('error', () => {
        if (Date.now() - start > maxWait) return reject(new Error('后端启动超时（30s）'))
        setTimeout(check, 500)
      })
      req.on('timeout', () => {
        req.destroy()
        if (Date.now() - start > maxWait) return reject(new Error('后端启动超时（30s）'))
        setTimeout(check, 500)
      })
      req.write(postData)
      req.end()
    }
    check()
  })
}

function waitForViteReady(maxWait = 30000) {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = () => {
      const req = http.get(`http://127.0.0.1:${VITE_PORT}`, { timeout: 2000 }, (res) => {
        res.resume()
        resolve()
      })
      req.on('error', () => {
        if (Date.now() - start > maxWait) return reject(new Error('Vite 启动超时'))
        setTimeout(check, 500)
      })
      req.on('timeout', () => {
        req.destroy()
        if (Date.now() - start > maxWait) return reject(new Error('Vite 启动超时'))
        setTimeout(check, 500)
      })
    }
    check()
  })
}

function startProcess(name, command, args, options) {
  const proc = spawn(command, args, { shell: true, stdio: ['pipe', 'pipe', 'pipe'], ...options })
  proc.stdout.on('data', (d) => process.stdout.write(`[${name}] ${d}`))
  proc.stderr.on('data', (d) => process.stderr.write(`[${name}] ${d}`))
  return proc
}

async function main() {
  let backendProc, viteProc, electronProc

  function forceKill(proc) {
    if (!proc || !proc.pid) return
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /F /T /PID ${proc.pid}`, { stdio: 'ignore' })
      } else {
        proc.kill('SIGKILL')
      }
    } catch {}
  }

  const cleanup = () => {
    if (electronProc) { electronProc.kill(); forceKill(electronProc) }
    if (viteProc) { viteProc.kill(); forceKill(viteProc) }
    if (backendProc) { backendProc.kill(); forceKill(backendProc) }
  }

  const shutdown = () => {
    cleanup()
    process.exit(0)
  }

  process.on('SIGINT', shutdown)
  process.on('SIGTERM', shutdown)
  if (process.stdin.isTTY) {
    process.stdin.on('close', shutdown)
  }

  // 进程意外退出时强制清理子进程（仅同步操作可用）
  process.on('exit', () => {
    const pids = [backendProc, viteProc, electronProc]
      .filter(p => p && p.pid)
      .map(p => p.pid)
    if (pids.length === 0) return
    if (process.platform === 'win32') {
      try {
        execSync(`taskkill /F /T /PID ${pids.join(' /PID ')}`, { stdio: 'ignore' })
      } catch {}
    }
  })

  // 1. 编译 Electron 主进程
  console.log('[dev-runner] 1/3 编译 Electron 主进程 ...')
  const tscProc = spawn('npx', ['tsc', '-p', 'electron/tsconfig.json'], {
    cwd: ROOT_DIR, shell: true, stdio: 'inherit'
  })
  await new Promise((resolve, reject) => {
    tscProc.on('close', (code) => {
      if (code !== 0) return reject(new Error('TypeScript 编译失败'))
      resolve()
    })
  })
  console.log('[dev-runner] ✓ TypeScript 编译完成')

  // 2. 启动后端（直接 spawn，不用 startProcess 以避免 shell: true 的管道问题）
  console.log('[dev-runner] 2/3 启动后端 FastAPI ...')
  const pythonBin = process.platform === 'win32'
    ? path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe')
    : path.join(BACKEND_DIR, '.venv', 'bin', 'python')
  backendProc = spawn(pythonBin, [
    '-m', 'uvicorn', 'app.main:app',
    '--host', '127.0.0.1', '--port', String(BACKEND_PORT),
  ], {
    cwd: BACKEND_DIR,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      TOOLBOX_DATA_DIR,
    }
  })
  backendProc.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`))
  backendProc.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`))
  backendProc.on('error', (err) => console.error(`[dev-runner] ❌ 后端进程错误:`, err.message))
  backendProc.on('exit', (code, signal) => {
    if (code !== null) console.log(`[dev-runner] ⚠ 后端进程退出, code: ${code}`)
  })

  await waitForBackendReady()
  console.log('[dev-runner] ✓ 后端已就绪 (http://127.0.0.1:4740)')

  // 3. 启动 Vite
  console.log('[dev-runner] 3/3 启动 Vite 开发服务器 ...')
  viteProc = startProcess('vite', 'npm', ['run', 'dev'], { cwd: FRONTEND_DIR })

  await waitForViteReady()
  console.log('[dev-runner] ✓ Vite 已就绪 (http://127.0.0.1:5173)')

  // 4. 启动 Electron
  console.log('[dev-runner] 启动 Electron ...')
  const electronPath = require('electron')
  electronProc = spawn(electronPath, ['.'], {
    cwd: ROOT_DIR,
    stdio: 'inherit',
    env: { ...process.env, BACKEND_MANAGED: '1' }
  })

  electronProc.on('close', (code) => {
    console.log('[dev-runner] Electron 退出, code:', code)
    cleanup()
    process.exit(code || 0)
  })
}

main().catch((err) => {
  console.error('[dev-runner] ❌ 启动失败:', err.message || err)
  process.exit(1)
})
