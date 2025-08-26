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
    /正在思考\.\.\./,
    /搜索中\.\.\./,
    /再次思考中\.\.\./,
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
  <div class="flex flex-col h-full">
    <!-- 消息列表 / 欢迎信息 -->
    <div ref="messageContainer" class="flex-1 overflow-y-auto p-2 scroll-smooth">
      
      <!-- 智能欢迎消息 -->
      <div v-if="messages.length === 0" class="max-w-4xl mx-auto p-6">
        
        <!-- 没有任何Collection时 - 引导添加 -->
        <div v-if="collections.length === 0 && !loadingCollections" class="text-center">
          <div class="mb-8">
            <div class="text-6xl mb-4">📚</div>
            <h2 class="text-2xl font-bold text-gray-900 mb-4">欢迎使用Collection问答</h2>
            <p class="text-gray-600 mb-8 max-w-lg mx-auto">
              通过添加URL创建您的第一个Collection，或者选择现有的Collection开始对话。
            </p>
          </div>
          
          <div class="bg-indigo-50 border border-indigo-200 rounded-xl p-6 mb-6">
            <div class="flex items-center justify-center mb-4">
              <div class="w-8 h-8 bg-indigo-500 rounded-full flex items-center justify-center text-white font-bold mr-3">1</div>
              <h3 class="text-lg font-semibold text-gray-900">创建您的第一个Collection</h3>
            </div>
            <p class="text-gray-600 mb-4">在下方输入一个URL，系统将自动抓取并处理内容，创建可搜索的Collection。</p>
          </div>

        </div>

        <!-- 有Collection但未选择时 - 显示可选择的Collection -->
        <div v-else-if="collections.length > 0 && !selectedCollection" class="text-center">
          <div class="mb-8">
            <div class="text-5xl mb-4">🎯</div>
            <h2 class="text-2xl font-bold text-gray-900 mb-4">选择一个Collection开始对话</h2>
            <p class="text-gray-600 mb-6">
              您有 {{ collections.length }} 个可用的Collection，请选择一个开始智能问答。
            </p>
          </div>

          <!-- Collection卡片列表 -->
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            <div 
              v-for="collection in collections" 
              :key="collection.collection_id"
              class="p-4 bg-white border-2 border-gray-200 rounded-xl hover:border-indigo-300 hover:shadow-md transition-all cursor-pointer"
              @click="handleCollectionChange(collection.collection_id)"
            >
              <div class="text-left">
                <div class="flex items-start justify-between mb-3">
                  <div class="text-2xl">📁</div>
                  <div class="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                    {{ collection.collection_id.substring(0, 8) }}...
                  </div>
                </div>
                <h3 class="font-semibold text-gray-900 mb-2 text-sm line-clamp-2">
                  {{ collection.document_title || '未命名Collection' }}
                </h3>
                <p class="text-xs text-gray-600 mb-3 line-clamp-3">
                  {{ collection.url || '无描述' }}
                </p>
                <div class="flex justify-between items-center text-xs text-gray-500">
                  <span>点击选择</span>
                  <span>→</span>
                </div>
              </div>
            </div>
          </div>

          <div class="bg-green-50 border border-green-200 rounded-xl p-4">
            <div class="flex items-center justify-center text-sm text-green-700">
              <span class="mr-2">✨</span>
              <span>您也可以通过下方的URL输入框添加新的Collection</span>
            </div>
          </div>
        </div>

        <!-- 已选择Collection时 - 显示Collection信息 -->
        <div v-else-if="selectedCollection" class="text-center">
          <div class="mb-8">
            <div class="text-5xl mb-4">💡</div>
            <h2 class="text-2xl font-bold text-gray-900 mb-4">
              {{ collections.find(c => c.collection_id === selectedCollection)?.document_title || 'Collection' }}
            </h2>
            <div class="max-w-2xl mx-auto">
              <div class="bg-indigo-50 border border-indigo-200 rounded-xl p-6 mb-6">
                <div class="text-left space-y-3">
                  <div class="flex items-center">
                    <span class="text-indigo-600 font-medium w-16">📋 标题:</span>
                    <span class="text-gray-700">{{ collections.find(c => c.collection_id === selectedCollection)?.document_title || '未知' }}</span>
                  </div>
                  <div class="flex items-center">
                    <span class="text-indigo-600 font-medium w-16">🔗 来源:</span>
                    <a 
                      :href="collections.find(c => c.collection_id === selectedCollection)?.url" 
                      target="_blank"
                      class="text-indigo-600 hover:text-indigo-800 underline text-sm truncate flex-1"
                    >
                      {{ collections.find(c => c.collection_id === selectedCollection)?.url }}
                    </a>
                  </div>
                  <div class="flex items-center">
                    <span class="text-blue-600 font-medium w-16">🆔 ID:</span>
                    <span class="text-gray-600 font-mono text-sm">{{ selectedCollection }}</span>
                  </div>
                </div>
              </div>
              
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                <div class="p-4 bg-gradient-to-r from-purple-50 to-pink-50 rounded-lg border border-purple-200">
                  <div class="text-2xl mb-2">🎯</div>
                  <h4 class="font-semibold text-gray-900 mb-2">准确回答</h4>
                  <p class="text-sm text-gray-600">基于选定Collection内容提供精准答案</p>
                </div>
                <div class="p-4 bg-gradient-to-r from-green-50 to-emerald-50 rounded-lg border border-green-200">
                  <div class="text-2xl mb-2">📖</div>
                  <h4 class="font-semibold text-gray-900 mb-2">来源引用</h4>
                  <p class="text-sm text-gray-600">每个回答都标注具体的文档来源</p>
                </div>
              </div>

              <div class="bg-amber-50 border border-amber-200 rounded-xl p-4">
                <div class="flex items-center justify-center text-sm text-amber-800">
                  <span class="mr-2">💬</span>
                  <span>现在您可以开始提问了！在下方输入您的问题。</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 加载状态 -->
        <div v-else-if="loadingCollections" class="text-center py-12">
          <div class="text-4xl mb-4">⏳</div>
          <h2 class="text-xl text-gray-600">正在加载Collection...</h2>
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
          class="max-w-[98%] p-4 rounded-2xl relative"
          :class="message.type === 'user' ? 'bg-indigo-600 text-white rounded-br-none' : 'bg-gray-100 text-gray-900 rounded-bl-none'"
        >
          <!-- Reasoning Chain (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.reasoning" class="mb-4 border-t border-gray-200 pt-3 pb-3">
            <el-collapse v-model="activeNames">
              <el-collapse-item title="思维链（" :name="'reasoning'">
                <div class="text-xs text-gray-700 leading-relaxed bg-gray-50 p-3 rounded-lg border border-gray-200 chat-message-content" v-html="marked(message.reasoning)"></div>
              </el-collapse-item>
            </el-collapse>
          </div>
          <div 
            v-if="message.content" 
            class="chat-message-content" 
            :class="{ 'status-message': isStatusMessage(message.content) }" 
            v-html="marked(message.content)"
          ></div>
          <div v-else>思考中...</div>
          <div class="text-xs opacity-70 mt-2 text-right" :class="message.type === 'assistant' ? 'text-left' : 'text-right'">{{ formatTime(message.timestamp) }}</div>

          <!-- Sources (for assistant messages) -->
          <div v-if="message.type === 'assistant' && message.sources && message.sources.length > 0" class="mt-4 border-t border-gray-200 pt-3">
            <el-collapse>
              <el-collapse-item title="参考来源" name="sources">
                <div v-for="(source, index) in message.sources" :key="index" class="mb-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <div class="flex justify-between items-center mb-2">
                    <a :href="source.url" target="_blank" class="text-sm font-medium text-indigo-600 hover:text-indigo-800 truncate">
                      {{ source.url.split('/').slice(0, 3).join('/') }}/.../{{ source.url.split('/').pop() }}
                    </a>
                    <span class="text-xs text-gray-500 font-mono">分数: {{ source.score.toFixed(4) }}</span>
                  </div>
                  <pre class="text-xs text-gray-700 leading-relaxed m-0 whitespace-pre-wrap">{{ source.content }}</pre>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="p-4 border-t border-gray-200 bg-white">
      <!-- Collection与Agentic Ingest 控制区 -->
      <div class="flex items-center mb-3 gap-3 max-w-3xl mx-auto">
        <!-- Collection选择下拉框 -->
        <el-select
          :model-value="selectedCollection"
          @update:model-value="handleCollectionChange"
          placeholder="选择Collection"
          class="w-48"
          :loading="loadingCollections"
          clearable
        >
          <el-option
            v-for="collection in collections"
            :key="collection.collection_id"
            :label="collection.document_title"
            :value="collection.collection_id"
          />
        </el-select>
        
        <!-- URL输入框 -->
        <el-input
          :model-value="agenticIngestUrl"
          @update:model-value="handleAgenticIngestUrlUpdate"
          placeholder="输入URL进行Agentic Ingest"
          class="flex-1 min-w-[100px]"
          clearable
        />
        
        <!-- 提交按钮 -->
        <el-button
          type="primary"
          @click="handleTriggerAgenticIngest"
          :loading="triggeringAgenticIngest"
          :disabled="!agenticIngestUrl.trim() || triggeringAgenticIngest"
          class="whitespace-nowrap"
        >
          <el-icon>
            <plus />
          </el-icon>
          处理
        </el-button>
      </div>
      
      <div class="flex gap-3 max-w-3xl mx-auto" @keydown.shift.enter="handleSendQuery">
        <el-input
          v-model="queryInput"
          :placeholder="getInputPlaceholder()"
          class="flex-1"
          type="textarea"
          :rows="2"
        />
        <el-button
          type="primary"
          @click="handleSendQuery"
          :disabled="isQueryDisabled()"
          :loading="loading"
          class="h-10 w-10 p-0 rounded-lg"
        >
          <el-icon>
            <promotion />
          </el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* line-clamp utilities for text truncation */
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.line-clamp-3 {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>

<style>
/* 全局聊天消息样式 */
</style>