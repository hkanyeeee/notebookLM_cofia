import { ref, reactive } from 'vue'
import { defineStore } from 'pinia'
import { notebookApi } from '../api/notebook'
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
  
  const loading = reactive({
    querying: false,
    addingDocument: false
  })

  const ingestionStatus = reactive<Map<string, IngestionProgress>>(new Map())

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
      console.error('Ingestion failed:', err);
      const status = ingestionStatus.get(url);
      if (status) {
        status.message = err.message || '与服务器连接失败';
        status.inProgress = false;
        status.error = true;
      }
    } finally {
      // 清理超时定时器
      try { if (timeoutId !== undefined) clearTimeout(timeoutId); } catch {}
    }
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
    if (documents.value.length > 0) return // 一旦有文档，课题区域禁用
    generating.value = true
    candidateUrls.value = []
    try {
      const { queries } = await notebookApi.generateSearchQueries(topic)
      // 并发请求 searxng，每个取4条
      const tasks = queries.map((q) => notebookApi.searchSearxng(q, 4))
      const results = await Promise.allSettled(tasks)
      const items: { title: string; url: string }[] = []
      for (const r of results) {
        if (r.status === 'fulfilled') {
          for (const it of r.value.items || []) {
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
          document_ids: documents.value.map(doc => doc.id)
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: data.answer || 'No content received.',
        timestamp: new Date(),
        sources: data.sources ? data.sources.sort((a: Source, b: Source) => b.score - a.score) : [],
      };
      messages.value.push(assistantMessage);

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

  return {
    documents,
    messages,
    loading,
    ingestionStatus,
    topicInput,
    candidateUrls,
    generating,
    addDocument,
    removeDocument,
    sendQuery,
    clearMessages,
    generateCandidatesFromTopic,
    addCandidate,
  }
})
