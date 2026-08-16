import { contextBridge, ipcRenderer } from 'electron'
import type { UpdateCommandResult, UpdateStatus } from './update-types'

contextBridge.exposeInMainWorld('desktopApi', {
  platform: process.platform,
  versions: {
    node: process.versions.node,
    chrome: process.versions.chrome,
    electron: process.versions.electron
  },
  getAppDataPath: () => ipcRenderer.invoke('get-app-data-path'),

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
