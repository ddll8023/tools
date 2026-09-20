/** 向应用页面暴露受限桌面 API，不公开通用 IPC 或磁盘写入能力。 */
import { contextBridge, ipcRenderer, webUtils } from 'electron'
import type { UpdateCommandResult, UpdateStatus } from './update-types'

/**
 * 应用版本：渲染进程不再提供 electron.app，改读应用包内的 package.json，
 * 取值与主进程 app.getVersion() 一致；主进程模块在 preload 里为 undefined，
 * 直接调用会抛错并导致整个 preload 加载失败。
 */
function readAppVersion(): string {
  try {
    return String(require('../package.json').version ?? '')
  } catch {
    return ''
  }
}

/** 渲染进程传入的文件对象类型（复用 Electron 自身声明，避免引入 DOM lib） */
type RendererFile = Parameters<typeof webUtils.getPathForFile>[0]

/**
 * File 经 contextBridge 传递后会失去磁盘来源，webUtils 再也取不到路径，
 * 因此在 preload 自己的 DOM 事件里提前解析，供主世界按文件名取用。
 */
let pendingPaths: string[] = []

function recordPaths(files: ArrayLike<RendererFile> | null | undefined): void {
  if (!files) return

  const paths: string[] = []
  for (const file of Array.from(files)) {
    try {
      const path = webUtils.getPathForFile(file)
      if (path) paths.push(path)
    } catch {
      // 页内构造或已失去磁盘来源的 File 直接忽略，由上层回退到上传流程
    }
  }
  pendingPaths = paths
}

window.addEventListener('drop', (event) => recordPaths(event.dataTransfer?.files), true)
window.addEventListener(
  'change',
  (event) => {
    const target = event.target
    if (target instanceof HTMLInputElement && target.type === 'file') {
      recordPaths(target.files)
    }
  },
  true
)

contextBridge.exposeInMainWorld('desktopApi', {
  platform: process.platform,
  versions: {
    node: process.versions.node,
    chrome: process.versions.chrome,
    electron: process.versions.electron,
    app: readAppVersion()
  },
  getAppDataPath: () => ipcRenderer.invoke('get-app-data-path'),

  // 本地文件选择：桌面端把磁盘路径交给后端，避免上传同目录图片资源
  fileDialog: {
    pickMarkdown: () =>
      ipcRenderer.invoke('dialog:pick-markdown') as Promise<{
        path: string
        name: string
        size: number
      } | null>,
    getPathForFile: (file: RendererFile) => {
      try {
        return webUtils.getPathForFile(file)
      } catch {
        return ''
      }
    },
    /** 取走最近一次拖入或选择文件时解析出的磁盘路径 */
    takeDroppedPaths: () => {
      const paths = pendingPaths
      pendingPaths = []
      return paths
    }
  },

  // 窗口控制
  windowControls: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    close: () => ipcRenderer.invoke('window:close'),
    isMaximized: () => ipcRenderer.invoke('window:isMaximized'),
    onMaximizeChange: (callback: (maximized: boolean) => void) => {
      ipcRenderer.on('window:maximize-changed', (_event, maximized) => callback(maximized))
    }
  },

  updater: {
    check: () => ipcRenderer.invoke('updater:check') as Promise<UpdateCommandResult>,
    quitAndInstall: () => ipcRenderer.invoke('updater:quit-and-install') as Promise<UpdateCommandResult>,
    onStatus: (callback: (status: UpdateStatus) => void) => {
      const listener = (_event: Electron.IpcRendererEvent, status: UpdateStatus) => callback(status)
      ipcRenderer.on('updater:status', listener)
      return () => ipcRenderer.removeListener('updater:status', listener)
    }
  }
})
