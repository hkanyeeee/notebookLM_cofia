import axios from 'axios'
import { useSessionStore } from '@/stores/session'

// 使用与 notebook.ts 相同的 API 配置
const API_BASE_URL = 'http://127.0.0.1:8000'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 1800000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    const sessionStore = useSessionStore()
    const sessionId = sessionStore.getSessionId()

    if (sessionId && config.headers) {
      config.headers['X-Session-ID'] = sessionId
    }

    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 通用请求函数
async function request<T = any>(url: string, options: { method: string; data?: any } = { method: 'GET' }): Promise<T> {
  try {
    const response = await api.request({
      url,
      method: options.method,
      data: options.data
    })
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error)) {
      throw new Error(error.response?.data?.detail || error.message)
    }
    throw error
  }
}

export interface CollectionStatus {
  id: number
  title: string
  chunks_count: number
  qdrant_count: number
  needs_fix: boolean
  status: 'complete' | 'missing' | 'partial'
}

export interface CollectionsStatusResponse {
  success: boolean
  collections: CollectionStatus[]
  stats: {
    total_collections: number
    needs_fix: number
    total_chunks: number
    missing_vectors: number
  }
}

export interface FixTaskStatus {
  status: 'running' | 'completed' | 'failed'
  total_collections: number
  completed_collections: number
  current_collection?: string
  total_chunks: number
  processed_chunks: number
  errors: number
  error?: string
}

export interface FixResponse {
  success: boolean
  task_id?: string
  message: string
}

export interface VerifyResult {
  collection_id: number
  db_chunks: number
  qdrant_points: number
  status: 'complete' | 'missing' | 'partial' | 'unknown'
  samples?: Array<{
    id: string
    content_preview: string
  }>
}

export interface VerifyResponse {
  success: boolean
  result: VerifyResult
}

/**
 * 获取所有集合的向量数据状态
 */
export async function getCollectionsStatus(): Promise<CollectionsStatusResponse> {
  return request('/vector-fix/collections/status', {
    method: 'GET'
  })
}

/**
 * 修复指定集合的向量数据
 */
export async function fixCollection(collectionId: number): Promise<FixResponse> {
  return request(`/vector-fix/collections/${collectionId}/fix`, {
    method: 'POST'
  })
}

/**
 * 修复所有需要修复的集合
 */
export async function fixAllCollections(): Promise<FixResponse> {
  return request('/vector-fix/collections/fix-all', {
    method: 'POST'
  })
}

/**
 * 获取修复任务状态
 */
export async function getFixStatus(taskId: string): Promise<{ success: boolean; status: FixTaskStatus }> {
  return request(`/vector-fix/status/${taskId}`, {
    method: 'GET'
  })
}

/**
 * 验证集合的向量数据
 */
export async function verifyCollection(collectionId: number): Promise<VerifyResponse> {
  return request(`/vector-fix/collections/${collectionId}/verify`, {
    method: 'POST'
  })
}

/**
 * 创建修复进度的EventSource连接
 */
export function createFixProgressStream(taskId: string): EventSource {
  const sessionId = localStorage.getItem('sessionId') || 'default-session'
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
  
  const eventSource = new EventSource(`${baseUrl}/vector-fix/progress/${taskId}`, {
    withCredentials: false
  })
  
  // 手动设置headers（虽然EventSource不支持自定义headers，但我们可以通过URL参数传递）
  // 注意：这里可能需要后端支持通过URL参数传递session_id
  
  return eventSource
}

/**
 * 轮询获取修复进度
 */
export async function pollFixProgress(
  taskId: string,
  onProgress: (status: FixTaskStatus) => void,
  onComplete: (status: FixTaskStatus) => void,
  onError: (error: string) => void
): Promise<void> {
  const poll = async () => {
    try {
      const response = await getFixStatus(taskId)
      const status = response.status
      
      onProgress(status)
      
      if (status.status === 'completed') {
        onComplete(status)
        return
      } else if (status.status === 'failed') {
        onError(status.error || '修复失败')
        return
      }
      
      // 继续轮询
      setTimeout(poll, 1000)
    } catch (error) {
      onError(error instanceof Error ? error.message : '获取状态失败')
    }
  }
  
  poll()
}
