import type { ApiResponse } from '@/types/tool'

const API_BASE = 'http://127.0.0.1:4740'

export const MINERU_PIPELINE_MODEL_ID = 'mineru-pipeline' as const

export type ModelId = typeof MINERU_PIPELINE_MODEL_ID
export type ModelStatus =
  | 'not_downloaded'
  | 'downloading'
  | 'ready'
  | 'failed'
  | 'interrupted'
  | 'cancelled'

export interface ModelStatusItem {
  model_id: ModelId
  name: string
  description: string
  source: string
  path: string
  approx_size_bytes: number
  status: ModelStatus
  progress: number | null
  stage: string
  error: string | null
  job_id: string | null
}

interface ModelStatusResponse {
  models: ModelStatusItem[]
}

async function readModelResponse<T>(response: Response): Promise<T> {
  const json: ApiResponse<T> = await response.json()
  if (json.code !== 0 || json.data === null) {
    throw new Error(json.message || '模型服务请求失败')
  }
  return json.data
}

export async function fetchModelStatus(): Promise<ModelStatusItem[]> {
  const response = await fetch(`${API_BASE}/api/v1/settings/models/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  const data = await readModelResponse<ModelStatusResponse>(response)
  return data.models
}

export async function startModelDownload(modelId: ModelId): Promise<ModelStatusItem> {
  const response = await fetch(`${API_BASE}/api/v1/settings/models/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
  })
  return readModelResponse<ModelStatusItem>(response)
}

export async function cancelModelDownload(modelId: ModelId): Promise<ModelStatusItem> {
  const response = await fetch(`${API_BASE}/api/v1/settings/models/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
  })
  return readModelResponse<ModelStatusItem>(response)
}
