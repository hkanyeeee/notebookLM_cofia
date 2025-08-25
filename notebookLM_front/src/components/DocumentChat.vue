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
  <div class="flex flex-col h-full">
    <!-- 消息列表 / 欢迎信息 -->
    <div ref="messageContainer" class="flex-1 overflow-y-auto p-6 scroll-smooth">
      <!-- 欢迎消息 -->
      <div v-if="messages.length === 0" class="text-center max-w-2xl mx-auto text-gray-700">
        <h2 class="text-xl font-semibold text-gray-900 mb-4">文档问答</h2>
        <p class="mb-10 text-base leading-relaxed">您可以输入一个课题，我会先生成搜索查询并抓取候选网页供添加；或者在左侧直接添加网址。</p>
        
        <!-- 课题输入 -->
        <div class="flex gap-3 items-center mb-6">
          <ElInput
            :model-value="topicInput"
            @update:model-value="handleTopicInputUpdate"
            placeholder="请输入课题，例如：Sora 2025 能力与限制"
            :disabled="generating"
            class="flex-1"
          />
          <ElButton
            type="primary"
            @click="handleGenerateCandidates"
            :loading="generating"
            :disabled="!topicInput.trim() || generating"
            class="whitespace-nowrap"
          >生成搜索</ElButton>
        </div>

        <!-- 候选URL按钮区 -->
        <div v-if="candidateUrls.length > 0" class="mt-6 text-left w-full max-w-2xl">
          <h3 class="text-lg font-medium mb-3">候选网址</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
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
                class="w-full h-auto overflow-hidden whitespace-nowrap p-3 text-left"
                @click="handleAddCandidate(item.url)"
              >
                <div class="w-full">
                  <div class="font-semibold mb-1 text-gray-900 truncate">{{ item.title }}</div>
                  <div class="text-xs text-gray-500 break-all truncate">{{ item.url }}</div>
                </div>
              </ElButton>
            </ElTooltip>
          </div>
        </div>

        <div v-if="messages.length === 0 && candidateUrls.length === 0" class="grid grid-cols-1 md:grid-cols-3 gap-6 mt-10">
          <div class="text-left p-5 bg-gray-50 rounded-lg border border-gray-200">
            <strong class="block mb-2 text-gray-900 text-sm">💡 智能问答</strong>
            <p class="text-xs text-gray-500 leading-relaxed">基于您添加的文档内容回答问题</p>
          </div>
          <div class="text-left p-5 bg-gray-50 rounded-lg border border-gray-200">
            <strong class="block mb-2 text-gray-900 text-sm">📚 文档总结</strong>
            <p class="text-xs text-gray-500 leading-relaxed">快速获取文档的核心要点</p>
          </div>
          <div class="text-left p-5 bg-gray-50 rounded-lg border border-gray-200">
            <strong class="block mb-2 text-gray-900 text-sm">🔍 深度分析</strong>
            <p class="text-xs text-gray-500 leading-relaxed">深入分析文档中的关键信息</p>
          </div>
        </div>
      </div>

      <!-- 对话消息 -->
      <div
        v-for="message in messages"
        :key="message.id"
        class="mb-6 flex"
        :class="message.type === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div 
          class="max-w-[70%] p-4 rounded-2xl relative"
          :class="message.type === 'user' 
            ? 'bg-indigo-600 text-white rounded-br-none' 
            : 'bg-gray-100 text-gray-900 rounded-bl-none'"
        >
          <!-- Reasoning Chain (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.reasoning" class="mb-4 border-t border-gray-200 pt-3 pb-3">
            <ElCollapse v-model="activeNames">
              <ElCollapseItem 
                :title="`思维链（${message.reasoning.length} 字）`" 
                name="reasoning"
                class="text-sm font-medium text-gray-700"
              >
                <div 
                  class="text-xs text-gray-700 leading-relaxed bg-gray-50 p-3 rounded-lg border border-gray-200"
                  v-html="marked(message.reasoning)"
                ></div>
              </ElCollapseItem>
            </ElCollapse>
          </div>
          <div 
            class="word-wrap break-words"
            v-if="message.content" 
            v-html="marked(message.content)" 
            :class="{ 'status-message': isStatusMessage(message.content) }"
          ></div>
          <div v-else>思考中...</div>
          <div class="text-xs opacity-70 mt-2 text-right" :class="message.type === 'assistant' ? 'text-left' : 'text-right'">
            {{ formatTime(message.timestamp) }}
          </div>

          <!-- Sources (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.sources && message.sources.length > 0" class="mt-4 border-t border-gray-200 pt-3">
            <ElCollapse>
              <ElCollapseItem title="参考来源" name="sources">
                <div v-for="(source, index) in message.sources" :key="index" class="mb-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <div class="flex justify-between items-center mb-2">
                    <a 
                      :href="source.url" 
                      target="_blank" 
                      class="text-sm font-medium text-indigo-600 hover:underline"
                    >
                      {{ source.url.split('/').slice(0, 3).join('/') }}/.../{{ source.url.split('/').pop() }}
                    </a>
                    <span class="text-xs text-gray-500 font-mono">分数: {{ source.score.toFixed(4) }}</span>
                  </div>
                  <pre class="text-xs text-gray-700 leading-relaxed m-0 whitespace-pre-wrap">{{ source.content }}</pre>
                </div>
              </ElCollapseItem>
            </ElCollapse>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="p-6 border-t border-gray-200 bg-white">
      <div class="flex gap-3 items-center max-w-3xl mx-auto" @keydown.ctrl.enter="handleSendQuery">
        <ElInput
          v-model="queryInput"
          placeholder="请输入关于文档的问题..."
          class="flex-1 query-input"
          type="textarea"
          :rows="2"
        />
        <ElButton
          type="primary"
          @click="handleSendQuery"
          :disabled="isQueryDisabled()"
          :loading="loading || ingestionStatus.size > 0"
          class="h-10 w-10 p-0 rounded-lg"
        >
          <ElIcon>
            <Promotion />
          </ElIcon>
        </ElButton>
      </div>
      <div class="text-center mt-3 text-xs text-gray-500">
        文档问答模式：{{ documents.length }} 个文档已添加
      </div>
    </div>
  </div>
</template>

<style scoped>
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