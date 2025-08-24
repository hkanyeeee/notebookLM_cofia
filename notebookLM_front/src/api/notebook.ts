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

export interface ToolSchema {
  name: string
  description: string
  parameters: {
    type: string
    properties: Record<string, any>
    required?: string[]
  }
}

export interface QueryRequest {
  query: string
  document_ids?: string[]
  tool_mode?: 'off' | 'auto' | 'json' | 'react' | 'harmony'
  tools?: ToolSchema[]
  max_steps?: number
}

export interface QueryResponse {
  success: boolean
  answer: string
  sources?: string[]
  message?: string
  tool_mode?: string
  steps?: Array<{
    type: string
    content: string
    tool_call?: {
      name: string
      arguments: Record<string, any>
    }
    tool_result?: {
      name: string
      result: string
      success: boolean
    }
  }>
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
  llm_answer?: string  // LLM生成的智能回答
}

export interface CollectionResult {
  chunk_id: string
  content: string
  score: number
  source_url: string
  source_title: string
}

// ModelInfo接口定义
export interface ModelInfo {
  id: string;
  name: string;
}

// 预定义工具配置
export const DEFAULT_TOOLS: ToolSchema[] = [
  {
    name: "web_search",
    description: "搜索网络信息并进行智能召回。能够生成搜索关键词，从网络搜索相关内容，爬取网页，进行文档切分、向量化索引，并基于用户查询召回最相关的内容片段。",
    parameters: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "搜索查询内容，可以是问题、关键词或主题"
        },
        session_id: {
          type: "string",
          description: "可选的会话ID，用于关联搜索结果。如果不提供会自动生成"
        },
        retrieve_only: {
          type: "boolean",
          description: "是否只从现有索引检索，不进行新的网络搜索。默认为 false",
          default: false
        }
      },
      required: ["query"]
    }
  }
]

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
  async queryDocuments(
    query: string,
    documentIds?: string[],
    options?: {
      tool_mode?: 'off' | 'auto' | 'json' | 'react' | 'harmony'
      tools?: ToolSchema[]
      max_steps?: number
    }
  ): Promise<QueryResponse> {
    try {
      const response = await api.post<QueryResponse>('/query', {
        query,
        document_ids: documentIds,
        tool_mode: options?.tool_mode,
        tools: options?.tools,
        max_steps: options?.max_steps
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

  // 查询文档内容（启用工具功能）
  async queryDocumentsWithTools(
    query: string,
    documentIds?: string[],
    toolMode: 'auto' | 'json' | 'react' | 'harmony' = 'auto',
    tools?: ToolSchema[],
    maxSteps: number = 6
  ): Promise<QueryResponse> {
    return this.queryDocuments(query, documentIds, {
      tool_mode: toolMode,
      tools: tools,
      max_steps: maxSteps
    })
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
  async generateSearchQueries(topic: string, model?: string): Promise<GenerateQueriesResponse> {
    const payload: any = { topic }
    if (model) {
      payload.model = model
    }
    const resp = await api.post<GenerateQueriesResponse>('/api/search/generate', payload)
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

  // 基于指定collection进行流式查询
  async queryCollectionStream(
    request: CollectionQueryRequest,
    onData: (data: any) => void,
    onComplete?: () => void,
    onError?: (error: any) => void
  ): Promise<void> {
    try {
      const response = await fetch(`${API_BASE_URL}/collections/query-stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': useSessionStore().getSessionId() || ''
        },
        body: JSON.stringify(request)
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('无法创建流读取器')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // 保留最后一个不完整的行

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim()
            if (dataStr && dataStr !== '[DONE]') {
              try {
                const data = JSON.parse(dataStr)
                onData(data)
              } catch (e) {
                console.warn('解析流式数据失败:', e, dataStr)
              }
            }
          }
        }
      }

      onComplete?.()
    } catch (error: any) {
      console.error('流式查询失败:', error)
      onError?.(error)
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
  },

  // 获取可用的LLM模型列表
  async getModels(): Promise<{ success: boolean; models?: ModelInfo[] }> {
    try {
      const response = await api.get('/models')
      return response.data
    } catch (error: any) {
      return {
        success: false,
        models: []
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

/**
 * 工具功能使用示例
 *
 * 以下是如何使用工具功能的不同方式：
 */

/**
 * 工具调用已整合到主要问答流程中：
 * - 普通问答：自动使用智能编排器进行问题拆解-思考-工具调用
 * - 文档问答：仅使用已上传文档，不启用工具
 * - Collection问答：仅使用collection内容，不启用工具
 */
