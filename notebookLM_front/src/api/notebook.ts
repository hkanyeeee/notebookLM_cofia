import axios from 'axios'
import { useSessionStore } from '@/stores/session'

// API基础配置
const API_BASE_URL = 'http://localhost:8000'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000, // 300秒超时
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

    console.log('API请求:', config.method?.toUpperCase(), config.url, config.data)
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    console.log('API响应:', response.status, response.data)
    return response
  },
  (error) => {
    console.error('响应错误:', error.response?.status, error.response?.data)
    return Promise.reject(error)
  }
)

// 接口类型定义
export interface IngestRequest {
  url: string
}

export interface IngestResponse {
  success: boolean
  document_id: string
  title?: string
  message?: string
}

export interface QueryRequest {
  query: string
  document_ids?: string[]
}

export interface QueryResponse {
  success: boolean
  answer: string
  sources?: string[]
  message?: string
}

// API方法
export const notebookApi = {
  // 获取API基础URL
  getBaseUrl(): string {
    return API_BASE_URL
  },

  // 添加文档（摄取网址内容）
  async ingestDocument(
    url: string,
    embedding_model: string = 'Qwen/Qwen3-Embedding-4B',
    embedding_dimensions: number = 2560
  ): Promise<IngestResponse> {
    try {
      const response = await api.post<IngestResponse>('/ingest', {
        url,
        embedding_model,
        embedding_dimensions
      })
      return response.data
    } catch (error: any) {
      return {
        success: false,
        document_id: '',
        title: '',
        message: error.message
      }
    }
  },

  // 查询文档内容
  async queryDocuments(query: string, documentIds?: string[]): Promise<QueryResponse> {
    try {
      const response = await api.post<QueryResponse>('/query', {
        query,
        document_ids: documentIds
      })
      return response.data
    } catch (error: any) {
      return {
        success: false,
        answer: '',
        sources: [],
        message: error.message
      }
    }
  },

  // 删除单个文档
  async deleteDocument(documentId: string): Promise<{ success: boolean; message?: string }> {
    try {
      const response = await api.delete(`/api/documents/${documentId}`)
      return response.data
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || error.message
      }
    }
  }
}

/**
 * 在页面关闭前，通知后端清理会话数据
 * @param sessionId
 */
export function cleanupSession(sessionId: string) {
  const url = `${API_BASE_URL}/api/session/cleanup`
  const data = new Blob([JSON.stringify({ session_id: sessionId })], { type: 'application/json' })
  navigator.sendBeacon(url, data)
  console.log(`Sent cleanup beacon for session: ${sessionId}`)
}
