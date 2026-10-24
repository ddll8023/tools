/** 桌面主进程：单实例、窗口、所属后端生命周期和受限桌面能力。 */
import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { statSync } from 'fs'
import { spawn, execSync, ChildProcess } from 'child_process'
import * as path from 'path'
import * as http from 'http'
import { pathToFileURL } from 'url'
import { AppLifecycle } from './app-lifecycle'
import { BackendRuntime } from './backend-runtime'
import { cancelMarkdownPdf, registerMarkdownPdfIpc } from './markdown-to-pdf'
import { registerMarkdownSourceIpc } from './markdown-source'
import {
  initializeUpdater,
  notifyUpdaterWindowReady,
  registerUpdaterIpc,
  setLifecycle,
} from './updater'

const APP_DATA_DIR_NAME = '工具盒子'
const INTERNAL_APP_NAME = 'toolbox-desktop'
const SAFE_USER_AGENT = `Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${process.versions.chrome} Safari/537.36 Electron/${process.versions.electron}`
const VITE_PORT = 5173
const VITE_URL = `http://127.0.0.1:${VITE_PORT}`
const ROOT_DIR = path.resolve(__dirname, '..')
const FRONTEND_DIR = path.join(ROOT_DIR, 'frontend')
const DEV_BACKEND_DIR = path.join(ROOT_DIR, 'backend')

/** 数据根只解析一次：环境变量、命令行显式值、默认目录三者取首个绝对路径。 */
function resolveDataRoot(): string {
  const argument = process.argv.find((item) => item.startsWith('--toolbox-data-dir='))
  const fromArgument = argument ? argument.slice('--toolbox-data-dir='.length) : ''
  const candidate = fromArgument || process.env.TOOLBOX_DATA_DIR || ''
  if (candidate) return path.resolve(candidate)
  return path.join(app.getPath('appData'), APP_DATA_DIR_NAME)
}

// Electron 可能把应用名拼入 User-Agent；内部标识必须保持 ASCII，中文仅用于界面和数据目录。
app.setName(INTERNAL_APP_NAME)
app.userAgentFallback = SAFE_USER_AGENT
const DATA_ROOT = resolveDataRoot()
app.setPath('userData', DATA_ROOT)

const isDev = !app.isPackaged
const PACKAGED_BACKEND_DIR = path.join(process.resourcesPath, 'backend')
const PACKAGED_BACKEND_EXECUTABLE = path.join(
  PACKAGED_BACKEND_DIR,
  process.platform === 'win32' ? 'toolbox-backend.exe' : 'toolbox-backend',
)

const backend = new BackendRuntime({
  isDev,
  dataRoot: DATA_ROOT,
  devBackendDir: DEV_BACKEND_DIR,
  packagedExecutable: PACKAGED_BACKEND_EXECUTABLE,
  packagedCwd: DATA_ROOT,
})
const lifecycle = new AppLifecycle(backend)

let viteProcess: ChildProcess | null = null
let mainWindow: BrowserWindow | null = null
// 退出流程一旦开始，窗口全部关闭不应被误认为“可重启”状态。
let quitRequested = false

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

  // 关闭窗口前先协调传输与后端；确认停止后才真正关闭。
  mainWindow.on('close', (event) => {
    if (lifecycle.stopped) return
    event.preventDefault()
    if (lifecycle.stopping) return
    void lifecycle.prepareClose(mainWindow, 'close').then((decision) => {
      if (!decision.ok) return
      stopVite()
      mainWindow?.close()
    })
  })

  if (isDev) {
    mainWindow.loadURL(VITE_URL)
    // 开发态直接查看渲染进程日志；由 dev-runner 拉起时同样有用。
    mainWindow.webContents.openDevTools()
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
  ipcMain.handle('get-app-data-path', () => DATA_ROOT)

  // 凭据只交给当前实例的渲染进程；不属于本次启动时直接失败，不返回其他后端凭据。
  ipcMain.handle('control:token', async () => {
    try {
      return await backend.readToken()
    } catch (error) {
      console.error('[main] 读取控制面凭据失败:', error instanceof Error ? error.message : error)
      return ''
    }
  })
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

  // 共享文件多选：只返回路径和文件元信息，具体读取与传输由业务处理
  ipcMain.handle('dialog:pick-files', async () => {
    const options: Electron.OpenDialogOptions = {
      title: '选择要投送的文件',
      properties: ['openFile', 'multiSelections'],
    }

    const result =
      mainWindow && !mainWindow.isDestroyed()
        ? await dialog.showOpenDialog(mainWindow, options)
        : await dialog.showOpenDialog(options)
    if (result.canceled) return []

    const picked: Array<{ path: string; name: string; size: number }> = []
    for (const filePath of result.filePaths) {
      try {
        picked.push({
          path: filePath,
          name: path.basename(filePath),
          size: statSync(filePath).size,
        })
      } catch {
        // 无法 stat 的条目直接跳过，由前端按缺失处理
      }
    }
    return picked
  })

  // 共享目录选择：返回绝对路径，作为来源或目标的校验由具体业务负责
  ipcMain.handle('dialog:pick-directory', async () => {
    const options: Electron.OpenDialogOptions = {
      title: '选择接收目录',
      properties: ['openDirectory', 'createDirectory'],
    }

    const result =
      mainWindow && !mainWindow.isDestroyed()
        ? await dialog.showOpenDialog(mainWindow, options)
        : await dialog.showOpenDialog(options)
    if (result.canceled || result.filePaths.length === 0) return ''
    return result.filePaths[0]
  })

  // 本地 Markdown 选择：返回绝对路径；Word 转换交后端读取，PDF 由主进程读取
  ipcMain.handle('dialog:pick-markdown', async () => {
    const options: Electron.OpenDialogOptions = {
      title: '选择 Markdown 文件',
      properties: ['openFile'],
      filters: [
        { name: 'Markdown', extensions: ['md', 'markdown'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    }

    const result =
      mainWindow && !mainWindow.isDestroyed()
        ? await dialog.showOpenDialog(mainWindow, options)
        : await dialog.showOpenDialog(options)
    if (result.canceled || result.filePaths.length === 0) return null

    const filePath = result.filePaths[0]
    try {
      return { path: filePath, name: path.basename(filePath), size: statSync(filePath).size }
    } catch {
      return null
    }
  })
}

/** 终止开发态 Vite 进程树；后端由 BackendRuntime 负责。 */
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
    // 进程已退出
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

// 单实例必须先于任何后端启动：第二个实例不生成凭据、不读取恢复记录。
const hasSingleInstanceLock = app.requestSingleInstanceLock()
if (!hasSingleInstanceLock) {
  app.exit(0)
}

// 终端中断同样走协调退出；开发启动器的信号不会绕过传输停止。
for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    app.quit()
  })
}

app.on('second-instance', () => {
  void ensureBackendAndWindow()
})

/**
 * 确保后端与窗口同时就绪：窗口存在时只聚焦；窗口已全部关闭且未处于停止状态时，
 * 按需重新启动后端再建窗口，避免出现没有后端的窗口。
 */
async function ensureBackendAndWindow(): Promise<void> {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
    return
  }
  if (lifecycle.stopped) return
  if (!backend.isRunning) {
    try {
      await backend.start()
    } catch (err) {
      console.error('[main] 重新启动后端失败:', err)
      return
    }
  }
  createWindow()
}

async function bootstrap(): Promise<void> {
  registerWindowIpc()
  registerUpdaterIpc()
  // PDF 打印与本地 Markdown 读取都只认主窗口主框架；打包态页面走 file:// 入口。
  const trustedPageUrl = isDev
    ? VITE_URL
    : pathToFileURL(path.join(ROOT_DIR, 'frontend', 'dist', 'index.html')).href
  registerMarkdownPdfIpc(() => mainWindow, trustedPageUrl)
  registerMarkdownSourceIpc(() => mainWindow, trustedPageUrl)
  setLifecycle(lifecycle)

  try {
    console.log('[main] 启动所属后端...')
    await backend.start()
    console.log('[main] 后端已就绪')
  } catch (err) {
    // 未取得本次启动身份时不继续业务接入，也不认领端口上的其他服务。
    console.error('[main] 后端启动失败:', err)
    const detail = err instanceof Error ? err.message : String(err)
    await lifecycle.stopWithoutPrompt()
    if (app.isReady()) {
      dialog.showErrorBox('后端启动失败', `${detail}\n\n已停止本次启动，请检查运行环境后重试。`)
    }
    app.quit()
    return
  }

  if (isDev) {
    console.log('[main] 开发模式，启动 Vite...')
    try {
      await startVite()
      console.log('[main] Vite 已就绪')
    } catch (err) {
      console.error('[main] Vite 启动失败:', err)
      await lifecycle.stopWithoutPrompt()
      app.quit()
      return
    }
  }

  createWindow()
  initializeUpdater()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length > 0) return
    void ensureBackendAndWindow()
  })
}

app.whenReady().then(async () => {
  if (!hasSingleInstanceLock) return
  await bootstrap()
})

app.on('window-all-closed', () => {
  stopVite()
  if (process.platform !== 'darwin') {
    app.quit()
    return
  }
  if (quitRequested) return
  // macOS 关闭全部窗口后保留应用：后端已随窗口关闭停止，再次激活时重新启动。
  lifecycle.resetForRestart()
  backend.reset()
})

app.on('before-quit', (event) => {
  // 打印窗口独立于主窗口，退出前必须一并中止，避免残留隐藏窗口。
  cancelMarkdownPdf()
  if (lifecycle.stopped) {
    stopVite()
    return
  }
  event.preventDefault()
  if (lifecycle.stopping) return
  void lifecycle.prepareClose(mainWindow, 'quit').then((decision) => {
    // 用户选择留下时不标记退出：否则之后关闭窗口将不再恢复可重启状态。
    if (!decision.ok) return
    quitRequested = true
    stopVite()
    const install = lifecycle.takeAfterStop()
    if (install) {
      // 安装动作自行结束应用；此处不再触发第二次退出。
      install()
      return
    }
    app.quit()
  })
})
