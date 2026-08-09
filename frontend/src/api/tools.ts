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

export interface QrCodeResponse {
  image_data_url: string
  filename: string
  source_type: 'text' | 'file'
  payload_size: number
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
  unavailable_reason?: string | null
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

export async function generateQrCode(
  content?: string,
  file?: File,
): Promise<QrCodeResponse> {
  if ((content === undefined) === (file === undefined)) {
    throw new Error('请提供文本或文件，且只能选择一种内容')
  }

  const formData = new FormData()
  if (file !== undefined) {
    formData.append('file', file)
  } else {
    formData.append('content', content ?? '')
  }

  const res = await fetch(`${API_BASE}/api/v1/tools/qr-code/generate`, {
    method: 'POST',
    body: formData,
  })
  const json: ApiResponse<QrCodeResponse> = await res.json()

  if (json.code !== 0) {
    throw new Error(json.message || '二维码生成失败')
  }

  return json.data as QrCodeResponse
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

/* ════════════════════════════════════════
   证件照 API
   ════════════════════════════════════════ */

export interface IdPhotoTemplateItem {
  id: string
  label: string
  description: string
  width: number | null
  height: number | null
  width_mm: number | null
  height_mm: number | null
  is_custom: boolean
}

export interface IdPhotoFileItem {
  kind: 'standard' | 'hd' | 'layout'
  filename: string
  file_size: number
  index: number
}

export interface IdPhotoResponse {
  task_id: string
  template_id: string
  template_name: string
  width: number
  height: number
  background_color: string
  model: string
  quality: number
  dpi: number
  max_file_size_kb: number | null
  files: IdPhotoFileItem[]
}

export interface IdPhotoRenderParams {
  task_id: string
  template_id: string
  width: number | null
  height: number | null
  background_color: string
  crop_scale: number
  offset_x: number
  offset_y: number
  include_layout: boolean
  quality: number
  dpi: number
  max_file_size_kb: number | null
}

export async function fetchIdPhotoTemplates(): Promise<IdPhotoTemplateItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/tools/id-photo/templates`, {
    method: 'POST',
  })
  const json: ApiResponse<IdPhotoTemplateItem[]> = await res.json()
  if (json.code !== 0) {
    throw new Error(json.message || '照片规格加载失败')
  }
  return json.data || []
}

export async function processIdPhoto(
  file: File,
  templateId: string,
  width?: number,
  height?: number,
  backgroundColor = 'white',
  includeLayout = true,
  quality = 95,
  dpi = 300,
  maxFileSizeKb?: number,
): Promise<IdPhotoResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('template_id', templateId)
  if (width !== undefined) formData.append('width', String(width))
  if (height !== undefined) formData.append('height', String(height))
  formData.append('background_color', backgroundColor)
  formData.append('include_layout', String(includeLayout))
  formData.append('quality', String(quality))
  formData.append('dpi', String(dpi))
  if (maxFileSizeKb !== undefined) {
    formData.append('max_file_size_kb', String(maxFileSizeKb))
  }

  const res = await fetch(`${API_BASE}/api/v1/tools/id-photo/process`, {
    method: 'POST',
    body: formData,
  })
  const json: ApiResponse<IdPhotoResponse> = await res.json()
  if (json.code !== 0) {
    throw new Error(json.message || '证件照处理失败')
  }
  return json.data as IdPhotoResponse
}

export async function renderIdPhoto(
  params: IdPhotoRenderParams,
): Promise<IdPhotoResponse> {
  const res = await fetch(`${API_BASE}/api/v1/tools/id-photo/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  const json: ApiResponse<IdPhotoResponse> = await res.json()
  if (json.code !== 0) {
    throw new Error(json.message || '证件照重新渲染失败')
  }
  return json.data as IdPhotoResponse
}

export async function fetchIdPhotoFile(
  taskId: string,
  fileIndex: number,
): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/v1/tools/id-photo/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId, file_index: fileIndex }),
  })

  const contentType = res.headers.get('content-type') || ''
  if (!res.ok || contentType.includes('application/json')) {
    if (contentType.includes('application/json')) {
      const json: ApiResponse<null> = await res.json()
      throw new Error(json.message || '文件读取失败')
    }
    throw new Error(`文件读取失败（HTTP ${res.status}）`)
  }
  return res.blob()
}

export async function downloadIdPhotoFile(
  taskId: string,
  fileIndex: number,
  fallbackFilename = `${taskId}_${fileIndex}.jpg`,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/tools/id-photo/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId, file_index: fileIndex }),
  })

  const contentType = res.headers.get('content-type') || ''
  if (!res.ok || contentType.includes('application/json')) {
    if (contentType.includes('application/json')) {
      const json: ApiResponse<null> = await res.json()
      throw new Error(json.message || '下载失败')
    }
    throw new Error(`下载失败（HTTP ${res.status}）`)
  }

  const filename = parseContentDispositionFilename(
    res.headers.get('content-disposition'),
    fallbackFilename,
  )
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
