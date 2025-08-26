<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { ElInput, ElButton, ElMessage, ElIcon } from 'element-plus'
import { Promotion, Edit, Check, Close, ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { marked } from 'marked'
import type { Message } from '../stores/notebook'
import { QueryType } from '../stores/types'

// 启用 GitHub 风格 Markdown（GFM），支持表格等语法
marked.setOptions({
  gfm: true,
  breaks: true,
})

// Props
interface Props {
  messages: Message[]
  loading: boolean
  queryType: QueryType
  selectedModel: string
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  (e: 'sendQuery', query: string): void
  (e: 'startEditMessage', messageId: string): void
  (e: 'cancelEditMessage', messageId: string): void
  (e: 'updateEditingMessage', messageId: string, content: string): void
  (e: 'resendEditedMessage', messageId: string): void
}>()

// 查询输入
const queryInput = ref('')
const messageContainer = ref<HTMLElement>()
// 控制分析过程的展开/折叠状态，默认为展开
const reasoningExpanded = ref<Record<string, boolean>>({})

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

// 开始编辑消息
function handleStartEdit(messageId: string) {
  emit('startEditMessage', messageId)
}

// 取消编辑消息
function handleCancelEdit(messageId: string) {
  emit('cancelEditMessage', messageId)
}

// 更新编辑中的消息内容
function handleUpdateEditingMessage(messageId: string, content: string) {
  emit('updateEditingMessage', messageId, content)
}

// 重新发送编辑后的消息
function handleResendMessage(messageId: string) {
  const message = props.messages.find(m => m.id === messageId)
  if (!message || !message.content.trim()) {
    ElMessage.warning('消息内容不能为空')
    return
  }
  emit('resendEditedMessage', messageId)
}

// 检查是否可以编辑消息（只有用户消息才能编辑）
function canEditMessage(message: Message) {
  return message.type === 'user'
}

// 双击检测逻辑
const clickTimers = ref<Record<string, number>>({})

// 处理消息点击（双击检测）
function handleMessageClick(messageId: string) {
  const now = Date.now()
  const lastClickTime = clickTimers.value[messageId]
  
  if (lastClickTime && now - lastClickTime < 300) {
    // 双击检测成功，触发编辑模式
    delete clickTimers.value[messageId]
    const message = props.messages.find(m => m.id === messageId)
    if (message && message.type === 'user' && !message.isEditing) {
      handleStartEdit(messageId)
    }
  } else {
    // 记录第一次点击时间
    clickTimers.value[messageId] = now
    // 300ms后清除记录
    setTimeout(() => {
      if (clickTimers.value[messageId] === now) {
        delete clickTimers.value[messageId]
      }
    }, 300)
  }
}

// 切换分析过程展开/折叠状态
function toggleReasoning(messageId: string) {
  reasoningExpanded.value[messageId] = !isReasoningExpanded(messageId)
}

// 检查分析过程是否展开（默认为收起）
function isReasoningExpanded(messageId: string) {
  return reasoningExpanded.value[messageId] === true
}

</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 消息列表 / 欢迎信息 -->
    <div ref="messageContainer" class="flex-1 overflow-y-auto p-2 scroll-smooth">
      <!-- 欢迎消息 -->
      <div v-if="messages.length === 0" class="text-center max-w-2xl mx-auto text-gray-700">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mt-10">
          <div class="text-left p-5 bg-gray-50 rounded-lg border border-gray-200">
            <strong class="block mb-2 text-sm font-medium text-gray-900">🌐 网络搜索</strong>
            <p class="text-xs text-gray-600 leading-relaxed">实时搜索最新信息</p>
          </div>
          <div class="text-left p-5 bg-gray-50 rounded-lg border border-gray-200">
            <strong class="block mb-2 text-sm font-medium text-gray-900">💬 智能对话</strong>
            <p class="text-xs text-gray-600 leading-relaxed">自然语言交互体验</p>
          </div>
          <div class="text-left p-5 bg-gray-50 rounded-lg border border-gray-200">
            <strong class="block mb-2 text-sm font-medium text-gray-900">🎯 精准回答</strong>
            <p class="text-xs text-gray-600 leading-relaxed">基于搜索结果生成准确答案</p>
          </div>
        </div>
      </div>

      <!-- 对话消息 -->
      <div
        v-for="message in messages"
        :key="message.id"
        class="mb-6 flex relative group"
        :class="message.type === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div 
          class="max-w-[98%] p-4 rounded-2xl relative"
          :class="message.type === 'user' ? 'bg-indigo-600 text-white rounded-br-none' : 'bg-gray-100 text-gray-900 rounded-bl-none'"
        >
          <!-- Reasoning Chain (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.reasoning" class="mb-4 border-t border-gray-200 pt-3">
            <div 
              class="text-sm font-medium text-gray-800 mb-2 cursor-pointer hover:text-indigo-600 flex items-center justify-between"
              @click="toggleReasoning(message.id)"
            >
              <span>分析过程</span>
              <ElIcon class="text-gray-500 hover:text-indigo-600 transition-transform duration-200" 
                      :class="{ 'rotate-180': !isReasoningExpanded(message.id) }">
                <ArrowUp />
              </ElIcon>
            </div>
            <div 
              v-if="isReasoningExpanded(message.id)"
              class="text-xs text-gray-700 leading-relaxed bg-gray-50 p-3 rounded-lg chat-message-content"
            >{{ message.reasoning }}</div>
          </div>

          <!-- 用户消息：编辑模式或普通显示 -->
          <div v-if="message.type === 'user'">
            <!-- 编辑模式 -->
            <div v-if="message.isEditing" class="space-y-3">
              <ElInput
                :model-value="message.content"
                @input="(value: string) => handleUpdateEditingMessage(message.id, value)"
                type="textarea"
                :rows="3"
                placeholder="编辑您的消息..."
                class="w-full"
              />
              <div class="flex gap-2 justify-end">
                <ElButton
                  size="small"
                  @click="handleCancelEdit(message.id)"
                >
                  <ElIcon><Close /></ElIcon>
                  取消
                </ElButton>
                <ElButton
                  type="primary"
                  size="small"
                  @click="handleResendMessage(message.id)"
                  :disabled="!message.content.trim()"
                >
                  <ElIcon><Check /></ElIcon>
                  重新发送
                </ElButton>
              </div>
            </div>
            <!-- 普通显示模式 -->
            <div v-else @click="handleMessageClick(message.id)" class="cursor-pointer">
              <div class="chat-message-content" v-html="marked(message.content)"></div>
              <div class="text-xs opacity-70 mt-2 text-right">{{ formatTime(message.timestamp) }}</div>
            </div>
          </div>

          <!-- 助手消息：普通显示 -->
          <div v-else>
            <div 
              v-if="message.content" 
              v-html="marked(message.content)"
              class="chat-message-content"
              :class="{ 'status-message': isStatusMessage(message.content) }">
            </div>
            <div class="status-message" v-else>思考中...</div>
            <div class="text-xs opacity-70 mt-2 text-left">{{ formatTime(message.timestamp) }}</div>
          </div>

          <!-- Sources (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.sources && message.sources.length > 0" class="mt-4 border-t border-gray-200 pt-3">
            <details class="group">
              <summary class="text-sm font-medium text-gray-800 cursor-pointer hover:text-indigo-600 list-none flex items-center">
                <span class="inline-block w-0 h-0 border-l-4 border-l-gray-400 border-t-2 border-b-2 border-t-transparent border-b-transparent mr-2 transition-transform group-open:rotate-90"></span>
                参考来源 ({{ message.sources.length }})
              </summary>
              <div class="mt-2 space-y-3">
                <div v-for="(source, index) in message.sources" :key="index" class="p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <div class="flex justify-between items-center mb-2">
                    <a :href="source.url" target="_blank" class="text-xs font-medium text-indigo-600 hover:underline">{{ source.url.split('/').slice(0, 3).join('/') }}/.../{{ source.url.split('/').pop() }}</a>
                    <span class="text-xs text-gray-600 font-mono">分数: {{ source.score.toFixed(4) }}</span>
                  </div>
                  <pre class="text-xs text-gray-700 leading-relaxed m-0">{{ source.content }}</pre>
                </div>
              </div>
            </details>
          </div>
        </div>
        

      </div>
    </div>

    <!-- 输入区域 -->
    <div class="p-6 border-t border-gray-200 bg-white">
      <div class="flex gap-3 items-center max-w-3xl mx-auto" @keydown.shift.enter="handleSendQuery">
        <ElInput
          v-model="queryInput"
          placeholder="请输入您的问题..."
          class="flex-1"
          type="textarea"
          :rows="2"
        />
        <ElButton
          type="primary"
          @click="handleSendQuery"
          :disabled="!queryInput.trim() || loading"
          :loading="loading"
          class="h-10 w-10 p-0 rounded-lg"
        >
          <ElIcon>
            <Promotion />
          </ElIcon>
        </ElButton>
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
</style>

<style>
/* 移除所有全局样式 */
</style>