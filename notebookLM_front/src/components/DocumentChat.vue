<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { ElInput, ElButton, ElMessage, ElIcon, ElCollapse, ElCollapseItem, ElTooltip } from 'element-plus'
import { Promotion } from '@element-plus/icons-vue'
import { marked } from 'marked'
import type { Message, Document, IngestionProgress } from '../stores/notebook'

// 启用 GitHub 风格 Markdown（GFM），支持表格等语法
marked.setOptions({
  gfm: true,
  breaks: true,
})

// Props
interface Props {
  messages: Message[]
  documents: Document[]
  loading: boolean
  ingestionStatus: Map<string, IngestionProgress>
  topicInput: string
  generating: boolean
  candidateUrls: Array<{ url: string; title: string }>
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  (e: 'sendQuery', query: string): void
  (e: 'generateCandidatesFromTopic'): void
  (e: 'addCandidate', url: string): void
  (e: 'update:topicInput', value: string): void
}>()

// 查询输入
const queryInput = ref('')
const messageContainer = ref<HTMLElement>()
// 控制思维链和参考来源的展开状态，默认展开思维链
const activeNames = ref(['reasoning'])

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

  // 文档问答：需要先添加文档
  if (props.documents.length === 0) {
    ElMessage.warning('请先添加一些文档再开始对话')
    return
  }
  if (props.ingestionStatus.size > 0) {
    ElMessage.warning('正在处理文档，请稍后再试')
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
    /正在思考\.\.\./,
    /搜索中\.\.\./,
    /再次思考中\.\.\./,
  ]
  return statusPatterns.some(pattern => pattern.test(content))
}

// 处理课题输入变化
function handleTopicInputUpdate(value: string) {
  emit('update:topicInput', value)
}

// 生成候选网址
function handleGenerateCandidates() {
  emit('generateCandidatesFromTopic')
}

// 添加候选网址
function handleAddCandidate(url: string) {
  emit('addCandidate', url)
}

// 判断查询按钮是否禁用
function isQueryDisabled() {
  if (!queryInput.value.trim()) return true
  if (props.loading) return true
  return props.documents.length === 0 || props.ingestionStatus.size > 0
}
</script>

<template>
  <div class="document-chat">
    <!-- 消息列表 / 欢迎信息 -->
    <div ref="messageContainer" class="messages-container">
      <!-- 欢迎消息 -->
      <div v-if="messages.length === 0" class="welcome-message">
        <h2>文档问答</h2>
        <p>您可以输入一个课题，我会先生成搜索查询并抓取候选网页供添加；或者在左侧直接添加网址。</p>
        
        <!-- 课题输入 -->
        <div class="topic-input">
          <ElInput
            :model-value="topicInput"
            @update:model-value="handleTopicInputUpdate"
            placeholder="请输入课题，例如：Sora 2025 能力与限制"
            :disabled="generating"
          />
          <ElButton
            type="primary"
            @click="handleGenerateCandidates"
            :loading="generating"
            :disabled="!topicInput.trim() || generating"
            class="topic-send-btn"
          >生成搜索</ElButton>
        </div>

        <!-- 候选URL按钮区 -->
        <div v-if="candidateUrls.length > 0" class="candidates">
          <h3>候选网址</h3>
          <div class="candidate-grid">
            <ElTooltip
              v-for="item in candidateUrls"
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
                @click="handleAddCandidate(item.url)"
              >
                <div class="candidate-item-content">
                  <div class="candidate-title">{{ item.title }}</div>
                  <div class="candidate-url">{{ item.url }}</div>
                </div>
              </ElButton>
            </ElTooltip>
          </div>
        </div>

        <div v-if="messages.length === 0 && candidateUrls.length === 0" class="welcome-features">
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
        v-for="message in messages"
        :key="message.id"
        class="message"
        :class="message.type"
      >
        <div class="message-content">
          <!-- Reasoning Chain (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.reasoning" class="reasoning-section">
            <ElCollapse v-model="activeNames">
              <ElCollapseItem :title="`思维链（${message.reasoning.length} 字）`" name="reasoning">
                <div class="reasoning-content" v-html="marked(message.reasoning)"></div>
              </ElCollapseItem>
            </ElCollapse>
          </div>
          <div class="message-text" v-if="message.content" v-html="marked(message.content)" :class="{ 'status-message': isStatusMessage(message.content) }"></div>
          <div class="message-text" v-else>思考中...</div>
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
      <div class="input-container" @keydown.ctrl.enter="handleSendQuery">
        <ElInput
          v-model="queryInput"
          placeholder="请输入关于文档的问题..."
          class="query-input"
          type="textarea"
          :rows="2"
        />
        <ElButton
          type="primary"
          @click="handleSendQuery"
          :disabled="isQueryDisabled()"
          :loading="loading || ingestionStatus.size > 0"
          class="send-btn"
        >
          <ElIcon>
            <Promotion />
          </ElIcon>
        </ElButton>
      </div>
      <div class="input-hint">
        <span>文档问答模式：{{ documents.length }} 个文档已添加</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.document-chat {
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
  margin: 40px auto;
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

.topic-input {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 24px;
}

.topic-send-btn {
  white-space: nowrap;
}

.candidates {
  margin-top: 24px;
  text-align: left;
  width: 100%;
  max-width: 800px;
}

.candidate-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.candidate-grid .candidate-item:first-child {
  margin-left: 12px;
}

.candidate-item {
  display: block;
  text-align: left;
  height: auto;
  overflow: hidden;
  white-space: nowrap;
  padding: 12px;
  width: 100%;
  min-width: 260px;
}

.candidate-item-content {
  width: 100%;
}

.candidate-title {
  font-weight: 600;
  margin-bottom: 4px;
  color: #111827;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-url {
  font-size: 12px;
  color: #6b7280;
  word-break: break-all;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  border-radius: 8px !important;
  padding: 12px 16px !important;
  margin: 8px 0 !important;
  color: #6b7280 !important;
  font-weight: 400 !important;
  position: relative !important;
  overflow: hidden !important;
}

.status-message::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.8) 50%,
    transparent 100%
  );
  animation: highlightSweep 1.5s ease-in-out infinite;
}

@keyframes highlightSweep {
  0% {
    left: -100%;
  }
  50% {
    left: 100%;
  }
  100% {
    left: 100%;
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

/* 响应式设计 */
@media (max-width: 768px) {
  .messages-container {
    padding: 16px;
    /* 确保有足够的滚动空间 */
    min-height: 0;
  }

  .welcome-message {
    margin: 20px auto;
    padding: 0 8px;
  }

  .message-content {
    max-width: 85%;
  }

  .welcome-features {
    grid-template-columns: 1fr;
    gap: 16px;
    margin-top: 24px;
  }

  .candidates {
    width: 100%;
    margin-left: 0;
    margin-top: 16px;
  }

  .candidate-grid {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .candidate-item {
    width: 100%;
  }

  .candidate-item-content {
    width: 100%;
  }

  .candidate-title,
  .candidate-url {
    width: 100%;
  }

  .topic-input {
    flex-direction: column;
    gap: 8px;
  }

  .topic-send-btn {
    width: 100%;
  }

  .input-area {
    padding: 16px;
  }
}
</style>

<style>
/* Markdown 内容的全局样式 */
.document-chat .message-text p {
  margin-top: 0;
  margin-bottom: 1em;
}
.document-chat .message-text h1,
.document-chat .message-text h2,
.document-chat .message-text h3,
.document-chat .message-text h4,
.document-chat .message-text h5,
.document-chat .message-text h6 {
  margin-top: 1.5em;
  margin-bottom: 1em;
  font-weight: 600;
}
.document-chat .message-text h1 {
  font-size: 1.75em;
}
.document-chat .message-text h2 {
  font-size: 1.5em;
}
.document-chat .message-text h3 {
  font-size: 1.25em;
}
.document-chat .message-text ul,
.document-chat .message-text ol {
  padding-left: 2em;
  margin-top: 1em;
  margin-bottom: 1em;
}
.document-chat .message-text li {
  margin-bottom: 0.5em;
}
.document-chat .message-text blockquote {
  padding: 0.5em 1em;
  margin: 1em 0;
  color: #6b7280;
  border-left: 0.25em solid #e5e7eb;
  background: #f9fafb;
}
.document-chat .message-text pre {
  background: #f3f4f6;
  padding: 1em;
  border-radius: 8px;
  overflow-x: auto;
  margin: 1em 0;
}
.document-chat .message-text code {
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
  font-size: 0.9em;
  background-color: rgba(27, 31, 35, 0.05);
  padding: 0.2em 0.4em;
  border-radius: 6px;
}
.document-chat .message-text pre > code {
  padding: 0;
  margin: 0;
  font-size: inherit;
  background-color: transparent;
  border-radius: 0;
}

/* 表格样式（GFM） */
.document-chat .message-text table {
  width: 100%;
  border-collapse: collapse;
  border-spacing: 0;
  margin: 1em 0;
}
.document-chat .message-text thead th {
  background: #f3f4f6;
}
.document-chat .message-text th,
.document-chat .message-text td {
  border: 1px solid #e5e7eb;
  padding: 8px 12px;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
}
.document-chat .message-text tr:nth-child(even) td {
  background: #fafafa;
}
.document-chat .message-text {
  overflow-x: auto;
}
</style>
