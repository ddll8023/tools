/**
 * 局域网投送控制面 API
 * 功能描述：开启、查询、停止投送会话，设置访问口令，处理待接收文件，管理待取件清单，读写偏好与接收记录
 */

import { apiFetch, readApiResponse } from '@/api/client'

export type LanSessionState = 'idle' | 'starting' | 'active' | 'closing' | 'closed' | 'failed'

export interface LanAddressItem {
  address: string
  url: string
  is_recommended: boolean
}

export interface LanCleanupFailure {
  path: string
  size_bytes: number
}

export interface LanPendingItem {
  upload_id: string
  name: string
  size_bytes: number
  uploaded_at: string
}

export interface LanOutgoingItem {
  file_id: string
  name: string
  size_bytes: number
  available: boolean
}

export interface LanSessionStatus {
  state: LanSessionState
  expires_at: string | null
  remaining_seconds: number
  device_name: string
  has_passphrase: boolean
  pending_count: number
  used_bytes: number
  max_bytes: number
  free_disk_bytes: number | null
  addresses: LanAddressItem[]
  cleanup_failures: LanCleanupFailure[]
  message: string
}

export interface LanPreferences {
  device_name: string
  receive_dir: string
  default_device_name: string
  default_receive_dir: string
  is_customized: boolean
}

export interface LanReceiveRecord {
  name: string
  size_bytes: number
  received_at: string
  destination: string
}

export interface LanRecoveryResult {
  recovered: boolean
  removed_files: number
  removed_bytes: number
  failures: string[]
}

const BASE_PATH = '/api/v1/tools/lan-transfer'
const SESSION_PATH = `${BASE_PATH}/session`
const PENDING_PATH = `${BASE_PATH}/pending`
const SEND_PATH = `${BASE_PATH}/send`
const SETTINGS_PATH = `${BASE_PATH}/settings`

async function postJson<T>(
  path: string,
  body: Record<string, unknown>,
  fallback: string,
): Promise<T> {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return readApiResponse<T>(response, fallback)
}

export async function startLanSession(): Promise<LanSessionStatus> {
  return postJson<LanSessionStatus>(`${SESSION_PATH}/start`, {}, '开启投送失败')
}

export async function fetchLanSessionStatus(): Promise<LanSessionStatus> {
  return postJson<LanSessionStatus>(`${SESSION_PATH}/status`, {}, '读取投送状态失败')
}

export async function stopLanSession(): Promise<LanSessionStatus> {
  return postJson<LanSessionStatus>(`${SESSION_PATH}/stop`, {}, '停止投送失败')
}

/** 传入空字符串表示清除访问口令。 */
export async function setLanPassphrase(passphrase: string): Promise<LanSessionStatus> {
  return postJson<LanSessionStatus>(
    `${SESSION_PATH}/passphrase`,
    { passphrase },
    '设置访问口令失败',
  )
}

async function readPendingList(
  path: string,
  body: Record<string, unknown>,
  fallback: string,
): Promise<LanPendingItem[]> {
  const data = await postJson<{ files: LanPendingItem[] }>(path, body, fallback)
  return data.files
}

export async function fetchPendingFiles(): Promise<LanPendingItem[]> {
  return readPendingList(`${PENDING_PATH}/list`, {}, '读取待接收列表失败')
}

export async function acceptPendingFile(uploadId: string): Promise<LanPendingItem[]> {
  return readPendingList(`${PENDING_PATH}/accept`, { upload_id: uploadId }, '接收文件失败')
}

export async function rejectPendingFile(uploadId: string): Promise<LanPendingItem[]> {
  return readPendingList(`${PENDING_PATH}/reject`, { upload_id: uploadId }, '拒绝文件失败')
}

async function readOutgoingList(
  path: string,
  body: Record<string, unknown>,
  fallback: string,
): Promise<LanOutgoingItem[]> {
  const data = await postJson<{ files: LanOutgoingItem[] }>(path, body, fallback)
  return data.files
}

export async function fetchOutgoingFiles(): Promise<LanOutgoingItem[]> {
  return readOutgoingList(`${SEND_PATH}/list`, {}, '读取待取件列表失败')
}

/** 传入本机绝对路径数组，后端原地读取，不复制文件。 */
export async function addOutgoingFiles(paths: string[]): Promise<LanOutgoingItem[]> {
  return readOutgoingList(`${SEND_PATH}/add`, { paths }, '添加待投送文件失败')
}

export async function removeOutgoingFile(fileId: string): Promise<LanOutgoingItem[]> {
  return readOutgoingList(`${SEND_PATH}/remove`, { file_id: fileId }, '移除待投送文件失败')
}

export async function fetchLanPreferences(): Promise<LanPreferences> {
  return postJson<LanPreferences>(`${SETTINGS_PATH}/get`, {}, '读取投送设置失败')
}

/** 设备名与接收目录传 undefined 表示不修改，传空字符串表示回退默认值。 */
export async function updateLanPreferences(payload: {
  device_name?: string
  receive_dir?: string
}): Promise<LanPreferences> {
  return postJson<LanPreferences>(`${SETTINGS_PATH}/update`, payload, '保存投送设置失败')
}

export async function fetchLanReceiveRecords(): Promise<LanReceiveRecord[]> {
  const data = await postJson<{ records: LanReceiveRecord[] }>(
    `${BASE_PATH}/records/list`,
    {},
    '读取接收记录失败'
  )
  return data.records
}

export async function fetchLanRecovery(): Promise<LanRecoveryResult> {
  return postJson<LanRecoveryResult>(`${BASE_PATH}/recovery/last`, {}, '读取回收结果失败')
}
