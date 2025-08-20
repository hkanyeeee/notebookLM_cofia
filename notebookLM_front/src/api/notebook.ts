import axios from 'axios'
import { useSessionStore } from '@/stores/session'

// API基础配置：使用相对路径，便于通过 Nginx 反代统一暴露 9001 端口
// const API_BASE_URL = 'http://127.0.0.1:8000'
const API_BASE_URL = ''

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

export interface GenerateQueriesResponse {
  queries: string[]
}

export interface SearxItem {
  title: string
  url: string
}

export interface SearxResponse {
  items: SearxItem[]
}

// Agentic Ingest相关接口
export interface AgenticIngestRequest {
  url: string
  embedding_model?: string
  embedding_dimensions?: number
  webhook_url?: string
  recursive_depth?: number
}

export interface AgenticIngestResponse {
  success: boolean
  message: string
  document_name: string
  collection_name: string
  total_chunks: number
}



// Collection相关接口
export interface AgenticCollection {
  collection_id: string
  collection_name: string
  document_title: string
  url: string
  created_at: string | null
}

export interface CollectionQueryRequest {
  collection_id: string
  query: string
  top_k?: number
}

export interface CollectionQueryResponse {
  success: boolean
  results: CollectionResult[]
  total_found: number
  message: string
}

export interface CollectionResult {
  chunk_id: string
  content: string
  score: number
  source_url: string
  source_title: string
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
    embedding_model: string = 'Qwen/Qwen3-Embedding-0.6B',
    embedding_dimensions: number = 1024
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
  },

  // 生成搜索查询（课题 -> 3个搜索词）
  async generateSearchQueries(topic: string): Promise<GenerateQueriesResponse> {
    const resp = await api.post<GenerateQueriesResponse>('/api/search/generate', { topic })
    return resp.data
  },

  // 调用 SearxNG 搜索（返回前4条标题+URL）
  async searchSearxng(query: string, count = 4): Promise<SearxResponse> {
    const resp = await api.post<SearxResponse>('/api/search/searxng', { query, count })
    return resp.data
  },



  // 触发agentic ingest
  async triggerAgenticIngest(request: AgenticIngestRequest): Promise<AgenticIngestResponse> {
    try {
      const response = await api.post<AgenticIngestResponse>('/agenttic-ingest', request)
      return response.data
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || error.message,
        document_name: '',
        collection_name: '',
        total_chunks: 0
      }
    }
  },

  // Collection相关API
  // 获取所有可用的collection列表
  async getCollections(): Promise<{ success: boolean; collections: AgenticCollection[]; total: number }> {
    try {
      const response = await api.get('/collections')
      return response.data
    } catch (error: any) {
      return {
        success: false,
        collections: [],
        total: 0
      }
    }
  },

  // 基于指定collection进行查询
  async queryCollection(request: CollectionQueryRequest): Promise<CollectionQueryResponse> {
    try {
      const response = await api.post<CollectionQueryResponse>('/collections/query', request)
      return response.data
    } catch (error: any) {
      return {
        success: false,
        results: [],
        total_found: 0,
        message: error.response?.data?.detail || error.message
      }
    }
  },

  // 获取指定collection的详细信息
  async getCollectionDetail(collectionId: string): Promise<{ success: boolean; collection?: any }> {
    try {
      const response = await api.get(`/collections/${collectionId}`)
      return response.data
    } catch (error: any) {
      return {
        success: false,
        collection: null
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
