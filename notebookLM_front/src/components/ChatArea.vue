<script setup lang="ts">
import { ref, nextTick, computed, watch } from 'vue'
import { useNotebookStore } from '../stores/notebook'
import { ElInput, ElButton, ElMessage, ElIcon, ElCollapse, ElCollapseItem, ElTooltip } from 'element-plus'
import { Refresh, Promotion } from '@element-plus/icons-vue'
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

// 发送查询
async function handleSendQuery() {
  const query = queryInput.value.trim()
  if (!query) {
    ElMessage.warning('请输入您的问题')
    return
  }

  if (store.documents.length === 0) {
    ElMessage.warning('请先添加一些文档再开始对话')
    return
  }

  if (store.ingestionStatus.size > 0) {
    ElMessage.warning('正在处理文档，请稍后再试')
    return
  }

  try {
    queryInput.value = ''
    await store.sendQuery(query)
  } catch {
    ElMessage.error('查询失败，请重试')
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
</script>

<template>
  <div class="chat-area">
    <!-- 头部 -->
    <header class="chat-header">
      <h1>对话</h1>
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
          <div class="message-text" v-html="marked(message.content)"></div>
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

      <!-- 加载状态 -->
      <div v-if="store.loading.querying" class="message assistant loading">
        <div class="message-content">
          <div class="typing-indicator">
            <span></span>
            <span></span>
            <span></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域：当无文档时禁用提问 -->
    <div class="input-area">
      <div class="input-container" @keydown.enter.shift.prevent="handleSendQuery">
        <ElInput
          v-model="queryInput"
          placeholder="请输入您的问题..."
          class="query-input"
          type="textarea"
          :rows="2"
        />
        <ElButton
          type="primary"
          @click="handleSendQuery"
          :disabled="store.loading.querying || !queryInput.trim() || store.documents.length === 0 || store.ingestionStatus.size > 0"
          :loading="store.loading.querying || store.ingestionStatus.size > 0"
          class="send-btn"
        >
          <ElIcon>
            <Promotion />
          </ElIcon>
        </ElButton>
      </div>
      <div class="input-hint">
        <span>{{ store.documents.length }} 个文档已添加</span>
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

.chat-header h1 {
  margin: 0;
  color: #111827;
  font-size: 20px;
  font-weight: 600;
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

/* 响应式设计 */
@media (max-width: 768px) {
  .chat-header {
    padding: 16px;
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
