/**
 * Electron 桌面 API 类型声明
 * 对应 electron/preload.ts 中暴露的 desktopApi 对象
 */
interface WindowControls {
  minimize: () => Promise<void>
  maximize: () => Promise<void>
  close: () => Promise<void>
  isMaximized: () => Promise<boolean>
  onMaximizeChange: (callback: (maximized: boolean) => void) => void
}

type UpdateStatus =
  | { state: 'idle' }
  | { state: 'checking' }
  | { state: 'available'; version: string }
  | { state: 'downloading'; version: string; percent: number; bytesPerSecond: number }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string }

interface UpdateCommandResult {
  ok: boolean
  error?: string
}

interface UpdaterApi {
  check: () => Promise<UpdateCommandResult>
  quitAndInstall: () => Promise<UpdateCommandResult>
  onStatus: (callback: (status: UpdateStatus) => void) => () => void
}

/** 本地文件选择：桌面端读取磁盘路径，供后端直接访问同目录资源 */
interface FileDialogApi {
  pickMarkdown: () => Promise<{ path: string; name: string; size: number } | null>
  getPathForFile: (file: File) => string
  takeDroppedPaths: () => string[]
}

interface DesktopApi {
  platform: string
  versions: {
    node: string
    chrome: string
    electron: string
    app: string
  }
  getAppDataPath: () => Promise<string>
  fileDialog: FileDialogApi
  windowControls: WindowControls
  updater: UpdaterApi
}

interface Window {
  desktopApi?: DesktopApi
}
