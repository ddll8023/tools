/** 使用独立沙箱窗口离线打印 Markdown HTML，串行执行并仅写入用户选择的 PDF 路径。 */
import { BrowserWindow, dialog, ipcMain, session, type IpcMainInvokeEvent } from 'electron'
import { randomUUID } from 'node:crypto'
import { rename, rm, writeFile } from 'node:fs/promises'
import * as path from 'node:path'
import type { MarkdownPdfResult, PrintRequest } from './markdown-to-pdf-types'

const SAFE_USER_AGENT = `Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${process.versions.chrome} Safari/537.36 Electron/${process.versions.electron}`
// 文档只通过自定义 https 源提供，避免与真实站点混用来源；其余请求一律拒绝。
const DOCUMENT_URL = 'https://markdown-pdf.invalid/document'
const PRINT_TIMEOUT = 180_000
const MAX_HTML_BYTES = 1024 * 1024 * 1024
const CONTENT_POLICY =
  "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; object-src 'none'"

interface PrintJob {
  id: string
  ownerId: number
  controller: AbortController
  window: BrowserWindow | null
  abortReason?: 'cancelled' | 'failed'
  failureMessage?: string
}

let activeJob: PrintJob | null = null

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** 逐字段校验打印请求，避免渲染进程传入任意结构或超大文档。 */
function isPrintRequest(value: unknown): value is PrintRequest {
  if (!isRecord(value) || !isRecord(value.options)) return false
  const options = value.options
  return typeof value.requestId === 'string' && /^[a-f0-9-]{36}$/.test(value.requestId)
    && typeof value.filename === 'string' && value.filename.length > 0 && value.filename.length <= 200
    && typeof value.html === 'string' && value.html.length > 0
    && Buffer.byteLength(value.html, 'utf8') <= MAX_HTML_BYTES
    && typeof options.landscape === 'boolean' && typeof options.pageNumbers === 'boolean'
    && typeof options.marginMm === 'number' && Number.isInteger(options.marginMm)
    && options.marginMm >= 10 && options.marginMm <= 30
    && typeof options.fontSize === 'number' && Number.isInteger(options.fontSize)
    && options.fontSize >= 8 && options.fontSize <= 20
}

/** 只接受主窗口主框架调用，并校验页面来源，防止其他渲染内容触发本地写盘。 */
function requireOwner(
  event: IpcMainInvokeEvent,
  getWindow: () => BrowserWindow | null,
  trustedUrl: string
): BrowserWindow {
  const owner = getWindow()
  if (!owner || owner.isDestroyed() || !event.senderFrame || event.sender !== owner.webContents
    || event.senderFrame !== owner.webContents.mainFrame) {
    throw new Error('不允许的 PDF 调用来源')
  }
  const current = new URL(event.senderFrame.url)
  current.hash = ''
  current.search = ''
  if (current.href !== new URL(trustedUrl).href) throw new Error('不允许的 PDF 页面来源')
  return owner
}

/** 应用退出、页面离开或用户主动取消时中止当前打印任务。 */
export function cancelMarkdownPdf(): void {
  if (!activeJob) return
  activeJob.abortReason ??= 'cancelled'
  activeJob.controller.abort()
  if (activeJob.window && !activeJob.window.isDestroyed()) activeJob.window.destroy()
}

function failMarkdownPdf(message: string): void {
  if (!activeJob) return
  activeJob.abortReason = 'failed'
  activeJob.failureMessage = message
  activeJob.controller.abort()
  if (activeJob.window && !activeJob.window.isDestroyed()) activeJob.window.destroy()
}

/** 注册打印与取消通道；同一时刻只允许一个任务，避免并发打印争抢内存。 */
export function registerMarkdownPdfIpc(
  getWindow: () => BrowserWindow | null,
  trustedUrl: string
): void {
  ipcMain.handle('markdown-pdf:export', async (event, value: unknown): Promise<MarkdownPdfResult> => {
    const owner = requireOwner(event, getWindow, trustedUrl)
    if (!isPrintRequest(value)) return { status: 'error', message: 'PDF 参数无效或文档超过 1GB' }
    if (activeJob) return { status: 'error', message: '已有 PDF 正在生成，请稍后重试' }
    return exportDocument(owner, value)
  })

  ipcMain.handle('markdown-pdf:cancel', (event, requestId: unknown): void => {
    requireOwner(event, getWindow, trustedUrl)
    if (activeJob?.ownerId === event.sender.id && activeJob.id === requestId) cancelMarkdownPdf()
  })
}

/** 渲染 HTML、打印为 PDF 并原子写入目标路径；任何失败都不破坏已有文件。 */
async function exportDocument(owner: BrowserWindow, request: PrintRequest): Promise<MarkdownPdfResult> {
  const ownerContents = owner.webContents
  const job: PrintJob = {
    id: request.requestId,
    ownerId: ownerContents.id,
    controller: new AbortController(),
    window: null,
  }
  activeJob = job

  const cancel = () => cancelMarkdownPdf()
  const fail = () => failMarkdownPdf('PDF 渲染窗口异常退出，可能是文档过大或内存不足')
  owner.once('closed', cancel)
  ownerContents.once('render-process-gone', fail)

  const printSession = session.fromPartition('markdown-pdf-print', { cache: false })
  printSession.setUserAgent(SAFE_USER_AGENT, 'zh-CN,zh')
  let protocolRegistered = false
  let temporaryPath: string | undefined
  let timer: NodeJS.Timeout | undefined
  let timedOut = false

  try {
    const stem = request.filename.replace(/\.(md|markdown|pdf)$/i, '')
      .replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').slice(0, 120) || 'document'
    const destination = await dialog.showSaveDialog(owner, {
      title: '保存 Markdown PDF',
      defaultPath: `${stem}.pdf`,
      filters: [{ name: 'PDF', extensions: ['pdf'] }],
      properties: ['showOverwriteConfirmation', 'createDirectory'],
    })
    if (destination.canceled || !destination.filePath || job.abortReason === 'cancelled') {
      return { status: 'cancelled' }
    }
    if (job.abortReason === 'failed') {
      return { status: 'error', message: job.failureMessage ?? 'PDF 渲染窗口异常退出' }
    }
    // 不在对话框确认后改写路径，避免绕过针对已有文件的覆盖确认。
    const outputPath = destination.filePath
    timer = setTimeout(() => { timedOut = true; cancel() }, PRINT_TIMEOUT)

    printSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
    printSession.setPermissionCheckHandler(() => false)
    printSession.protocol.handle('https', (incoming) => {
      if (incoming.url !== DOCUMENT_URL) return new Response(null, { status: 403 })
      // Electron 43 的 protocol.handle 对字符串响应体的 Unicode 处理存在 ByteString 兼容问题；先编码成 UTF-8 字节。
      return new Response(Buffer.from(request.html, 'utf8'), {
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          'Content-Security-Policy': CONTENT_POLICY,
          'Cache-Control': 'no-store',
        },
      })
    })
    protocolRegistered = true
    // 文档在内存中提供；图片只允许 Data URL，不放行 localhost、file 或其他网络地址。
    printSession.webRequest.onBeforeRequest((details, callback) => {
      const allowed = (details.url === DOCUMENT_URL && details.resourceType === 'mainFrame')
        || (details.url.startsWith('data:image/') && details.resourceType === 'image')
      callback({ cancel: !allowed })
    })

    job.window = new BrowserWindow({
      show: false,
      width: request.options.landscape ? 1123 : 794,
      height: 900,
      webPreferences: {
        session: printSession,
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        webSecurity: true,
        webviewTag: false,
        spellcheck: false,
        backgroundThrottling: false,
      },
    })
    const contents = job.window.webContents
    contents.setWindowOpenHandler(() => ({ action: 'deny' }))
    contents.on('will-navigate', (event) => {
      if (event.url !== DOCUMENT_URL) event.preventDefault()
    })
    contents.on('will-frame-navigate', (event) => {
      if (event.url !== DOCUMENT_URL) event.preventDefault()
    })
    contents.on('will-attach-webview', (event) => event.preventDefault())
    contents.on('render-process-gone', fail)

    const cancelled = new Promise<never>((_resolve, reject) => {
      job.controller.signal.addEventListener('abort', () => reject(new Error('打印已中止')), { once: true })
    })
    const generate = async (): Promise<Buffer> => {
      await contents.loadURL(DOCUMENT_URL)
      // 此脚本是主进程固定代码，用户文档脚本由响应头 CSP 禁止执行。
      await contents.executeJavaScript(`(async () => {
        await document.fonts.ready;
        await Promise.all(Array.from(document.images, image => image.decode()));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      })()`)
      const margin = request.options.marginMm / 25.4
      return contents.printToPDF({
        pageSize: 'A4',
        landscape: request.options.landscape,
        printBackground: true,
        preferCSSPageSize: false,
        margins: { top: margin, bottom: margin, left: margin, right: margin },
        displayHeaderFooter: request.options.pageNumbers,
        headerTemplate: '<span></span>',
        footerTemplate: '<div style="font-size:9px;width:100%;text-align:center;color:#666"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
      })
    }

    const pdf = await Promise.race([generate(), cancelled])
    clearTimeout(timer)
    if (job.abortReason === 'failed') {
      return { status: 'error', message: job.failureMessage ?? 'PDF 渲染窗口异常退出' }
    }
    if (job.controller.signal.aborted) return { status: 'cancelled' }
    if (pdf.length < 5 || pdf.subarray(0, 5).toString('ascii') !== '%PDF-') throw new Error('无效 PDF 输出')

    temporaryPath = path.join(path.dirname(outputPath), `.${path.basename(outputPath)}.${randomUUID()}.tmp`)
    await writeFile(temporaryPath, pdf, { flag: 'wx' })
    if (job.abortReason === 'failed') {
      return { status: 'error', message: job.failureMessage ?? 'PDF 渲染窗口异常退出' }
    }
    if (job.controller.signal.aborted) return { status: 'cancelled' }
    // 先写入同目录临时文件，成功后原子替换，避免失败时破坏已有 PDF。
    await rename(temporaryPath, outputPath)
    temporaryPath = undefined
    return { status: 'saved', filename: path.basename(outputPath) }
  } catch {
    if (timedOut) return { status: 'error', message: 'PDF 排版超时，请减少图片或拆分文档' }
    if (job.abortReason === 'failed') {
      return { status: 'error', message: job.failureMessage ?? 'PDF 渲染窗口异常退出' }
    }
    if (job.controller.signal.aborted) return { status: 'cancelled' }
    return { status: 'error', message: 'PDF 生成或保存失败，请检查文档和目标目录权限后重试' }
  } finally {
    clearTimeout(timer)
    owner.removeListener('closed', cancel)
    ownerContents.removeListener('render-process-gone', fail)
    if (job.window && !job.window.isDestroyed()) {
      job.window.webContents.removeListener('render-process-gone', fail)
      job.window.destroy()
    }
    if (protocolRegistered) printSession.protocol.unhandle('https')
    printSession.webRequest.onBeforeRequest(null)
    if (temporaryPath) await rm(temporaryPath, { force: true }).catch(() => undefined)
    if (activeJob === job) activeJob = null
  }
}
