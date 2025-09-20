import { ref, reactive } from 'vue'
import { notebookApi, type AgenticIngestRequest, type AgenticCollection, type CollectionQueryRequest, type CollectionResult } from '../api/notebook'
import type { Message } from './types'
import { QueryType } from './types'
import { useModelStore } from './useModelStore'

export function useCollectionStore() {
  // 获取模型 store
  const modelStore = useModelStore()
  
  // Agentic Ingest相关状态
  const agenticIngestUrl = ref<string>('')
  
  // Collection相关状态
  const collections = ref<AgenticCollection[]>([])
  const selectedCollection = ref<string>('')
  const collectionQueryInput = ref<string>('')

  const loading = reactive({
    triggeringAgenticIngest: false,
    loadingCollections: false,
    queryingCollection: false,
    deletingCollection: false,
  })

  // 触发agentic ingest
  async function triggerAgenticIngest() {
    const url = agenticIngestUrl.value.trim()
    if (!url) {
      throw new Error('请输入要处理的URL')
    }

    loading.triggeringAgenticIngest = true
    try {
      const request: AgenticIngestRequest = {
        url,
        model: modelStore.selectedModel.value,
        embedding_model: 'Qwen/Qwen3-Embedding-0.6B',
        embedding_dimensions: 1024,
        recursive_depth: 2
      }

      const response = await notebookApi.triggerAgenticIngest(request)
      if (response.success) {
        // 处理成功，清空输入框并刷新collection列表
        agenticIngestUrl.value = ''
        await loadCollections()
        return {
          success: true,
          message: response.message,
          document_name: response.document_name
        }
      } else {
        throw new Error(response.message || 'Agentic ingest失败')
      }
    } catch (error: any) {
      console.error('触发agentic ingest失败:', error)
      throw error
    } finally {
      loading.triggeringAgenticIngest = false
    }
  }

  // 获取collection列表
  async function loadCollections() {
    loading.loadingCollections = true
    try {
      const response = await notebookApi.getCollections()
      if (response.success) {
        collections.value = response.collections
      } else {
        console.error('获取collection列表失败')
        collections.value = []
      }
    } catch (error) {
      console.error('获取collection列表出错:', error)
      collections.value = []
    } finally {
      loading.loadingCollections = false
    }
  }

  // 执行Collection查询的独立方法
  async function performCollectionQuery(
    query: string, 
    queryType: QueryType,
    _unused: boolean, // 保持参数兼容，但不再使用
    messages: Message[],
    onMessageUpdate: (messageIndex: number, message: Partial<Message>) => void,
    selectedModel?: string  // 添加模型参数
  ) {
    const collectionId = selectedCollection.value || ''
    
    // 如果问答类型是COLLECTION但没有选择collection，抛出错误
    if (queryType === QueryType.COLLECTION && !collectionId) {
      throw new Error('请选择一个Collection')
    }

    // 添加用户消息
    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: query,
      timestamp: new Date()
    }
    messages.push(userMessage)

    // 创建助手回复消息
    const assistantMessage: Message = {
      id: (Date.now() + 1).toString(),
      type: 'assistant',
      content: '',
      timestamp: new Date(),
      sources: [],
      reasoning: ''
    }
    messages.push(assistantMessage)
    const messageIndex = messages.length - 1

    loading.queryingCollection = true

    try {
      const request: CollectionQueryRequest = {
        collection_id: collectionId,
        query,
        top_k: 20,
        model: selectedModel  // 传递选中的模型
      }
      
      // Collection问答不使用web search工具
      // 移除web search工具配置，确保只使用collection内的内容

      // 使用流式查询
      await notebookApi.queryCollectionStream(
        request,
        (data) => {
          // 处理流式数据
          if (data.type === 'status') {
            // 更新消息内容显示状态信息
            onMessageUpdate(messageIndex, {
              content: data.message
            })
          } else if (data.type === 'search_results') {
            // 搜索结果摘要
            onMessageUpdate(messageIndex, {
              content: data.message
            })
          } else if (data.type === 'llm_start') {
            // 开始生成LLM回答
            onMessageUpdate(messageIndex, {
              content: '处理中...'
            })
          } else if (data.type === 'content') {
            // LLM生成的内容
            const currentMessage = messages[messageIndex]
            const newContent = (currentMessage.content === '处理中...' || 
                              currentMessage.content.includes('处理中') ||
                              currentMessage.content.includes('找到') && currentMessage.content.includes('个相关结果')) 
                              ? data.content 
                              : currentMessage.content + data.content
            
            onMessageUpdate(messageIndex, {
              content: newContent
            })
          } else if (data.type === 'reasoning') {
            // 思维链内容
            const currentMessage = messages[messageIndex]
            onMessageUpdate(messageIndex, {
              reasoning: (currentMessage.reasoning || '') + data.content
            })
          } else if (data.type === 'sources') {
            // 参考来源数据
            onMessageUpdate(messageIndex, {
              sources: data.sources
            })
          } else if (data.type === 'error') {
            // 错误信息
            onMessageUpdate(messageIndex, {
              content: `❌ ${data.message}`
            })
          } else if (data.type === 'complete') {
            // 完成
            console.log('流式查询完成')
          }
        },
        () => {
          // 查询完成
          console.log('Collection流式查询完成')
        },
        (error) => {
          // 查询出错
          console.error('Collection流式查询出错:', error)
          onMessageUpdate(messageIndex, {
            content: `❌ 查询失败: ${error.message}`
          })
        }
      )

    } catch (error: any) {
      console.error('Collection查询失败:', error)
      
      // 更新消息显示错误
      if (messages[messageIndex]) {
        onMessageUpdate(messageIndex, {
          content: `❌ 查询失败: ${error.message}`
        })
      }
      
      throw error
    } finally {
      loading.queryingCollection = false
    }
  }

  // 基于指定collection进行查询
  async function queryCollection(selectedModel?: string) {
    const query = collectionQueryInput.value.trim()
    const collectionId = selectedCollection.value
    
    if (!query) {
      throw new Error('请输入查询内容')
    }
    if (!collectionId) {
      throw new Error('请选择一个Collection')
    }

    loading.queryingCollection = true
    try {
      const request: CollectionQueryRequest = {
        collection_id: collectionId,
        query,
        top_k: 20,
        model: selectedModel  // 传递选中的模型
      }

      const response = await notebookApi.queryCollection(request)
      if (response.success) {
        return {
          success: true,
          message: response.message,
          total_found: response.total_found,
          results: response.results
        }
      } else {
        throw new Error(response.message || 'Collection查询失败')
      }
    } catch (error: any) {
      console.error('Collection查询失败:', error)
      throw error
    } finally {
      loading.queryingCollection = false
    }
  }

  // 清空collection查询结果
  function clearCollectionResults() {
    collectionQueryInput.value = ''
  }

  // 删除collection
  async function deleteCollection(collectionId: string) {
    loading.deletingCollection = true
    try {
      const response = await notebookApi.deleteCollection(collectionId)
      if (response.success) {
        // 删除成功后刷新collection列表
        await loadCollections()
        
        // 如果删除的是当前选中的collection，则清空选择
        if (selectedCollection.value === collectionId) {
          selectedCollection.value = ''
        }
        
        return {
          success: true,
          message: response.message,
          deleted_chunks_count: response.deleted_chunks_count
        }
      } else {
        throw new Error(response.message || 'Collection删除失败')
      }
    } catch (error: any) {
      console.error('删除Collection失败:', error)
      throw error
    } finally {
      loading.deletingCollection = false
    }
  }

  return {
    // 状态
    agenticIngestUrl,
    collections,
    selectedCollection,
    collectionQueryInput,
    loading,
    
    // 方法
    triggerAgenticIngest,
    loadCollections,
    performCollectionQuery,
    queryCollection,
    clearCollectionResults,
    deleteCollection,
  }
}
