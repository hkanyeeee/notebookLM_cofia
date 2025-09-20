import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'
import { useDocumentStore } from './useDocumentStore'
import { useMessageStore } from './useMessageStore'
import { useCollectionStore } from './useCollectionStore'
import { useModelStore } from './useModelStore'
import { QueryType } from './types'

// 重新导出类型，保持向后兼容
export { QueryType } from './types'
export type { Document, Source, Message, IngestionProgress } from './types'

// 从本地存储读取保存的工具启用状态
function getStoredToolsEnabled(): boolean {
  try {
    const stored = localStorage.getItem('tools_enabled')
    return stored !== null ? JSON.parse(stored) : true // 默认启用
  } catch {
    return true
  }
}

// 保存工具启用状态到本地存储
function storeToolsEnabled(enabled: boolean) {
  try {
    localStorage.setItem('tools_enabled', JSON.stringify(enabled))
  } catch {
    // 忽略存储错误
  }
}

export const useNotebookStore = defineStore('notebook', () => {
  // 问答类型状态
  const queryType = ref<QueryType>(QueryType.NORMAL) // 默认为普通问答
  
  // 工具启用状态（仅对普通问答有效）
  const toolsEnabled = ref<boolean>(getStoredToolsEnabled())

  // 监听工具启用状态变化，自动保存到本地存储
  watch(toolsEnabled, (newValue) => {
    storeToolsEnabled(newValue)
  })

  // 初始化各个子store
  const modelStore = useModelStore()
  const documentStore = useDocumentStore(modelStore.selectedModel.value)
  const messageStore = useMessageStore()
  const collectionStore = useCollectionStore()

  // 计算属性：是否处于Collection查询模式（当问答类型为COLLECTION或选择了collection时）
  const isCollectionQueryMode = computed(() => 
    queryType.value === QueryType.COLLECTION || !!collectionStore.selectedCollection.value
  )
  
  // 计算属性：当前模式是否应该启用web search工具
  const shouldUseWebSearch = computed(() => 
    queryType.value === QueryType.NORMAL  // 只有普通问答使用web search
  )

  // 合并loading状态
  const loading = computed(() => ({
    querying: false, // 这个状态会在sendQuery中动态管理
    addingDocument: false,
    triggeringAutoIngest: collectionStore.loading.triggeringAutoIngest,
    loadingCollections: collectionStore.loading.loadingCollections,
    queryingCollection: collectionStore.loading.queryingCollection,
    deletingCollection: collectionStore.loading.deletingCollection,
    loadingModels: modelStore.loading.loadingModels
  }))

  // 实际的查询状态
  const queryingState = ref(false)

  // 增强的sendQuery方法，处理所有类型的查询
  async function sendQuery(query: string) {
    queryingState.value = true
    
    try {
      // 如果问答类型为COLLECTION，执行Collection查询
      if (queryType.value === QueryType.COLLECTION) {
        return await collectionStore.performCollectionQuery(
          query, 
          queryType.value,
          false, // Collection问答不使用web search
          messageStore.messages.value,
          (messageIndex: number, messageUpdate: any) => {
            messageStore.messages.value[messageIndex] = {
              ...messageStore.messages.value[messageIndex],
              ...messageUpdate
            }
          },
          modelStore.selectedModel.value  // 传递当前选择的模型
        )
      }
      
      // 否则执行普通/文档查询
      return await messageStore.sendQuery(
        query,
        queryType.value,
        modelStore.selectedModel.value,
        documentStore.documents.value.map(doc => doc.id),
        undefined, // performCollectionQuery参数
        queryType.value === QueryType.NORMAL ? toolsEnabled.value : undefined // 仅普通问答传递工具启用状态
      )
    } finally {
      queryingState.value = false
    }
  }

  // 监听文档添加成功，自动切换问答类型
  function handleDocumentAdded() {
    if (queryType.value === QueryType.NORMAL) {
      queryType.value = QueryType.DOCUMENT
    }
  }

  // 监听collection添加成功，自动切换问答类型  
  function handleCollectionAdded() {
    if (queryType.value === QueryType.NORMAL) {
      queryType.value = QueryType.DOCUMENT
    }
  }

  // 重写loading的getter，包含实际的查询状态
  const loadingWithQuery = computed(() => ({
    ...loading.value,
    querying: queryingState.value
  }))

  // 监听问答类型切换，自动清空聊天历史和候选网址
  watch(queryType, (newType, oldType) => {
    if (oldType !== undefined && newType !== oldType) {
      messageStore.clearMessages()
      // 当切换到非文档问答模式时，清空候选网址和课题输入
      if (newType !== QueryType.DOCUMENT) {
        documentStore.candidateUrls.value = []
        documentStore.topicInput.value = ''
      }
      // 当切换到非Collection模式时，清空选中的collection
      if (newType !== QueryType.COLLECTION) {
        collectionStore.selectedCollection.value = ''
      }
      console.log(`问答类型从 ${oldType} 切换到 ${newType}，已清空聊天历史`)
    }
  })

  return {
    // 问答类型相关
    queryType,
    isCollectionQueryMode,
    shouldUseWebSearch,
    
    // 工具配置
    toolsEnabled,
    
    // 文档相关 (来自 documentStore)
    documents: documentStore.documents,
    topicInput: documentStore.topicInput,
    candidateUrls: documentStore.candidateUrls,
    generating: documentStore.generating,
    ingestionStatus: documentStore.ingestionStatus,
    
    // 消息相关 (来自 messageStore)
    messages: messageStore.messages,
    
    // Collection相关 (来自 collectionStore)  
    autoIngestUrl: collectionStore.autoIngestUrl,
    collections: collectionStore.collections,
    selectedCollection: collectionStore.selectedCollection,
    collectionQueryInput: collectionStore.collectionQueryInput,
    
    // 模型相关 (来自 modelStore)
    models: modelStore.models,
    selectedModel: modelStore.selectedModel,
    
    // 加载状态
    loading: loadingWithQuery,
    
    // 文档方法
    addDocument: documentStore.addDocument,
    cancelIngestion: documentStore.cancelIngestion,
    removeDocument: documentStore.removeDocument,
    generateCandidatesFromTopic: documentStore.generateCandidatesFromTopic,
    addCandidate: documentStore.addCandidate,
    
    // 消息方法
    sendQuery,
    clearMessages: messageStore.clearMessages,
    startEditMessage: messageStore.startEditMessage,
    cancelEditMessage: messageStore.cancelEditMessage,
    updateEditingMessage: messageStore.updateEditingMessage,
    resendEditedMessage: (messageId: string) => messageStore.resendEditedMessage(
      messageId,
      queryType.value,
      modelStore.selectedModel.value,
      documentStore.documents.value.map(doc => doc.id),
      queryType.value === QueryType.COLLECTION ? 
        ((query: string) => collectionStore.performCollectionQuery(
          query,
          queryType.value,
          false,
          messageStore.messages.value,
          (messageIndex: number, messageUpdate: any) => {
            messageStore.messages.value[messageIndex] = {
              ...messageStore.messages.value[messageIndex],
              ...messageUpdate
            }
          },
          modelStore.selectedModel.value  // 传递当前选择的模型
        )) : undefined,
      queryType.value === QueryType.NORMAL ? toolsEnabled.value : undefined // 仅普通问答传递工具启用状态
    ),
    
    // Collection方法
    triggerAutoIngest: collectionStore.triggerAutoIngest,
    loadCollections: collectionStore.loadCollections,
    performCollectionQuery: collectionStore.performCollectionQuery,
    queryCollection: collectionStore.queryCollection,
    clearCollectionResults: collectionStore.clearCollectionResults,
    deleteCollection: collectionStore.deleteCollection,
    
    // 模型方法
    loadModels: modelStore.loadModels,
    
  }
})
