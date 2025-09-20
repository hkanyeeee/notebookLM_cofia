/**
 * Agentic Ingest API 客户端
 */

import { apiRequest } from './notebook'

// 任务状态枚举
export enum TaskStatus {
  PENDING = 'pending',
  RUNNING = 'running',
  COMPLETED = 'completed',
  PARTIALLY_COMPLETED = 'partially_completed',
  FAILED = 'failed'
}

// 子文档任务信息
export interface SubDocTask {
  url: string
  status: TaskStatus
  error?: string
  started_at?: string
  completed_at?: string
}

// 摄取任务状态
export interface IngestTaskStatus {
  task_id: string
  parent_url: string
  document_name: string
  collection_name: string
  total_sub_docs: number
  completed_sub_docs: number
  failed_sub_docs: number
  status: TaskStatus
  created_at: string
  started_at?: string
  completed_at?: string
  error?: string
  sub_docs: SubDocTask[]
  progress_percentage: number
}

// Agentic Ingest 请求参数
export interface AgenticIngestRequest {
  url: string
  model?: string
  embedding_model?: string
  embedding_dimensions?: number
  webhook_url?: string
  recursive_depth?: number
  webhook_fallback?: boolean
}

// Agentic Ingest 响应
export interface AgenticIngestResponse {
  success: boolean
  message: string
  document_name: string
  collection_name: string
  total_chunks: number
  source_id: number
  sub_docs_task_id?: string
  sub_docs_count?: number
  sub_docs_processing?: boolean
}

/**
 * 执行 Agentic Ingest
 */
export async function agenticIngest(params: AgenticIngestRequest): Promise<AgenticIngestResponse> {
  const response = await apiRequest('/api/agenttic-ingest', {
    method: 'POST',
    body: JSON.stringify(params)
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '摄取失败')
  }
  
  return response.json()
}

/**
 * 获取摄取任务状态
 */
export async function getIngestTaskStatus(taskId: string): Promise<IngestTaskStatus> {
  const response = await apiRequest(`/api/ingest-status/${taskId}`)
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取任务状态失败')
  }
  
  const result = await response.json()
  return result.status
}

/**
 * 获取所有活跃的摄取任务
 */
export async function listIngestTasks(): Promise<IngestTaskStatus[]> {
  const response = await apiRequest('/api/ingest-tasks')
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '获取任务列表失败')
  }
  
  const result = await response.json()
  return result.tasks
}

/**
 * 删除摄取任务
 */
export async function deleteIngestTask(taskId: string): Promise<void> {
  const response = await apiRequest(`/api/ingest-task/${taskId}`, {
    method: 'DELETE'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || '删除任务失败')
  }
}

/**
 * 创建摄取进度流
 */
export function createIngestProgressStream(taskId: string): EventSource {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
  const url = `${baseUrl}/api/ingest-progress/${taskId}`
  
  const eventSource = new EventSource(url)
  
  eventSource.onerror = (event) => {
    console.error('摄取进度流连接错误:', event)
  }
  
  return eventSource
}

/**
 * 轮询获取摄取进度
 */
export async function pollIngestProgress(
  taskId: string,
  onProgress: (status: IngestTaskStatus) => void,
  onComplete: (status: IngestTaskStatus) => void,
  onError: (error: string) => void
): Promise<void> {
  const poll = async () => {
    try {
      const status = await getIngestTaskStatus(taskId)
      
      onProgress(status)
      
      if (status.status === TaskStatus.COMPLETED || status.status === TaskStatus.PARTIALLY_COMPLETED) {
        onComplete(status)
        return
      } else if (status.status === TaskStatus.FAILED) {
        onError(status.error || '摄取失败')
        return
      }
      
      // 继续轮询
      setTimeout(poll, 2000) // 2秒间隔
    } catch (error) {
      onError(error instanceof Error ? error.message : '获取状态失败')
    }
  }
  
  poll()
}
