/**
 * 应用退出、窗口关闭与更新安装的统一协调。
 *
 * 顺序固定为：确认传输状态 → 请求取消并等待后端与 USB 确认停止 → 关闭或安装。
 * 有活动任务或状态未知时默认留在应用；停止未确认时如实记录，不冒充正常取消。
 */
import { BrowserWindow, dialog } from 'electron'
import { BackendRuntime, RuntimeSnapshot } from './backend-runtime'

export type LifecycleDecision = { ok: true } | { ok: false; reason: string }

const STOP_TIMEOUT_MS = 30000

export class AppLifecycle {
  private readonly backend: BackendRuntime
  private stopPromise: Promise<LifecycleDecision> | null = null
  private decision: LifecycleDecision | null = null
  private afterStop: (() => void) | null = null

  constructor(backend: BackendRuntime) {
    this.backend = backend
  }

  /** 已完成停止确认，退出事件可以放行。 */
  get stopped(): boolean {
    return this.decision?.ok === true
  }

  /** 正在停止中，重复的退出或关闭请求应等待同一结论。 */
  get stopping(): boolean {
    return this.stopPromise !== null && this.decision === null
  }

  private async snapshot(): Promise<{ value: RuntimeSnapshot | null; error: string }> {
    try {
      return { value: await this.backend.status(), error: '' }
    } catch (error) {
      return { value: null, error: error instanceof Error ? error.message : String(error) }
    }
  }

  private async askUser(
    window: BrowserWindow,
    snapshot: RuntimeSnapshot | null,
    error: string,
    reason: 'close' | 'quit' | 'install',
  ): Promise<boolean> {
    const action = reason === 'install' ? '安装更新' : reason === 'quit' ? '退出应用' : '关闭窗口'
    const options: Electron.MessageBoxOptions = snapshot && snapshot.usb_active_tasks > 0
      ? {
          type: 'warning',
          buttons: ['留在应用', `停止传输并${action}`],
          defaultId: 0,
          cancelId: 0,
          message: `仍有 ${snapshot.usb_active_tasks} 个有线传输任务在进行`,
          detail: `${action}会请求停止这些任务并中断旧队列。已完成的内容不会回滚，设备中可能留下残留，未确认结果不会被当作成功。`,
        }
      : {
          type: 'warning',
          buttons: ['留在应用', `仍然${action}`],
          defaultId: 0,
          cancelId: 0,
          message: '无法确认有线传输状态',
          detail: `${error || '后端未返回状态'}。无法确认时默认留在应用；若仍要继续，可能中断正在进行的设备写入。`,
        }
    const result = await dialog.showMessageBox(window, options)
    return result.response === 1
  }

  /** 执行停止；重复调用共享同一过程，结果被缓存供退出事件放行。 */
  private runStop(): Promise<LifecycleDecision> {
    if (this.stopPromise) return this.stopPromise
    this.stopPromise = (async (): Promise<LifecycleDecision> => {
      const outcome = await this.backend.stop(STOP_TIMEOUT_MS)
      if (outcome.confirmed) {
        console.log('[lifecycle] 后端与 USB 已确认停止')
      } else {
        // 超时或强制中断：如实记录，写前记录仍是结果不确定时的兜底。
        console.warn(`[lifecycle] 后端停止未确认: ${outcome.detail}`)
      }
      this.backend.reset()
      this.decision = { ok: true }
      return this.decision
    })()
    return this.stopPromise
  }

  /** 无交互停止：仅用于启动失败等已无业务可保护的情况。 */
  async stopWithoutPrompt(): Promise<LifecycleDecision> {
    return this.runStop()
  }

  /** 窗口关闭或退出前调用；返回 ok 表示可以继续关闭或退出。 */
  async prepareClose(window: BrowserWindow | null, reason: 'close' | 'quit'): Promise<LifecycleDecision> {
    if (this.decision) return this.decision
    if (this.stopPromise) return this.stopPromise
    const { value, error } = await this.snapshot()
    if (value && value.usb_active_tasks === 0 && !value.usb_busy) {
      return this.runStop()
    }
    if (!window || window.isDestroyed()) {
      // 没有可交互窗口时不弹模态框，避免退出被无法关闭的对话框挂住。
      // 仍按“状态未知”如实记录，然后继续有序停止，不静默中断写入。
      console.warn(`[lifecycle] 无可用窗口，按状态未知继续停止: ${error || '后端未返回状态'}`)
      return this.runStop()
    }
    if (!(await this.askUser(window, value, error, reason))) {
      return { ok: false, reason: 'user-stayed' }
    }
    return this.runStop()
  }

  async prepareInstall(window: BrowserWindow | null, run: () => void): Promise<LifecycleDecision> {    if (this.decision) {
      this.afterStop = run
      return this.decision
    }
    const decision = await this.prepareClose(window, 'quit')
    if (decision.ok) this.afterStop = run
    return decision
  }

  /** 取出待执行的安装动作；只允许执行一次。 */
  takeAfterStop(): (() => void) | null {
    const action = this.afterStop
    this.afterStop = null
    return action
  }

  /**
   * macOS 关闭全部窗口后仍可再次激活：清空已停止状态以便重新启动后端。
   * 退出或安装路径不会经过此处，因此不会把正在进行的退出误当作重启。
   */
  resetForRestart(): void {
    this.stopPromise = null
    this.decision = null
    this.afterStop = null
  }
}
