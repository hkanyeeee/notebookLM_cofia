import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { useDocumentStore } from './useDocumentStore'
import { useMessageStore } from './useMessageStore'
import { useCollectionStore } from './useCollectionStore'
import { useModelStore } from './useModelStore'
import { QueryType } from './types'

// 重新导出类型，保持向后兼容
export { QueryType } from './types'
export type { Document, Source, Message, IngestionProgress } from './types'

export const useNotebookStore = defineStore('notebook', () => {
  // 问答类型状态
  const queryType = ref<QueryType>(QueryType.NORMAL) // 默认为普通问答

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
    triggeringAgenticIngest: collectionStore.loading.triggeringAgenticIngest,
    loadingCollections: collectionStore.loading.loadingCollections,
    queryingCollection: collectionStore.loading.queryingCollection,
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
          }
        )
      }
      
      // 否则执行普通/文档查询
      return await messageStore.sendQuery(
        query,
        queryType.value,
        modelStore.selectedModel.value,
        documentStore.documents.value.map(doc => doc.id)
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

  return {
    // 问答类型相关
    queryType,
    isCollectionQueryMode,
    shouldUseWebSearch,
    
    // 文档相关 (来自 documentStore)
    documents: documentStore.documents,
    topicInput: documentStore.topicInput,
    candidateUrls: documentStore.candidateUrls,
    generating: documentStore.generating,
    ingestionStatus: documentStore.ingestionStatus,
    
    // 消息相关 (来自 messageStore)
    messages: messageStore.messages,
    
    // Collection相关 (来自 collectionStore)  
    agenticIngestUrl: collectionStore.agenticIngestUrl,
    collections: collectionStore.collections,
    selectedCollection: collectionStore.selectedCollection,
    collectionQueryResults: collectionStore.collectionQueryResults,
    collectionQueryInput: collectionStore.collectionQueryInput,
    
    // 模型相关 (来自 modelStore)
    models: modelStore.models,
    selectedModel: modelStore.selectedModel,
    normalChatModelError: modelStore.normalChatModelError,
    NORMAL_CHAT_MODEL: modelStore.NORMAL_CHAT_MODEL,
    
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
          }
        )) : undefined
    ),
    
    // Collection方法
    triggerAgenticIngest: collectionStore.triggerAgenticIngest,
    loadCollections: collectionStore.loadCollections,
    performCollectionQuery: collectionStore.performCollectionQuery,
    queryCollection: collectionStore.queryCollection,
    clearCollectionResults: collectionStore.clearCollectionResults,
    
    // 模型方法
    loadModels: modelStore.loadModels,
    validateNormalChatModel: modelStore.validateNormalChatModel,
    forceSelectNormalChatModel: modelStore.forceSelectNormalChatModel,
    
  }
})
