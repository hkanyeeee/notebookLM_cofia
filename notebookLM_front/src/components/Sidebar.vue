<script setup lang="ts">
import { ref, computed } from 'vue'
import { useNotebookStore, QueryType } from '../stores/notebook'
import { ElButton, ElInput, ElMessage, ElDialog, ElIcon, ElTooltip } from 'element-plus'
import { Plus, Document, Delete, Fold, Expand } from '@element-plus/icons-vue'
import type { AgenticCollection } from '../api/notebook'

interface Props {
  collapsed: boolean
}

interface Emits {
  (e: 'toggle'): void
}

defineProps<Props>()
defineEmits<Emits>()

const store = useNotebookStore()

// 计算属性：是否处于普通问答模式
const isNormalQueryMode = computed(() => store.queryType === QueryType.NORMAL)

// 计算属性：是否处于文档问答模式
const isDocumentQueryMode = computed(() => store.queryType === QueryType.DOCUMENT)

// 添加URL对话框
const showAddDialog = ref(false)
const newUrl = ref('')



// 添加文档
async function handleAddDocument() {
  const urls = newUrl.value
    .split(/[,，\n]+/)
    .map((url) => url.trim())
    .filter((url) => url)

  if (urls.length === 0) {
    ElMessage.warning('请输入至少一个有效的网址')
    return
  }

  // 验证所有URL格式
  for (const url of urls) {
    try {
      new URL(url)
    } catch {
      ElMessage.error(`无效的网址格式: ${url}`)
      return // 如果任何一个URL无效，则停止
    }
  }

  // 并发处理多个URL
  showAddDialog.value = false
  const promises = urls.map((url) => store.addDocument(url))
  // 使用 Promise.all 并发执行，但不阻塞 UI
  Promise.all(promises).catch((err) => {
    console.error('批量添加文档时发生错误:', err)
  })
  
  // 清空输入并关闭对话框
  newUrl.value = ''
}

// 删除文档
async function handleRemoveDocument(id: string) {
  try {
    await store.removeDocument(id)
    ElMessage.success('文档已成功删除')
  } catch (error) {
    console.error(error)
    ElMessage.error('删除文档失败，请稍后重试')
  }
}

// 删除处理失败的URL
function handleRemoveFailedUrl(url: string) {
  store.ingestionStatus.delete(url)
  ElMessage.success('已移除失败的URL')
}
</script>

<template>
  <aside class="border-r flex flex-col fixed left-0 top-0 h-screen z-50 transition-all duration-300 overflow-hidden sidebar-container" :class="{ 'w-20': collapsed, 'w-96': !collapsed }">
    <!-- 头部 -->
    <div class="p-5 border-b flex items-center justify-between min-h-[70px] sidebar-header">
      <div v-if="!collapsed" class="flex-1">
        <h2 class="m-0 text-xl font-semibold sidebar-title">文档</h2>
      </div>
      <ElButton text @click="$emit('toggle')" class="p-2 rounded-md">
        <ElIcon>
          <Fold v-if="!collapsed" />
          <Expand v-else />
        </ElIcon>
      </ElButton>
    </div>

    <!-- 添加文档按钮 - 只在文档问答模式下显示 -->
    <div v-if="isDocumentQueryMode" class="p-5 border-b sidebar-section">
      <ElButton
        type="primary"
        :icon="Plus"
        @click="showAddDialog = true"
        :disabled="store.loading.addingDocument || store.loading.querying"
        :loading="store.loading.addingDocument || store.loading.querying"
        :class="collapsed ? 'w-10 mx-auto block' : 'w-full h-10'"
      >
        <span v-if="!collapsed">添加网址</span>
      </ElButton>
    </div>

    <!-- Ingestion Progress Section -->
    <div class="px-5 pb-5 sidebar-ingestion" v-if="!collapsed && store.ingestionStatus.size > 0">
      <h3 class="my-3 text-base font-medium sidebar-section-title">正在处理</h3>
      <div v-for="[url, status] in store.ingestionStatus.entries()" :key="url" class="mb-4">
        <div class="flex justify-between items-center mb-1.5 gap-2">
          <span class="text-sm font-medium whitespace-nowrap overflow-hidden text-ellipsis max-w-[180px] sidebar-url">{{ url }}</span>
          <span class="text-xs sidebar-status-text">{{ status.message }}</span>
          <!-- 进行中或失败时均支持删除/取消，以优化体验 -->
          <ElButton 
            text 
            type="danger" 
            size="small"
            @click="status.inProgress ? store.cancelIngestion(url) : handleRemoveFailedUrl(url)"
            class="ml-2 opacity-80 hover:opacity-100 transition-opacity"
          >
            <ElIcon>
              <Delete />
            </ElIcon>
          </ElButton>
        </div>
        <ElProgress
          :percentage="status.total > 0 ? Math.round((status.progress / status.total) * 100) : 0"
          :status="status.error ? 'exception' : (status.inProgress ? '' : 'success')"
        />
      </div>
    </div>

    <!-- 文档列表 -->
    <div class="flex-1 p-5 overflow-y-auto relative" v-if="!collapsed">
      <div class="transition-opacity duration-300" :class="{ 'opacity-30': store.isCollectionQueryMode || isNormalQueryMode }">
        <h3 class="m-0 mb-4 text-base font-medium sidebar-section-title">文档列表</h3>
        <div class="flex flex-col gap-3">
          <ElTooltip
            v-for="doc in store.documents"
            :key="doc.id"
            placement="right"
            effect="light"
          >
            <template #content>
              <div>
                <div>{{ doc.title }}</div>
                <div>{{ doc.url }}</div>
              </div>
            </template>
            <div class="flex items-center p-3 rounded-lg border transition-all duration-200 group sidebar-document-item">
              <ElIcon class="mr-3 sidebar-document-icon">
                <Document />
              </ElIcon>
              <div class="flex-1 min-w-0">
                <div class="font-medium text-sm mb-1 overflow-hidden text-ellipsis whitespace-nowrap sidebar-document-title">{{ doc.title }}</div>
                <div class="text-xs overflow-hidden text-ellipsis whitespace-nowrap sidebar-document-url">{{ doc.url }}</div>
              </div>
              <ElButton text type="danger" @click="handleRemoveDocument(doc.id)" class="opacity-0 group-hover:opacity-100 transition-opacity">
                <ElIcon>
                  <Delete />
                </ElIcon>
              </ElButton>
            </div>
          </ElTooltip>

          <div v-if="store.documents.length === 0" class="text-center mt-10 sidebar-empty-state">
            <p class="my-2">还没有添加任何文档</p>
            <p class="my-2 text-xs sidebar-empty-hint">可在右侧输入课题，或点击上方按钮添加网址</p>
          </div>
        </div>
      </div>

      <!-- Collection查询模式蒙版 -->
      <div v-if="store.isCollectionQueryMode" class="absolute inset-0 backdrop-blur-sm flex items-center justify-center z-10 sidebar-overlay">
        <div class="rounded-xl p-6 text-center shadow-lg border max-w-[280px] sidebar-modal">
          <h4 class="m-0 mb-3 text-base font-semibold sidebar-modal-title">Collection查询模式</h4>
          <p class="my-2 text-sm leading-relaxed sidebar-modal-text">当前正在使用Collection进行查询</p>
          <p class="font-medium py-2 px-3 rounded-md mt-4 text-xs sidebar-modal-collection">{{ store.collections.find((c: AgenticCollection) => c.collection_id === store.selectedCollection)?.document_title || '未知Collection' }}</p>
        </div>
      </div>

      <!-- 普通问答模式蒙版 -->
      <div v-if="isNormalQueryMode" class="absolute inset-0 backdrop-blur-sm flex items-center justify-center z-10 sidebar-overlay">
        <div class="rounded-xl p-6 text-center shadow-lg border max-w-[280px] sidebar-modal">
          <h4 class="m-0 mb-3 text-base font-semibold sidebar-modal-title">普通问答模式</h4>
          <p class="my-2 text-sm leading-relaxed sidebar-modal-text">当前正在使用网络搜索进行问答</p>
          <p class="font-medium py-2 px-3 rounded-md mt-4 text-xs sidebar-modal-collection">该模式将自动使用工具为您提供最新的信息和答案</p>
        </div>
      </div>
    </div>

    <!-- 添加URL对话框 -->
    <ElDialog v-model="showAddDialog" title="添加网址" width="400px">
      <ElInput
        v-model="newUrl"
        type="textarea"
        :rows="5"
        placeholder="用逗号分隔多个网址，例如：https://example.com, https://another-example.com"
        @keyup.enter.native.stop
        @keydown.shift.enter="handleAddDocument"
      />
      <template #footer>
        <ElButton @click="showAddDialog = false">取消</ElButton>
        <ElButton type="primary" @click="handleAddDocument" :loading="store.loading.addingDocument">
          添加
        </ElButton>
      </template>
    </ElDialog>


  </aside>
</template>

<!-- 响应式设计 -->
<style scoped>
/* 侧边栏容器 */
.sidebar-container {
  background-color: var(--color-surface);
  border-color: var(--color-border);
}

/* 侧边栏头部 */
.sidebar-header {
  background-color: var(--color-surface);
  border-color: var(--color-border);
}

.sidebar-title {
  color: var(--color-text);
}

/* 侧边栏节 */
.sidebar-section {
  border-color: var(--color-border);
}

.sidebar-ingestion {
  border-color: var(--color-border);
}

.sidebar-section-title {
  color: var(--color-text-secondary);
}

/* 处理状态文本 */
.sidebar-url {
  color: var(--color-text-secondary);
}

.sidebar-status-text {
  color: var(--color-text-muted);
}

/* 文档项 */
.sidebar-document-item {
  background-color: var(--color-surface-light);
  border-color: var(--color-border);
}

.sidebar-document-item:hover {
  background-color: var(--color-surface-lighter);
  border-color: var(--color-border-light);
}

.sidebar-document-icon {
  color: var(--color-text-muted);
}

.sidebar-document-title {
  color: var(--color-text);
}

.sidebar-document-url {
  color: var(--color-text-muted);
}

/* 空状态 */
.sidebar-empty-state {
  color: var(--color-text-muted);
}

.sidebar-empty-hint {
  color: var(--color-text-muted);
  opacity: 0.8;
}

/* 蒙版和对话框 */
.sidebar-overlay {
  background-color: rgba(0, 0, 0, 0.1);
}

html.dark .sidebar-overlay {
  background-color: rgba(0, 0, 0, 0.2);
}

.sidebar-modal {
  background-color: var(--color-surface);
  border-color: var(--color-border);
}

.sidebar-modal-title {
  color: var(--color-text);
}

.sidebar-modal-text {
  color: var(--color-text-secondary);
}

.sidebar-modal-collection {
  color: var(--el-color-primary);
  background-color: rgba(79, 70, 229, 0.1);
}

html.dark .sidebar-modal-collection {
  color: #6366f1;
  background-color: rgba(99, 102, 241, 0.2);
}

/* 移动端侧边栏样式在 App.vue 中处理 */
</style>
