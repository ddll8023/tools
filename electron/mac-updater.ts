/**
 * macOS 免签名自定义更新器（方案 B）。
 *
 * 未配置 Apple Developer ID 证书时，Squirrel.Mac/electron-updater 会在
 * “重启安装”阶段因代码签名校验失败而拒绝未签名产物，因此 macOS 平台
 * 走独立更新链路：GitHub Releases API 检查 → HTTPS 流式下载 ZIP 并
 * 校验 SHA-512 → 由 update-helper（ELECTRON_RUN_AS_NODE 运行的纯 Node
 * 脚本）完成解压、校验、原子替换与重启。
 *
 * Windows/Linux 仍使用 electron-updater，见 updater.ts。
 */
import { app } from 'electron'
import { spawn } from 'child_process'
import * as crypto from 'crypto'
import * as fs from 'fs'
import * as http from 'http'
import * as https from 'https'
import * as path from 'path'
import { broadcast, getCurrentStatus } from './update-state'
import type { UpdateCommandResult } from './update-types'

const OWNER = 'ddll8023'
const REPO = 'tools'
const RELEASES_API = `https://api.github.com/repos/${OWNER}/${REPO}/releases/latest`
const RELEASE_DOWNLOAD = `https://github.com/${OWNER}/${REPO}/releases/download`
const ARCH_SUFFIX = process.arch === 'arm64' ? 'arm64' : 'x64'
const RESULT_FILE = () => path.join(app.getPath('userData'), 'update-result.json')
const UPDATE_DIR = () => path.join(app.getPath('userData'), 'update')
const HELPER_NAME = 'update-helper.js'
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000

interface ReleaseAsset {
  name: string
  url: string
}

interface PendingUpdate {
  version: string
  zipName: string
  downloadUrl: string
  sha512?: string
  sha512Source: 'latest-mac.yml' | 'none'
}

let initialized = false
let pendingUpdate: PendingUpdate | null = null
let checkPromise: Promise<UpdateCommandResult> | null = null
let installing = false

function versionOf(tag: string): string {
  return tag.replace(/^v/, '')
}

function isZipDownloadable(name: string, version: string): boolean {
  return name === `toolbox-${version}-mac-${ARCH_SUFFIX}.zip`
}

/** 简单 semver 比较（x.y.z，忽略预发布段），a > b 返回正数 */
export function compareVersions(a: string, b: string): number {
  const parse = (value: string) =>
    value.split('.').map((part) => {
      const num = parseInt(part, 10)
      return Number.isNaN(num) ? 0 : num
    })
  const va = parse(a)
  const vb = parse(b)
  for (let i = 0; i < Math.max(va.length, vb.length); i++) {
    const diff = (va[i] ?? 0) - (vb[i] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}

/** 带重定向跟随的 GET 请求（GitHub 资产下载会 302 到对象存储） */
function get(url: string): Promise<{ status: number; body: Buffer }> {
  return new Promise((resolve, reject) => {
    const follow = (target: string, redirects: number) => {
      const client = target.startsWith('https:') ? https : http
      const request = client.get(target, { headers: { 'User-Agent': 'toolbox-desktop-updater' } }, (response) => {
        const status = response.statusCode ?? 0
        const location = response.headers.location
        if (status >= 300 && status < 400 && location) {
          response.resume()
          if (redirects >= 5) {
            reject(new Error(`重定向次数过多: ${target}`))
            return
          }
          follow(new URL(location, target).toString(), redirects + 1)
          return
        }
        const chunks: Buffer[] = []
        response.on('data', (chunk: Buffer) => chunks.push(chunk))
        response.on('end', () => {
          resolve({ status, body: Buffer.concat(chunks) })
        })
      })
      request.on('error', reject)
      request.setTimeout(30000, () => {
        request.destroy(new Error(`请求超时: ${target}`))
      })
    }
    follow(url, 0)
  })
}

/** 流式下载（边下载边回调，返回响应头与状态码；非 200 时不触发数据回调） */
function streamDownload(
  url: string,
  onChunk: (chunk: Buffer, total: number) => void,
): Promise<{ status: number; headers: http.IncomingHttpHeaders }> {
  return new Promise((resolve, reject) => {
    const follow = (target: string, redirects: number) => {
      const client = target.startsWith('https:') ? https : http
      const request = client.get(target, { headers: { 'User-Agent': 'toolbox-desktop-updater' } }, (response) => {
        const status = response.statusCode ?? 0
        const location = response.headers.location
        if (status >= 300 && status < 400 && location) {
          response.resume()
          if (redirects >= 5) {
            reject(new Error(`重定向次数过多: ${target}`))
            return
          }
          follow(new URL(location, target).toString(), redirects + 1)
          return
        }
        const total = Number(response.headers['content-length'] || 0)
        if (status !== 200) {
          response.resume()
          resolve({ status, headers: response.headers })
          return
        }
        response.on('data', (chunk: Buffer) => {
          try {
            onChunk(chunk, total)
          } catch (error) {
            request.destroy(error as Error)
          }
        })
        response.on('end', () => resolve({ status, headers: response.headers }))
        response.on('error', reject)
      })
      request.on('error', reject)
      request.setTimeout(30000, () => {
        request.destroy(new Error(`请求超时: ${target}`))
      })
    }
    follow(url, 0)
  })
}

/** 从 GitHub API 获取最新 Release 的 tag 与资产列表 */
async function fetchLatestRelease(): Promise<{ version: string; assets: ReleaseAsset[] }> {
  const response = await get(RELEASES_API)
  if (response.status !== 200) {
    throw new Error(`GitHub Releases API 返回 ${response.status}`)
  }
  const data = JSON.parse(response.body.toString('utf8')) as {
    tag_name?: string
    assets?: Array<{ name: string; browser_download_url: string }>
  }
  if (!data.tag_name) {
    throw new Error('GitHub Releases 响应缺少 tag_name')
  }
  return {
    version: versionOf(data.tag_name),
    assets: (data.assets ?? []).map((asset) => ({ name: asset.name, url: asset.browser_download_url })),
  }
}

/** 解析 latest-mac.yml，取出指定 zip 的 SHA-512（base64） */
function parseSha512FromMeta(ymlText: string, zipName: string): string | undefined {
  const lines = ymlText.split('\n')
  let currentUrl: string | null = null
  for (const line of lines) {
    const urlMatch = line.match(/^\s*-\s*url:\s*(\S+)/)
    if (urlMatch) {
      currentUrl = urlMatch[1]
      continue
    }
    if (currentUrl !== zipName) continue
    const shaMatch = line.match(/^\s*sha512:\s*(\S+)/)
    if (shaMatch) {
      const sha512 = shaMatch[1].trim()
      if (/^[A-Za-z0-9+/=]+$/.test(sha512)) return sha512
    }
  }
  return undefined
}

async function resolveSha512(pending: PendingUpdate): Promise<void> {
  try {
    const metaUrl = `${RELEASE_DOWNLOAD}/v${pending.version}/latest-mac.yml`
    const response = await get(metaUrl)
    if (response.status === 200) {
      const sha512 = parseSha512FromMeta(response.body.toString('utf8'), pending.zipName)
      if (sha512) {
        pending.sha512 = sha512
        pending.sha512Source = 'latest-mac.yml'
        return
      }
    }
  } catch (error) {
    console.warn('[mac-updater] 获取 latest-mac.yml 失败:', error instanceof Error ? error.message : error)
  }
  // 取不到校验和：降级为仅 HTTPS 完整性，并记录原因
  pending.sha512 = undefined
  pending.sha512Source = 'none'
  console.warn('[mac-updater] 未取得 SHA-512 校验和（latest-mac.yml 缺失或格式异常），降级为仅 HTTPS 完整性校验')
}

function cleanExpiredFiles() {
  const dir = UPDATE_DIR()
  if (!fs.existsSync(dir)) return
  const now = Date.now()
  for (const name of fs.readdirSync(dir)) {
    if (!/^toolbox-.*\.zip$/.test(name) && !name.startsWith('stage-') && !name.startsWith('backup-')) continue
    const fullPath = path.join(dir, name)
    try {
      const stat = fs.statSync(fullPath)
      if (now - stat.mtimeMs > RETENTION_MS) {
        fs.rmSync(fullPath, { recursive: true, force: true })
        console.log(`[mac-updater] 已清理过期更新文件: ${name}`)
      }
    } catch {
      // 文件可能已被删除，忽略
    }
  }
}

function consumeResultFile() {
  try {
    if (!fs.existsSync(RESULT_FILE())) return
    const payload = JSON.parse(fs.readFileSync(RESULT_FILE(), 'utf8')) as {
      state?: string
      message?: string
      version?: string
    }
    if (payload.state === 'failed') {
      broadcast({ state: 'error', message: `上次更新安装失败：${payload.message ?? '未知原因'}` })
    } else if (payload.state === 'success') {
      console.log(`[mac-updater] 上次更新安装成功（${payload.version ?? '未知版本'}）`)
    }
    fs.rmSync(RESULT_FILE(), { force: true })
  } catch {
    fs.rmSync(RESULT_FILE(), { force: true })
  }
}

/** 流式下载 ZIP 并实时计算 SHA-512 */
async function downloadUpdate(pending: PendingUpdate): Promise<boolean> {
  const dir = UPDATE_DIR()
  fs.mkdirSync(dir, { recursive: true })
  const zipPath = path.join(dir, pending.zipName)
  const hash = crypto.createHash('sha512')
  let received = 0
  let lastChunkTime = Date.now()
  let lastChunkBytes = 0
  let bytesPerSecond = 0
  let lastBroadcastTime = 0

  broadcast({ state: 'downloading', version: pending.version, percent: 0, bytesPerSecond: 0 })

  // 先写临时文件，全部完成后再改名为正式文件名，避免残留半个包
  const tmpPath = `${zipPath}.part`
  let fd: number | null = null
  try {
    fd = fs.openSync(tmpPath, 'w')
  } catch (error) {
    broadcast({ state: 'error', message: '无法创建更新包文件' })
    return false
  }

  const response = await streamDownload(pending.downloadUrl, (chunk, total) => {
    received += chunk.length
    hash.update(chunk)
    fs.writeSync(fd as number, chunk)
    const now = Date.now()
    const elapsed = (now - lastChunkTime) / 1000
    if (elapsed >= 1) {
      bytesPerSecond = Math.round((received - lastChunkBytes) / elapsed)
      lastChunkTime = now
      lastChunkBytes = received
    }
    // 节流广播，避免高频 IPC 影响下载性能
    if (now - lastBroadcastTime >= 200 || received === 0) {
      lastBroadcastTime = now
      const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((received / total) * 100))) : 0
      broadcast({ state: 'downloading', version: pending.version, percent, bytesPerSecond })
    }
  })

  if (fd !== null) {
    fs.closeSync(fd)
    fd = null
  }
  if (response.status !== 200) {
    fs.rmSync(tmpPath, { force: true })
    broadcast({ state: 'error', message: '更新包下载失败' })
    return false
  }
  if (received === 0) {
    fs.rmSync(tmpPath, { force: true })
    broadcast({ state: 'error', message: '更新包内容为空' })
    return false
  }

  // 校验 SHA-512（仅在元数据可用时）
  if (pending.sha512) {
    const actual = hash.digest('base64')
    if (actual !== pending.sha512) {
      console.error(`[mac-updater] SHA-512 校验失败: 期望 ${pending.sha512}，实际 ${actual}`)
      broadcast({ state: 'error', message: '更新包校验失败，已停止安装' })
      fs.rmSync(tmpPath, { force: true })
      return false
    }
    console.log('[mac-updater] SHA-512 校验通过')
  }

  fs.renameSync(tmpPath, zipPath)
  broadcast({ state: 'downloaded', version: pending.version })
  return true
}

function spawnHelper() {
  const helperPath = path.join(process.resourcesPath, HELPER_NAME)
  if (!fs.existsSync(helperPath)) {
    broadcast({ state: 'error', message: '更新安装器缺失，无法安装' })
    return false
  }
  const appRoot = path.resolve(path.dirname(process.execPath), '..', '..')
  const pending = pendingUpdate
  if (!pending) return false
  const zipPath = path.join(UPDATE_DIR(), pending.zipName)
  const args = [
    '--zip', zipPath,
    '--target', appRoot,
    '--version', pending.version,
    '--result', RESULT_FILE(),
    '--wait-pid', String(process.pid),
  ]
  installing = true
  const child = spawn(process.execPath, args, {
    detached: true,
    stdio: 'ignore',
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
  })
  child.unref()
  console.log(`[mac-updater] 已启动安装 helper，准备安装 ${pending.version}`)
  return true
}

/** 用户退出应用时自动安装已下载的版本（对应 electron-updater 的 autoInstallOnAppQuit） */
export function maybeInstallOnQuit() {
  if (installing || process.platform !== 'darwin') return
  const status = getCurrentStatus()
  if (status.state !== 'downloaded') return
  spawnHelper()
}

export function checkForUpdates(): Promise<UpdateCommandResult> {
  if (checkPromise) return checkPromise

  broadcast({ state: 'checking' })
  const request = (async (): Promise<UpdateCommandResult> => {
    try {
      cleanExpiredFiles()
      const latest = await fetchLatestRelease()
      const currentVersion = app.getVersion()
      if (compareVersions(latest.version, currentVersion) <= 0) {
        broadcast({ state: 'idle' })
        return { ok: true }
      }

      const asset = latest.assets.find((item) => isZipDownloadable(item.name, latest.version))
      if (!asset) {
        broadcast({ state: 'idle' })
        console.warn(`[mac-updater] Release ${latest.version} 缺少 ${ARCH_SUFFIX} ZIP 资产`)
        return { ok: true }
      }

      const pending: PendingUpdate = {
        version: latest.version,
        zipName: asset.name,
        downloadUrl: asset.url,
        sha512Source: 'none',
      }
      pendingUpdate = pending
      await resolveSha512(pending)
      broadcast({ state: 'available', version: pending.version })

      const downloaded = await downloadUpdate(pending)
      return { ok: downloaded }
    } catch (error) {
      console.error('[mac-updater] 更新检查失败:', error instanceof Error ? error.message : error)
      broadcast({ state: 'error', message: '更新检查失败，请稍后重试' })
      return { ok: false, error: '更新检查失败' }
    }
  })()

  checkPromise = request.finally(() => {
    checkPromise = null
  })
  return checkPromise
}

export function quitAndInstall(): UpdateCommandResult {
  if (getCurrentStatus().state !== 'downloaded' || !pendingUpdate) {
    return { ok: false, error: '当前没有可安装的更新' }
  }
  if (!spawnHelper()) {
    return { ok: false, error: '无法启动更新安装器' }
  }
  app.quit()
  return { ok: true }
}

export function initializeMacUpdater() {
  if (initialized) return
  initialized = true
  consumeResultFile()
  // 不阻塞首屏和后端启动，应用打开后再异步检查。
  setTimeout(() => {
    void checkForUpdates()
  }, 5000)
}
