import { ref, reactive } from 'vue'
import { defineStore } from 'pinia'
import { notebookApi } from '../api/notebook'

// 文档接口
interface Document {
  id: string
  title: string
  url: string
  createdAt: Date
}

// 消息接口
interface Message {
  id: string
  type: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export const useNotebookStore = defineStore('notebook', () => {
  // 文档列表
  const documents = ref<Document[]>([])

  // 对话历史
  const messages = ref<Message[]>([])

  // 加载状态
  const loading = reactive({
    addingDocument: false,
    querying: false,
  })

  // 添加文档（网址）
  async function addDocument(url: string) {
    loading.addingDocument = true
    try {
      const response = await notebookApi.ingestDocument(url)

      const newDoc: Document = {
        id: response.document_id,
        title: response.title || `文档 ${documents.value.length + 1}`,
        url: url,
        createdAt: new Date(),
      }

      documents.value.push(newDoc)
      return newDoc
    } catch (error) {
      console.error('添加文档失败:', error)
      throw error
    } finally {
      loading.addingDocument = false
    }
  }

  // 删除文档
  async function removeDocument(id: string) {
    try {
      const response = await notebookApi.deleteDocument(id)
      if (response.success) {
        const index = documents.value.findIndex((doc) => doc.id === id)
        if (index > -1) {
          documents.value.splice(index, 1)
        }
      } else {
        // 如果后端返回 success: false，可以抛出错误或记录日志
        throw new Error(response.message || 'Failed to delete document on the server.')
      }
    } catch (error) {
      console.error('删除文档失败:', error)
      // 重新抛出错误，以便UI层可以捕获并显示消息
      throw error
    }
  }

  // 发送查询
  async function sendQuery(query: string) {
    // 添加用户消息
    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: query,
      timestamp: new Date(),
    }
    messages.value.push(userMessage)

    loading.querying = true
    try {
      // 获取所有文档ID用于查询
      const documentIds = documents.value.map((doc) => doc.id)

      const response = await notebookApi.queryDocuments(query, documentIds)

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: response.answer,
        timestamp: new Date(),
      }
      messages.value.push(assistantMessage)

      return assistantMessage
    } catch (error) {
      console.error('查询失败:', error)
      throw error
    } finally {
      loading.querying = false
    }
  }

  // 清空对话
  function clearMessages() {
    messages.value = []
  }

  return {
    documents,
    messages,
    loading,
    addDocument,
    removeDocument,
    sendQuery,
    clearMessages,
  }
})
