const { spawn } = require('child_process')
const path = require('path')
const http = require('http')

const ROOT_DIR = path.resolve(__dirname, '..')
const FRONTEND_DIR = path.join(ROOT_DIR, 'frontend')
const BACKEND_DIR = path.join(ROOT_DIR, 'backend')
const VITE_PORT = 5173
const BACKEND_PORT = 4740

function waitForBackendReady(maxWait = 30000) {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = () => {
      const postData = JSON.stringify({})
      const req = http.request(`http://127.0.0.1:${BACKEND_PORT}/api/v1/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        timeout: 2000
      }, (res) => {
        let body = ''
        res.on('data', (chunk) => body += chunk)
        res.on('end', () => resolve())
      })
      req.on('error', () => {
        if (Date.now() - start > maxWait) return reject(new Error('后端启动超时'))
        setTimeout(check, 500)
      })
      req.on('timeout', () => {
        req.destroy()
        if (Date.now() - start > maxWait) return reject(new Error('后端启动超时'))
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

  const cleanup = () => {
    if (electronProc) electronProc.kill()
    if (viteProc) viteProc.kill()
    if (backendProc) backendProc.kill()
  }

  process.on('SIGINT', () => {
    cleanup()
    process.exit(0)
  })

  // 1. 启动后端
  console.log('[dev-runner] 启动后端 FastAPI ...')
  backendProc = startProcess('backend', 'uv', [
    'run', 'uvicorn', 'app.main:app',
    '--host', '127.0.0.1', '--port', String(BACKEND_PORT), '--reload'
  ], { cwd: BACKEND_DIR })

  await waitForBackendReady()
  console.log('[dev-runner] 后端已就绪')

  // 2. 启动 Vite
  console.log('[dev-runner] 启动 Vite 开发服务器 ...')
  viteProc = startProcess('vite', 'npm', ['run', 'dev'], { cwd: FRONTEND_DIR })

  await waitForViteReady()
  console.log('[dev-runner] Vite 已就绪')

  // 3. 启动 Electron
  console.log('[dev-runner] 启动 Electron ...')
  const electronPath = require('electron')
  electronProc = spawn(electronPath, ['.'], {
    cwd: __dirname,
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
  console.error('[dev-runner] 启动失败:', err)
  process.exit(1)
})
