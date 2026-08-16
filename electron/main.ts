import { app, BrowserWindow, ipcMain } from 'electron'
import { existsSync } from 'fs'
import { spawn, execSync, ChildProcess } from 'child_process'
import * as path from 'path'
import * as http from 'http'
import {
  initializeUpdater,
  notifyUpdaterWindowReady,
  registerUpdaterIpc,
} from './updater'

const isDev = !app.isPackaged
const VITE_PORT = 5173
const VITE_URL = `http://127.0.0.1:${VITE_PORT}`
const BACKEND_PORT = 4740
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`
const ROOT_DIR = path.resolve(__dirname, '..')
const FRONTEND_DIR = path.join(ROOT_DIR, 'frontend')
const DEV_BACKEND_DIR = path.join(ROOT_DIR, 'backend')
const PACKAGED_BACKEND_DIR = path.join(process.resourcesPath, 'backend')
const PACKAGED_BACKEND_EXECUTABLE = path.join(
  PACKAGED_BACKEND_DIR,
  process.platform === 'win32' ? 'toolbox-backend.exe' : 'toolbox-backend',
)

let viteProcess: ChildProcess | null = null
let backendProcess: ChildProcess | null = null
let mainWindow: BrowserWindow | null = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    frame: false,
    title: '工具盒子',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  // 监听最大化状态变化通知渲染进程（窗口级事件，可随窗口重复注册）
  mainWindow.on('maximize', () => {
    mainWindow?.webContents.send('window:maximize-changed', true)
  })
  mainWindow.on('unmaximize', () => {
    mainWindow?.webContents.send('window:maximize-changed', false)
  })

  if (isDev) {
    mainWindow.loadURL(VITE_URL)
    if (!process.env.BACKEND_MANAGED) {
      mainWindow.webContents.openDevTools()
    }
  } else {
    mainWindow.loadFile(path.join(ROOT_DIR, 'frontend', 'dist', 'index.html'))
  }

  mainWindow.webContents.once('did-finish-load', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      notifyUpdaterWindowReady(mainWindow)
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

/** 窗口控制 IPC：只注册一次，避免窗口重建时重复注册抛错 */
function registerWindowIpc() {
  ipcMain.handle('get-app-data-path', () => app.getPath('userData'))
  ipcMain.handle('window:minimize', () => {
    mainWindow?.minimize()
  })
  ipcMain.handle('window:maximize', () => {
    if (mainWindow?.isMaximized()) {
      mainWindow.unmaximize()
    } else {
      mainWindow?.maximize()
    }
  })
  ipcMain.handle('window:close', () => {
    mainWindow?.close()
  })
  ipcMain.handle('window:isMaximized', () => mainWindow?.isMaximized() ?? false)
}

/** 终止进程树：macOS/Linux 杀进程组，Windows 用 taskkill /T */
function killProcessTree(proc: ChildProcess) {
  if (!proc || !proc.pid) return
  try {
    if (process.platform === 'win32') {
      execSync(`taskkill /F /T /PID ${proc.pid}`, { stdio: 'ignore' })
    } else {
      try {
        process.kill(-proc.pid, 'SIGTERM')
      } catch {
        proc.kill()
      }
    }
  } catch {
    try {
      proc.kill()
    } catch {
      // 进程已退出
    }
  }
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
        res.on('end', () => {
          try {
            const json = JSON.parse(body)
            if (json.code === 0) return resolve()
          } catch {
            // 响应不是预期的 JSON，继续等待
          }
          if (Date.now() > deadline) { reject(new Error('后端启动超时')); return }
          setTimeout(check, 500)
        })
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
    if (!isDev && !existsSync(PACKAGED_BACKEND_EXECUTABLE)) {
      reject(new Error(`未找到后端运行时: ${PACKAGED_BACKEND_EXECUTABLE}`))
      return
    }

    const command = isDev ? 'uv' : PACKAGED_BACKEND_EXECUTABLE
    const args = isDev
      ? [
          'run', 'uvicorn', 'app.main:app',
          '--host', '127.0.0.1', '--port', String(BACKEND_PORT),
        ]
      : []
    const cwd = isDev ? DEV_BACKEND_DIR : app.getPath('userData')

    backendProcess = spawn(command, args, {
      cwd,
      shell: isDev,
      // 创建独立进程组，退出时可按组终止 uv 与 uvicorn 子进程
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        ...(isDev ? {} : { TOOLBOX_DATA_DIR: app.getPath('userData') }),
      },
    })

    backendProcess.stdout?.on('data', (data: Buffer) => {
      process.stdout.write(`[backend] ${data}`)
    })
    backendProcess.stderr?.on('data', (data: Buffer) => {
      process.stderr.write(`[backend] ${data}`)
    })

    let settled = false
    const succeed = () => {
      if (settled) return
      settled = true
      resolve()
    }
    const fail = (error: Error) => {
      if (settled) return
      settled = true
      reject(error)
    }

    backendProcess.on('error', fail)
    backendProcess.on('exit', (code) => {
      if (code !== null && code !== 0) {
        fail(new Error(`后端进程退出，code=${code}`))
      }
    })

    waitForBackendReady().then(succeed).catch(fail)
  })
}

function stopBackend() {
  if (backendProcess) {
    killProcessTree(backendProcess)
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
      // 创建独立进程组，退出时可按组终止 npm 与 vite 子进程
      detached: process.platform !== 'win32',
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
    killProcessTree(viteProcess)
    viteProcess = null
  }
}

app.whenReady().then(async () => {
  registerWindowIpc()
  registerUpdaterIpc()

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
  } else {
    console.log('[main] 生产模式，启动内置后端...')
    try {
      await startBackend()
      console.log('[main] 内置后端已就绪')
    } catch (err) {
      console.error('[main] 内置后端启动失败:', err)
    }
  }

  createWindow()
  initializeUpdater()

  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      if (!isDev && !backendProcess) {
        try {
          await startBackend()
        } catch (err) {
          console.error('[main] 重新启动内置后端失败:', err)
        }
      }
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
