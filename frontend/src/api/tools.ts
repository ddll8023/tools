/**
 * 工具 API
 * 功能描述：PDF 转 Markdown 等工具的后端 API 调用
 */

import type { ApiResponse } from '@/types/tool'

const API_BASE = 'http://127.0.0.1:4740'

export interface ConvertResponse {
  task_id: string
  filename: string
  page_count?: number
}

export interface PdfToWordConvertResponse {
  task_id: string
  filename: string
  output_filename: string
  page_count: number
  engine: 'pdf2docx'
  warnings: string[]
}

export interface PreviewResponse {
  markdown_content: string
  page_count: number
  table_count: number
  image_count: number
}

export interface EpubConvertResponse {
  task_id: string
  filename: string
  chapter_count: number
  image_count: number
}

export interface EpubPreviewResponse {
  markdown_content: string
  chapter_count: number
  table_count: number
  image_count: number
  filename: string
}

export interface GetProgressResponse {
  progress: number
  stage: string
}

export interface ToolItem {
  id: string
  name: string
  path: string
  display_name: string
  description: string
  icon: string
  available: boolean
}

/**
 * 解析 Content-Disposition 中的文件名。
 * 优先处理 RFC 5987 的 filename*=utf-8''（中文文件名时 FastAPI/Starlette 输出此格式），
 * 失败时回退到普通 filename= 或默认名。
 */
function parseContentDispositionFilename(
  disposition: string | null,
  fallback: string,
): string {
  if (!disposition) return fallback
  const star = /filename\*=utf-8''([^;]+)/i.exec(disposition)
  if (star) {
    try {
      return decodeURIComponent(star[1].trim())
    } catch {
      return fallback
    }
  }
  const plain =
    /filename="([^"]*)"/i.exec(disposition) ||
    /filename=([^;]+)/i.exec(disposition)
  if (plain) return plain[1].trim()
  return fallback
}

export async function fetchToolList(): Promise<ToolItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/tools/list`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  const json: ApiResponse<{ tools: ToolItem[] }> = await res.json()

  if (json.code !== 0) {
    throw new Error(json.message || '获取工具列表失败')
  }

  return json.data?.tools ?? []
}

export async function convertPdf(file: File, deepParse = false): Promise<ConvertResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('deep_parse', String(deepParse))

  const res = await fetch(`${API_BASE}/api/v1/tools/pdf-to-markdown/convert`, {
    method: 'POST',
    body: formData,
  })

  const json: ApiResponse<ConvertResponse> = await res.json()

  if (json.code !== 0) {
    throw new Error(json.message || '转换失败')
  }

  return json.data as ConvertResponse
}

export async function getProgress(taskId: string): Promise<GetProgressResponse> {
  const res = await fetch(`${API_BASE}/api/v1/tools/pdf-to-markdown/progress`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  })

  const json: ApiResponse<GetProgressResponse> = await res.json()

  if (json.code !== 0) {
    throw new Error(json.message || '获取进度失败')
  }

  return json.data as GetProgressResponse
}

export async function getPreview(taskId: string): Promise<PreviewResponse> {
  const res = await fetch(`${API_BASE}/api/v1/tools/pdf-to-markdown/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  })

  const json: ApiResponse<PreviewResponse> = await res.json()

  if (json.code !== 0) {
    throw new Error(json.message || '获取预览失败')
  }

  return json.data as PreviewResponse
}

export async function downloadMd(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/tools/pdf-to-markdown/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  })

  if (!res.ok) {
    const json = await res.json()
    throw new Error(json.message || '下载失败')
  }

  const disposition = res.headers.get('content-disposition')
  const filename = parseContentDispositionFilename(disposition, `${taskId}.md`)

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()

  URL.revokeObjectURL(url)
}

/* ════════════════════════════════════════
   PDF 转 Word API
   ════════════════════════════════════════ */

export async function convertPdfToWord(file: File): Promise<PdfToWordConvertResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${API_BASE}/api/v1/tools/pdf-to-word/convert`, {
    method: 'POST',
    body: formData,
  })

  const json: ApiResponse<PdfToWordConvertResponse> = await res.json()
  if (json.code !== 0) {
    throw new Error(json.message || '转换失败')
  }

  return json.data as PdfToWordConvertResponse
}

export async function downloadWord(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/tools/pdf-to-word/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  })

  const contentType = res.headers.get('content-type') || ''
  if (!res.ok || contentType.includes('application/json')) {
    if (contentType.includes('application/json')) {
      const json: ApiResponse<null> = await res.json()
      throw new Error(json.message || '下载失败')
    }
    throw new Error(`下载失败（HTTP ${res.status}）`)
  }

  const disposition = res.headers.get('content-disposition')
  const filename = parseContentDispositionFilename(disposition, `${taskId}.docx`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/* ════════════════════════════════════════
   EPUB 转 Markdown API
   ════════════════════════════════════════ */

export async function convertEpub(file: File): Promise<EpubConvertResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${API_BASE}/api/v1/tools/epub-to-markdown/convert`, {
    method: 'POST',
    body: formData,
  })
  const json: ApiResponse<EpubConvertResponse> = await res.json()
  if (json.code !== 0) {
    throw new Error(json.message || '转换失败')
  }
  return json.data as EpubConvertResponse
}

export async function getEpubPreview(taskId: string): Promise<EpubPreviewResponse> {
  const res = await fetch(`${API_BASE}/api/v1/tools/epub-to-markdown/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  })
  const json: ApiResponse<EpubPreviewResponse> = await res.json()
  if (json.code !== 0) {
    throw new Error(json.message || '获取预览失败')
  }
  return json.data as EpubPreviewResponse
}

export async function downloadEpub(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/tools/epub-to-markdown/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  })
  if (!res.ok) {
    const contentType = res.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      const json: ApiResponse<null> = await res.json()
      throw new Error(json.message || '下载失败')
    }
    throw new Error(`下载失败（HTTP ${res.status}）`)
  }

  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    const json: ApiResponse<null> = await res.json()
    throw new Error(json.message || '下载失败')
  }

  const disposition = res.headers.get('content-disposition')
  const filename = parseContentDispositionFilename(disposition, `${taskId}.zip`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/* ════════════════════════════════════════
   Word 转 PDF API
   ════════════════════════════════════════ */

export async function convertWord(file: File): Promise<ConvertResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${API_BASE}/api/v1/tools/word-to-pdf/convert`, {
    method: 'POST',
    body: formData,
  })

  const json: ApiResponse<ConvertResponse> = await res.json()

  if (json.code !== 0) {
    throw new Error(json.message || '转换失败')
  }

  return json.data as ConvertResponse
}

export async function downloadPdf(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/tools/word-to-pdf/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  })

  if (!res.ok) {
    const json = await res.json()
    throw new Error(json.message || '下载失败')
  }

  const disposition = res.headers.get('content-disposition')
  const filename = parseContentDispositionFilename(disposition, `${taskId}.pdf`)

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()

  URL.revokeObjectURL(url)
}

/* ════════════════════════════════════════
   图片格式转换 API
   ════════════════════════════════════════ */

export interface ImageConvertFileItem {
  original_name: string
  converted_name: string
  file_size: number
  original_format: string
  index: number
}

export interface ImageConvertResponse {
  task_id: string
  files: ImageConvertFileItem[]
  is_batch: boolean
}

export async function convertImages(
  files: File[],
  targetFormat: string,
  quality = 85,
): Promise<ImageConvertResponse> {
  const formData = new FormData()
  files.forEach((f) => formData.append('files', f))
  formData.append('target_format', targetFormat)
  formData.append('quality', String(quality))

  const res = await fetch(`${API_BASE}/api/v1/tools/image-converter/convert`, {
    method: 'POST',
    body: formData,
  })

  const json: ApiResponse<ImageConvertResponse> = await res.json()

  if (json.code !== 0) {
    throw new Error(json.message || '转换失败')
  }

  return json.data as ImageConvertResponse
}

export async function downloadConvertedFile(taskId: string, fileIndex: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/tools/image-converter/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId, file_index: fileIndex }),
  })

  if (!res.ok) {
    const json = await res.json()
    throw new Error(json.message || '下载失败')
  }

  const disposition = res.headers.get('content-disposition')
  const filename = parseContentDispositionFilename(disposition, `${taskId}_${fileIndex}.png`)

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()

  URL.revokeObjectURL(url)
}

export async function downloadAllConverted(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/tools/image-converter/download-all`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  })

  if (!res.ok) {
    const json = await res.json()
    throw new Error(json.message || '下载失败')
  }

  const disposition = res.headers.get('content-disposition')
  const filename = parseContentDispositionFilename(disposition, `图片转换_${taskId}.zip`)

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()

  URL.revokeObjectURL(url)
}
