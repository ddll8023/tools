import { BrowserWindow } from 'electron'
import type { UpdateStatus } from './update-types'

let currentStatus: UpdateStatus = { state: 'idle' }

export function getCurrentStatus(): UpdateStatus {
  return currentStatus
}

export function broadcast(status: UpdateStatus) {
  currentStatus = status
  for (const window of BrowserWindow.getAllWindows()) {
    if (!window.isDestroyed() && !window.webContents.isDestroyed()) {
      window.webContents.send('updater:status', status)
    }
  }
}
