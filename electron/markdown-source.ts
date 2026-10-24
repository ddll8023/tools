/**
 * 读取本地 Markdown 及其引用图片，把图片转成 Data URL 供渲染进程离线排版。
 * 支持单个 .md（按目录与 Obsidian 库根解析图片）和资源 ZIP（在内存中解包，不写盘）。
 */
import { ipcMain, type BrowserWindow, type IpcMainInvokeEvent } from 'electron'
import { readFile, stat } from 'node:fs/promises'
import * as path from 'node:path'
import { inflateRawSync } from 'node:zlib'
import type { PreparedMarkdownPayload } from './markdown-source-types'

const MAX_MARKDOWN_BYTES = 50 * 1024 * 1024
const MAX_IMAGE_BYTES = 20 * 1024 * 1024
const MAX_TOTAL_IMAGE_BYTES = 768 * 1024 * 1024
const MAX_ARCHIVE_MEMBERS = 4096
const MAX_ARCHIVE_UNPACKED_BYTES = 1024 * 1024 * 1024
// 与渲染进程的图片白名单保持一致：只嵌入浏览器可直接解码且不产生脚本执行的格式。
const IMAGE_MIME: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
}
const MARKDOWN_EXTENSIONS = ['.md', '.markdown']
// Obsidian 库根相对路径（如 408/分类/a.png）需要按库根解析，向上查找的层数需要上限。
const MAX_ANCESTOR_DEPTH = 12
const IMAGE_PATTERN = /!\[[^\]]*\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+["'][^"']*["'])?\s*\)/g

/** 图片字节来源：磁盘目录或 ZIP 内存条目，两者只在取字节这一步不同。 */
interface ImageSource {
  load(relative: string, budget: { used: number }): Promise<{ data: Buffer } | { warning: string }>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** 只接受主窗口主框架调用，避免其他渲染内容借通道读取任意本地文件。 */
function requireOwner(
  event: IpcMainInvokeEvent,
  getWindow: () => BrowserWindow | null,
  trustedUrl: string
): void {
  const owner = getWindow()
  if (!owner || owner.isDestroyed() || !event.senderFrame || event.sender !== owner.webContents
    || event.senderFrame !== owner.webContents.mainFrame) {
    throw new Error('不允许的 Markdown 读取来源')
  }
  const current = new URL(event.senderFrame.url)
  current.hash = ''
  current.search = ''
  if (current.href !== new URL(trustedUrl).href) throw new Error('不允许的 Markdown 页面来源')
}

/** 归一化 Markdown 中的图片引用：去尖括号、拒绝远程地址与越界路径。 */
function normalizeImageReference(source: string): { relative: string } | { warning: string } {
  if (/^(?:data|https?|ftp):/i.test(source)) return { warning: `已跳过远程或内嵌图片: ${source}` }
  let decoded: string
  try {
    decoded = decodeURIComponent(source)
  } catch {
    return { warning: `图片路径无法解析: ${source}` }
  }
  const relative = decoded.replace(/\\/g, '/').replace(/^\.\//, '')
  if (path.isAbsolute(relative) || relative.split('/').includes('..')) {
    return { warning: `已跳过越界图片路径: ${source}` }
  }
  if (!IMAGE_MIME[path.extname(relative).toLowerCase()]) {
    return { warning: `图片格式不支持，已跳过: ${source}` }
  }
  return { relative }
}

/** 从 Markdown 文件所在目录逐级向上查找 Obsidian 库根，用于解析库根相对图片路径。 */
async function findVaultRoot(startDir: string): Promise<string> {
  let current = startDir
  for (let depth = 0; depth <= MAX_ANCESTOR_DEPTH; depth++) {
    try {
      const info = await stat(path.join(current, '.obsidian'))
      if (info.isDirectory()) return current
    } catch {
      // 该层不是库根，继续向上
    }
    const parent = path.dirname(current)
    if (parent === current) break
    current = parent
  }
  return ''
}

/** 磁盘目录来源：同目录优先，其次是库根与中间各级祖先目录。 */
function createDirectorySource(baseDir: string, vaultRoot: string): ImageSource {
  const ancestors: string[] = []
  let current = baseDir
  for (let depth = 0; depth <= MAX_ANCESTOR_DEPTH; depth++) {
    ancestors.push(current)
    if (vaultRoot && current === vaultRoot) break
    const parent = path.dirname(current)
    if (parent === current) break
    current = parent
  }
  if (vaultRoot && !ancestors.includes(vaultRoot)) ancestors.push(vaultRoot)

  return {
    async load(relative, budget) {
      for (const ancestor of ancestors) {
        const candidate = path.join(ancestor, relative)
        let size: number
        try {
          const info = await stat(candidate)
          if (!info.isFile()) continue
          size = info.size
        } catch {
          continue
        }
        if (size > MAX_IMAGE_BYTES) return { warning: `图片超过 20MB，已跳过: ${relative}` }
        if (budget.used + size > MAX_TOTAL_IMAGE_BYTES) {
          return { warning: '图片总量超过 768MB，请拆分文档' }
        }
        try {
          const data = await readFile(candidate)
          budget.used += data.byteLength
          return { data }
        } catch {
          return { warning: `图片无法读取: ${relative}` }
        }
      }
      return { warning: `图片文件不存在: ${relative}` }
    },
  }
}

/** 读取 EOCD 记录，定位中央目录；只支持非 ZIP64 且无加密的常规压缩包。 */
function readZipEntries(buffer: Buffer): Array<{ name: string; data: Buffer }> {
  let eocd = -1
  const searchStart = Math.max(0, buffer.length - 0xffff - 22)
  for (let offset = buffer.length - 22; offset >= searchStart; offset--) {
    if (buffer.readUInt32LE(offset) === 0x06054b50) { eocd = offset; break }
  }
  if (eocd < 0) throw new Error('ZIP 文件损坏或格式不支持')

  const memberCount = buffer.readUInt16LE(eocd + 10)
  const directorySize = buffer.readUInt32LE(eocd + 12)
  const directoryOffset = buffer.readUInt32LE(eocd + 16)
  if (memberCount > MAX_ARCHIVE_MEMBERS) {
    throw new Error(`ZIP 文件包含的条目不能超过 ${MAX_ARCHIVE_MEMBERS} 个`)
  }
  if (directoryOffset + directorySize > buffer.length) throw new Error('ZIP 中央目录越界')

  const entries: Array<{ name: string; data: Buffer }> = []
  let unpacked = 0
  let cursor = directoryOffset
  for (let index = 0; index < memberCount; index++) {
    if (buffer.readUInt32LE(cursor) !== 0x02014b50) throw new Error('ZIP 中央目录损坏')
    const flags = buffer.readUInt16LE(cursor + 8)
    const method = buffer.readUInt16LE(cursor + 10)
    const compressedSize = buffer.readUInt32LE(cursor + 20)
    const uncompressedSize = buffer.readUInt32LE(cursor + 24)
    const nameLength = buffer.readUInt16LE(cursor + 28)
    const extraLength = buffer.readUInt16LE(cursor + 30)
    const commentLength = buffer.readUInt16LE(cursor + 32)
    const externalAttr = buffer.readUInt32LE(cursor + 38)
    const localOffset = buffer.readUInt32LE(cursor + 42)
    const name = buffer.toString('utf8', cursor + 46, cursor + 46 + nameLength)
    cursor += 46 + nameLength + extraLength + commentLength

    // 加密、符号链接和非常规压缩方式一律跳过，避免越权读取或写出。
    if (flags & 0x1) throw new Error('ZIP 不支持加密条目')
    if (((externalAttr >>> 16) & 0xf000) === 0xa000) throw new Error('ZIP 不支持符号链接')
    if (name.endsWith('/')) continue
    if (!MARKDOWN_EXTENSIONS.includes(path.extname(name).toLowerCase())
      && !IMAGE_MIME[path.extname(name).toLowerCase()]) continue

    unpacked += uncompressedSize
    if (unpacked > MAX_ARCHIVE_UNPACKED_BYTES) {
      throw new Error(`ZIP 解压后的内容不能超过 ${MAX_ARCHIVE_UNPACKED_BYTES / 1024 / 1024}MB`)
    }
    if (buffer.readUInt32LE(localOffset) !== 0x04034b50) throw new Error('ZIP 本地头损坏')
    const localNameLength = buffer.readUInt16LE(localOffset + 26)
    const localExtraLength = buffer.readUInt16LE(localOffset + 28)
    const dataStart = localOffset + 30 + localNameLength + localExtraLength
    const raw = buffer.subarray(dataStart, dataStart + compressedSize)
    if (method === 0) entries.push({ name, data: raw })
    else if (method === 8) entries.push({ name, data: inflateRawSync(raw, { maxOutputLength: uncompressedSize + 1 }) })
    else throw new Error('ZIP 使用了不支持的压缩方式')
  }
  return entries
}

/** ZIP 来源：按 Markdown 所在目录逐级向上匹配条目名，兼容打包时包含或多跳一级目录。 */
function createArchiveSource(
  entries: Map<string, Buffer>,
  markdownDir: string
): ImageSource {
  const prefixes: string[] = []
  let current = markdownDir
  for (let depth = 0; depth <= MAX_ANCESTOR_DEPTH; depth++) {
    prefixes.push(current ? `${current}/` : '')
    if (!current) break
    const parent = path.posix.dirname(current)
    current = parent === '.' ? '' : parent
  }

  return {
    async load(relative, budget) {
      for (const prefix of prefixes) {
        const data = entries.get(`${prefix}${relative}`)
        if (!data) continue
        if (data.byteLength > MAX_IMAGE_BYTES) return { warning: `图片超过 20MB，已跳过: ${relative}` }
        if (budget.used + data.byteLength > MAX_TOTAL_IMAGE_BYTES) {
          return { warning: '图片总量超过 768MB，请拆分文档' }
        }
        budget.used += data.byteLength
        return { data }
      }
      return { warning: `图片文件不存在: ${relative}` }
    },
  }
}

/** 按 Markdown 文本中的图片引用收集 Data URL，缺失项转为警告而不是中断整篇文档。 */
async function collectImages(
  markdownContent: string,
  source: ImageSource
): Promise<{ images: Record<string, string>; warnings: string[] }> {
  const images: Record<string, string> = {}
  const warnings = new Set<string>()
  const budget = { used: 0 }
  for (const match of markdownContent.matchAll(IMAGE_PATTERN)) {
    const raw = match[1].replace(/^<|>$/g, '')
    if (!raw || Object.prototype.hasOwnProperty.call(images, raw)) continue
    const normalized = normalizeImageReference(raw)
    if ('warning' in normalized) {
      warnings.add(normalized.warning)
      continue
    }
    const loaded = await source.load(normalized.relative, budget)
    if ('warning' in loaded) {
      warnings.add(loaded.warning)
      continue
    }
    const mime = IMAGE_MIME[path.extname(normalized.relative).toLowerCase()]
    images[raw] = `data:${mime};base64,${loaded.data.toString('base64')}`
  }
  return { images, warnings: [...warnings] }
}

function failure(filename: string, message: string): PreparedMarkdownPayload {
  return { filename, markdownContent: '', images: {}, warnings: [], error: message }
}

/** 单文件来源：读取 .md，并按所在目录与 Obsidian 库根解析图片。 */
async function prepareMarkdownFile(resolved: string): Promise<PreparedMarkdownPayload> {
  const filename = path.basename(resolved)
  let content: string
  try {
    const info = await stat(resolved)
    if (!info.isFile()) return failure(filename, '本地 Markdown 文件不存在或无法读取')
    if (info.size > MAX_MARKDOWN_BYTES) return failure(filename, '该文件不能超过 50MB')
    content = (await readFile(resolved, 'utf-8')).replace(/^\uFEFF/, '')
  } catch {
    return failure(filename, '本地 Markdown 文件不存在或无法读取')
  }

  const baseDir = path.dirname(resolved)
  const source = createDirectorySource(baseDir, await findVaultRoot(baseDir))
  const { images, warnings } = await collectImages(content, source)
  return { filename, markdownContent: content, images, warnings }
}

/** 资源包来源：内存解包，要求恰好一个 .md，图片按条目名解析。 */
async function prepareMarkdownArchive(resolved: string): Promise<PreparedMarkdownPayload> {
  const filename = path.basename(resolved)
  let buffer: Buffer
  try {
    const info = await stat(resolved)
    if (!info.isFile()) return failure(filename, 'ZIP 文件不存在或无法读取')
    if (info.size > MAX_MARKDOWN_BYTES) return failure(filename, '该文件不能超过 50MB')
    buffer = await readFile(resolved)
  } catch {
    return failure(filename, 'ZIP 文件不存在或无法读取')
  }

  let entries: Array<{ name: string; data: Buffer }>
  try {
    entries = readZipEntries(buffer)
  } catch (error: unknown) {
    return failure(filename, error instanceof Error ? error.message : 'ZIP 文件无法读取')
  }

  const markdownEntries = entries.filter((entry) =>
    MARKDOWN_EXTENSIONS.includes(path.extname(entry.name).toLowerCase()))
  if (markdownEntries.length === 0) return failure(filename, 'ZIP 中未找到 .md 或 .markdown 文件')
  if (markdownEntries.length > 1) return failure(filename, 'ZIP 中只能包含一个 .md 或 .markdown 文件')

  const markdownEntry = markdownEntries[0]
  const markdownContent = markdownEntry.data.toString('utf-8').replace(/^\uFEFF/, '')
  const archive = new Map(entries.map((entry) => [entry.name, entry.data]))
  const markdownDir = path.posix.dirname(markdownEntry.name)
  const source = createArchiveSource(archive, markdownDir === '.' ? '' : markdownDir)
  const { images, warnings } = await collectImages(markdownContent, source)
  return {
    filename: path.posix.basename(markdownEntry.name),
    markdownContent,
    images,
    warnings,
  }
}

/** 按扩展名分派到单文件或资源包处理。 */
async function prepareMarkdown(sourcePath: string): Promise<PreparedMarkdownPayload> {
  const resolved = path.resolve(sourcePath)
  const extension = path.extname(resolved).toLowerCase()
  if (extension === '.zip') return prepareMarkdownArchive(resolved)
  if (!MARKDOWN_EXTENSIONS.includes(extension)) {
    return failure(path.basename(resolved), '本地文件必须是 .md、.markdown 或 .zip')
  }
  return prepareMarkdownFile(resolved)
}

/** 注册本地 Markdown 读取通道；只解析用户显式选择的文件路径。 */
export function registerMarkdownSourceIpc(
  getWindow: () => BrowserWindow | null,
  trustedUrl: string
): void {
  ipcMain.handle('markdown-source:prepare', async (event, value: unknown): Promise<PreparedMarkdownPayload> => {
    requireOwner(event, getWindow, trustedUrl)
    if (!isRecord(value) || typeof value.path !== 'string' || !value.path) {
      return failure('', '缺少本地 Markdown 路径')
    }
    return prepareMarkdown(value.path)
  })
}
