import { ref, reactive } from 'vue'
import { notebookApi } from '../api/notebook'
import { useSessionStore } from './session'
import type { Document, IngestionProgress, QueryType } from './types'
import { useModelStore } from './useModelStore'

export function useDocumentStore(initialModel?: string) {
  const sessionStore = useSessionStore()

  const modelStore = useModelStore()
  
  const documents = ref<Document[]>([])
  
  // 课题模式：在未添加任何网址时，允许输入课题并生成候选URL
  const topicInput = ref<string>('')
  const candidateUrls = ref<{ title: string; url: string }[]>([])
  const generating = ref<boolean>(false)

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
      // 传递模型参数给API
      const resp = await notebookApi.generateSearchQueries(topic, modelStore.selectedModel.value)
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

  return {
    // 状态
    documents,
    topicInput,
    candidateUrls,
    generating,
    ingestionStatus,
    
    // 方法
    addDocument,
    cancelIngestion,
    removeDocument,
    generateCandidatesFromTopic,
    addCandidate,
  }
}
