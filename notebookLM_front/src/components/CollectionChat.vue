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
    <div ref="messageContainer" class="flex-1 overflow-y-auto p-6 scroll-smooth">
      <!-- Collection查询结果区域 -->
      <div v-if="collectionQueryResults.length > 0 && messages.length === 0" class="mb-6 p-5 bg-gray-50 rounded-lg border border-gray-200">
        <div class="flex justify-between items-center mb-4 pb-3 border-b border-gray-200">
          <h3 class="text-lg font-semibold text-gray-900">Collection搜索结果 ({{ collectionQueryResults.length }} 个相关文档片段)</h3>
          <div class="flex gap-2 items-center">
            <button @click="showDetailedResults = !showDetailedResults" class="text-sm text-gray-600 hover:text-gray-900">
              {{ showDetailedResults ? '隐藏详细结果' : '查看详细结果' }}
            </button>
            <button @click="handleClearCollectionResults()" class="text-sm text-gray-600 hover:text-gray-900">
              清空结果
            </button>
          </div>
        </div>
        <div v-if="showDetailedResults" class="max-h-96 overflow-y-auto">
          <div 
            v-for="(result, index) in collectionQueryResults" 
            :key="index" 
            class="mb-3 p-4 bg-white rounded-lg border border-gray-200 hover:border-gray-300 hover:shadow-sm transition-all duration-200"
          >
            <div class="flex justify-between items-center mb-2">
              <span class="text-xs text-gray-500 font-mono bg-gray-100 px-2 py-1 rounded">相关度: {{ result.score.toFixed(4) }}</span>
              <a :href="result.source_url" target="_blank" class="text-sm font-medium text-indigo-600 hover:text-indigo-800 truncate max-w-[400px]">
                {{ result.source_title }}
              </a>
            </div>
            <p class="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{{ result.content }}</p>
          </div>
        </div>
        <div v-else class="p-4 bg-white rounded-lg border border-gray-200 text-center">
          <p class="text-sm text-gray-700 mb-2">
            📄 找到 {{ collectionQueryResults.length }} 个相关文档片段，
            <button @click="handleSendQuery()" class="text-sm font-medium text-indigo-600 hover:text-indigo-800">
              点击生成智能回答
            </button>
          </p>
        </div>
      </div>
      
      <!-- 欢迎消息 -->
      <div v-if="messages.length === 0 && collectionQueryResults.length === 0" class="text-center max-w-2xl mx-auto text-gray-700">
        <h2 class="text-2xl font-semibold text-gray-900 mb-4">Collection问答</h2>
        <p class="mb-10 text-base leading-relaxed">选择一个Collection进行基于知识库的问答，同时可以结合网络搜索获取最新信息。</p>
        
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mt-10">
          <div class="text-left p-5 bg-gray-50 rounded-lg border border-gray-200">
            <strong class="block mb-2 text-sm font-medium text-gray-900">📚 知识库问答</strong>
            <p class="text-xs text-gray-600 leading-relaxed">基于Collection中的文档回答</p>
          </div>
          <div class="text-left p-5 bg-gray-50 rounded-lg border border-gray-200">
            <strong class="block mb-2 text-sm font-medium text-gray-900">🔍 混合搜索</strong>
            <p class="text-xs text-gray-600 leading-relaxed">结合知识库和网络搜索</p>
          </div>
          <div class="text-left p-5 bg-gray-50 rounded-lg border border-gray-200">
            <strong class="block mb-2 text-sm font-medium text-gray-900">📊 精准匹配</strong>
            <p class="text-xs text-gray-600 leading-relaxed">智能检索相关文档片段</p>
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
          <div v-if="message.type === 'assistant' && message.reasoning" class="mb-4 border-t border-gray-200 pt-3 pb-3">
            <el-collapse v-model="activeNames">
              <el-collapse-item title="思维链（" :name="'reasoning'">
                <div class="text-xs text-gray-700 leading-relaxed bg-gray-50 p-3 rounded-lg border border-gray-200" v-html="marked(message.reasoning)"></div>
              </el-collapse-item>
            </el-collapse>
          </div>
          <div v-if="message.content" class="whitespace-pre-wrap" :class="{ 'text-gray-600': isStatusMessage(message.content) }" v-html="marked(message.content)"></div>
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
    <div class="p-6 border-t border-gray-200 bg-white">
      <!-- Collection与Agentic Ingest 控制区 -->
      <div class="flex items-center mb-5 gap-3 max-w-4xl mx-auto">
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
          class="flex-1 min-w-[200px]"
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
      
      <div class="flex gap-3 max-w-4xl mx-auto" @keydown.ctrl.enter="handleSendQuery">
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
      <div class="text-center mt-3 text-xs text-gray-600">
        <span>
          Collection问答模式：
          {{ selectedCollection 
            ? collections.find(c => c.collection_id === selectedCollection)?.document_title || '未知Collection' 
            : '请选择Collection' }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 移除所有scoped样式，因为已转换为Tailwind类 */
</style>

<style>
/* 移除所有全局样式，因为已转换为Tailwind类 */
</style>