import type { MindMapData } from '../types'
import { normalizeData } from './tree-ops'

const ZIP_END_SIGNATURE = 0x06054b50
const ZIP_CENTRAL_SIGNATURE = 0x02014b50
const ZIP_LOCAL_SIGNATURE = 0x04034b50
const ZIP_END_LENGTH = 22
const ZIP_MAX_COMMENT_LENGTH = 0xffff
const MAX_XMIND_ENTRY_SIZE = 64 * 1024 * 1024
const UINT32_MAX = 0xffffffff

export type XMindInput = Blob | ArrayBuffer | Uint8Array

export class XMindFormatError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'XMindFormatError'
  }
}

interface ZipEntry {
  name: string
  flags: number
  method: number
  compressedSize: number
  uncompressedSize: number
  localHeaderOffset: number
}

interface XMindTopicRecord {
  id?: unknown
  title?: unknown
  text?: unknown
  children?: unknown
  labels?: unknown
  notes?: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function toBytes(value: ArrayBuffer | Uint8Array): Uint8Array {
  if (value instanceof ArrayBuffer) return new Uint8Array(value)
  return new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
}

async function readInput(input: XMindInput): Promise<Uint8Array> {
  if (typeof Blob !== 'undefined' && input instanceof Blob) {
    return new Uint8Array(await input.arrayBuffer())
  }
  if (input instanceof ArrayBuffer) return toBytes(input)
  return toBytes(input)
}

function ensureRange(bytes: Uint8Array, offset: number, length: number): void {
  if (
    offset < 0 ||
    length < 0 ||
    offset > bytes.length ||
    length > bytes.length - offset
  ) {
    throw new XMindFormatError('XMind 压缩包结构损坏。')
  }
}

function getView(bytes: Uint8Array): DataView {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
}

function readUint16(bytes: Uint8Array, offset: number): number {
  ensureRange(bytes, offset, 2)
  return getView(bytes).getUint16(offset, true)
}

function readUint32(bytes: Uint8Array, offset: number): number {
  ensureRange(bytes, offset, 4)
  return getView(bytes).getUint32(offset, true)
}

function findEndOfCentralDirectory(bytes: Uint8Array): number {
  if (bytes.length < ZIP_END_LENGTH) {
    throw new XMindFormatError('不是有效的 XMind 文件。')
  }
  const firstOffset = Math.max(0, bytes.length - ZIP_END_LENGTH - ZIP_MAX_COMMENT_LENGTH)
  for (let offset = bytes.length - ZIP_END_LENGTH; offset >= firstOffset; offset--) {
    if (readUint32(bytes, offset) === ZIP_END_SIGNATURE) return offset
  }
  throw new XMindFormatError('不是有效的 XMind 文件。')
}

function decodeZipName(bytes: Uint8Array, flags: number): string {
  // XMind archive entry names are ASCII in practice. UTF-8 is used whenever
  // the archive sets the language encoding flag, and is a safe fallback for
  // the remaining names we need to inspect.
  void flags
  return new TextDecoder('utf-8', { fatal: false }).decode(bytes)
}

function readZipEntries(bytes: Uint8Array): ZipEntry[] {
  const endOffset = findEndOfCentralDirectory(bytes)
  ensureRange(bytes, endOffset, ZIP_END_LENGTH)

  const diskNumber = readUint16(bytes, endOffset + 4)
  const centralDisk = readUint16(bytes, endOffset + 6)
  const entriesOnDisk = readUint16(bytes, endOffset + 8)
  const totalEntries = readUint16(bytes, endOffset + 10)
  const centralSize = readUint32(bytes, endOffset + 12)
  const centralOffset = readUint32(bytes, endOffset + 16)
  const commentLength = readUint16(bytes, endOffset + 20)

  if (diskNumber !== 0 || centralDisk !== 0 || entriesOnDisk !== totalEntries) {
    throw new XMindFormatError('不支持分卷 XMind 压缩包。')
  }
  if (commentLength > ZIP_MAX_COMMENT_LENGTH) {
    throw new XMindFormatError('XMind 压缩包注释长度无效。')
  }
  if (totalEntries === 0xffff || centralSize === UINT32_MAX || centralOffset === UINT32_MAX) {
    throw new XMindFormatError('不支持 ZIP64 格式的 XMind 文件。')
  }
  ensureRange(bytes, endOffset, ZIP_END_LENGTH + commentLength)
  ensureRange(bytes, centralOffset, centralSize)

  const entries: ZipEntry[] = []
  let offset = centralOffset
  for (let index = 0; index < totalEntries; index++) {
    ensureRange(bytes, offset, 46)
    if (readUint32(bytes, offset) !== ZIP_CENTRAL_SIGNATURE) {
      throw new XMindFormatError('XMind 压缩包目录损坏。')
    }

    const flags = readUint16(bytes, offset + 8)
    const method = readUint16(bytes, offset + 10)
    const compressedSize = readUint32(bytes, offset + 20)
    const uncompressedSize = readUint32(bytes, offset + 24)
    const nameLength = readUint16(bytes, offset + 28)
    const extraLength = readUint16(bytes, offset + 30)
    const entryCommentLength = readUint16(bytes, offset + 32)
    const localHeaderOffset = readUint32(bytes, offset + 42)
    const recordLength = 46 + nameLength + extraLength + entryCommentLength

    if (
      compressedSize === UINT32_MAX ||
      uncompressedSize === UINT32_MAX ||
      localHeaderOffset === UINT32_MAX
    ) {
      throw new XMindFormatError('不支持 ZIP64 格式的 XMind 文件。')
    }
    ensureRange(bytes, offset, recordLength)
    const name = decodeZipName(bytes.slice(offset + 46, offset + 46 + nameLength), flags)
    entries.push({
      name,
      flags,
      method,
      compressedSize,
      uncompressedSize,
      localHeaderOffset,
    })
    offset += recordLength
  }

  return entries
}

async function inflateRaw(data: Uint8Array): Promise<Uint8Array> {
  if (typeof DecompressionStream === 'undefined') {
    throw new XMindFormatError('当前运行环境不支持读取压缩的 XMind 文件。')
  }

  const stream = new Blob([data])
    .stream()
    .pipeThrough(new DecompressionStream('deflate-raw'))
  const result = new Uint8Array(await new Response(stream).arrayBuffer())
  if (result.length > MAX_XMIND_ENTRY_SIZE) {
    throw new XMindFormatError('XMind 文件解压后的内容过大。')
  }
  return result
}

async function readZipEntry(bytes: Uint8Array, entry: ZipEntry): Promise<Uint8Array> {
  if (entry.flags & 0x0001) {
    throw new XMindFormatError('不支持加密的 XMind 文件。')
  }
  if (entry.uncompressedSize > MAX_XMIND_ENTRY_SIZE) {
    throw new XMindFormatError('XMind 文件解压后的内容过大。')
  }

  const localOffset = entry.localHeaderOffset
  ensureRange(bytes, localOffset, 30)
  if (readUint32(bytes, localOffset) !== ZIP_LOCAL_SIGNATURE) {
    throw new XMindFormatError('XMind 文件的本地目录损坏。')
  }

  const nameLength = readUint16(bytes, localOffset + 26)
  const extraLength = readUint16(bytes, localOffset + 28)
  const dataOffset = localOffset + 30 + nameLength + extraLength
  ensureRange(bytes, dataOffset, entry.compressedSize)
  const compressed = bytes.slice(dataOffset, dataOffset + entry.compressedSize)

  let result: Uint8Array
  if (entry.method === 0) {
    result = compressed
  } else if (entry.method === 8) {
    result = await inflateRaw(compressed)
  } else {
    throw new XMindFormatError(`不支持 ZIP 压缩方式：${entry.method}。`)
  }

  if (result.length !== entry.uncompressedSize) {
    throw new XMindFormatError('XMind 文件解压校验失败。')
  }
  return result
}

function findZipEntry(entries: ZipEntry[], filename: string): ZipEntry | undefined {
  return entries.find((entry) => {
    const name = entry.name.replace(/\\/g, '/')
    return name === filename || name.endsWith(`/${filename}`)
  })
}

async function readNamedEntry(
  bytes: Uint8Array,
  entries: ZipEntry[],
  filename: string,
): Promise<string | null> {
  const entry = findZipEntry(entries, filename)
  if (!entry) return null
  const content = await readZipEntry(bytes, entry)
  return new TextDecoder('utf-8', { fatal: false }).decode(content)
}

function uniqueId(rawId: unknown, fallback: string, used: Set<string>): string {
  const base = readString(rawId)?.trim() || fallback
  let candidate = base
  let suffix = 2
  while (used.has(candidate)) {
    candidate = `${base}-${suffix}`
    suffix++
  }
  used.add(candidate)
  return candidate
}

function getTopicChildren(topic: XMindTopicRecord): XMindTopicRecord[] {
  if (Array.isArray(topic.children)) {
    return topic.children.filter(isRecord) as XMindTopicRecord[]
  }
  if (!isRecord(topic.children)) return []
  const attached = topic.children.attached
  if (!Array.isArray(attached)) return []
  return attached.filter(isRecord) as XMindTopicRecord[]
}

function getTopicRemark(topic: XMindTopicRecord): string | undefined {
  if (typeof topic.notes === 'string') return topic.notes || undefined
  if (!isRecord(topic.notes)) return undefined
  const plain = topic.notes.plain
  if (typeof plain === 'string') return plain || undefined
  if (!isRecord(plain)) return undefined
  const content = readString(plain.content)?.trim()
  return content || undefined
}

function getTopicTags(topic: XMindTopicRecord): string[] | undefined {
  const values = Array.isArray(topic.labels)
    ? topic.labels.filter((value): value is string => typeof value === 'string')
    : typeof topic.labels === 'string'
      ? [topic.labels]
      : []
  const tags = values.map((value) => value.trim()).filter(Boolean)
  return tags.length > 0 ? tags : undefined
}

function convertJsonTopic(
  topic: XMindTopicRecord,
  path: string,
  usedIds: Set<string>,
): MindMapData {
  const title = readString(topic.title) ?? readString(topic.text) ?? '未命名主题'
  const children = getTopicChildren(topic)
  const node: MindMapData = {
    id: uniqueId(topic.id, path, usedIds),
    text: title,
  }
  const remark = getTopicRemark(topic)
  const tags = getTopicTags(topic)
  if (remark) node.remark = remark
  if (tags) node.tags = tags
  if (children.length > 0) {
    node.children = children.map((child, index) =>
      convertJsonTopic(child, `${path}-${index}`, usedIds),
    )
  }
  return node
}

function parseJsonContent(content: string): MindMapData[] {
  let parsed: unknown
  try {
    parsed = JSON.parse(content) as unknown
  } catch {
    throw new XMindFormatError('XMind 的 content.json 格式无效。')
  }

  let sheets: unknown[] = []
  if (Array.isArray(parsed)) {
    sheets = parsed
  } else if (isRecord(parsed) && isRecord(parsed.rootTopic)) {
    sheets = [parsed]
  } else if (isRecord(parsed) && Array.isArray(parsed.sheets)) {
    sheets = parsed.sheets
  }
  if (sheets.length === 0) {
    throw new XMindFormatError('XMind 文件中没有可导入的主题。')
  }

  const usedIds = new Set<string>()
  const roots: MindMapData[] = []
  sheets.forEach((sheet, sheetIndex) => {
    if (!isRecord(sheet) || !isRecord(sheet.rootTopic)) return
    roots.push(convertJsonTopic(
      sheet.rootTopic as XMindTopicRecord,
      `xmind-${sheetIndex}`,
      usedIds,
    ))
  })

  if (roots.length === 0) {
    throw new XMindFormatError('XMind 文件中没有可导入的主题。')
  }
  return roots
}

function getElementsByLocalName(
  parent: Document | Element,
  localName: string,
): Element[] {
  const namespaced = Array.from(parent.getElementsByTagNameNS('*', localName))
  if (namespaced.length > 0) return namespaced
  return Array.from(parent.getElementsByTagName(localName))
}

function getDirectChild(parent: Element, localName: string): Element | null {
  return Array.from(parent.children).find((child) => child.localName === localName) ?? null
}

function getDirectChildren(parent: Element, localName: string): Element[] {
  return Array.from(parent.children).filter((child) => child.localName === localName)
}

function convertXmlTopic(
  topic: Element,
  path: string,
  usedIds: Set<string>,
): MindMapData {
  const title = getDirectChild(topic, 'title')?.textContent ?? '未命名主题'
  const node: MindMapData = {
    id: uniqueId(topic.getAttribute('id'), path, usedIds),
    text: title,
  }

  const notes = getDirectChild(topic, 'notes')?.textContent?.trim()
  if (notes) node.remark = notes

  const childrenElement = getDirectChild(topic, 'children')
  const childTopics = childrenElement
    ? getDirectChildren(childrenElement, 'topics')
      .filter((group) => !group.getAttribute('type') || group.getAttribute('type') === 'attached')
      .flatMap((group) => getDirectChildren(group, 'topic'))
    : []
  if (childTopics.length > 0) {
    node.children = childTopics.map((child, index) =>
      convertXmlTopic(child, `${path}-${index}`, usedIds),
    )
  }
  return node
}

function parseXmlContent(content: string): MindMapData[] {
  if (typeof DOMParser === 'undefined') {
    throw new XMindFormatError('当前运行环境不支持读取旧版 XMind 文件。')
  }
  const document = new DOMParser().parseFromString(content, 'application/xml')
  if (document.getElementsByTagName('parsererror').length > 0) {
    throw new XMindFormatError('XMind 的 content.xml 格式无效。')
  }

  const sheets = getElementsByLocalName(document, 'sheet')
  const usedIds = new Set<string>()
  const roots: MindMapData[] = []
  sheets.forEach((sheet, sheetIndex) => {
    const topic = getDirectChild(sheet, 'topic')
    if (topic) roots.push(convertXmlTopic(topic, `xmind-${sheetIndex}`, usedIds))
  })
  if (roots.length === 0) {
    throw new XMindFormatError('XMind 文件中没有可导入的主题。')
  }
  return roots
}

/** Read modern content.json or legacy content.xml from an XMind ZIP file. */
export async function parseXMindFile(input: XMindInput): Promise<MindMapData[]> {
  const bytes = await readInput(input)
  const entries = readZipEntries(bytes)
  const jsonContent = await readNamedEntry(bytes, entries, 'content.json')
  if (jsonContent !== null) return parseJsonContent(jsonContent)

  const xmlContent = await readNamedEntry(bytes, entries, 'content.xml')
  if (xmlContent !== null) return parseXmlContent(xmlContent)

  throw new XMindFormatError('XMind 文件缺少 content.json 或 content.xml。')
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function toModernTopic(node: MindMapData, root: boolean): Record<string, unknown> {
  const topic: Record<string, unknown> = {
    id: node.id,
    class: 'topic',
    title: node.text,
  }
  if (root) topic.structureClass = 'org.xmind.ui.map.unbalanced'
  if (node.tags && node.tags.length > 0) topic.labels = [...node.tags]
  if (node.remark) topic.notes = { plain: { content: node.remark } }
  if (node.children && node.children.length > 0) {
    topic.children = {
      attached: node.children.map((child) => toModernTopic(child, false)),
    }
  }
  return topic
}

function toLegacyXmlTopic(node: MindMapData, root: boolean): string {
  const parts = [
    `<topic id="${escapeXml(node.id)}"${root ? ' structure-class="org.xmind.ui.logic.right"' : ''}>`,
    `<title>${escapeXml(node.text)}</title>`,
  ]
  if (node.children && node.children.length > 0) {
    parts.push('<children><topics type="attached">')
    for (const child of node.children) parts.push(toLegacyXmlTopic(child, false))
    parts.push('</topics></children>')
  }
  parts.push('</topic>')
  return parts.join('')
}

function createLegacyContent(roots: MindMapData[]): string {
  const sheets = roots.map((root, index) => [
    `<sheet id="sheet-${index + 1}">`,
    toLegacyXmlTopic(root, true),
    `<title>Map ${index + 1}</title>`,
    '</sheet>',
  ].join('')).join('')
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
    '<xmap-content xmlns="urn:xmind:xmap:xmlns:content:2.0" ',
    'xmlns:fo="http://www.w3.org/1999/XSL/Format" ',
    'xmlns:svg="http://www.w3.org/2000/svg" ',
    'xmlns:xhtml="http://www.w3.org/1999/xhtml" ',
    'xmlns:xlink="http://www.w3.org/1999/xlink" version="2.0">',
    sheets,
    '</xmap-content>',
  ].join('')
}

function createCrcTable(): Uint32Array {
  const table = new Uint32Array(256)
  for (let index = 0; index < table.length; index++) {
    let value = index
    for (let bit = 0; bit < 8; bit++) {
      value = (value & 1) !== 0 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
    }
    table[index] = value >>> 0
  }
  return table
}

const CRC_TABLE = createCrcTable()

function crc32(bytes: Uint8Array): number {
  let value = 0xffffffff
  for (const byte of bytes) {
    value = CRC_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8)
  }
  return (value ^ 0xffffffff) >>> 0
}

function writeUint16(bytes: Uint8Array, offset: number, value: number): void {
  new DataView(bytes.buffer).setUint16(offset, value, true)
}

function writeUint32(bytes: Uint8Array, offset: number, value: number): void {
  new DataView(bytes.buffer).setUint32(offset, value, true)
}

function concatBytes(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const result = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    result.set(chunk, offset)
    offset += chunk.length
  }
  return result
}

function createStoredZip(entries: { name: string; data: Uint8Array }[]): Blob {
  const encoder = new TextEncoder()
  const localChunks: Uint8Array[] = []
  const centralChunks: Uint8Array[] = []
  let localOffset = 0

  for (const entry of entries) {
    const name = encoder.encode(entry.name)
    const data = entry.data
    const checksum = crc32(data)
    if (name.length > 0xffff || data.length > UINT32_MAX || localOffset > UINT32_MAX) {
      throw new XMindFormatError('导出的 XMind 文件过大。')
    }

    const local = new Uint8Array(30 + name.length + data.length)
    writeUint32(local, 0, ZIP_LOCAL_SIGNATURE)
    writeUint16(local, 4, 20)
    writeUint16(local, 6, 0x0800)
    writeUint16(local, 8, 0)
    writeUint16(local, 10, 0)
    writeUint16(local, 12, 0)
    writeUint32(local, 14, checksum)
    writeUint32(local, 18, data.length)
    writeUint32(local, 22, data.length)
    writeUint16(local, 26, name.length)
    writeUint16(local, 28, 0)
    local.set(name, 30)
    local.set(data, 30 + name.length)
    localChunks.push(local)

    const central = new Uint8Array(46 + name.length)
    writeUint32(central, 0, ZIP_CENTRAL_SIGNATURE)
    writeUint16(central, 4, 20)
    writeUint16(central, 6, 20)
    writeUint16(central, 8, 0x0800)
    writeUint16(central, 10, 0)
    writeUint16(central, 12, 0)
    writeUint16(central, 14, 0)
    writeUint32(central, 16, checksum)
    writeUint32(central, 20, data.length)
    writeUint32(central, 24, data.length)
    writeUint16(central, 28, name.length)
    writeUint16(central, 30, 0)
    writeUint16(central, 32, 0)
    writeUint16(central, 34, 0)
    writeUint16(central, 36, 0)
    writeUint32(central, 38, 0)
    writeUint32(central, 42, localOffset)
    central.set(name, 46)
    centralChunks.push(central)
    localOffset += local.length
  }

  const centralDirectory = concatBytes(centralChunks)
  if (
    entries.length > 0xffff ||
    centralDirectory.length > UINT32_MAX ||
    localOffset > UINT32_MAX
  ) {
    throw new XMindFormatError('导出的 XMind 文件过大。')
  }

  const end = new Uint8Array(ZIP_END_LENGTH)
  writeUint32(end, 0, ZIP_END_SIGNATURE)
  writeUint16(end, 4, 0)
  writeUint16(end, 6, 0)
  writeUint16(end, 8, entries.length)
  writeUint16(end, 10, entries.length)
  writeUint32(end, 12, centralDirectory.length)
  writeUint32(end, 16, localOffset)
  writeUint16(end, 20, 0)

  return new Blob(
    [concatBytes([...localChunks, centralDirectory, end])],
    { type: 'application/x-xmind' },
  )
}

/** Build a portable XMind archive with modern JSON and legacy XML content. */
export function exportMindMapToXMind(data: MindMapData | MindMapData[]): Blob {
  const roots = normalizeData(data)
  if (roots.length === 0) throw new XMindFormatError('没有可导出的思维导图内容。')

  const sheets = roots.map((root, index) => ({
    id: `sheet-${index + 1}`,
    class: 'sheet',
    title: `Map ${index + 1}`,
    rootTopic: toModernTopic(root, true),
    topicPositioning: 'fixed',
  }))
  const manifest = {
    'file-entries': {
      'content.json': {},
      'content.xml': {},
      'metadata.json': {},
    },
  }
  const encoder = new TextEncoder()
  return createStoredZip([
    { name: 'content.json', data: encoder.encode(JSON.stringify(sheets)) },
    { name: 'content.xml', data: encoder.encode(createLegacyContent(roots)) },
    { name: 'manifest.json', data: encoder.encode(JSON.stringify(manifest)) },
    { name: 'metadata.json', data: encoder.encode('{}') },
  ])
}
