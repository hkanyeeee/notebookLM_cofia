<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { ElInput, ElButton, ElMessage, ElIcon, ElCollapse, ElCollapseItem, ElSelect, ElOption } from 'element-plus'
import { Promotion, Plus } from '@element-plus/icons-vue'
import { marked } from 'marked'
import type { Message } from '../stores/notebook'
import type { AgenticCollection, CollectionResult } from '../api/notebook'

// 启用 GitHub 风格 Markdown（GFM），支持表格等语法
marked.setOptions({
  gfm: true,
  breaks: true,
})

// Props
interface Props {
  messages: Message[]
  collections: AgenticCollection[]
  selectedCollection: string | null
  loading: boolean
  loadingCollections: boolean
  collectionQueryResults: CollectionResult[]
  agenticIngestUrl: string
  triggeringAgenticIngest: boolean
  shouldUseWebSearch: boolean
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  (e: 'sendQuery', query: string): void
  (e: 'update:selectedCollection', value: string | null): void
  (e: 'update:agenticIngestUrl', value: string): void
  (e: 'triggerAgenticIngest'): void
  (e: 'clearCollectionResults'): void
}>()

// 查询输入
const queryInput = ref('')
const messageContainer = ref<HTMLElement>()
const showDetailedResults = ref(false)

// 监听消息变化，自动滚动到底部
watch(() => props.messages.length, async () => {
  await nextTick()
  scrollToBottom()
}, { flush: 'post' })

// 监听loading状态变化，当查询完成时滚动
watch(() => props.loading, async (newVal, oldVal) => {
  if (oldVal && !newVal) {
    // 查询完成，滚动到底部
    await nextTick()
    scrollToBottom()
  }
}, { flush: 'post' })

// 流式过程中，监听最后一条消息内容和思维链变化，持续滚动
watch(
  () => {
    if (props.messages.length === 0) return ''
    const lastMsg = props.messages[props.messages.length - 1]
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

  // Collection问答：需要选择collection
  if (!props.selectedCollection) {
    ElMessage.warning('请先选择一个Collection')
    return
  }

  queryInput.value = ''
  emit('sendQuery', query)
}

// 滚动到底部
function scrollToBottom() {
  if (messageContainer.value) {
    messageContainer.value.scrollTop = messageContainer.value.scrollHeight
  }
}

// 格式化时间
function formatTime(date: Date) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

// 判断消息是否为状态消息
function isStatusMessage(content: string) {
  const statusPatterns = [
    /🔍.*搜索/,
    /✅.*完成/,
    /🔧.*工具/,
    /正在处理.*请稍候/,
  ]
  return statusPatterns.some(pattern => pattern.test(content))
}

// 处理Collection选择变化
function handleCollectionChange(value: string | null) {
  emit('update:selectedCollection', value)
}

// 处理Agentic Ingest URL变化
function handleAgenticIngestUrlUpdate(value: string) {
  emit('update:agenticIngestUrl', value)
}

// 触发Agentic Ingest
function handleTriggerAgenticIngest() {
  emit('triggerAgenticIngest')
}

// 清空Collection结果
function handleClearCollectionResults() {
  emit('clearCollectionResults')
}

// 判断查询按钮是否禁用
function isQueryDisabled() {
  if (!queryInput.value.trim()) return true
  if (props.loading) return true
  return !props.selectedCollection
}

// 获取输入框placeholder
function getInputPlaceholder() {
  return props.selectedCollection 
    ? `在 '${props.collections.find(c => c.collection_id === props.selectedCollection)?.document_title}' 中查询...`
    : '请先选择Collection，然后输入问题...'
}
</script>

<template>
  <div class="collection-chat">
    <!-- 消息列表 / 欢迎信息 -->
    <div ref="messageContainer" class="messages-container">
      <!-- Collection查询结果区域 -->
      <div v-if="collectionQueryResults.length > 0 && messages.length === 0" class="collection-results">
        <div class="collection-results-header">
          <h3>Collection搜索结果 ({{ collectionQueryResults.length }} 个相关文档片段)</h3>
          <div class="collection-results-actions">
            <ElButton text @click="showDetailedResults = !showDetailedResults" class="toggle-results-btn">
              {{ showDetailedResults ? '隐藏详细结果' : '查看详细结果' }}
            </ElButton>
            <ElButton text @click="handleClearCollectionResults()" class="clear-results-btn">
              清空结果
            </ElButton>
          </div>
        </div>
        <div v-if="showDetailedResults" class="collection-results-list">
          <div 
            v-for="(result, index) in collectionQueryResults" 
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
            📄 找到 {{ collectionQueryResults.length }} 个相关文档片段，
            <ElButton type="primary" size="small" @click="handleSendQuery()">
              点击生成智能回答
            </ElButton>
          </p>
        </div>
      </div>
      
      <!-- 欢迎消息 -->
      <div v-if="messages.length === 0 && collectionQueryResults.length === 0" class="welcome-message">
        <h2>Collection问答</h2>
        <p>选择一个Collection进行基于知识库的问答，同时可以结合网络搜索获取最新信息。</p>
        
        <div class="welcome-features">
          <div class="feature-item">
            <strong>📚 知识库问答</strong>
            <p>基于Collection中的文档回答</p>
          </div>
          <div class="feature-item">
            <strong>🔍 混合搜索</strong>
            <p>结合知识库和网络搜索</p>
          </div>
          <div class="feature-item">
            <strong>📊 精准匹配</strong>
            <p>智能检索相关文档片段</p>
          </div>
        </div>
      </div>

      <!-- 对话消息 -->
      <div
        v-for="message in messages"
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
          <div class="message-text" v-if="message.content" v-html="marked(message.content)" :class="{ 'status-message': isStatusMessage(message.content) }"></div>
          <div class="message-text" v-else>信息加载中...</div>
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

    <!-- 输入区域 -->
    <div class="input-area">
      <!-- Collection与Agentic Ingest 控制区 -->
      <div class="agentic-controls">
        <!-- Collection选择下拉框 -->
        <ElSelect
          :model-value="selectedCollection"
          @update:model-value="handleCollectionChange"
          placeholder="选择Collection"
          class="collection-selector"
          :loading="loadingCollections"
          clearable
        >
          <ElOption
            v-for="collection in collections"
            :key="collection.collection_id"
            :label="collection.document_title"
            :value="collection.collection_id"
          />
        </ElSelect>
        
        <!-- URL输入框 -->
        <ElInput
          :model-value="agenticIngestUrl"
          @update:model-value="handleAgenticIngestUrlUpdate"
          placeholder="输入URL进行Agentic Ingest"
          class="url-input"
          clearable
        />
        
        <!-- 提交按钮 -->
        <ElButton
          type="primary"
          @click="handleTriggerAgenticIngest"
          :loading="triggeringAgenticIngest"
          :disabled="!agenticIngestUrl.trim() || triggeringAgenticIngest"
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
          :placeholder="getInputPlaceholder()"
          class="query-input"
          type="textarea"
          :rows="2"
        />
        <ElButton
          type="primary"
          @click="handleSendQuery"
          :disabled="isQueryDisabled()"
          :loading="loading"
          class="send-btn"
        >
          <ElIcon>
            <Promotion />
          </ElIcon>
        </ElButton>
      </div>
      <div class="input-hint">
        <span>
          Collection问答模式{{ shouldUseWebSearch ? '（已启用网络搜索）' : '' }}：
          {{ selectedCollection 
            ? collections.find(c => c.collection_id === selectedCollection)?.document_title || '未知Collection' 
            : '请选择Collection' }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.collection-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
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

.clear-results-btn,
.toggle-results-btn {
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
  white-space: pre-wrap;
}

:deep(.el-collapse-item__header) {
  font-size: 14px;
  font-weight: 500;
  color: #374151;
}

:deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

/* 状态消息样式 */
.status-message {
  background: linear-gradient(135deg, #f0f9ff 0%, #e0f7fa 100%) !important;
  border: 1px solid #b3e5fc !important;
  border-radius: 8px !important;
  padding: 12px 16px !important;
  margin: 8px 0 !important;
  color: #0277bd !important;
  font-weight: 500 !important;
  animation: statusPulse 1.5s ease-in-out infinite !important;
  box-shadow: 0 2px 8px rgba(2, 119, 189, 0.1) !important;
  position: relative !important;
}

.status-message::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: linear-gradient(to bottom, #29b6f6, #0288d1);
  border-radius: 8px 0 0 8px;
}

@keyframes statusPulse {
  0%, 100% {
    opacity: 0.9;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.01);
  }
}

.input-area {
  padding: 24px;
  border-top: 1px solid #e5e7eb;
  background: white;
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

/* 响应式设计 */
@media (max-width: 768px) {
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

  .input-area {
    padding: 16px;
  }
}
</style>

<style>
/* Markdown 内容的全局样式 */
.collection-chat .message-text p {
  margin-top: 0;
  margin-bottom: 1em;
}
.collection-chat .message-text h1,
.collection-chat .message-text h2,
.collection-chat .message-text h3,
.collection-chat .message-text h4,
.collection-chat .message-text h5,
.collection-chat .message-text h6 {
  margin-top: 1.5em;
  margin-bottom: 1em;
  font-weight: 600;
}
.collection-chat .message-text h1 {
  font-size: 1.75em;
}
.collection-chat .message-text h2 {
  font-size: 1.5em;
}
.collection-chat .message-text h3 {
  font-size: 1.25em;
}
.collection-chat .message-text ul,
.collection-chat .message-text ol {
  padding-left: 2em;
  margin-top: 1em;
  margin-bottom: 1em;
}
.collection-chat .message-text li {
  margin-bottom: 0.5em;
}
.collection-chat .message-text blockquote {
  padding: 0.5em 1em;
  margin: 1em 0;
  color: #6b7280;
  border-left: 0.25em solid #e5e7eb;
  background: #f9fafb;
}
.collection-chat .message-text pre {
  background: #f3f4f6;
  padding: 1em;
  border-radius: 8px;
  overflow-x: auto;
  margin: 1em 0;
}
.collection-chat .message-text code {
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
  font-size: 0.9em;
  background-color: rgba(27, 31, 35, 0.05);
  padding: 0.2em 0.4em;
  border-radius: 6px;
}
.collection-chat .message-text pre > code {
  padding: 0;
  margin: 0;
  font-size: inherit;
  background-color: transparent;
  border-radius: 0;
}

/* 表格样式（GFM） */
.collection-chat .message-text table {
  width: 100%;
  border-collapse: collapse;
  border-spacing: 0;
  margin: 1em 0;
}
.collection-chat .message-text thead th {
  background: #f3f4f6;
}
.collection-chat .message-text th,
.collection-chat .message-text td {
  border: 1px solid #e5e7eb;
  padding: 8px 12px;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
}
.collection-chat .message-text tr:nth-child(even) td {
  background: #fafafa;
}
.collection-chat .message-text {
  overflow-x: auto;
}
</style>
