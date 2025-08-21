import { ref, reactive, computed } from 'vue'
import { defineStore } from 'pinia'
import { notebookApi, type AgenticIngestRequest, type AgenticCollection, type CollectionQueryRequest, type CollectionResult, type ModelInfo, DEFAULT_TOOLS } from '../api/notebook'
import { useSessionStore } from './session'

// 问答类型枚举
export enum QueryType {
  NORMAL = 'normal',      // 普通问答（启用web search）
  DOCUMENT = 'document',  // 文档问答（不启用web search）
  COLLECTION = 'collection' // collection问答（启用web search）
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
}

// Ingestion status interface for a single URL
export interface IngestionProgress {
  progress: number
  total: number
  message: string
  inProgress: boolean
  error: boolean
}

export const useNotebookStore = defineStore('notebook', () => {
  const sessionStore = useSessionStore()

  const documents = ref<Document[]>([])
  const messages = ref<Message[]>([])
  // 课题模式：在未添加任何网址时，允许输入课题并生成候选URL
  const topicInput = ref<string>('')
  const candidateUrls = ref<{ title: string; url: string }[]>([])
  const generating = ref<boolean>(false)
  
  // Agentic Ingest相关状态
  const agenticIngestUrl = ref<string>('')
  
  // Collection相关状态
  const collections = ref<AgenticCollection[]>([])
  const selectedCollection = ref<string>('')
  const collectionQueryResults = ref<CollectionResult[]>([])
  const collectionQueryInput = ref<string>('')
  
  // 模型相关状态
  const models = ref<ModelInfo[]>([])
  const selectedModel = ref<string>('')  // 当前选中的模型ID
  
  // 问答类型状态
  const queryType = ref<QueryType>(QueryType.DOCUMENT) // 默认为文档问答
  
  // 计算属性：是否处于Collection查询模式（当问答类型为COLLECTION或选择了collection时）
  const isCollectionQueryMode = computed(() => queryType.value === QueryType.COLLECTION || !!selectedCollection.value)
  
  // 计算属性：当前模式是否应该启用web search工具
  const shouldUseWebSearch = computed(() => 
    queryType.value === QueryType.NORMAL || queryType.value === QueryType.COLLECTION
  )
  
  const loading = reactive({
    querying: false,
    addingDocument: false,
    exporting: false,
    triggeringAgenticIngest: false,
    loadingCollections: false,
    queryingCollection: false,
    loadingModels: false
  })

  const ingestionStatus = reactive<Map<string, IngestionProgress>>(new Map())
  // 跟踪每个 URL 的 AbortController，用于取消进行中的摄取
  const controllers = new Map<string, AbortController>()

  async function addDocument(url: string) {
    ingestionStatus.set(url, {
      progress: 0,
      total: 0,
      message: '准备中...',
      inProgress: true,
      error: false,
    });

    let timeoutId: number | undefined;
    let controller: AbortController | null = null;
    try {
      controller = new AbortController();
      controllers.set(url, controller);
      timeoutId = window.setTimeout(() => controller?.abort(), 300000);
      const response = await fetch(`${notebookApi.getBaseUrl()}/ingest`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': sessionStore.getSessionId() || '',
        },
        body: JSON.stringify({ url }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Failed to get response reader');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data:')) {
            const jsonStr = line.substring(5);
            if (jsonStr) {
              try {
                const data = JSON.parse(jsonStr);
                const status = ingestionStatus.get(url);
                if (!status) continue;

                switch (data.type) {
                  case 'status':
                    status.message = data.message;
                    break;
                  case 'total_chunks':
                    status.total = data.value;
                    status.message = `发现 ${data.value} 个块`;
                    break;
                  case 'progress':
                    status.progress = data.value;
                    status.message = `正在处理 ${data.value} / ${status.total}`;
                    break;
                  case 'complete':
                    const newDoc: Document = {
                      id: data.document_id,
                      title: data.title || url,
                      url: url,
                      createdAt: new Date(),
                    };
                    if (!documents.value.some(doc => doc.id === newDoc.id)) {
                      documents.value.push(newDoc);
                      // 成功添加文档后自动切换到文档问答模式
                      if (queryType.value === QueryType.NORMAL) {
                        queryType.value = QueryType.DOCUMENT;
                      }
                    }
                    status.message = data.message || '处理完成!';
                    status.inProgress = false;
                    setTimeout(() => ingestionStatus.delete(url), 5000);
                    break;
                  case 'error':
                    status.message = `错误: ${data.message}`;
                    status.inProgress = false;
                    status.error = true;
                    break;
                }
              } catch (e) {
                console.error('Failed to parse stream data:', e);
              }
            }
          }
        }
      }
    } catch (err: any) {
      // 若为用户主动取消（AbortError），静默处理，不视为错误
      const isAbort = (controller?.signal?.aborted === true) ||
        (err && (err.name === 'AbortError' || /aborted/i.test(String(err.message || ''))));
      if (!isAbort) {
        console.error('Ingestion failed:', err);
        const status = ingestionStatus.get(url);
        if (status) {
          status.message = err?.message || '与服务器连接失败';
          status.inProgress = false;
          status.error = true;
        }
      }
    } finally {
      // 清理超时定时器
      try { if (timeoutId !== undefined) clearTimeout(timeoutId); } catch {}
      controllers.delete(url)
    }
  }

  // 取消并移除正在进行中的摄取记录
  function cancelIngestion(url: string) {
    const c = controllers.get(url)
    if (c) {
      try { c.abort() } catch {}
    }
    controllers.delete(url)
    ingestionStatus.delete(url)
  }

  async function removeDocument(id: string) {
    try {
      const response = await notebookApi.deleteDocument(id)
      if (response.success) {
        const index = documents.value.findIndex((doc) => doc.id === id)
        if (index > -1) {
          documents.value.splice(index, 1)
        }
      } else {
        throw new Error(response.message || 'Failed to delete document on the server.')
      }
    } catch (error) {
      console.error('删除文档失败:', error)
      throw error
    }
  }

  // ---- 课题工作流：生成查询 -> SearxNG 并发搜索 -> 展示候选URL按钮 ----
  async function generateCandidatesFromTopic() {
    const topic = topicInput.value.trim()
    if (!topic) return
    generating.value = true
    candidateUrls.value = []
    try {
      const resp = await notebookApi.generateSearchQueries(topic)
      let queries = resp?.queries as any
      // 兼容不规范返回：若 queries 为字符串，尝试解析/提取
      if (typeof queries === 'string') {
        let parsed: any = null
        const text = queries.trim()
        try {
          parsed = JSON.parse(text)
        } catch {
          try {
            // 去掉可能的 ```json 包裹
            const stripped = text.replace(/^```(?:json)?\s*|\s*```$/g, '')
            // 尝试提取首个 {...} 对象
            const m = stripped.match(/\{[\s\S]*\}/)
            if (m) parsed = JSON.parse(m[0].replace(/'/g, '"'))
          } catch {}
        }
        if (parsed && Array.isArray(parsed.queries)) {
          queries = parsed.queries
        } else {
          // 再退一步：按行切分
          queries = text.split(/\n+/).map((s: string) => s.trim()).filter(Boolean)
        }
      }
      if (!Array.isArray(queries)) {
        queries = [String(topic), `${topic} 关键点`, `${topic} 最新进展`]
      }
      // 并发请求 searxng，每个取4条；如果某个失败，不影响其它
      const tasks = queries.map(async (q: string) => {
        try {
          return await notebookApi.searchSearxng(q, 4)
        } catch (e) {
          console.warn('searxng search failed for query:', q, e)
          return { items: [] }
        }
      })
      const results = await Promise.allSettled(tasks)
      const items: { title: string; url: string }[] = []
      for (const r of results) {
        if (r.status === 'fulfilled' && r.value) {
          for (const it of (r.value as any).items || []) {
            if (it.url && !items.find((x) => x.url === it.url)) {
              items.push({ title: it.title, url: it.url })
            }
          }
        }
      }
      candidateUrls.value = items.slice(0, 12)
    } finally {
      generating.value = false
    }
  }

  // 选择一个候选URL，触发 addDocument
  async function addCandidate(url: string) {
    await addDocument(url)
  }

  async function sendQuery(query: string) {
    // 如果问答类型为COLLECTION，执行Collection查询
    if (queryType.value === QueryType.COLLECTION) {
      return await performCollectionQuery(query)
    }
    
    // 否则执行普通/文档查询
    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: query,
      timestamp: new Date(),
    }
    messages.value.push(userMessage)
    
    loading.querying = true

    let timeoutId: number | undefined;
    let controller: AbortController | null = null;
    try {
      controller = new AbortController();
      timeoutId = window.setTimeout(() => controller?.abort(), 300000);
      
      // 构建查询参数
      const queryParams: any = {
        query,
        top_k: 60,
        stream: true,
        model: selectedModel.value,  // 添加选中的模型
        query_type: queryType.value, // 添加问答类型参数
      }
      
      // 根据问答类型决定文档范围和工具配置
      if (queryType.value === QueryType.DOCUMENT) {
        // 文档问答模式：使用已添加的文档，不启用工具
        queryParams.document_ids = documents.value.map(doc => doc.id)
        queryParams.tool_mode = 'off'
      } else if (queryType.value === QueryType.NORMAL) {
        // 普通问答模式：不限制文档范围，启用web search工具
        queryParams.tool_mode = 'auto'
        queryParams.tools = DEFAULT_TOOLS
      }
      
      const response = await fetch(`${notebookApi.getBaseUrl()}/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': sessionStore.getSessionId() || '',
        },
        body: JSON.stringify(queryParams),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      // 先插入一个空的 assistant 消息，后续增量填充
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: '',
        timestamp: new Date(),
        sources: [],
        reasoning: '',
      };
      const messageIndex = messages.value.length;
      messages.value.push(assistantMessage);

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Failed to get response reader');
      }

      const decoder = new TextDecoder();
      let buffer = '';
      let accumulatedContent = '';
      let accumulatedReasoning = '';
      let isToolRunning = false;
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          const jsonStr = line.slice(5).trim();
          if (!jsonStr) continue;
          try {
            const evt = JSON.parse(jsonStr);
            if (evt.type === 'reasoning' && typeof evt.content === 'string') {
              accumulatedReasoning += evt.content;
              messages.value[messageIndex] = {
                ...messages.value[messageIndex],
                reasoning: accumulatedReasoning,
              };
            } else if (evt.type === 'content' && typeof evt.content === 'string') {
              // 如果正在运行工具且内容为空，则先显示等待状态
              if (!accumulatedContent && isToolRunning) {
                messages.value[messageIndex] = {
                  ...messages.value[messageIndex],
                  content: '🔍 正在处理工具结果，请稍候...',
                };
              } else {
                accumulatedContent += evt.content;
                messages.value[messageIndex] = {
                  ...messages.value[messageIndex],
                  content: accumulatedContent,
                };
              }
            } else if (evt.type === 'tool_call') {
              // 工具调用开始
              isToolRunning = true;
              const toolName = evt.tool_name || evt.name || 'unknown';
              let statusMessage = '';
              if (toolName === 'web_search') {
                statusMessage = '🔍 正在搜索网络信息...';
              } else {
                statusMessage = `🔧 正在调用工具: ${toolName}...`;
              }
              messages.value[messageIndex] = {
                ...messages.value[messageIndex],
                content: statusMessage,
              };
            } else if (evt.type === 'tool_result') {
              // 工具调用完成
              isToolRunning = false;
              const toolName = evt.tool_name || evt.name || 'unknown';
              let statusMessage = '';
              if (toolName === 'web_search') {
                statusMessage = '✅ 网络搜索完成，正在生成回答...';
              } else {
                statusMessage = `✅ 工具 ${toolName} 执行完成，正在处理结果...`;
              }
              messages.value[messageIndex] = {
                ...messages.value[messageIndex],
                content: statusMessage,
              };
            } else if (evt.type === 'status' && typeof evt.message === 'string') {
              // 状态更新
              messages.value[messageIndex] = {
                ...messages.value[messageIndex],
                content: evt.message,
              };
            } else if (evt.type === 'sources' && Array.isArray(evt.sources)) {
              messages.value[messageIndex] = {
                ...messages.value[messageIndex],
                sources: (evt.sources as Source[]).sort((a: Source, b: Source) => b.score - a.score),
              };
            } else if (evt.type === 'error') {
              throw new Error(evt.message || 'stream error');
            }
          } catch (e) {
            console.warn('Failed to parse stream line:', line, e);
          }
        }
      }

    } catch (error) {
      console.error('查询失败:', error);
      messages.value.push({
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: '**抱歉，处理您的请求时发生错误。**',
        timestamp: new Date(),
      });
    } finally {
      loading.querying = false;
      try { if (timeoutId !== undefined) clearTimeout(timeoutId); } catch {}
    }
  }

  // 执行Collection查询的独立方法
  async function performCollectionQuery(query: string) {
    const collectionId = selectedCollection.value || ''
    
    // 如果问答类型是COLLECTION但没有选择collection，抛出错误
    if (queryType.value === QueryType.COLLECTION && !collectionId) {
      throw new Error('请选择一个Collection')
    }

    // 添加用户消息
    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: query,
      timestamp: new Date()
    }
    messages.value.push(userMessage)

    // 创建助手回复消息
    const assistantMessage: Message = {
      id: (Date.now() + 1).toString(),
      type: 'assistant',
      content: '',
      timestamp: new Date(),
      sources: [],
      reasoning: ''
    }
    messages.value.push(assistantMessage)
    const messageIndex = messages.value.length - 1

    loading.queryingCollection = true
    loading.querying = true // 使用通用的查询状态

    try {
      const request: CollectionQueryRequest & { 
        use_web_search?: boolean, 
        tools?: any[], 
        tool_mode?: string 
      } = {
        collection_id: collectionId,
        query,
        top_k: 20
      }
      
      // 如果应该启用web search，添加工具配置
      if (shouldUseWebSearch.value) {
        request.use_web_search = true
        request.tools = DEFAULT_TOOLS
        request.tool_mode = 'auto'
      }

      // 使用流式查询
      await notebookApi.queryCollectionStream(
        request,
        (data) => {
          // 处理流式数据
          if (data.type === 'status') {
            // 更新消息内容显示状态信息
            messages.value[messageIndex] = {
              ...messages.value[messageIndex],
              content: data.message
            }
          } else if (data.type === 'search_results') {
            // 搜索结果摘要
            messages.value[messageIndex] = {
              ...messages.value[messageIndex],
              content: data.message
            }
          } else if (data.type === 'llm_start') {
            // 开始生成LLM回答
            messages.value[messageIndex] = {
              ...messages.value[messageIndex],
              content: '正在生成智能回答...'
            }
          } else if (data.type === 'content') {
            // LLM生成的内容
            const currentMessage = messages.value[messageIndex]
            const newContent = (currentMessage.content === '正在生成智能回答...' || 
                              currentMessage.content.includes('正在生成智能回答') ||
                              currentMessage.content.includes('找到') && currentMessage.content.includes('个相关结果')) 
                              ? data.content 
                              : currentMessage.content + data.content
            
            messages.value[messageIndex] = {
              ...messages.value[messageIndex],
              content: newContent
            }
          } else if (data.type === 'reasoning') {
            // 思维链内容
            const currentMessage = messages.value[messageIndex]
            messages.value[messageIndex] = {
              ...messages.value[messageIndex],
              reasoning: (currentMessage.reasoning || '') + data.content
            }
          } else if (data.type === 'error') {
            // 错误信息
            messages.value[messageIndex] = {
              ...messages.value[messageIndex],
              content: `❌ ${data.message}`
            }
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
          messages.value[messageIndex] = {
            ...messages.value[messageIndex],
            content: `❌ 查询失败: ${error.message}`
          }
        }
      )

      // 同时获取搜索结果用于显示
      const response = await notebookApi.queryCollection(request)
      if (response.success) {
        collectionQueryResults.value = response.results
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
      collectionQueryResults.value = []
      
      // 更新消息显示错误
      if (messages.value[messageIndex]) {
        messages.value[messageIndex] = {
          ...messages.value[messageIndex],
          content: `❌ 查询失败: ${error.message}`
        }
      }
      
      throw error
    } finally {
      loading.queryingCollection = false
      loading.querying = false
    }
  }

  function clearMessages() {
    messages.value = []
  }

  async function exportConversation() {
    const sessionId = sessionStore.getSessionId()
    if (!sessionId) {
      throw new Error('No session ID found')
    }
    
    loading.exporting = true
    try {
      // 将当前对话历史发送到后端
      const response = await fetch(`${notebookApi.getBaseUrl()}/export/conversation/${sessionId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': sessionId,
        },
        body: JSON.stringify({
          messages: messages.value
        }),
      })
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `conversation_export_${sessionId}.zip`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
      
      return { success: true }
    } catch (error) {
      console.error('Export failed:', error)
      throw error
    } finally {
      loading.exporting = false
    }
  }



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
        embedding_model: 'Qwen/Qwen3-Embedding-0.6B',
        embedding_dimensions: 1024,
        recursive_depth: 1
      }

      const response = await notebookApi.triggerAgenticIngest(request)
      if (response.success) {
        // 处理成功，清空输入框并刷新collection列表
        agenticIngestUrl.value = ''
        await loadCollections()
        // 成功添加collection后自动切换到文档问答模式
        if (queryType.value === QueryType.NORMAL) {
          queryType.value = QueryType.DOCUMENT
        }
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

  // 获取可用的LLM模型列表
  async function loadModels() {
    loading.loadingModels = true
    try {
      const response = await notebookApi.getModels()
      if (response.success) {
        models.value = response.models ? response.models.filter(model => model.name.indexOf('embedding') === -1) : []
        // 如果还没有选择模型且有可用模型，选择第一个
        if (!selectedModel.value && models.value.length > 0) {
          selectedModel.value = models.value[0].id
        }
      } else {
        console.error('获取模型列表失败')
        models.value = []
      }
    } catch (error) {
      console.error('获取模型列表出错:', error)
      models.value = []
    } finally {
      loading.loadingModels = false
    }
  }

  // 基于指定collection进行查询
  async function queryCollection() {
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
        top_k: 20
      }

      const response = await notebookApi.queryCollection(request)
      if (response.success) {
        collectionQueryResults.value = response.results
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
      collectionQueryResults.value = []
      throw error
    } finally {
      loading.queryingCollection = false
    }
  }

  // 清空collection查询结果
  function clearCollectionResults() {
    collectionQueryResults.value = []
    collectionQueryInput.value = ''
  }

  return {
    documents,
    messages,
    loading,
    ingestionStatus,
    topicInput,
    candidateUrls,
    generating,
    // Agentic Ingest相关
    agenticIngestUrl,
    // Collection相关
    collections,
    selectedCollection,
    collectionQueryResults,
    collectionQueryInput,
    isCollectionQueryMode,
    // 模型相关
    models,
    selectedModel,
    // 问答类型相关
    queryType,
    shouldUseWebSearch,
    // 方法
    addDocument,
    cancelIngestion,
    removeDocument,
    sendQuery,
    performCollectionQuery,
    clearMessages,
    generateCandidatesFromTopic,
    addCandidate,
    exportConversation,
    triggerAgenticIngest,
    loadCollections,
    queryCollection,
    clearCollectionResults,
    loadModels,
  }
})
