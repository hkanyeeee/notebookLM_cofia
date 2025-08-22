import { ref } from 'vue'
import { notebookApi, DEFAULT_TOOLS } from '../api/notebook'
import { useSessionStore } from './session'
import type { Message, Source, QueryType } from './types'

export function useMessageStore() {
  const sessionStore = useSessionStore()
  
  const messages = ref<Message[]>([])

  async function sendQuery(
    query: string, 
    queryType: QueryType, 
    selectedModel: string,
    documentIds?: string[],
    performCollectionQuery?: (query: string) => Promise<any>
  ) {
    // 如果问答类型为COLLECTION，执行Collection查询
    if (queryType === QueryType.COLLECTION && performCollectionQuery) {
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
        model: selectedModel,  // 添加选中的模型
        query_type: queryType, // 添加问答类型参数
      }
      
      // 根据问答类型决定文档范围和工具配置
      if (queryType === QueryType.DOCUMENT) {
        // 文档问答模式：使用已添加的文档，不启用工具
        queryParams.document_ids = documentIds || []
        queryParams.tool_mode = 'off'
      } else if (queryType === QueryType.NORMAL) {
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
    }
  }

  return {
    // 状态
    messages,
    
    // 方法
    sendQuery,
    clearMessages,
    exportConversation,
  }
}
