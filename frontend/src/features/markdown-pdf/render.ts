/** 管理可取消的渲染 Worker、HTML 清洗以及预览/导出共用的文档模板。 */
import DOMPurify from 'dompurify'
import printCss from './print.css?raw'
import type { PdfDocument, PdfOptions, PreparedMarkdown, RenderedMarkdown } from './types'

export function renderMarkdown(source: PreparedMarkdown, signal: AbortSignal): Promise<PdfDocument> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('已取消', 'AbortError')); return }
    const worker = new Worker(new URL('./render.worker.ts', import.meta.url), { type: 'module' })
    const stop = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', cancel)
      worker.terminate()
    }
    const cancel = () => { stop(); reject(new DOMException('已取消', 'AbortError')) }
    const timer = window.setTimeout(() => { stop(); reject(new Error('文档渲染超时，请减少公式或拆分文档')) }, 180_000)
    signal.addEventListener('abort', cancel, { once: true })
    worker.onerror = () => { stop(); reject(new Error('文档渲染引擎加载失败，请重试')) }
    worker.onmessage = (event: MessageEvent<
      { ok: true; result: RenderedMarkdown } | { ok: false; message: string }
    >) => {
      stop()
      if (!event.data.ok) { reject(new Error(event.data.message)); return }
      try {
        // 原始 HTML 已被转义；仍对最终输出清洗，覆盖解析库及 SVG 组合边界。
        const html = DOMPurify.sanitize(event.data.result.html, {
          USE_PROFILES: { html: true, svg: true },
          FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'foreignObject', 'use', 'image', 'form', 'input', 'button'],
          FORBID_ATTR: ['srcset', 'target'],
          ALLOW_DATA_ATTR: false,
        })
        // 预览禁用链接导航；PDF 保留链接，两者内容和排版样式保持一致。
        const previewHtml = DOMPurify.sanitize(html, {
          USE_PROFILES: { html: true, svg: true }, FORBID_ATTR: ['href', 'xlink:href'],
        })
        resolve({ html, previewHtml, warnings: event.data.result.warnings })
      } catch { reject(new Error('文档安全处理失败')) }
    }
    try { worker.postMessage(source) } catch {
      stop()
      reject(new Error('文档过大或无法传入渲染引擎'))
    }
  })
}

export function buildPdfHtml(content: string, options: PdfOptions): string {
  const imageHeight = (options.landscape ? 210 : 297) - options.marginMm * 2 - 5
  const policy = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; base-uri 'none'; form-action 'none'"
  return `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><style>${printCss}\n:root { --document-font-size: ${options.fontSize}pt; --document-margin: ${options.marginMm}mm; --document-image-height: ${imageHeight}mm; }</style></head><body><article class="document">${content}</article></body></html>`
}
