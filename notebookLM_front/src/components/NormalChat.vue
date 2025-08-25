<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { ElInput, ElButton, ElMessage, ElIcon, ElCollapse, ElCollapseItem } from 'element-plus'
import { Promotion } from '@element-plus/icons-vue'
import { marked } from 'marked'
import type { Message } from '../stores/notebook'

// 启用 GitHub 风格 Markdown（GFM），支持表格等语法
marked.setOptions({
  gfm: true,
  breaks: true,
})

// Props
interface Props {
  messages: Message[]
  loading: boolean
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  (e: 'sendQuery', query: string): void
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
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 消息列表 / 欢迎信息 -->
    <div ref="messageContainer" class="flex-1 overflow-y-auto p-6 scroll-smooth">
      <!-- 欢迎消息 -->
      <div v-if="messages.length === 0" class="text-center max-w-2xl mx-auto text-gray-700">
        <h2 class="text-xl font-semibold text-gray-900 mb-4">普通问答</h2>
        <p class="mb-10 text-base leading-relaxed">我会使用网络搜索为您提供最新的信息和答案，直接在下方输入您的问题即可开始对话。</p>
        
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
        class="mb-6 flex"
        :class="message.type === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div 
          class="max-w-[70%] p-4 rounded-2xl relative"
          :class="message.type === 'user' ? 'bg-indigo-600 text-white rounded-br-none' : 'bg-gray-100 text-gray-900 rounded-bl-none'"
        >
          <!-- Reasoning Chain (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.reasoning" class="mb-4 border-gray-200 pt-3 pb-3">
            <ElCollapse v-model="activeNames">
              <ElCollapseItem title="分析过程" name="reasoning">
                <div class="text-xs text-gray-700 leading-relaxed bg-gray-50 p-3 rounded-lg border border-gray-200" v-html="marked(message.reasoning)"></div>
              </ElCollapseItem>
            </ElCollapse>
          </div>
          <div 
            v-if="message.content" 
            v-html="marked(message.content)" 
            :class="{ 'bg-gray-50 p-3 rounded-lg border border-gray-200': isStatusMessage(message.content) }"
          ></div>
          <div v-else>思考中...</div>
          <div class="text-xs opacity-70 mt-2 text-right" :class="message.type === 'assistant' ? 'text-left' : 'text-right'">{{ formatTime(message.timestamp) }}</div>

          <!-- Sources (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.sources && message.sources.length > 0" class="mt-4  border-gray-200 pt-3">
            <ElCollapse>
              <ElCollapseItem title="参考来源" name="sources">
                <div v-for="(source, index) in message.sources" :key="index" class="mb-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <div class="flex justify-between items-center mb-2">
                    <a :href="source.url" target="_blank" class="text-xs font-medium text-indigo-600 hover:underline">{{ source.url.split('/').slice(0, 3).join('/') }}/.../{{ source.url.split('/').pop() }}</a>
                    <span class="text-xs text-gray-600 font-mono">分数: {{ source.score.toFixed(4) }}</span>
                  </div>
                  <pre class="text-xs text-gray-700 leading-relaxed m-0">{{ source.content }}</pre>
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
      <div class="text-center mt-3 text-xs text-gray-600">
        <span>普通问答模式</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 移除所有scoped样式 */
</style>

<style>
/* 移除所有全局样式 */
</style>