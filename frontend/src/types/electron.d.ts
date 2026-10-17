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

/** 共享本机选择能力：返回路径及选择结果，实际文件访问由具体业务后端校验 */
interface FileDialogApi {
  /** 多业务共用的文件多选对话框，返回绝对路径及文件元信息 */
  pickFiles: () => Promise<Array<{ path: string; name: string; size: number }>>
  /** 选择本机来源或目标目录，返回绝对路径；取消时为空字符串 */
  pickDirectory: () => Promise<string>
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
  /** 控制面凭据，仅桌面外壳可提供；缺失时前端不得直连控制面 */
  getControlToken: () => Promise<string>
  fileDialog: FileDialogApi
  windowControls: WindowControls
  updater: UpdaterApi
}

interface Window {
  desktopApi?: DesktopApi
}
