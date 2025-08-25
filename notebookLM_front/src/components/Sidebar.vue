<script setup lang="ts">
import { ref, computed } from 'vue'
import { useNotebookStore, QueryType } from '../stores/notebook'
import { ElButton, ElInput, ElMessage, ElDialog, ElIcon, ElTooltip } from 'element-plus'
import { Plus, Document, Delete, Fold, Expand } from '@element-plus/icons-vue'

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

// 添加URL对话框
const showAddDialog = ref(false)
const newUrl = ref('')

// 导出对话历史
async function handleExportConversation() {
  try {
    await store.exportConversation()
    ElMessage.success('导出成功')
  } catch (error) {
    console.error('导出失败:', error)
    ElMessage.error('导出失败，请重试')
  }
}

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
  <aside class="bg-white border-r border-gray-200 flex flex-col fixed left-0 top-0 h-screen z-50 transition-all duration-300 overflow-hidden" :class="{ 'w-20': collapsed, 'w-96': !collapsed }">
    <!-- 头部 -->
    <div class="p-5 border-b border-gray-200 flex items-center justify-between min-h-[70px]">
      <div v-if="!collapsed" class="flex-1">
        <h2 class="m-0 text-gray-800 text-xl font-semibold">文档</h2>
      </div>
      <ElButton text @click="$emit('toggle')" class="p-2 rounded-md">
        <ElIcon>
          <Fold v-if="!collapsed" />
          <Expand v-else />
        </ElIcon>
      </ElButton>
    </div>

    <!-- 添加文档按钮 -->
    <div class="p-5 border-b border-gray-200">
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
    <div class="px-5 pb-5 border-gray-200" v-if="!collapsed && store.ingestionStatus.size > 0">
      <h3 class="my-3 text-gray-700 text-base font-medium">正在处理</h3>
      <div v-for="[url, status] in store.ingestionStatus.entries()" :key="url" class="mb-4">
        <div class="flex justify-between items-center mb-1.5 gap-2">
          <span class="text-sm font-medium text-gray-700 whitespace-nowrap overflow-hidden text-ellipsis max-w-[180px]">{{ url }}</span>
          <span class="text-xs text-gray-500">{{ status.message }}</span>
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
        <h3 class="m-0 mb-4 text-gray-700 text-base font-medium">文档列表</h3>
        <div class="flex flex-col gap-3">
          <ElTooltip
            v-for="doc in store.documents"
            :key="doc.id"
            placement="right"
            effect="dark"
          >
            <template #content>
              <div>
                <div>{{ doc.title }}</div>
                <div>{{ doc.url }}</div>
              </div>
            </template>
            <div class="flex items-center p-3 bg-gray-50 rounded-lg border border-gray-200 transition-all duration-200 hover:bg-gray-100 hover:border-gray-300 group">
              <ElIcon class="mr-3 text-gray-500">
                <Document />
              </ElIcon>
              <div class="flex-1 min-w-0">
                <div class="font-medium text-gray-900 text-sm mb-1 overflow-hidden text-ellipsis whitespace-nowrap">{{ doc.title }}</div>
                <div class="text-gray-500 text-xs overflow-hidden text-ellipsis whitespace-nowrap">{{ doc.url }}</div>
              </div>
              <ElButton text type="danger" @click="handleRemoveDocument(doc.id)" class="opacity-0 group-hover:opacity-100 transition-opacity">
                <ElIcon>
                  <Delete />
                </ElIcon>
              </ElButton>
            </div>
          </ElTooltip>

          <div v-if="store.documents.length === 0" class="text-center text-gray-500 mt-10">
            <p class="my-2">还没有添加任何文档</p>
            <p class="my-2 text-xs text-gray-400">可在右侧输入课题，或点击上方按钮添加网址</p>
          </div>
        </div>
      </div>

      <!-- Collection查询模式蒙版 -->
      <div v-if="store.isCollectionQueryMode" class="absolute inset-0 bg-gray-500/10 backdrop-blur-sm flex items-center justify-center z-10">
        <div class="bg-white rounded-xl p-6 text-center shadow-lg border border-gray-200 max-w-[280px]">
          <h4 class="m-0 mb-3 text-gray-900 text-base font-semibold">Collection查询模式</h4>
          <p class="my-2 text-gray-500 text-sm leading-relaxed">当前正在使用Collection进行查询</p>
          <p class="text-indigo-600 font-medium bg-blue-50 py-2 px-3 rounded-md mt-4 text-xs">{{ store.collections.find(c => c.collection_id === store.selectedCollection)?.document_title || '未知Collection' }}</p>
        </div>
      </div>

      <!-- 普通问答模式蒙版 -->
      <div v-if="isNormalQueryMode" class="absolute inset-0 bg-gray-500/10 backdrop-blur-sm flex items-center justify-center z-10">
        <div class="bg-white rounded-xl p-6 text-center shadow-lg border border-gray-200 max-w-[280px]">
          <h4 class="m-0 mb-3 text-gray-900 text-base font-semibold">普通问答模式</h4>
          <p class="my-2 text-gray-500 text-sm leading-relaxed">当前正在使用网络搜索进行问答</p>
          <p class="text-indigo-600 font-medium bg-blue-50 py-2 px-3 rounded-md mt-4 text-xs">该模式将自动使用工具为您提供最新的信息和答案</p>
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

    <!-- 导出按钮 -->
    <div class="text-center" v-if="!collapsed">
      <ElButton
        type="success"
        @click="handleExportConversation"
        :disabled="store.documents.length === 0 || store.messages.length === 0 || store.loading.querying"
        :loading="store.loading.exporting"
        class="w-[90%] h-10 my-2.5"
      >
        导出对话历史
      </ElButton>
    </div>
  </aside>
</template>

<!-- 响应式设计：在移动端隐藏侧边栏 -->
<style scoped>
@media (max-width: 768px) {
  aside {
    display: none;
  }
}
</style>
