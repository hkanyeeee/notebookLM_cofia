import { ref, reactive } from 'vue'
import { defineStore } from 'pinia'
import { notebookApi, type AgenticIngestRequest, type AgenticCollection, type CollectionQueryRequest, type CollectionResult } from '../api/notebook'
import { useSessionStore } from './session'

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
  
  const loading = reactive({
    querying: false,
    addingDocument: false,
    exporting: false,
    triggeringAgenticIngest: false,
    loadingCollections: false,
    queryingCollection: false
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
      const response = await fetch(`${notebookApi.getBaseUrl()}/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': sessionStore.getSessionId() || '',
        },
        body: JSON.stringify({
          query,
          top_k: 60,
          document_ids: documents.value.map(doc => doc.id),
          stream: true,
        }),
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
              accumulatedContent += evt.content;
              messages.value[messageIndex] = {
                ...messages.value[messageIndex],
                content: accumulatedContent,
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
    // 方法
    addDocument,
    cancelIngestion,
    removeDocument,
    sendQuery,
    clearMessages,
    generateCandidatesFromTopic,
    addCandidate,
    exportConversation,
    triggerAgenticIngest,
    loadCollections,
    queryCollection,
    clearCollectionResults,
  }
})
