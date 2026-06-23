import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('desktopApi', {
  platform: process.platform,
  versions: {
    node: process.versions.node,
    chrome: process.versions.chrome,
    electron: process.versions.electron
  },
  getAppDataPath: () => ipcRenderer.invoke('get-app-data-path')
})
