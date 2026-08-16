import { app, BrowserWindow, ipcMain } from 'electron'
import { autoUpdater } from 'electron-updater'
import type { ProgressInfo, UpdateDownloadedEvent, UpdateInfo } from 'electron-updater'
import type { UpdateCommandResult, UpdateStatus } from './update-types'

let initialized = false
let currentStatus: UpdateStatus = { state: 'idle' }
let checkPromise: Promise<UpdateCommandResult> | null = null

function broadcast(status: UpdateStatus) {
  currentStatus = status
  for (const window of BrowserWindow.getAllWindows()) {
    if (!window.isDestroyed() && !window.webContents.isDestroyed()) {
      window.webContents.send('updater:status', status)
    }
  }
}

function versionOf(info: UpdateInfo | UpdateDownloadedEvent): string {
  return info.version || '新版本'
}

function handleUpdaterError(error: Error) {
  if (/no published versions on github/i.test(error.message)) {
    // 首个正式 Release 创建前，GitHub 会返回此错误；这不应打扰用户。
    console.warn('[updater] 暂无可用的 GitHub Release')
    broadcast({ state: 'idle' })
    return
  }

  console.error('[updater] 更新失败:', error)
  broadcast({ state: 'error', message: '更新检查失败，请稍后重试' })
}

export function registerUpdaterIpc() {
  ipcMain.handle('updater:check', () => checkForUpdates())
  ipcMain.handle('updater:quit-and-install', () => {
    if (!app.isPackaged || !autoUpdater.isUpdaterActive()) {
      return { ok: false, error: '当前没有可安装的更新' } satisfies UpdateCommandResult
    }

    autoUpdater.quitAndInstall()
    return { ok: true } satisfies UpdateCommandResult
  })
}

export function notifyUpdaterWindowReady(window: BrowserWindow) {
  if (!window.isDestroyed() && !window.webContents.isDestroyed()) {
    window.webContents.send('updater:status', currentStatus)
  }
}

export function initializeUpdater() {
  if (!app.isPackaged || initialized) return
  initialized = true

  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = true
  autoUpdater.allowDowngrade = false

  autoUpdater.on('checking-for-update', () => {
    broadcast({ state: 'checking' })
  })
  autoUpdater.on('update-available', (info) => {
    broadcast({ state: 'available', version: versionOf(info) })
  })
  autoUpdater.on('update-not-available', () => {
    broadcast({ state: 'idle' })
  })
  autoUpdater.on('download-progress', (progress: ProgressInfo) => {
    const percent = Math.max(0, Math.min(100, Math.round(progress.percent)))
    const currentVersion = currentStatus.state === 'available' || currentStatus.state === 'downloading'
      ? currentStatus.version
      : '新版本'
    broadcast({
      state: 'downloading',
      version: currentVersion,
      percent,
      bytesPerSecond: progress.bytesPerSecond,
    })
  })
  autoUpdater.on('update-downloaded', (event: UpdateDownloadedEvent) => {
    broadcast({ state: 'downloaded', version: versionOf(event) })
  })
  autoUpdater.on('update-cancelled', () => {
    broadcast({ state: 'idle' })
  })
  autoUpdater.on('error', handleUpdaterError)

  // 不阻塞首屏和后端启动，应用打开后再异步检查。
  setTimeout(() => {
    void checkForUpdates()
  }, 5000)
}

export function checkForUpdates(): Promise<UpdateCommandResult> {
  if (!app.isPackaged) {
    return Promise.resolve({ ok: false, error: '开发模式不检查更新' })
  }
  if (checkPromise) return checkPromise

  broadcast({ state: 'checking' })
  const request = autoUpdater.checkForUpdates()
    .then(() => ({ ok: true } satisfies UpdateCommandResult))
    .catch((error: unknown) => {
      // electron-updater 通常会先触发 error 事件；仅在没有事件状态时兜底处理。
      if (currentStatus.state === 'checking') {
        handleUpdaterError(error instanceof Error ? error : new Error(String(error)))
      }
      return { ok: false, error: '更新检查失败' } satisfies UpdateCommandResult
    })

  checkPromise = request.finally(() => {
    checkPromise = null
  })
  return checkPromise
}
