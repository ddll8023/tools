/** 桌面主进程：单实例、窗口、便携数据目录、所属后端生命周期和受限桌面能力。 */
import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { mkdirSync, rmSync, statSync, writeFileSync } from 'fs'
import { spawn, execSync, ChildProcess } from 'child_process'
import * as path from 'path'
import * as http from 'http'
import { pathToFileURL } from 'url'
import { AppLifecycle } from './app-lifecycle'
import { BackendRuntime } from './backend-runtime'
import { cancelMarkdownPdf, registerMarkdownPdfIpc } from './markdown-to-pdf'
import { registerMarkdownSourceIpc } from './markdown-source'

const APP_DATA_DIR_NAME = '工具盒子'
const PORTABLE_DATA_DIR_NAME = 'data'
const DEV_DATA_DIR_NAME = '.dev-data'
const INTERNAL_APP_NAME = 'toolbox-desktop'
const SAFE_USER_AGENT = `Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${process.versions.chrome} Safari/537.36 Electron/${process.versions.electron}`
const VITE_PORT = 5173
const VITE_URL = `http://127.0.0.1:${VITE_PORT}`
const ROOT_DIR = path.resolve(__dirname, '..')
const FRONTEND_DIR = path.join(ROOT_DIR, 'frontend')
const DEV_BACKEND_DIR = path.join(ROOT_DIR, 'backend')

/** 打包态数据根：程序目录下的 data/；macOS 的可执行文件在 .app 包体内，取 .app 所在目录。 */
function portableDataRoot(): string {
  const executable = app.getPath('exe')
  const root =
    process.platform === 'darwin'
      ? path.resolve(path.dirname(executable), '..', '..', '..')
      : path.dirname(executable)
  return path.join(root, PORTABLE_DATA_DIR_NAME)
}

/** mkdir 不暴露只读目录，必须实际写一个探针文件再删掉才能确认可写。 */
function ensureWritableDirectory(directory: string): boolean {
  try {
    mkdirSync(directory, { recursive: true })
    const probe = path.join(directory, `.write-probe-${process.pid}`)
    writeFileSync(probe, '')
    rmSync(probe, { force: true })
    return true
  } catch {
    return false
  }
}

/**
 * 数据根只解析一次：命令行与环境的显式目录优先；其次打包态的程序目录 data/、
 * 开发态的项目根 .dev-data，两者互不覆盖；程序目录不可写时回退系统默认位置并提示。
 */
function resolveDataRoot(): string {
  const argument = process.argv.find((item) => item.startsWith('--toolbox-data-dir='))
  const fromArgument = argument ? argument.slice('--toolbox-data-dir='.length) : ''
  const candidate = fromArgument || process.env.TOOLBOX_DATA_DIR || ''
  if (candidate) return path.resolve(candidate)
  const preferred = app.isPackaged ? portableDataRoot() : path.join(ROOT_DIR, DEV_DATA_DIR_NAME)
  if (ensureWritableDirectory(preferred)) return preferred
  const fallback = path.join(app.getPath('appData'), APP_DATA_DIR_NAME)
  console.warn(`[main] ${preferred} 不可写，数据改存系统默认位置: ${fallback}`)
  return ensureWritableDirectory(fallback) ? fallback : preferred
}

// Electron 可能把应用名拼入 User-Agent；内部标识必须保持 ASCII，中文仅用于界面和数据目录。
app.setName(INTERNAL_APP_NAME)
app.userAgentFallback = SAFE_USER_AGENT
const DATA_ROOT = resolveDataRoot()
app.setPath('userData', DATA_ROOT)
// Chromium 会话数据与主进程临时文件同样留在数据根内，不散落到系统目录。
try {
  const sessionData = path.join(DATA_ROOT, 'session')
  const temp = path.join(DATA_ROOT, 'temp')
  mkdirSync(sessionData, { recursive: true })
  mkdirSync(temp, { recursive: true })
  app.setPath('sessionData', sessionData)
  app.setPath('temp', temp)
} catch (error) {
  console.error('[main] 无法重定向会话/临时目录:', error instanceof Error ? error.message : error)
}

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
        { name: 'Markdown 与资源包', extensions: ['md', 'markdown', 'zip'] },
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
  if (!mainWindow || mainWindow.isDestroyed()) return
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.focus()
})

async function bootstrap(): Promise<void> {
  registerWindowIpc()
  // PDF 打印与本地 Markdown 读取都只认主窗口主框架；打包态页面走 file:// 入口。
  const trustedPageUrl = isDev
    ? VITE_URL
    : pathToFileURL(path.join(ROOT_DIR, 'frontend', 'dist', 'index.html')).href
  registerMarkdownPdfIpc(() => mainWindow, trustedPageUrl)
  registerMarkdownSourceIpc(() => mainWindow, trustedPageUrl)

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
}

app.whenReady().then(async () => {
  if (!hasSingleInstanceLock) return
  await bootstrap()
})

app.on('window-all-closed', () => {
  // 全平台一致：主窗口关闭即完整退出，后端已在窗口 close 前有序停止。
  stopVite()
  app.quit()
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
    if (!decision.ok) return
    stopVite()
    app.quit()
  })
})
