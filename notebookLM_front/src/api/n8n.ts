import axios from 'axios'

// API基础URL
// const API_BASE_URL = 'http://localhost:8000'
const API_BASE_URL = ''

// 工作流执行相关接口
export const n8nApi = {
  // 获取工作流执行列表
  async getWorkflowExecutions(params?: {
    sessionId?: string
    status?: string
    limit?: number
  }) {
    const response = await axios.get(`${API_BASE_URL}/workflow-executions`, { params })
    return response.data
  },

  // 获取正在运行的工作流
  async getRunningWorkflows(sessionId?: string) {
    const params = sessionId ? { session_id: sessionId } : {}
    const response = await axios.get(`${API_BASE_URL}/workflow-executions/running`, { params })
    return response.data
  },

  // 创建工作流执行记录
  async createWorkflowExecution(data: {
    execution_id: string
    document_name: string
    workflow_id?: string
    session_id: string
  }) {
    const response = await axios.post(`${API_BASE_URL}/workflow-execution`, data)
    return response.data
  },

  // 更新工作流执行状态
  async updateWorkflowStatus(executionId: string, data: {
    status: 'success' | 'error' | 'stopped'
    stopped_at?: string
  }) {
    const response = await axios.put(`${API_BASE_URL}/workflow-execution/${executionId}/status`, data)
    return response.data
  }
}

// 工作流执行数据类型定义
export interface WorkflowExecution {
  id: number
  executionId: string
  documentName: string
  workflowId?: string
  status: 'running' | 'success' | 'error' | 'stopped'
  startedAt?: string
  stoppedAt?: string
  sessionId: string
}

export interface WorkflowExecutionsResponse {
  success: boolean
  runningWorkflows: WorkflowExecution[]
  workflowHistory: WorkflowExecution[]
  total: number
}
