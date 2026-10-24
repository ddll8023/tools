/**
 * Markdown 转 PDF 的来源准备：桌面端读取本地文件与图片，浏览器端直读上传文件。
 * 只产出渲染所需的 Markdown 文本与图片 Data URL，不包含排版或打印逻辑。
 */
import type { PreparedMarkdown } from './types'

const MAX_ARCHIVE_MEMBERS = 4096
const MAX_ARCHIVE_UNPACKED_BYTES = 1024 * 1024 * 1024
const MARKDOWN_EXTENSIONS = ['.md', '.markdown']
// 与主进程和渲染进程保持同一白名单：只接受浏览器可直接解码的位图格式。
const IMAGE_MIME: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
}
const IMAGE_PATTERN = /!\[[^\]]*\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+["'][^"']*["'])?\s*\)/g

/** 中央目录条目：data 为原始字节，compressed 标记是否需要 deflate 解压。 */
interface ArchiveEntry {
  name: string
  data: Uint8Array
  compressed: boolean
}

/** 读取浏览器上传的单个 Markdown 文件。 */
async function readUploadedMarkdown(file: File): Promise<string> {
  const text = await file.text()
  return text.replace(/^\uFEFF/, '')
}

/** 读取 EOCD 记录定位中央目录，只支持非加密的 store/deflate 条目。 */
function readZipDirectory(buffer: ArrayBuffer): ArchiveEntry[] {
  const view = new DataView(buffer)
  const bytes = new Uint8Array(buffer)
  let eocd = -1
  const searchStart = Math.max(0, bytes.length - 0xffff - 22)
  for (let offset = bytes.length - 22; offset >= searchStart; offset--) {
    if (view.getUint32(offset, true) === 0x06054b50) { eocd = offset; break }
  }
  if (eocd < 0) throw new Error('ZIP 文件损坏或格式不支持')

  const memberCount = view.getUint16(eocd + 10, true)
  const directorySize = view.getUint32(eocd + 12, true)
  const directoryOffset = view.getUint32(eocd + 16, true)
  if (memberCount > MAX_ARCHIVE_MEMBERS) {
    throw new Error(`ZIP 文件包含的条目不能超过 ${MAX_ARCHIVE_MEMBERS} 个`)
  }
  if (directoryOffset + directorySize > bytes.length) throw new Error('ZIP 中央目录越界')

  const entries: ArchiveEntry[] = []
  let unpacked = 0
  let cursor = directoryOffset
  for (let index = 0; index < memberCount; index++) {
    if (view.getUint32(cursor, true) !== 0x02014b50) throw new Error('ZIP 中央目录损坏')
    const flags = view.getUint16(cursor + 8, true)
    const method = view.getUint16(cursor + 10, true)
    const compressedSize = view.getUint32(cursor + 20, true)
    const uncompressedSize = view.getUint32(cursor + 24, true)
    const nameLength = view.getUint16(cursor + 28, true)
    const extraLength = view.getUint16(cursor + 30, true)
    const commentLength = view.getUint16(cursor + 32, true)
    const localOffset = view.getUint32(cursor + 42, true)
    const name = new TextDecoder().decode(bytes.subarray(cursor + 46, cursor + 46 + nameLength))
    cursor += 46 + nameLength + extraLength + commentLength

    if (flags & 0x1) throw new Error('ZIP 不支持加密条目')
    if (name.endsWith('/')) continue
    const extension = name.slice(name.lastIndexOf('.')).toLowerCase()
    if (!MARKDOWN_EXTENSIONS.includes(extension) && !IMAGE_MIME[extension]) continue

    unpacked += uncompressedSize
    if (unpacked > MAX_ARCHIVE_UNPACKED_BYTES) {
      throw new Error(`ZIP 解压后的内容不能超过 ${MAX_ARCHIVE_UNPACKED_BYTES / 1024 / 1024}MB`)
    }
    if (view.getUint32(localOffset, true) !== 0x04034b50) throw new Error('ZIP 本地头损坏')
    const localNameLength = view.getUint16(localOffset + 26, true)
    const localExtraLength = view.getUint16(localOffset + 28, true)
    const dataStart = localOffset + 30 + localNameLength + localExtraLength
    const raw = bytes.subarray(dataStart, dataStart + compressedSize)
    if (method === 0) entries.push({ name, data: raw, compressed: false })
    else if (method === 8) entries.push({ name, data: raw, compressed: true })
    else throw new Error('ZIP 使用了不支持的压缩方式')
  }
  return entries
}

/** 使用浏览器内置的 deflate-raw 解压，不引入额外依赖。 */
async function inflateRaw(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data as BlobPart]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
  return new Uint8Array(await new Response(stream).arrayBuffer())
}

/** 把字节转成 Data URL，键使用 Markdown 中的原始引用路径。 */
function toDataUrl(data: Uint8Array, mime: string): string {
  let binary = ''
  const chunk = 0x8000
  for (let offset = 0; offset < data.length; offset += chunk) {
    binary += String.fromCharCode(...data.subarray(offset, offset + chunk))
  }
  return `data:${mime};base64,${btoa(binary)}`
}

/** 按 Markdown 中的图片引用收集 Data URL；缺失或不支持的引用转为警告。 */
function collectImages(
  content: string,
  files: Map<string, Uint8Array>,
  markdownDir: string
): { images: Record<string, string>; warnings: string[] } {
  const images: Record<string, string> = {}
  const warnings = new Set<string>()
  const prefixes: string[] = []
  let current = markdownDir
  for (let depth = 0; depth <= 12; depth++) {
    prefixes.push(current ? `${current}/` : '')
    if (!current) break
    const parent = current.includes('/') ? current.slice(0, current.lastIndexOf('/')) : ''
    current = parent
  }

  for (const match of content.matchAll(IMAGE_PATTERN)) {
    const raw = match[1].replace(/^<|>$/g, '')
    if (!raw || Object.prototype.hasOwnProperty.call(images, raw)) continue
    if (/^(?:data|https?|ftp):/i.test(raw)) {
      warnings.add(`已跳过远程或内嵌图片: ${raw}`)
      continue
    }
    let relative: string
    try {
      relative = decodeURIComponent(raw).replace(/\\/g, '/').replace(/^\.\//, '')
    } catch {
      warnings.add(`图片路径无法解析: ${raw}`)
      continue
    }
    if (relative.startsWith('/') || relative.split('/').includes('..')) {
      warnings.add(`已跳过越界图片路径: ${raw}`)
      continue
    }
    const extension = relative.slice(relative.lastIndexOf('.')).toLowerCase()
    const mime = IMAGE_MIME[extension]
    if (!mime) {
      warnings.add(`图片格式不支持，已跳过: ${raw}`)
      continue
    }
    const data = prefixes.map((prefix) => files.get(`${prefix}${relative}`)).find(Boolean)
    if (!data) {
      warnings.add(`图片文件不存在: ${raw}`)
      continue
    }
    images[raw] = toDataUrl(data, mime)
  }
  return { images, warnings: [...warnings] }
}

/** 资源 ZIP 在浏览器内解包，要求恰好包含一个 Markdown。 */
async function readUploadedArchive(file: File): Promise<PreparedMarkdown> {
  const directory = readZipDirectory(await file.arrayBuffer())
  const files = new Map<string, Uint8Array>()
  for (const entry of directory) {
    files.set(entry.name, entry.compressed ? await inflateRaw(entry.data) : entry.data)
  }

  const markdownNames = [...files.keys()].filter((name) =>
    MARKDOWN_EXTENSIONS.includes(name.slice(name.lastIndexOf('.')).toLowerCase()))
  if (markdownNames.length === 0) throw new Error('ZIP 中未找到 .md 或 .markdown 文件')
  if (markdownNames.length > 1) throw new Error('ZIP 中只能包含一个 .md 或 .markdown 文件')

  const markdownName = markdownNames[0]
  const markdownData = files.get(markdownName)
  if (!markdownData) throw new Error('ZIP 中未找到 .md 或 .markdown 文件')
  const content = new TextDecoder().decode(markdownData).replace(/^\uFEFF/, '')
  const slash = markdownName.lastIndexOf('/')
  const { images, warnings } = collectImages(content, files, slash < 0 ? '' : markdownName.slice(0, slash))
  return {
    filename: markdownName.slice(slash + 1),
    markdown_content: content,
    images,
    warnings,
  }
}

/** 桌面端由主进程解析同目录及 Obsidian 库根图片，失败时抛出可直接展示的原因。 */
async function prepareLocalMarkdown(filePath: string): Promise<PreparedMarkdown> {
  const api = window.desktopApi?.markdownSource
  if (!api) throw new Error('当前环境不支持读取本地文件，请改用上传方式')
  const prepared = await api.prepare(filePath)
  if (prepared.error) throw new Error(prepared.error)
  return {
    filename: prepared.filename,
    markdown_content: prepared.markdownContent,
    images: prepared.images,
    warnings: prepared.warnings,
  }
}

/**
 * 准备待渲染的 Markdown。
 * 桌面端本地文件走主进程读取以获取同目录图片；上传文件在页面内解析 Markdown 或 ZIP。
 */
export async function prepareMarkdownSource(
  source: { kind: 'local'; path: string } | { kind: 'upload'; file: File },
): Promise<PreparedMarkdown> {
  if (source.kind === 'local') return prepareLocalMarkdown(source.path)
  if (/\.zip$/i.test(source.file.name)) return readUploadedArchive(source.file)
  return {
    filename: source.file.name,
    markdown_content: await readUploadedMarkdown(source.file),
    images: {},
    warnings: ['浏览器上传只包含 Markdown 本身，图片需改用桌面端「选择本地 Markdown」读取'],
  }
}
