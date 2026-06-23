import { app, BrowserWindow } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import * as path from 'path'
import * as http from 'http'

const isDev = !app.isPackaged
const VITE_PORT = 5173
const VITE_URL = `http://127.0.0.1:${VITE_PORT}`
const BACKEND_PORT = 4740
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`
const ROOT_DIR = path.resolve(__dirname, '..')
const FRONTEND_DIR = path.join(ROOT_DIR, 'frontend')
const BACKEND_DIR = path.join(ROOT_DIR, 'backend')

let viteProcess: ChildProcess | null = null
let backendProcess: ChildProcess | null = null
let mainWindow: BrowserWindow | null = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    title: '工具盒子',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  if (isDev) {
    mainWindow.loadURL(VITE_URL)
    if (!process.env.BACKEND_MANAGED) {
      mainWindow.webContents.openDevTools()
    }
  } else {
    mainWindow.loadFile(path.join(ROOT_DIR, 'frontend', 'dist', 'index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function waitForBackendReady(): Promise<void> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + 30000
    const check = () => {
      const postData = JSON.stringify({})
      const req = http.request(`${BACKEND_URL}/api/v1/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        timeout: 2000
      }, (res) => {
        let body = ''
        res.on('data', (chunk) => body += chunk)
        res.on('end', () => resolve())
      })
      req.on('error', () => {
        if (Date.now() > deadline) { reject(new Error('后端启动超时')); return }
        setTimeout(check, 500)
      })
      req.on('timeout', () => {
        req.destroy()
        if (Date.now() > deadline) { reject(new Error('后端启动超时')); return }
        setTimeout(check, 500)
      })
      req.write(postData)
      req.end()
    }
    check()
  })
}

function startBackend(): Promise<void> {
  return new Promise((resolve, reject) => {
    backendProcess = spawn('uv', [
      'run', 'uvicorn', 'app.main:app',
      '--host', '127.0.0.1', '--port', String(BACKEND_PORT)
    ], {
      cwd: BACKEND_DIR,
      shell: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' }
    })

    backendProcess.stdout?.on('data', (data: Buffer) => {
      process.stdout.write(`[backend] ${data}`)
    })
    backendProcess.stderr?.on('data', (data: Buffer) => {
      process.stderr.write(`[backend] ${data}`)
    })

    backendProcess.on('error', reject)

    waitForBackendReady().then(resolve).catch(reject)
  })
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
}

function waitForViteReady(): Promise<void> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + 30000
    const check = () => {
      const req = http.get(VITE_URL, { timeout: 2000 }, (res) => {
        res.resume()
        resolve()
      })
      req.on('error', () => {
        if (Date.now() > deadline) {
          reject(new Error('Vite 启动超时'))
        } else {
          setTimeout(check, 500)
        }
      })
      req.on('timeout', () => {
        req.destroy()
        if (Date.now() > deadline) {
          reject(new Error('Vite 启动超时'))
        } else {
          setTimeout(check, 500)
        }
      })
    }
    check()
  })
}

function startVite(): Promise<void> {
  return new Promise((resolve, reject) => {
    viteProcess = spawn('npm', ['run', 'dev'], {
      cwd: FRONTEND_DIR,
      shell: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env }
    })

    viteProcess.stdout?.on('data', (data: Buffer) => {
      process.stdout.write(`[vite] ${data}`)
    })
    viteProcess.stderr?.on('data', (data: Buffer) => {
      process.stderr.write(`[vite] ${data}`)
    })

    viteProcess.on('error', reject)
    viteProcess.on('exit', (code) => {
      if (code !== 0) {
        console.log(`[vite] 进程退出, code: ${code}`)
      }
    })

    waitForViteReady().then(resolve).catch(reject)
  })
}

function stopVite() {
  if (viteProcess) {
    viteProcess.kill()
    viteProcess = null
  }
}

app.whenReady().then(async () => {
  if (isDev) {
    if (process.env.BACKEND_MANAGED) {
      console.log('[main] 由 dev-runner 管理，跳过后端和 Vite 启动')
    } else {
      console.log('[main] 开发模式，启动后端...')
      try {
        await startBackend()
        console.log('[main] 后端已就绪')
      } catch (err) {
        console.error('[main] 后端启动失败:', err)
      }

      console.log('[main] 开发模式，启动 Vite...')
      try {
        await startVite()
        console.log('[main] Vite 已就绪')
      } catch (err) {
        console.error('[main] Vite 启动失败:', err)
        app.quit()
        return
      }
    }
  }

  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (!process.env.BACKEND_MANAGED) {
    stopBackend()
    stopVite()
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  if (!process.env.BACKEND_MANAGED) {
    stopBackend()
    stopVite()
  }
})
