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
  <aside class="sidebar" :class="{ collapsed }">
    <!-- 头部 -->
    <div class="sidebar-header">
      <div v-if="!collapsed" class="logo">
        <h2>文档</h2>
      </div>
      <ElButton text @click="$emit('toggle')" class="toggle-btn">
        <ElIcon>
          <Fold v-if="!collapsed" />
          <Expand v-else />
        </ElIcon>
      </ElButton>
    </div>

    <!-- 添加文档按钮 -->
    <div class="add-section">
      <ElButton
        type="primary"
        :icon="Plus"
        @click="showAddDialog = true"
        :disabled="store.loading.addingDocument || store.loading.querying"
        :loading="store.loading.addingDocument || store.loading.querying"
        class="add-btn"
        :class="{ 'collapsed-btn': collapsed }"
      >
        <span v-if="!collapsed">添加网址</span>
      </ElButton>
    </div>

    <!-- Ingestion Progress Section -->
    <div class="ingestion-progress-section" v-if="store.ingestionStatus.size > 0">
      <h3>正在处理</h3>
      <div v-for="[url, status] in store.ingestionStatus.entries()" :key="url" class="progress-item">
        <div class="progress-info">
          <span class="progress-url">{{ url }}</span>
          <span class="progress-message">{{ status.message }}</span>
          <!-- 进行中或失败时均支持删除/取消，以优化体验 -->
          <ElButton 
            text 
            type="danger" 
            size="small"
            @click="status.inProgress ? store.cancelIngestion(url) : handleRemoveFailedUrl(url)"
            class="remove-failed-btn"
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
    <div class="documents-section" v-if="!collapsed" :class="{ 'collection-mode': store.isCollectionQueryMode, 'normal-mode': isNormalQueryMode }">
      <div class="documents-section-content">
        <h3>文档列表</h3>
        <div class="documents-list">
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
            <div class="document-item">
              <ElIcon class="doc-icon">
                <Document />
              </ElIcon>
              <div class="doc-info">
                <div class="doc-title">{{ doc.title }}</div>
                <div class="doc-url">{{ doc.url }}</div>
              </div>
              <ElButton text type="danger" @click="handleRemoveDocument(doc.id)" class="delete-btn">
                <ElIcon>
                  <Delete />
                </ElIcon>
              </ElButton>
            </div>
          </ElTooltip>

          <div v-if="store.documents.length === 0" class="empty-state">
            <p>还没有添加任何文档</p>
            <p class="empty-hint">可在右侧输入课题，或点击上方按钮添加网址</p>
          </div>
        </div>
      </div>

      <!-- Collection查询模式蒙版 -->
      <div v-if="store.isCollectionQueryMode" class="collection-overlay">
        <div class="collection-overlay-content">
          <h4>Collection查询模式</h4>
          <p>当前正在使用Collection进行查询</p>
          <p class="collection-name">{{ store.collections.find(c => c.collection_id === store.selectedCollection)?.document_title || '未知Collection' }}</p>
        </div>
      </div>

      <!-- 普通问答模式蒙版 -->
      <div v-if="isNormalQueryMode" class="normal-overlay">
        <div class="normal-overlay-content">
          <h4>普通问答模式</h4>
          <p>当前正在使用网络搜索进行问答</p>
          <p class="normal-description">该模式将自动使用工具为您提供最新的信息和答案</p>
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
        @keydown.enter.shift.prevent="handleAddDocument"
      />
      <template #footer>
        <ElButton @click="showAddDialog = false">取消</ElButton>
        <ElButton type="primary" @click="handleAddDocument" :loading="store.loading.addingDocument">
          添加
        </ElButton>
      </template>
    </ElDialog>

    <!-- 导出按钮 -->
    <div class="export-section" style="text-align: center;" v-if="!collapsed">
      <ElButton
        type="success"
        @click="handleExportConversation"
        :disabled="store.documents.length === 0 || store.messages.length === 0 || store.loading.querying"
        :loading="store.loading.exporting"
        class="export-btn"
        style="width: 90%; height: 40px; margin: 10px 0px;"
      >
        导出对话历史
      </ElButton>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 400px;
  background: white;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  position: fixed;
  left: 0;
  top: 0;
  height: 100vh;
  z-index: 1000;
  transition: width 0.3s ease;
}

.sidebar.collapsed {
  width: 80px;
}

.sidebar-header {
  padding: 20px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 70px;
}

.logo h2 {
  margin: 0;
  color: #1f2937;
  font-size: 20px;
  font-weight: 600;
}

.toggle-btn {
  padding: 8px;
  border-radius: 6px;
}

.add-section {
  padding: 20px;
  border-bottom: 1px solid #e5e7eb;
}

.add-btn {
  width: 100%;
  height: 40px;
}

.add-btn.collapsed-btn {
  width: 40px;
  margin: 0 auto;
  display: block;
}

.ingestion-progress-section {
  padding: 0 20px 20px;
  border-bottom: 1px solid #e5e7eb;
}

.ingestion-progress-section h3 {
  margin: 12px 0 12px 0;
  color: #374151;
  font-size: 16px;
  font-weight: 500;
}

.progress-item {
  margin-bottom: 16px;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  gap: 8px;
}

.progress-url {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
}

.progress-message {
  font-size: 12px;
  color: #6b7280;
}

.remove-failed-btn {
  margin-left: 8px;
  opacity: 0.8;
  transition: opacity 0.2s;
}

.remove-failed-btn:hover {
  opacity: 1;
}


.documents-section {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  position: relative;
}

.documents-section-content {
  transition: opacity 0.3s ease;
}

.documents-section.collection-mode .documents-section-content,
.documents-section.normal-mode .documents-section-content {
  opacity: 0.3;
}

.collection-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(107, 114, 128, 0.1);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}

.collection-overlay-content {
  background: white;
  border-radius: 12px;
  padding: 24px;
  text-align: center;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
  border: 1px solid #e5e7eb;
  max-width: 280px;
}

.collection-overlay-content h4 {
  margin: 0 0 12px 0;
  color: #111827;
  font-size: 16px;
  font-weight: 600;
}

.collection-overlay-content p {
  margin: 8px 0;
  color: #6b7280;
  font-size: 14px;
  line-height: 1.4;
}

.collection-overlay-content .collection-name {
  color: #4f46e5;
  font-weight: 500;
  background: #f0f9ff;
  padding: 8px 12px;
  border-radius: 6px;
  margin-top: 16px;
  font-size: 13px;
}

.normal-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(107, 114, 128, 0.1);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}

.normal-overlay-content {
  background: white;
  border-radius: 12px;
  padding: 24px;
  text-align: center;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
  border: 1px solid #e5e7eb;
  max-width: 280px;
}

.normal-overlay-content h4 {
  margin: 0 0 12px 0;
  color: #111827;
  font-size: 16px;
  font-weight: 600;
}

.normal-overlay-content p {
  margin: 8px 0;
  color: #6b7280;
  font-size: 14px;
  line-height: 1.4;
}

.normal-overlay-content .normal-description {
  color: #4f46e5;
  font-weight: 500;
  background: #f0f9ff;
  padding: 8px 12px;
  border-radius: 6px;
  margin-top: 16px;
  font-size: 13px;
}

.documents-section h3 {
  margin: 0 0 16px 0;
  color: #374151;
  font-size: 16px;
  font-weight: 500;
}

.documents-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.document-item {
  display: flex;
  align-items: center;
  padding: 12px;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  transition: all 0.2s;
}

.document-item:hover {
  background: #f3f4f6;
  border-color: #d1d5db;
}

.doc-icon {
  margin-right: 12px;
  color: #6b7280;
}

.doc-info {
  flex: 1;
  min-width: 0;
}

.doc-title {
  font-weight: 500;
  color: #111827;
  font-size: 14px;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-url {
  color: #6b7280;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
}

.document-item:hover .delete-btn {
  opacity: 1;
}

.empty-state {
  text-align: center;
  color: #6b7280;
  margin-top: 40px;
}

.empty-state p {
  margin: 8px 0;
}

.empty-hint {
  font-size: 12px;
  color: #9ca3af;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .sidebar {
    /* 在移动端完全隐藏侧边栏 */
    display: none;
  }
}
</style>
