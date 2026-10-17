import { app, BrowserWindow, ipcMain } from 'electron'
import { autoUpdater } from 'electron-updater'
import type { ProgressInfo, UpdateDownloadedEvent, UpdateInfo } from 'electron-updater'
import type { AppLifecycle } from './app-lifecycle'
import * as macUpdater from './mac-updater'
import { broadcast, getCurrentStatus } from './update-state'
import type { UpdateCommandResult, UpdateStatus } from './update-types'

const isMacCustom = process.platform === 'darwin'

let initialized = false
let checkPromise: Promise<UpdateCommandResult> | null = null
let lifecycle: AppLifecycle | null = null

/** 由主进程注入退出协调器；未注入时拒绝安装，不绕过传输停止。 */
export function setLifecycle(value: AppLifecycle) {
  lifecycle = value
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
  // 显式安装也先走退出协调：Windows 的 quitAndInstall 会在内部先启动安装器。
  ipcMain.handle('updater:quit-and-install', async (): Promise<UpdateCommandResult> => {
    if (!lifecycle) {
      return { ok: false, error: '退出协调未就绪，暂不能安装更新' }
    }
    if (isMacCustom) {
      if (getCurrentStatus().state !== 'downloaded') {
        return { ok: false, error: '当前没有可安装的更新' }
      }
      const window = BrowserWindow.getAllWindows()[0] ?? null
      const decision = await lifecycle.prepareInstall(window, () => {
        void macUpdater.installOnQuit().then((result) => {
          if (result.ok) {
            // helper 已在等待本进程退出；现在才真正结束应用。
            app.quit()
            return
          }
          // 安装器未启动时不结束应用，保留当前状态供用户重试。
          broadcast({ state: 'error', message: result.error ?? '无法启动更新安装器' })
        })
      })
      if (!decision.ok) return { ok: false, error: '已取消安装：有线传输未停止' }
      // 停止已确认：立即执行已登记的安装动作，不依赖退出事件是否再次到达。
      lifecycle.takeAfterStop()?.()
      return { ok: true }
    }

    if (!app.isPackaged || !autoUpdater.isUpdaterActive()) {
      return { ok: false, error: '当前没有可安装的更新' }
    }
    const window = BrowserWindow.getAllWindows()[0] ?? null
    const decision = await lifecycle.prepareInstall(window, () => {
      autoUpdater.quitAndInstall()
    })
    if (!decision.ok) return { ok: false, error: '已取消安装：有线传输未停止' }
    lifecycle.takeAfterStop()?.()
    return { ok: true }
  })
}

export function notifyUpdaterWindowReady(window: BrowserWindow) {
  if (!window.isDestroyed() && !window.webContents.isDestroyed()) {
    window.webContents.send('updater:status', getCurrentStatus())
  }
}

export function initializeUpdater() {
  if (!app.isPackaged || initialized) return
  initialized = true

  // macOS：免签名自定义更新器（未签名产物无法通过 Squirrel.Mac 的代码签名校验）
  if (isMacCustom) {
    macUpdater.initializeMacUpdater()
    // 第二次 before-quit 才表示停止已确认；此时才允许退出即安装。
    app.on('before-quit', () => {
      if (lifecycle?.stopped) {
        void macUpdater.installOnQuit()
      }
    })
    return
  }

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
    const status = getCurrentStatus()
    const currentVersion = status.state === 'available' || status.state === 'downloading'
      ? status.version
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
  if (isMacCustom) {
    return macUpdater.checkForUpdates()
  }
  if (checkPromise) return checkPromise

  broadcast({ state: 'checking' })
  const request = autoUpdater.checkForUpdates()
    .then(() => ({ ok: true } satisfies UpdateCommandResult))
    .catch((error: unknown) => {
      // electron-updater 通常会先触发 error 事件；仅在没有事件状态时兜底处理。
      if (getCurrentStatus().state === 'checking') {
        handleUpdaterError(error instanceof Error ? error : new Error(String(error)))
      }
      return { ok: false, error: '更新检查失败' } satisfies UpdateCommandResult
    })

  checkPromise = request.finally(() => {
    checkPromise = null
  })
  return checkPromise
}
