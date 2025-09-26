<script setup lang="ts">
import { ref, nextTick, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElInput, ElButton, ElMessage, ElIcon, ElCollapse, ElCollapseItem, ElSelect, ElOption, ElMessageBox } from 'element-plus'
import { Promotion, Plus, Tools, Delete, Folder, ArrowRight, Document, Link, Tickets, Loading, ArrowDown } from '@element-plus/icons-vue'
import { marked } from 'marked'
import type { Message } from '../stores/notebook'
import type { AutoCollection, CollectionResult } from '../api/notebook'
import VectorFixDialog from './VectorFixDialog.vue'
import IngestTaskMonitor from './IngestTaskMonitor.vue'

// 启用 GitHub 风格 Markdown（GFM），支持表格等语法
marked.setOptions({
  gfm: true,
  breaks: true,
})

// Props
interface Props {
  messages: Message[]
  collections: AutoCollection[]
  selectedCollection: string | null
  loading: boolean
  loadingCollections: boolean
  autoIngestUrl: string
  triggeringAutoIngest: boolean
  shouldUseWebSearch: boolean
  deletingCollection: boolean
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  (e: 'sendQuery', query: string): void
  (e: 'update:selectedCollection', value: string | null): void
  (e: 'update:autoIngestUrl', value: string): void
  (e: 'triggerAutoIngest'): void
  (e: 'clearCollectionResults'): void
  (e: 'deleteCollection', collectionId: string): void
  (e: 'renameCollection', collectionId: string): void
}>()

// 查询输入
const queryInput = ref('')
const messageContainer = ref<HTMLElement>()
// 控制思维链和参考来源的展开状态，默认收起思维链
const activeNames = ref([])
// 向量修复对话框
const showVectorFixDialog = ref(false)

// 移动端判断与 Auto Ingest 折叠控制（移动端默认收起）
const isMobile = ref(false)
const autoIngestCollapsed = ref(true)

function checkMobile() {
  isMobile.value = window.innerWidth <= 768
  // 移动端默认收起，桌面端默认展开
  autoIngestCollapsed.value = isMobile.value
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', checkMobile)
})

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

// 处理Auto Ingest URL变化
function handleAutoIngestUrlUpdate(value: string) {
  emit('update:autoIngestUrl', value)
}

// 触发Auto Ingest
function handleTriggerAutoIngest() {
  emit('triggerAutoIngest')
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
    ? `在 '${props.collections.find(c => c.collection_id === props.selectedCollection)?.display_name || props.collections.find(c => c.collection_id === props.selectedCollection)?.document_title}' 中查询...`
    : '请先选择Collection，然后输入问题...'
}

// 处理删除Collection
async function handleDeleteCollection(collectionId: string) {
  const collection = props.collections.find(c => c.collection_id === collectionId)
  if (!collection) return

  try {
    await ElMessageBox.confirm(
      `确定要删除Collection "${collection.document_title}" 吗？此操作不可撤销！`,
      '确认删除',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )
    
    emit('deleteCollection', collectionId)
  } catch {
    // 用户取消删除
  }
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 消息列表 / 欢迎信息 -->
    <div ref="messageContainer" class="flex-1 overflow-y-auto p-2 scroll-smooth" :class="messages.length === 0 ? ['flex','items-center','justify-center'] : []">
      
      <!-- 智能欢迎消息 -->
      <div v-if="messages.length === 0" class="max-w-4xl mx-auto p-6">
        
        <!-- 没有任何Collection时 - 引导添加 -->
        <div v-if="collections.length === 0 && !loadingCollections">
          <div class="mb-8 mt-14 md:mt-8">
            <div class="mx-auto mt-8 mb-10 text-base leading-relaxed text-center font-medium" style="color: var(--color-text-secondary)">欢迎使用Collection问答</div>
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
        <div v-else-if="collections.length > 0 && !selectedCollection">
          <div class="mb-8 mt-14 md:mt-8">
            <div class="mx-auto mt-8 mb-10 text-base leading-relaxed text-center font-medium" style="color: var(--color-text-secondary)">选择一个Collection开始对话</div>
            <p class="text-gray-600 mb-6 text-center">
              您有 {{ collections.length }} 个可用的Collection，请选择一个开始智能问答。
            </p>

          </div>

          <!-- Collection卡片列表 -->
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8 h-[350px] overflow-y-auto scroll-smooth">
            <div 
              v-for="collection in collections" 
              :key="collection.collection_id"
              class="p-4 border-2 rounded-xl hover:border-indigo-300 hover:shadow-md transition-all cursor-pointer collection-item"
              @click="handleCollectionChange(collection.collection_id)"
            >
              <div class="text-left">
                <div class="flex items-start justify-between mb-3">
                  <div class="text-2xl">
                    <ElIcon class="text-indigo-600">
                      <Folder />
                    </ElIcon>
                  </div>
                  <div class="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                    {{ collection.collection_id.substring(0, 8) }}...
                  </div>
                </div>
                <h3 class="font-semibold text-gray-900 mb-2 text-sm text-ellipsis-2">
                  {{ collection.display_name || collection.document_title || '未命名Collection' }}
                </h3>
                <p class="text-xs text-gray-600 mb-3 text-ellipsis-3">
                  {{ collection.url || '无描述' }}
                </p>
                <div class="flex justify-between items-center text-xs text-gray-500">
                  <span>点击选择</span>
                  <ElIcon>
                    <ArrowRight />
                  </ElIcon>
                </div>
              </div>
            </div>
          </div>

        </div>

        <!-- 已选择Collection时 - 显示Collection信息 -->
        <div v-else-if="selectedCollection" class="text-left">
          <div class="mb-8 mt-14 md:mt-8">
            <div class="mx-auto mt-8 mb-10 text-base leading-relaxed pl-4 border-l-4 border-indigo-600" style="color: var(--color-text-secondary)">
              {{ collections.find(c => c.collection_id === selectedCollection)?.display_name || collections.find(c => c.collection_id === selectedCollection)?.document_title || 'Collection' }}
            </div>
            <div class="max-w-2xl mx-auto">
              <div class="bg-indigo-50 border border-indigo-200 rounded-xl p-6 mb-6">
                <div class="text-left space-y-2">
                  <div class="flex items-center">
                    <span class="text-indigo-600 font-medium w-16 flex items-center">
                      <ElIcon class="mr-1"><Document /></ElIcon> 标题:
                    </span>
                    <span class="text-gray-700 text-sm font-medium">{{ collections.find(c => c.collection_id === selectedCollection)?.display_name || collections.find(c => c.collection_id === selectedCollection)?.document_title || '未知' }}</span>
                  </div>
                  <div class="flex items-center">
                    <span class="text-indigo-600 font-medium w-16 flex items-center">
                      <ElIcon class="mr-1"><Link /></ElIcon> 来源:
                    </span>
                    <a 
                      :href="collections.find(c => c.collection_id === selectedCollection)?.url" 
                      target="_blank"
                      class="text-indigo-600 hover:text-indigo-800 underline text-sm truncate flex-1"
                    >
                      {{ collections.find(c => c.collection_id === selectedCollection)?.url }}
                    </a>
                  </div>
                  <div class="flex items-center">
                    <span class="text-indigo-600 font-medium w-16 flex items-center">
                      <ElIcon class="mr-1"><Tickets /></ElIcon> ID:
                    </span>
                    <span class="text-gray-600 font-mono text-sm">{{ selectedCollection }}</span>
                  </div>
                </div>
                
                <!-- Collection操作按钮 -->
                <div class="flex justify-end mt-4 space-x-2">
                  <el-button 
                    type="primary" 
                    size="small"
                    @click="() => $emit('renameCollection', selectedCollection!)"
                  >
                    重命名
                  </el-button>
                  <el-button 
                    type="danger" 
                    :icon="Delete"
                    size="small"
                    :loading="deletingCollection"
                    :disabled="deletingCollection"
                    @click="handleDeleteCollection(selectedCollection!)"
                  >
                    删除Collection
                  </el-button>
                </div>
              </div>

            </div>
          </div>
        </div>

        <!-- 加载状态 -->
        <div v-else-if="loadingCollections" class="text-center py-12">
          <div class="text-4xl mb-4">
            <ElIcon class="text-4xl animate-spin">
              <Loading />
            </ElIcon>
          </div>
          <h2 class="text-xl text-gray-600">正在加载Collection...</h2>
        </div>

        <!-- 向量数据修复按钮 -->
        <div class="mb-6 text-center">
          <el-button 
            type="primary" 
            :icon="Tools" 
            @click="showVectorFixDialog = true"
            class="bg-indigo-600 hover:bg-indigo-700 border-indigo-600 hover:border-indigo-700"
          >
            向量数据修复
          </el-button>
        </div>

        <!-- Auto Ingest 任务监控 -->
        <div class="mb-6">
          <IngestTaskMonitor />
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
              <el-collapse-item 
                :title="`思维链（${message.reasoning.length} 字）`" 
                :name="'reasoning'"
                class="text-sm font-medium text-gray-700"
              >
                <div class="text-xs text-gray-700 leading-relaxed p-3 rounded-lg border border-gray-200 chat-message-content" v-html="marked(message.reasoning)"></div>
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
    <div class="p-4 border-t bg-[var(--color-surface)] border-[var(--color-border)]">
      <!-- 移动端：Auto Ingest 折叠开关 -->
      <div v-if="isMobile" class="max-w-3xl mx-auto mb-2">
        <button
          class="w-full flex items-center justify-between text-sm px-3 py-2 rounded-md border bg-[var(--color-surface)] border-[var(--color-border)] hover:bg-[var(--color-surface-light)] transition shadow-sm font-medium"
          @click="autoIngestCollapsed = !autoIngestCollapsed"
        >
          <span class="text-[var(--color-text)]">Collection 选择（可选）</span>
          <el-icon :class="[{ 'rotate-180': !autoIngestCollapsed }, 'transition-transform']">
            <ArrowDown />
          </el-icon>
        </button>
      </div>

      <!-- Collection与Auto Ingest 控制区 -->
      <div
        class="flex flex-col sm:flex-row sm:items-center mb-2 gap-2 max-w-3xl mx-auto"
        v-show="!isMobile || !autoIngestCollapsed"
      >
        <!-- Collection选择下拉框和删除按钮 -->
        <div class="flex items-center gap-1 w-full sm:w-auto">
          <el-select
            :model-value="selectedCollection"
            @update:model-value="handleCollectionChange"
            placeholder="选择Collection"
            class="w-full sm:w-80 md:w-96 lg:w-[420px]"
            :loading="loadingCollections"
            size="small"
            filterable
            clearable
          >
            <el-option
              v-for="collection in collections"
              :key="collection.collection_id"
              :label="collection.display_name || collection.document_title"
              :value="collection.collection_id"
            />
          </el-select>
        </div>
        
        <!-- URL输入框 -->
        <el-input
          :model-value="autoIngestUrl"
          @update:model-value="handleAutoIngestUrlUpdate"
          placeholder="输入URL进行Auto Ingest"
          class="flex-1 min-w-0 w-full sm:w-auto"
          size="small"
          clearable
        />
        
        <!-- 提交按钮 -->
        <el-button
          type="primary"
          @click="handleTriggerAutoIngest"
          :loading="triggeringAutoIngest"
          :disabled="!autoIngestUrl.trim() || triggeringAutoIngest"
          class="whitespace-nowrap sm:shrink-0 w-full sm:w-auto"
          size="small"
        >
          <el-icon>
            <plus />
          </el-icon>
          处理
        </el-button>
      </div>
      
      <div class="flex flex-col sm:flex-row gap-3 max-w-3xl mx-auto" @keydown.shift.enter.prevent="handleSendQuery">
        <el-input
          v-model="queryInput"
          :placeholder="getInputPlaceholder()"
          class="flex-1 w-full"
          type="textarea"
          :rows="2"
        />
        <el-button
          type="primary"
          @click="handleSendQuery"
          :disabled="isQueryDisabled()"
          :loading="loading"
          class="h-10 w-full sm:w-10 p-0 rounded-lg sm:shrink-0"
        >
          <el-icon>
            <promotion />
          </el-icon>
        </el-button>
      </div>
    </div>

    <!-- 向量修复对话框 -->
    <VectorFixDialog 
      v-model:visible="showVectorFixDialog"
      @refresh-collections="$emit('clearCollectionResults')"
    />
  </div>
</template>
