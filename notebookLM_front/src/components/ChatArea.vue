<script setup lang="ts">
import { ref, nextTick, computed, watch, onMounted } from 'vue'
import { useNotebookStore } from '../stores/notebook'
import { ElInput, ElButton, ElMessage, ElIcon, ElCollapse, ElCollapseItem, ElTooltip, ElSelect, ElOption } from 'element-plus'
import { Refresh, Promotion, Plus } from '@element-plus/icons-vue'
import { marked } from 'marked'

// 启用 GitHub 风格 Markdown（GFM），支持表格等语法
marked.setOptions({
  gfm: true,
  breaks: true,
})

const store = useNotebookStore()

// 查询输入
const queryInput = ref('')
const messageContainer = ref<HTMLElement>()

// 控制详细搜索结果的显示
const showDetailedResults = ref(false)

// 监听消息变化，自动滚动到底部
watch(() => store.messages.length, async () => {
  await nextTick()
  scrollToBottom()
}, { flush: 'post' })

// 监听loading状态变化，当查询完成时滚动
watch(() => store.loading.querying, async (newVal, oldVal) => {
  if (oldVal && !newVal) {
    // 查询完成，滚动到底部
    await nextTick()
    scrollToBottom()
  }
}, { flush: 'post' })

// 流式过程中，监听最后一条消息内容和思维链变化，持续滚动
watch(
  () => {
    if (store.messages.length === 0) return ''
    const lastMsg = store.messages[store.messages.length - 1]
    return lastMsg.content + (lastMsg.reasoning || '')
  },
  async () => {
    await nextTick()
    scrollToBottom()
  },
  { flush: 'post' }
)

// 发送查询
async function handleSendQuery() {
  const query = queryInput.value.trim()
  if (!query) {
    ElMessage.warning('请输入您的问题')
    return
  }

  // Collection查询模式验证
  if (store.isCollectionQueryMode) {
    if (!store.selectedCollection) {
      ElMessage.warning('请先选择一个Collection')
      return
    }
  } else {
    // 普通查询模式验证
    if (store.documents.length === 0) {
      ElMessage.warning('请先添加一些文档再开始对话')
      return
    }

    if (store.ingestionStatus.size > 0) {
      ElMessage.warning('正在处理文档，请稍后再试')
      return
    }
  }

  try {
    queryInput.value = ''
    const result = await store.sendQuery(query)
    
    // 如果是Collection查询模式，显示查询结果提示
    if (store.isCollectionQueryMode && result && result.success) {
      ElMessage.success(`找到 ${result.total_found} 个相关结果`)
    }
  } catch (error: any) {
    ElMessage.error(error.message || '查询失败，请重试')
  }
}

// 滚动到底部
function scrollToBottom() {
  if (messageContainer.value) {
    messageContainer.value.scrollTop = messageContainer.value.scrollHeight
  }
}

// 清空对话
function handleClearMessages() {
  store.clearMessages()
  ElMessage.success('对话已清空')
}

// 格式化时间
function formatTime(date: Date) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

// 组件挂载时加载collection列表和模型列表
onMounted(async () => {
  try {
    await Promise.all([
      store.loadCollections(),
      store.loadModels()
    ])
  } catch (error) {
    console.warn('初始加载数据失败:', error)
  }
})

// 触发agentic ingest
async function handleTriggerAgenticIngest() {
  const url = store.agenticIngestUrl.trim()
  if (!url) {
    ElMessage.warning('请输入要处理的URL')
    return
  }

  try {
    const result = await store.triggerAgenticIngest()
    if (result.success) {
      ElMessage.success(`成功触发Agentic Ingest：${result.document_name}`)
    }
  } catch (error: any) {
    ElMessage.error(error.message || 'Agentic Ingest失败')
  }
}

// Collection查询已整合到sendQuery方法中，此方法保留用于向后兼容
async function handleCollectionQuery() {
  const query = store.collectionQueryInput.trim()
  
  if (!query) {
    ElMessage.warning('请输入查询内容')
    return
  }

  try {
    const result = await store.performCollectionQuery(query)
    if (result.success) {
      ElMessage.success(`找到 ${result.total_found} 个相关结果`)
    }
  } catch (error: any) {
    ElMessage.error(error.message || 'Collection查询失败')
  }
}
</script>

<template>
  <div class="chat-area">
    <!-- 头部 -->
    <header class="chat-header">
      <div class="header-left">
        <h1>对话</h1>
        <div class="model-selector">
          <ElSelect
            v-model="store.selectedModel"
            placeholder="选择模型"
            class="model-select"
            :loading="store.loading.loadingModels"
            clearable
            filterable
          >
            <ElOption
              v-for="model in store.models"
              :key="model.id"
              :label="model.name"
              :value="model.id"
            />
          </ElSelect>
        </div>
      </div>
      
      <div class="header-actions">
        <ElButton text @click="handleClearMessages" :disabled="store.messages.length === 0">
          <ElIcon>
            <Refresh />
          </ElIcon>
          清空对话
        </ElButton>
      </div>
    </header>

    <!-- 消息列表 / 欢迎与课题输入 -->
    <div ref="messageContainer" class="messages-container">
      <!-- Collection查询结果区域 -->
      <div v-if="store.collectionQueryResults.length > 0 && store.messages.length === 0" class="collection-results">
        <div class="collection-results-header">
          <h3>Collection搜索结果 ({{ store.collectionQueryResults.length }} 个相关文档片段)</h3>
          <div class="collection-results-actions">
            <ElButton text @click="showDetailedResults = !showDetailedResults" class="toggle-results-btn">
              {{ showDetailedResults ? '隐藏详细结果' : '查看详细结果' }}
            </ElButton>
            <ElButton text @click="store.clearCollectionResults()" class="clear-results-btn">
              清空结果
            </ElButton>
          </div>
        </div>
        <div v-if="showDetailedResults" class="collection-results-list">
          <div 
            v-for="(result, index) in store.collectionQueryResults" 
            :key="index" 
            class="collection-result-item"
          >
            <div class="result-header">
              <div class="result-score">相关度: {{ result.score.toFixed(4) }}</div>
              <a :href="result.source_url" target="_blank" class="result-url">
                {{ result.source_title }}
              </a>
            </div>
            <div class="result-content">{{ result.content }}</div>
          </div>
        </div>
        <div v-else class="collection-results-summary">
          <p class="summary-text">
            📄 找到 {{ store.collectionQueryResults.length }} 个相关文档片段，
            <ElButton type="primary" size="small" @click="handleSendQuery()">
              点击生成智能回答
            </ElButton>
          </p>
        </div>
      </div>
      
      <div v-if="store.messages.length === 0" class="welcome-message">
        <h2>欢迎</h2>
        <p>您可以输入一个课题，我会先生成搜索查询并抓取候选网页供添加；或者在左侧直接添加网址。</p>
        <div class="topic-input">
          <ElInput
            v-model="store.topicInput"
            placeholder="请输入课题，例如：Sora 2025 能力与限制"
            :disabled="store.generating"
          />
          <ElButton
            type="primary"
            @click="store.generateCandidatesFromTopic()"
            :loading="store.generating"
            :disabled="!store.topicInput.trim() || store.generating"
            class="topic-send-btn"
          >生成搜索</ElButton>
        </div>

        <!-- 候选URL按钮区 -->
        <div v-if="store.candidateUrls.length > 0" class="candidates">
          <h3>候选网址</h3>
          <div class="candidate-grid">
            <ElTooltip
              v-for="item in store.candidateUrls"
              :key="item.url"
              placement="top"
              effect="dark"
            >
              <template #content>
                <div>
                  <div>{{ item.title }}</div>
                  <div>{{ item.url }}</div>
                </div>
              </template>
              <ElButton
                class="candidate-item"
                @click="store.addCandidate(item.url)"
              >
                <div class="candidate-item-content">
                  <div class="candidate-title">{{ item.title }}</div>
                  <div class="candidate-url">{{ item.url }}</div>
                </div>
              </ElButton>
            </ElTooltip>
          </div>
        </div>

        <div class="welcome-features">
          <div class="feature-item">
            <strong>💡 智能问答</strong>
            <p>基于您添加的文档内容回答问题</p>
          </div>
          <div class="feature-item">
            <strong>📚 文档总结</strong>
            <p>快速获取文档的核心要点</p>
          </div>
          <div class="feature-item">
            <strong>🔍 深度分析</strong>
            <p>深入分析文档中的关键信息</p>
          </div>
        </div>
      </div>


      <!-- 对话消息 -->
      <div
        v-for="message in store.messages"
        :key="message.id"
        class="message"
        :class="message.type"
      >
        <div class="message-content">
          <!-- Reasoning Chain (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.reasoning" class="reasoning-section">
            <ElCollapse>
              <ElCollapseItem :title="`思维链（${message.reasoning.length} 字）`" name="reasoning">
                <div class="reasoning-content" v-html="marked(message.reasoning)"></div>
              </ElCollapseItem>
            </ElCollapse>
          </div>
          <div class="message-text" v-if="message.content" v-html="marked(message.content)"></div>
          <div class="message-text" v-else>{{"信息加载中..."}}</div>
          <div class="message-time">{{ formatTime(message.timestamp) }}</div>

          <!-- Sources (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.sources && message.sources.length > 0" class="sources-section">
            <ElCollapse>
              <ElCollapseItem title="参考来源" name="sources">
                <div v-for="(source, index) in message.sources" :key="index" class="source-item">
                  <div class="source-header">
                    <a :href="source.url" target="_blank" class="source-url">{{ source.url.split('/').slice(0, 3).join('/') }}/.../{{ source.url.split('/').pop() }}</a>
                    <span class="source-score">分数: {{ source.score.toFixed(4) }}</span>
                  </div>
                  <pre class="source-content">{{ source.content }}</pre>
                </div>
              </ElCollapseItem>
            </ElCollapse>
          </div>
        </div>
      </div>

      
    </div>

    <!-- 输入区域：当无文档时禁用提问 -->
    <div class="input-area">
        
      <!-- Collection与Agentic Ingest 控制区 -->
      <div class="agentic-controls">
        <!-- Collection选择下拉框 -->
        <ElSelect
          v-model="store.selectedCollection"
          placeholder="选择Collection"
          class="collection-selector"
          :loading="store.loading.loadingCollections"
          clearable
        >
          <ElOption
            v-for="collection in store.collections"
            :key="collection.collection_id"
            :label="collection.document_title"
            :value="collection.collection_id"
          />
        </ElSelect>
        
        <!-- URL输入框 -->
        <ElInput
          v-model="store.agenticIngestUrl"
          placeholder="输入URL进行Agentic Ingest"
          class="url-input"
          clearable
        />
        
        <!-- 提交按钮 -->
        <ElButton
          type="primary"
          @click="handleTriggerAgenticIngest"
          :loading="store.loading.triggeringAgenticIngest"
          :disabled="!store.agenticIngestUrl.trim() || store.loading.triggeringAgenticIngest"
          class="trigger-btn"
        >
          <ElIcon>
            <Plus />
          </ElIcon>
          处理
        </ElButton>
      </div>
      <div class="input-container" @keydown.enter.shift.prevent="handleSendQuery">
        <ElInput
          v-model="queryInput"
          :placeholder="store.isCollectionQueryMode ? `在 '${store.collections.find(c => c.collection_id === store.selectedCollection)?.document_title}' 中查询...` : '请输入您的问题...'"
          class="query-input"
          type="textarea"
          :rows="2"
        />
        <ElButton
          type="primary"
          @click="handleSendQuery"
          :disabled="store.loading.querying || store.loading.queryingCollection || !queryInput.trim() || (!store.isCollectionQueryMode && (store.documents.length === 0 || store.ingestionStatus.size > 0))"
          :loading="store.loading.querying || store.loading.queryingCollection || (!store.isCollectionQueryMode && store.ingestionStatus.size > 0)"
          class="send-btn"
        >
          <ElIcon>
            <Promotion />
          </ElIcon>
        </ElButton>
      </div>
      <div class="input-hint">
        <span v-if="store.isCollectionQueryMode">
          Collection查询模式：{{ store.collections.find(c => c.collection_id === store.selectedCollection)?.document_title || '未知Collection' }}
        </span>
        <span v-else>
          {{ store.documents.length }} 个文档已添加
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-area {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: white;
}

.chat-header {
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: white;
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 24px;
  flex: 1;
}

.chat-header h1 {
  margin: 0;
  color: #111827;
  font-size: 20px;
  font-weight: 600;
  white-space: nowrap;
}

.model-selector {
  margin-left: 24px;
}

.model-select {
  width: 200px;
}

.agentic-controls {
  display: flex;
  align-items: center;
  margin: auto;
  margin-bottom: 20px;
  gap: 12px;
  flex: 1;
  max-width: 800px;
}

.collection-selector {
  width: 200px;
}



.url-input {
  flex: 1;
  min-width: 200px;
}

.trigger-btn {
  white-space: nowrap;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  scroll-behavior: smooth;
}

.welcome-message {
  text-align: center;
  max-width: 600px;
  margin: 60px auto;
  color: #374151;
}

.topic-input {
  display: flex;
  gap: 12px;
  align-items: center;
}

.topic-send-btn {
  white-space: nowrap;
}

.candidates {
  margin-top: 24px;
  text-align: left;
  width: 1000px;
  margin-left: -200px;
}

.candidate-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
  .candidate-item:first-child {
    margin-left: 12px;
  }
}

.candidate-item {
  display: block;
  text-align: left;
  height: auto;
  padding: 12px;
  width: 320px;
  .candidate-item-content {
    width: 320px;
  }
}

.candidate-title {
  font-weight: 600;
  margin-bottom: 4px;
  color: #111827;
  width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-url {
  font-size: 12px;
  color: #6b7280;
  word-break: break-all;
  width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.welcome-message h2 {
  color: #111827;
  margin-bottom: 16px;
  font-size: 24px;
  font-weight: 600;
}

.welcome-message > p {
  margin-bottom: 40px;
  font-size: 16px;
  line-height: 1.6;
}

.welcome-features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 24px;
  margin-top: 40px;
}

.feature-item {
  text-align: left;
  padding: 20px;
  background: #f9fafb;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
}

.feature-item strong {
  display: block;
  margin-bottom: 8px;
  color: #111827;
  font-size: 14px;
}

.feature-item p {
  margin: 0;
  font-size: 13px;
  color: #6b7280;
  line-height: 1.5;
}

.message {
  margin-bottom: 24px;
  display: flex;
}

.message.user {
  justify-content: flex-end;
}

.message.assistant {
  justify-content: flex-start;
}

.message-content {
  max-width: 70%;
  padding: 16px 20px;
  border-radius: 18px;
  position: relative;
}

.message.user .message-content {
  background: #4f46e5;
  color: white;
  border-bottom-right-radius: 4px;
}

.message.assistant .message-content {
  background: #f3f4f6;
  color: #111827;
  border-bottom-left-radius: 4px;
}

.message-text {
  word-wrap: break-word;
}

.message-time {
  font-size: 11px;
  opacity: 0.7;
  margin-top: 8px;
  text-align: right;
}

.message.assistant .message-time {
  text-align: left;
}

.reasoning-section {
  margin-bottom: 16px;
  border-top: 1px solid #e5e7eb;
  padding-top: 12px;
  padding-bottom: 12px;
}

.reasoning-content {
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
  background-color: #f9fafb;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.sources-section {
  margin-top: 16px;
  border-top: 1px solid #e5e7eb;
  padding-top: 12px;
}

.source-item {
  margin-bottom: 12px;
  padding: 12px;
  background-color: #f9fafb;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.source-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.source-url {
  font-size: 13px;
  font-weight: 500;
  color: #4f46e5;
  text-decoration: none;
}
.source-url:hover {
  text-decoration: underline;
}

.source-score {
  font-size: 12px;
  color: #6b7280;
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
}

.source-content {
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
  margin: 0;
  white-space: pre-wrap; /* Preserve whitespace and wrap text */
}

:deep(.el-collapse-item__header) {
  font-size: 14px;
  font-weight: 500;
  color: #374151;
}

:deep(.el-collapse-item__content) {
  padding-bottom: 0;
}


/* 打字指示器 */
.typing-indicator {
  display: flex;
  gap: 4px;
  align-items: center;
}

.typing-indicator span {
  width: 6px;
  height: 6px;
  background: #9ca3af;
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%,
  60%,
  100% {
    transform: translateY(0);
  }
  30% {
    transform: translateY(-10px);
  }
}

.input-area {
  padding: 24px;
  border-top: 1px solid #e5e7eb;
  background: white;
}

.input-container {
  display: flex;
  gap: 12px;
  align-items: center;
  max-width: 800px;
  margin: 0 auto;
}

.query-input {
  flex: 1;
}

.send-btn {
  height: 40px;
  width: 40px;
  padding: 0;
  border-radius: 8px;
}

.input-hint {
  text-align: center;
  margin-top: 12px;
  color: #6b7280;
  font-size: 12px;
}

/* Collection查询结果样式 */
.collection-results {
  margin-bottom: 24px;
  padding: 20px;
  background: #f9fafb;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
}

.collection-results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e5e7eb;
}

.collection-results-header h3 {
  margin: 0;
  color: #111827;
  font-size: 16px;
  font-weight: 600;
}

.collection-results-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.clear-results-btn, .toggle-results-btn {
  font-size: 12px;
}

.collection-results-summary {
  padding: 16px;
  background: white;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  text-align: center;
}

.summary-text {
  margin: 0;
  color: #374151;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}

.collection-results-list {
  max-height: 400px;
  overflow-y: auto;
}

.collection-result-item {
  margin-bottom: 12px;
  padding: 16px;
  background: white;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  transition: all 0.2s ease;
}

.collection-result-item:hover {
  border-color: #d1d5db;
  box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
}

.collection-result-item:last-child {
  margin-bottom: 0;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.result-score {
  font-size: 12px;
  color: #6b7280;
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
  background: #f3f4f6;
  padding: 2px 8px;
  border-radius: 4px;
}

.result-url {
  font-size: 13px;
  font-weight: 500;
  color: #4f46e5;
  text-decoration: none;
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-url:hover {
  text-decoration: underline;
}

.result-content {
  font-size: 14px;
  color: #374151;
  line-height: 1.6;
  white-space: pre-wrap;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .chat-header {
    padding: 16px;
    flex-direction: column;
    gap: 16px;
    align-items: stretch;
  }

  .header-left {
    flex-direction: column;
    gap: 16px;
    align-items: stretch;
  }

  .agentic-controls {
    flex-direction: column;
    gap: 12px;
    max-width: none;
  }

  .collection-selector {
    width: 100%;
  }



  .url-input {
    min-width: auto;
  }

  .header-actions {
    align-self: center;
  }

  .messages-container {
    padding: 16px;
  }

  .message-content {
    max-width: 85%;
  }

  .welcome-features {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .input-area {
    padding: 16px;
  }
}
</style>
<style>
/* Markdown 内容的全局样式 */
.message-text p {
  margin-top: 0;
  margin-bottom: 1em;
}
.message-text h1,
.message-text h2,
.message-text h3,
.message-text h4,
.message-text h5,
.message-text h6 {
  margin-top: 1.5em;
  margin-bottom: 1em;
  font-weight: 600;
}
.message-text h1 {
  font-size: 1.75em;
}
.message-text h2 {
  font-size: 1.5em;
}
.message-text h3 {
  font-size: 1.25em;
}
.message-text ul,
.message-text ol {
  padding-left: 2em;
  margin-top: 1em;
  margin-bottom: 1em;
}
.message-text li {
  margin-bottom: 0.5em;
}
.message-text blockquote {
  padding: 0.5em 1em;
  margin: 1em 0;
  color: #6b7280;
  border-left: 0.25em solid #e5e7eb;
  background: #f9fafb;
}
.message-text pre {
  background: #f3f4f6;
  padding: 1em;
  border-radius: 8px;
  overflow-x: auto;
  margin: 1em 0;
}
.message-text code {
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
  font-size: 0.9em;
  background-color: rgba(27, 31, 35, 0.05);
  padding: 0.2em 0.4em;
  border-radius: 6px;
}
.message-text pre > code {
  padding: 0;
  margin: 0;
  font-size: inherit;
  background-color: transparent;
  border-radius: 0;
}

/* 表格样式（GFM） */
.message-text table {
  width: 100%;
  border-collapse: collapse;
  border-spacing: 0;
  margin: 1em 0;
}
.message-text thead th {
  background: #f3f4f6;
}
.message-text th,
.message-text td {
  border: 1px solid #e5e7eb;
  padding: 8px 12px;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
}
.message-text tr:nth-child(even) td {
  background: #fafafa;
}
.message-text {
  overflow-x: auto; /* 表格超宽时允许横向滚动 */
}
</style>
