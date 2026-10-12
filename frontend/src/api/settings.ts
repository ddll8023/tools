/** 设置页的本地模型状态与管理 API。 */
import { apiFetch, readApiResponse } from '@/api/client'

export const MINERU_PIPELINE_MODEL_ID = 'mineru-pipeline' as const
export const ID_PHOTO_MODEL_ID = 'id-photo' as const

export type ModelId = typeof MINERU_PIPELINE_MODEL_ID | typeof ID_PHOTO_MODEL_ID
export type ModelStatus =
  | 'not_downloaded'
  | 'downloading'
  | 'ready'
  | 'failed'
  | 'interrupted'
  | 'cancelled'
  | 'incomplete'
  | 'unavailable'

export interface ModelStatusItem {
  model_id: ModelId
  name: string
  description: string
  source: string
  path: string
  approx_size_bytes: number | null
  status: ModelStatus
  progress: number | null
  stage: string
  error: string | null
  job_id: string | null
  can_download: boolean
  can_delete: boolean
  delete_reason: string | null
}

interface ModelStatusResponse {
  models: ModelStatusItem[]
}

export async function fetchModelStatus(): Promise<ModelStatusItem[]> {
  const response = await apiFetch(`/api/v1/settings/models/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  const data = await readApiResponse<ModelStatusResponse>(response, '模型服务请求失败')
  return data.models
}

export async function startModelDownload(modelId: ModelId): Promise<ModelStatusItem> {
  const response = await apiFetch(`/api/v1/settings/models/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
  })
  return readApiResponse<ModelStatusItem>(response, '模型服务请求失败')
}

export async function cancelModelDownload(modelId: ModelId): Promise<ModelStatusItem> {
  const response = await apiFetch(`/api/v1/settings/models/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
  })
  return readApiResponse<ModelStatusItem>(response, '模型服务请求失败')
}

export async function deleteModel(modelId: ModelId): Promise<ModelStatusItem> {
  const response = await apiFetch(`/api/v1/settings/models/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
  })
  return readApiResponse<ModelStatusItem>(response, '模型服务请求失败')
}
