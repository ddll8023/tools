export type UpdateStatus =
  | { state: 'idle' }
  | { state: 'checking' }
  | { state: 'available'; version: string }
  | {
      state: 'downloading'
      version: string
      percent: number
      bytesPerSecond: number
    }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string }

export interface UpdateCommandResult {
  ok: boolean
  error?: string
}
