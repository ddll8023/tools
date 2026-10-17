/**
 * 所属后端运行时的启动、身份核对、凭据读取和有序停止。
 *
 * 就绪判断绑定本次启动标识：端口上有其他后端响应时既不认领也不终止，
 * 避免误连或误杀不属于当前窗口的服务。
 */
import { spawn, execSync, ChildProcess } from 'child_process'
import { existsSync, readFileSync } from 'fs'
import * as http from 'http'
import * as path from 'path'

const BACKEND_PORT = 18740
const READY_TIMEOUT_MS = 30000
const TOKEN_MAX_ATTEMPTS = 40
const TOKEN_RETRY_DELAY_MS = 100

export interface BackendIdentity {
  instance_id: string
  launch_id: string
  pid: number
}

export interface RuntimeSnapshot extends BackendIdentity {
  phase: 'starting' | 'running' | 'stopping' | 'stopped' | 'interrupted'
  usb_active_tasks: number
  usb_busy: boolean
  usb_stopped: boolean
  usb_forced: boolean
  record_errors: string[]
}

export interface StopOutcome {
  /** 是否确认停止；false 表示超时或强制中断，结果可能不完整。 */
  confirmed: boolean
  forced: boolean
  activeTasks: number
  detail: string
}

export interface BackendOptions {
  isDev: boolean
  /** 与主进程完全一致的数据根；凭据、记录和更新结果都放在这里。 */
  dataRoot: string
  devBackendDir: string
  packagedExecutable: string
  packagedCwd: string
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function randomLaunchId(): string {
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
}

/** 只向本机端口发请求；返回解析后的统一响应壳，不记录凭据。 */
function postJson(
  routePath: string,
  body: unknown,
  token: string | null,
  timeoutMs: number,
): Promise<{ status: number; json: unknown }> {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body)
    const headers: Record<string, string | number> = {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    }
    if (token) headers.Authorization = `Bearer ${token}`
    const request = http.request(
      `http://127.0.0.1:${BACKEND_PORT}${routePath}`,
      { method: 'POST', headers, timeout: timeoutMs },
      (response) => {
        let text = ''
        response.on('data', (chunk) => { text += chunk })
        response.on('end', () => {
          try {
            resolve({ status: response.statusCode ?? 0, json: JSON.parse(text) })
          } catch {
            reject(new Error('后端响应不是有效 JSON'))
          }
        })
      },
    )
    request.on('error', reject)
    request.on('timeout', () => request.destroy(new Error('后端请求超时')))
    request.write(payload)
    request.end()
  })
}

function envelopeData(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'object' || value === null) return null
  const shell = value as { code?: unknown; data?: unknown }
  if (shell.code !== 0) return null
  if (typeof shell.data !== 'object' || shell.data === null) return null
  return shell.data as Record<string, unknown>
}

export class BackendRuntime {
  private readonly options: BackendOptions
  private process: ChildProcess | null = null
  private identity: BackendIdentity | null = null
  private token: string | null = null
  private launchId = ''
  private exited = false
  /** 后端最近几行 stderr，用于启动失败时展示具体原因。 */
  private recentErrorLines: string[] = []

  constructor(options: BackendOptions) {
    this.options = options
  }

  get currentIdentity(): BackendIdentity | null {
    return this.identity ? { ...this.identity } : null
  }

  get isRunning(): boolean {
    return this.process !== null && !this.exited
  }

  /** 启动后必须取得属于本次启动的身份；否则视为失败，不继续业务连接。 */
  async start(): Promise<void> {
    if (this.isRunning) return
    const { isDev, devBackendDir, packagedExecutable, packagedCwd, dataRoot } = this.options
    if (!isDev && !existsSync(packagedExecutable)) {
      throw new Error(`未找到后端运行时: ${packagedExecutable}`)
    }
    this.launchId = randomLaunchId()
    this.exited = false
    this.token = null
    this.identity = null
    this.recentErrorLines = []
    const command = isDev ? 'uv' : packagedExecutable
    const args = isDev
      ? ['run', 'uvicorn', 'toolbox_backend.main:app', '--app-dir', 'src', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)]
      : []
    const child = spawn(command, args, {
      cwd: isDev ? devBackendDir : packagedCwd,
      shell: isDev,
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        PYTHONIOENCODING: 'utf-8',
        TOOLBOX_DATA_DIR: dataRoot,
        TOOLBOX_LAUNCH_ID: this.launchId,
      },
    })
    this.process = child
    child.stdout?.on('data', (data: Buffer) => process.stdout.write(`[backend] ${data}`))
    child.stderr?.on('data', (data: Buffer) => {
      process.stderr.write(`[backend] ${data}`)
      // 只保留最近几行用于失败提示；日志不包含凭据。
      const lines = data.toString('utf8').split('\n').map((line) => line.trim()).filter(Boolean)
      if (lines.length > 0) {
        this.recentErrorLines = [...this.recentErrorLines, ...lines].slice(-8)
      }
    })
    child.on('exit', () => { this.exited = true })
    const spawnError = new Promise<never>((_resolve, reject) => child.on('error', reject))
    await Promise.race([this.waitForIdentity(), spawnError])
  }

  /** 轮询健康响应，直到返回的启动标识与本次一致。 */
  private async waitForIdentity(): Promise<void> {
    const deadline = Date.now() + READY_TIMEOUT_MS
    while (Date.now() < deadline) {
      if (this.exited) {
        throw new Error(`后端进程在就绪前退出${this.errorHint()}`)
      }
      try {
        const response = await postJson('/api/v1/health', {}, null, 2000)
        const data = envelopeData(response.json)
        if (data && data.launch_id === this.launchId && typeof data.instance_id === 'string') {
          this.identity = {
            instance_id: data.instance_id,
            launch_id: this.launchId,
            pid: typeof data.pid === 'number' ? data.pid : 0,
          }
          return
        }
        // 端口上有其他实例：不认领，继续等待本次启动真正就绪。
      } catch {
        // 尚未监听，继续等待
      }
      await delay(300)
    }
    throw new Error(`后端启动超时或未能确认本次启动身份${this.errorHint()}`)
  }

  /** 优先取包含“所有权”的行，否则取最后一行；两者都用于失败提示。 */
  private errorHint(): string {
    const ownership = this.recentErrorLines.find((line) => line.includes('所有权'))
    const line = ownership ?? this.recentErrorLines[this.recentErrorLines.length - 1]
    return line ? `：${line}` : ''
  }

  /**
   * 读取凭据并要求其绑定当前实例；不匹配时拒绝返回。
   * 文件尚未生成或正处于原子替换窗口时短暂重试，最终仍失败则报告原因。
   */
  async readToken(): Promise<string> {
    if (this.token) return this.token
    const tokenPath = path.join(this.options.dataRoot, 'runtime', 'control-token')
    let lastError = '凭据文件尚未生成'
    for (let attempt = 0; attempt < TOKEN_MAX_ATTEMPTS; attempt += 1) {
      try {
        const bundle = JSON.parse(readFileSync(tokenPath, 'utf-8')) as {
          instance_id?: unknown
          launch_id?: unknown
          token?: unknown
        }
        if (typeof bundle.token !== 'string' || !bundle.token) {
          lastError = '凭据内容缺失'
        } else if (!this.identity || bundle.instance_id !== this.identity.instance_id || bundle.launch_id !== this.launchId) {
          lastError = '凭据不属于当前后端实例'
        } else {
          this.token = bundle.token
          return this.token
        }
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error)
      }
      await delay(TOKEN_RETRY_DELAY_MS)
    }
    throw new Error(`读取控制面凭据失败（${lastError}）: ${tokenPath}`)
  }

  /** 查询停止进度；未取得身份或请求失败时抛出，由调用方按“状态未知”处理。 */
  async status(): Promise<RuntimeSnapshot> {
    if (!this.identity) throw new Error('尚未取得后端启动身份')
    const token = await this.readToken()
    const response = await postJson('/runtime/status', { expected_instance_id: this.identity.instance_id }, token, 5000)
    const data = envelopeData(response.json)
    if (!data) throw new Error('后端未返回运行时状态')
    return data as unknown as RuntimeSnapshot
  }

  /**
   * 请求有序停止并等待确认。
   * 后端确认 USB 已停止后才向其发 SIGTERM 并等待退出；任何环节未确认都标为 forced。
   */
  async stop(timeoutMs: number): Promise<StopOutcome> {
    if (!this.isRunning) return { confirmed: true, forced: false, activeTasks: 0, detail: '后端未运行' }
    let activeTasks = 0
    let usbStopped = false
    let usbForced = false
    let detail = ''
    try {
      const identity = this.identity
      if (!identity) throw new Error('缺少启动身份，无法请求有序停止')
      const token = await this.readToken()
      const response = await postJson(
        '/runtime/stop',
        { expected_instance_id: identity.instance_id },
        token,
        timeoutMs,
      )
      const data = envelopeData(response.json) as RuntimeSnapshot | null
      if (!data) throw new Error('后端未返回停止结果')
      activeTasks = data.usb_active_tasks
      usbStopped = data.usb_stopped
      usbForced = data.usb_forced
      detail = usbForced
        ? '后端报告 USB 停止未确认'
        : usbStopped ? 'USB 已确认停止' : '后端未确认 USB 已停止'
    } catch (error) {
      detail = error instanceof Error ? error.message : String(error)
    }

    if (usbStopped && !usbForced) {
      // 停止已确认：让后端正常结束，其收尾会释放应用锁。
      this.terminate()
      if (await this.waitForExit(timeoutMs)) {
        return { confirmed: true, forced: false, activeTasks, detail }
      }
      detail = `${detail}；后端进程未在期限内退出`
    }
    this.forceKill()
    const exited = await this.waitForExit(5000)
    return {
      confirmed: false,
      forced: true,
      activeTasks,
      detail: `${detail}${exited ? '' : '；进程退出未确认'}`,
    }
  }

  private async waitForExit(timeoutMs: number): Promise<boolean> {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      if (!this.isRunning) return true
      await delay(100)
    }
    return !this.isRunning
  }

  /** 只向本次启动的进程组发 SIGTERM，不按端口探测或结束其他后端。 */
  terminate(): void {
    this.signal('SIGTERM')
  }

  /** 强制结束本次启动的进程组，仅用于已判定停止未确认的情况。 */
  forceKill(): void {
    const child = this.process
    if (!child || !child.pid) return
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /F /T /PID ${child.pid}`, { stdio: 'ignore' })
      } else {
        try {
          process.kill(-child.pid, 'SIGKILL')
        } catch {
          child.kill('SIGKILL')
        }
      }
    } catch {
      // 进程已退出
    }
  }

  private signal(signal: NodeJS.Signals): void {
    const child = this.process
    if (!child || !child.pid) return
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /T /PID ${child.pid}`, { stdio: 'ignore' })
      } else {
        try {
          process.kill(-child.pid, signal)
        } catch {
          child.kill(signal)
        }
      }
    } catch {
      // 进程已退出
    }
  }

  /** 释放句柄引用；退出流程完成后调用，便于再次激活时重新启动。 */
  reset(): void {
    this.process = null
    this.identity = null
    this.token = null
    this.exited = false
    this.recentErrorLines = []
  }
}
