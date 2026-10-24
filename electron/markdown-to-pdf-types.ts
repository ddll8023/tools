/** Markdown PDF 打印通道的请求与结果契约，主进程与 preload 共用。 */
export interface MarkdownPdfOptions {
  landscape: boolean
  marginMm: number
  fontSize: number
  pageNumbers: boolean
}

export interface PrintRequest {
  requestId: string
  filename: string
  html: string
  options: MarkdownPdfOptions
}

export type MarkdownPdfResult =
  | { status: 'saved'; filename: string }
  | { status: 'cancelled' }
  | { status: 'error'; message: string }
