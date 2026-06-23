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

interface DesktopApi {
  platform: string
  versions: {
    node: string
    chrome: string
    electron: string
  }
  getAppDataPath: () => Promise<string>
  windowControls: WindowControls
}

interface Window {
  desktopApi?: DesktopApi
}
