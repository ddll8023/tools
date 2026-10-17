/** USB 控制面 API 与运行时边界解析；文件内容不经过 HTTP。 */
import { apiFetch, readApiResponse } from '@/api/client'

export interface UsbStorageItem {
  id: number
  description: string
  capacity_bytes: number | null
  free_bytes: number | null
  access_capability: number | null
  information_complete: boolean
}
export interface UsbDeviceItem {
  device_id: string
  vendor_id: number
  product_id: number
  name: string
  model: string
  serial: string | null
}
export interface UsbDirectoryEntry {
  object_id: number
  parent_id: number
  storage_id: number
  raw_name: string
  name: string
  is_folder: boolean
  size_bytes: number | null
  modified_at: string | null
}
export interface UsbRecordError { record_id: string | null; message: string }
export interface UsbSessionSummary {
  session_id: string
  device: UsbDeviceItem
  storages: UsbStorageItem[]
  connected_at: string
  last_device_response_at: string
  closing: boolean
}
export interface UsbStatus {
  instance_id: string
  revision: number
  platform_supported: boolean
  platform_reason: string | null
  dependency_available: boolean
  dependency_state: 'unsupported' | 'missing' | 'located' | 'loaded' | 'failed'
  dependency_reason: string | null
  worker_running: boolean
  busy: boolean
  session: UsbSessionSummary | null
  record_errors: UsbRecordError[]
}
export interface UsbDeviceList { instance_id: string; scan_id: string; devices: UsbDeviceItem[] }
export interface UsbDirectoryList {
  instance_id: string
  session_id: string
  storage_id: number
  folder_id: number
  entries: UsbDirectoryEntry[]
  complete: boolean
  missing_ids: number[]
  message: string
}
export interface UsbCopyRequest {
  instance_id: string
  session_id: string
  direction: 'download' | 'upload'
  source_objects: Array<{ storage_id: number; object_id: number }>
  source_paths: string[]
  local_target: string | null
  target_storage_id: number | null
  target_folder_id: number | null
}
export interface UsbPreparedCopy { request: UsbCopyRequest; submission_token: string; expires_at: number }
export type UsbTaskState = 'queued' | 'running' | 'cancelling' | 'completed' | 'partial_success' | 'failed' | 'cancelled' | 'interrupted'
export interface UsbProgress {
  stage: string
  current_name: string
  discovered: number
  processed: number
  known_bytes: number
  total_known: boolean
  current_sent: number
  current_total: number | null
}
export interface UsbCounts {
  succeeded: number
  reused: number
  skipped: number
  failed: number
  unexecuted: number
  unconfirmed: number
  copied_bytes: number
  effects: number
}
export interface UsbTaskSummary {
  task_id: string
  request: UsbCopyRequest
  target_label: string
  state: UsbTaskState
  created_at: number
  updated_at: number
  revision: number
  progress: UsbProgress
  counts: UsbCounts
  entry_count: number
  planned_count: number
  enumeration_complete: boolean
  stop_reason: string
  message: string
  cancel_requested: boolean
  active_intent: Record<string, string> | null
  record_error: string | null
  historical: boolean
}
export interface UsbEntryResult {
  entry_id: string
  source: string
  raw_name: string
  destination: string
  status: 'succeeded' | 'skipped' | 'failed' | 'unexecuted' | 'unconfirmed'
  is_folder: boolean
  message: string
  size_bytes: number | null
  effect: boolean
  reused: boolean
  object_id: number | null
  residual: string | null
  size_checked: boolean
}
export interface UsbTaskList { instance_id: string; tasks: UsbTaskSummary[]; record_errors: UsbRecordError[] }
export interface UsbTaskEntries { instance_id: string; task: UsbTaskSummary; entries: UsbEntryResult[]; offset: number; total: number; next_offset: number | null }

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('USB 服务返回了无效对象')
  return value as Record<string, unknown>
}
function text(value: unknown): string {
  if (typeof value !== 'string') throw new Error('USB 服务返回了无效文本')
  return value
}
function number(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) throw new Error('USB 服务返回了无效数值')
  return value
}
function integer(value: unknown): number {
  const result = number(value)
  if (!Number.isSafeInteger(result)) throw new Error('USB 服务返回的整数无法安全表示')
  return result
}
function bool(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('USB 服务返回了无效状态')
  return value
}
function nullable<T>(value: unknown, parse: (value: unknown) => T): T | null { return value === null ? null : parse(value) }
function array<T>(value: unknown, parse: (value: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new Error('USB 服务返回了无效列表')
  return value.map(parse)
}
function choice<T extends string>(value: unknown, choices: readonly T[]): T {
  const result = choices.find((item) => item === value)
  if (result === undefined) throw new Error('USB 服务返回了未知状态')
  return result
}
function parseDevice(value: unknown): UsbDeviceItem {
  const v = object(value)
  return { device_id: text(v.device_id), vendor_id: integer(v.vendor_id), product_id: integer(v.product_id), name: text(v.name), model: text(v.model), serial: nullable(v.serial, text) }
}
function parseStorage(value: unknown): UsbStorageItem {
  const v = object(value)
  return { id: integer(v.id), description: text(v.description), capacity_bytes: nullable(v.capacity_bytes, integer), free_bytes: nullable(v.free_bytes, integer), access_capability: nullable(v.access_capability, integer), information_complete: bool(v.information_complete) }
}
function parseRecordError(value: unknown): UsbRecordError {
  const v = object(value)
  return { record_id: nullable(v.record_id, text), message: text(v.message) }
}
function parseSession(value: unknown): UsbSessionSummary {
  const v = object(value)
  return { session_id: text(v.session_id), device: parseDevice(v.device), storages: array(v.storages, parseStorage), connected_at: text(v.connected_at), last_device_response_at: text(v.last_device_response_at), closing: bool(v.closing) }
}
function parseStatus(value: unknown): UsbStatus {
  const v = object(value)
  return { instance_id: text(v.instance_id), revision: integer(v.revision), platform_supported: bool(v.platform_supported), platform_reason: nullable(v.platform_reason, text), dependency_available: bool(v.dependency_available), dependency_state: choice(v.dependency_state, ['unsupported', 'missing', 'located', 'loaded', 'failed'] as const), dependency_reason: nullable(v.dependency_reason, text), worker_running: bool(v.worker_running), busy: bool(v.busy), session: nullable(v.session, parseSession), record_errors: array(v.record_errors, parseRecordError) }
}
function parseEntry(value: unknown): UsbDirectoryEntry {
  const v = object(value)
  return { object_id: integer(v.object_id), parent_id: integer(v.parent_id), storage_id: integer(v.storage_id), raw_name: text(v.raw_name), name: text(v.name), is_folder: bool(v.is_folder), size_bytes: nullable(v.size_bytes, integer), modified_at: nullable(v.modified_at, text) }
}
function parseCopy(value: unknown): UsbCopyRequest {
  const v = object(value)
  return { instance_id: text(v.instance_id), session_id: text(v.session_id), direction: choice(v.direction, ['download', 'upload'] as const), source_objects: array(v.source_objects, (item) => { const ref = object(item); return { storage_id: integer(ref.storage_id), object_id: integer(ref.object_id) } }), source_paths: array(v.source_paths, text), local_target: nullable(v.local_target, text), target_storage_id: nullable(v.target_storage_id, integer), target_folder_id: nullable(v.target_folder_id, integer) }
}
function parseProgress(value: unknown): UsbProgress {
  const v = object(value)
  return { stage: text(v.stage), current_name: text(v.current_name), discovered: integer(v.discovered), processed: integer(v.processed), known_bytes: integer(v.known_bytes), total_known: bool(v.total_known), current_sent: integer(v.current_sent), current_total: nullable(v.current_total, integer) }
}
function parseCounts(value: unknown): UsbCounts {
  const v = object(value)
  return { succeeded: integer(v.succeeded), reused: integer(v.reused), skipped: integer(v.skipped), failed: integer(v.failed), unexecuted: integer(v.unexecuted), unconfirmed: integer(v.unconfirmed), copied_bytes: integer(v.copied_bytes), effects: integer(v.effects) }
}
function parseTask(value: unknown): UsbTaskSummary {
  const v = object(value)
  const intent = nullable(v.active_intent, (item) => Object.fromEntries(Object.entries(object(item)).map(([key, field]) => [key, text(field)])))
  return { task_id: text(v.task_id), request: parseCopy(v.request), target_label: text(v.target_label), state: choice(v.state, ['queued', 'running', 'cancelling', 'completed', 'partial_success', 'failed', 'cancelled', 'interrupted'] as const), created_at: number(v.created_at), updated_at: number(v.updated_at), revision: integer(v.revision), progress: parseProgress(v.progress), counts: parseCounts(v.counts), entry_count: integer(v.entry_count), planned_count: integer(v.planned_count), enumeration_complete: bool(v.enumeration_complete), stop_reason: text(v.stop_reason), message: text(v.message), cancel_requested: bool(v.cancel_requested), active_intent: intent, record_error: nullable(v.record_error, text), historical: bool(v.historical) }
}
function parseResult(value: unknown): UsbEntryResult {
  const v = object(value)
  return { entry_id: text(v.entry_id), source: text(v.source), raw_name: text(v.raw_name), destination: text(v.destination), status: choice(v.status, ['succeeded', 'skipped', 'failed', 'unexecuted', 'unconfirmed'] as const), is_folder: bool(v.is_folder), message: text(v.message), size_bytes: nullable(v.size_bytes, integer), effect: bool(v.effect), reused: bool(v.reused), object_id: nullable(v.object_id, integer), residual: nullable(v.residual, text), size_checked: bool(v.size_checked) }
}
function parseTasks(value: unknown): UsbTaskList {
  const v = object(value)
  return { instance_id: text(v.instance_id), tasks: array(v.tasks, parseTask), record_errors: array(v.record_errors, parseRecordError) }
}

async function post<T>(path: string, body: unknown, parse: (value: unknown) => T, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) controller.abort()
  const timeout = setTimeout(() => { timedOut = true; controller.abort() }, path === '/directory/list' ? 120000 : 45000)
  try {
    const response = await apiFetch(`/api/v1/tools/usb-transfer${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: controller.signal,
    })
    return parse(await readApiResponse<unknown>(response, '有线传输请求失败'))
  } catch (error) {
    if (timedOut) throw new Error('请求超时；后端操作可能仍在执行，请查询任务状态，不要盲目重传')
    throw error
  } finally {
    clearTimeout(timeout)
    signal?.removeEventListener('abort', abort)
  }
}
export const fetchUsbStatus = (signal?: AbortSignal) => post('/status', {}, parseStatus, signal)
export const scanUsbDevices = (signal?: AbortSignal) => post('/devices/scan', {}, (value): UsbDeviceList => {
  const v = object(value)
  return { instance_id: text(v.instance_id), scan_id: text(v.scan_id), devices: array(v.devices, parseDevice) }
}, signal)
export const openUsbSession = (instanceId: string, scanId: string, deviceId: string, signal?: AbortSignal) => post('/session/open', { instance_id: instanceId, scan_id: scanId, device_id: deviceId }, parseStatus, signal)
export const closeUsbSession = (instanceId: string, sessionId: string, signal?: AbortSignal) => post('/session/close', { instance_id: instanceId, session_id: sessionId }, parseStatus, signal)
export const fetchUsbDirectory = (instanceId: string, sessionId: string, storageId: number, folderId: number, signal?: AbortSignal) => post('/directory/list', { instance_id: instanceId, session_id: sessionId, storage_id: storageId, folder_id: folderId }, (value): UsbDirectoryList => {
  const v = object(value)
  return { instance_id: text(v.instance_id), session_id: text(v.session_id), storage_id: integer(v.storage_id), folder_id: integer(v.folder_id), entries: array(v.entries, parseEntry), complete: bool(v.complete), missing_ids: array(v.missing_ids, integer), message: text(v.message) }
}, signal)
export const prepareUsbCopy = (request: UsbCopyRequest, signal?: AbortSignal) => post('/tasks/prepare', request, (value): UsbPreparedCopy => {
  const v = object(value)
  return { request: parseCopy(v.request), submission_token: text(v.submission_token), expires_at: number(v.expires_at) }
}, signal)
export const submitUsbCopy = (prepared: UsbPreparedCopy, signal?: AbortSignal) => post('/tasks/submit', { request: prepared.request, submission_token: prepared.submission_token }, parseTask, signal)
export const fetchUsbTasks = (signal?: AbortSignal) => post('/tasks/list', {}, parseTasks, signal)
export const cancelUsbTask = (taskId: string, signal?: AbortSignal) => post('/tasks/cancel', { task_id: taskId }, parseTask, signal)
export const removeUsbRecord = (taskId: string, signal?: AbortSignal) => post('/tasks/remove', { task_id: taskId }, parseTasks, signal)
export const fetchUsbTaskEntries = (taskId: string, offset = 0, signal?: AbortSignal) => post('/tasks/entries', { task_id: taskId, offset, limit: 50 }, (value): UsbTaskEntries => {
  const v = object(value)
  return { instance_id: text(v.instance_id), task: parseTask(v.task), entries: array(v.entries, parseResult), offset: integer(v.offset), total: integer(v.total), next_offset: nullable(v.next_offset, integer) }
}, signal)

export function usbTaskActive(task: UsbTaskSummary): boolean { return ['queued', 'running', 'cancelling'].includes(task.state) }
export function formatUsbSize(bytes: number | null): string {
  if (bytes === null) return '未知'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  let value = bytes / 1024
  let index = 0
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1 }
  return `${value.toFixed(1)} ${units[index]}`
}
