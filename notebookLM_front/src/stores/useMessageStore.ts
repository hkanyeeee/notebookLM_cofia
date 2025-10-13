import { ref } from 'vue'
import { notebookApi, DEFAULT_TOOLS } from '../api/notebook'
import { useSessionStore } from './session'
import type { Message, Source } from './types'
import { QueryType } from './types'
import { audioManager } from '../utils/audioManager'

export function useMessageStore() {
  const sessionStore = useSessionStore()
  
  const messages = ref<Message[]>([])

  async function sendQuery(
    query: string, 
    queryType: QueryType, 
    selectedModel: string,
    documentIds?: string[],
    // 移除 performCollectionQuery 参数
    toolsEnabled?: boolean
  ) {
    // 其余逻辑保持
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
      timeoutId = window.setTimeout(() => controller?.abort(), 3600000);
      
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
        // 文档问答模式：使用已添加的文档，不启用工具，不使用消息历史
        queryParams.document_ids = documentIds || []
        // 注意：文档问答不传递tool_mode参数，让后端使用专门的文档问答逻辑
      } else if (queryType === QueryType.NORMAL) {
        // 普通问答模式：不限制文档范围，根据用户设置启用/禁用工具，使用消息历史
        if (toolsEnabled === true) {
          queryParams.tool_mode = 'auto'
          queryParams.tools = DEFAULT_TOOLS
        } else {
          // 工具关闭时，显式传递 'off' 模式
          queryParams.tool_mode = 'off'
        }
        
        // 添加消息历史 (排除刚添加的用户消息)
        const conversationHistory = messages.value.slice(0, -1).map(msg => ({
          role: msg.type === 'user' ? 'user' : 'assistant',
          content: msg.content
        }))
        queryParams.conversation_history = conversationHistory
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

      let accumulatedContent = '';
      let accumulatedReasoning = '';
      let isToolRunning = false;
      let lastActivity = Date.now();
      const STREAM_TIMEOUT = 3600000; // 3600秒无数据自动结束
      let parseErrors = 0; // 解析错误计数
      
      // 使用新的流式API方法
      await notebookApi.queryDocumentsStream(
        query,
        queryParams,
        (evt) => {
          // 处理流式数据
          lastActivity = Date.now(); // 更新活动时间
          
          try {
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
                  content: '正在思考...',
                };
              } else {
                // 累积内容并直接显示
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
              if (toolName === 'web_search' || toolName === 'web_search_and_recall') {
                statusMessage = '搜索中...';
              } else {
                statusMessage = '正在思考...';
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
              
              // 可用时在控制台输出指标，后续可展示在 UI
              if (typeof evt.latency_ms === 'number') {
                console.log(`[tool_result] ${toolName} latency_ms=${evt.latency_ms} retries=${evt.retries ?? 0}`)
              }
              
              // 如果工具失败，直接把错误信息展示出来，避免误导
              if (evt.success === false) {
                const errorText = typeof evt.result === 'string' ? evt.result : (evt.result?.error || '工具执行失败');
                messages.value[messageIndex] = {
                  ...messages.value[messageIndex],
                  content: `工具失败：${errorText}`,
                };
              } else {
                // 工具成功执行，显示简洁的状态信息
                if (toolName === 'web_search' || toolName === 'web_search_and_recall') {
                  statusMessage = '正在分析搜索结果...';
                } else {
                  statusMessage = '正在处理...';
                }
                
                messages.value[messageIndex] = {
                  ...messages.value[messageIndex],
                  content: statusMessage,
                };
              }
            } else if (evt.type === 'final_answer') {
              // 最终答案 - 结束工具运行状态并显示最终内容
              console.log('[Frontend] 收到最终答案事件:', evt);
              isToolRunning = false;
              if (evt.content && typeof evt.content === 'string') {
                // 如果有内容，使用最终答案内容（不累积，因为可能是完整替换）
                const finalContent = evt.content.trim();
                if (finalContent) {
                  messages.value[messageIndex] = {
                    ...messages.value[messageIndex],
                    content: finalContent,
                  };
                }
              }
              // 最终答案标记流式处理结束
              console.log('[Frontend] 最终答案处理完成，结束流式处理');

              // 播放提示音通知用户消息完成
              playNotificationSound();

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
            } else if (evt.type === 'complete') {
              // 流式处理完成
              console.log('[Frontend] 流式处理完成');
              isToolRunning = false;

              // 播放提示音通知用户消息完成
              playNotificationSound();

            } else if (evt.type === 'error') {
              // 将错误作为消息内容展示，并结束本次流式
              const errorText = typeof evt.message === 'string' ? evt.message : '流式处理发生错误';
              messages.value[messageIndex] = {
                ...messages.value[messageIndex],
                content: errorText,
              };
              // 播放提示音，提示本条消息已完成（即使为错误）
              playNotificationSound();
              return;
            }
          } catch (e) {
            console.warn('Failed to parse stream event:', evt, e);
            // 如果解析失败太多次，可能是响应格式错误，强制结束
            if (++parseErrors > 10) {
              console.error('流式响应解析错误过多，强制结束');
              // 设置错误消息
              if (accumulatedContent === '' || accumulatedContent === '正在思考...' || accumulatedContent === '搜索中...') {
                messages.value[messageIndex] = {
                  ...messages.value[messageIndex],
                  content: '响应格式错误，请重试。',
                };
              }
              return;
            }
          }
        },
        () => {
          // 完成回调
          console.log('查询完成');
        },
        (error) => {
          // 错误回调
          console.error('查询失败:', error);
          throw error;
        },
        controller.signal
      );

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

  // 播放消息完成提示音
  async function playNotificationSound() {
    try {
      const success = await audioManager.playNotification()
      if (success) {
        console.log('消息完成提示音播放成功')
      } else {
        console.log('音频播放失败，但可能已显示通知')
      }
    } catch (error) {
      console.warn('播放提示音时发生错误:', error)
    }
  }

  function clearMessages() {
    messages.value = []
  }

  // 音频管理相关方法
  function initializeAudioManager() {
    return audioManager.initialize()
  }

  function setAudioVolume(volume: number) {
    audioManager.setVolume(volume)
  }

  function setAudioEnabled(enabled: boolean) {
    audioManager.setEnabled(enabled)
  }

  function getAudioStatus() {
    return audioManager.getStatus()
  }

  // 开始编辑消息
  function startEditMessage(messageId: string) {
    const message = messages.value.find(m => m.id === messageId)
    if (message && message.type === 'user') {
      message.isEditing = true
      message.originalContent = message.content
    }
  }

  // 取消编辑消息
  function cancelEditMessage(messageId: string) {
    const message = messages.value.find(m => m.id === messageId)
    if (message && message.isEditing) {
      message.content = message.originalContent || message.content
      message.isEditing = false
      message.originalContent = undefined
    }
  }

  // 更新正在编辑的消息内容
  function updateEditingMessage(messageId: string, newContent: string) {
    const message = messages.value.find(m => m.id === messageId)
    if (message && message.isEditing) {
      message.content = newContent
    }
  }

  // 重新发送编辑后的消息并删除后续历史
  async function resendEditedMessage(
    messageId: string, 
    queryType: QueryType, 
    selectedModel: string,
    documentIds?: string[],
    // 移除 performCollectionQuery 参数
    toolsEnabled?: boolean
  ) {
    const messageIndex = messages.value.findIndex(m => m.id === messageId)
    if (messageIndex === -1) return

    const message = messages.value[messageIndex]
    if (!message || !message.isEditing) return

    const queryContent = message.content

    // 结束编辑状态
    message.isEditing = false
    message.originalContent = undefined

    // 删除该消息及其后的所有消息（因为sendQuery会重新添加用户消息）
    messages.value = messages.value.slice(0, messageIndex)

    // 重新发送查询
    await sendQuery(queryContent, queryType, selectedModel, documentIds, toolsEnabled)
  }

  return {
    // 状态
    messages,
    
    // 方法
    sendQuery,
    clearMessages,
    startEditMessage,
    cancelEditMessage,
    updateEditingMessage,
    resendEditedMessage,
    
    // 音频管理方法
    initializeAudioManager,
    setAudioVolume,
    setAudioEnabled,
    getAudioStatus,
  }
}
