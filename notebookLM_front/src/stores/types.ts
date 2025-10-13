// 问答类型枚举
export enum QueryType {
  NORMAL = 'normal',      // 普通问答（启用web search）
  DOCUMENT = 'document',  // 文档问答（不启用web search）
}

// Document interface
export interface Document {
  id: string
  title: string
  url: string
  createdAt: Date
}

// Source interface for query results
export interface Source {
  url: string;
  content: string;
  score: number;
}

// Message interface
export interface Message {
  id: string
  type: 'user' | 'assistant'
  content: string
  timestamp: Date
  sources?: Source[] // Optional sources for assistant messages
  reasoning?: string // Optional reasoning chain for assistant messages
  isEditing?: boolean // Optional flag to indicate if message is being edited
  originalContent?: string // Optional field to store original content during editing
}

// Ingestion status interface for a single URL
export interface IngestionProgress {
  progress: number
  total: number
  message: string
  inProgress: boolean
  error: boolean
}
