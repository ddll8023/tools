/**
 * 控制面 API 客户端
 * 功能描述：统一附带桌面端专属凭据，并复用后端 {code,message,data} 响应壳
 * 依赖：electron/preload.ts 暴露的 desktopApi.getControlToken
 */

import type { ApiResponse } from '@/types/tool'

const API_BASE = 'http://127.0.0.1:18740'

/** 凭据只缓存在渲染进程内存中，不写入 localStorage、cookie 或任何静态资源。 */
let cachedToken: string | null = null

async function resolveToken(): Promise<string> {
  if (cachedToken !== null) return cachedToken
  cachedToken = (await window.desktopApi?.getControlToken?.()) ?? ''
  return cachedToken
}

async function sendWithToken(path: string, init: RequestInit): Promise<Response> {
  const token = await resolveToken()
  if (!token) {
    throw new Error('无法获取桌面端凭据，请通过工具盒子应用使用该功能')
  }
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${token}`)
  return fetch(`${API_BASE}${path}`, { ...init, headers })
}

/**
 * 发送控制面请求。
 * 后端重启会更换凭据，因此首次 401 时丢弃缓存重试一次，仍失败则提示重启应用。
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const response = await sendWithToken(path, init)
  if (response.status !== 401) return response

  cachedToken = null
  const retried = await sendWithToken(path, init)
  if (retried.status === 401) {
    throw new Error('控制面未授权，请重启工具盒子后重试')
  }
  return retried
}

/** 解析统一响应壳；code 非 0 或 data 缺失时抛出后端返回的消息。 */
export async function readApiResponse<T>(response: Response, fallback: string): Promise<T> {
  const json: ApiResponse<T> = await response.json()
  if (json.code !== 0 || json.data === null) {
    throw new Error(json.message || fallback)
  }
  return json.data
}
