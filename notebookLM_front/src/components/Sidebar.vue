<script setup lang="ts">
import { ref } from 'vue'
import { useNotebookStore } from '../stores/notebook'
import { ElButton, ElInput, ElMessage, ElDialog, ElIcon } from 'element-plus'
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

// 添加URL对话框
const showAddDialog = ref(false)
const newUrl = ref('')

// 添加文档
async function handleAddDocument() {
  if (!newUrl.value.trim()) {
    ElMessage.warning('请输入有效的网址')
    return
  }

  // 简单的URL验证
  try {
    new URL(newUrl.value)
  } catch {
    ElMessage.error('请输入有效的网址格式')
    return
  }

  try {
    await store.addDocument(newUrl.value)
    ElMessage.success('文档添加成功')
    newUrl.value = ''
    showAddDialog.value = false
  } catch {
    ElMessage.error('添加文档失败')
  }
}

// 删除文档
function handleRemoveDocument(id: string) {
  store.removeDocument(id)
  ElMessage.success('文档已删除')
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
        :disabled="store.loading.addingDocument"
        :loading="store.loading.addingDocument"
        class="add-btn"
        :class="{ 'collapsed-btn': collapsed }"
      >
        <span v-if="!collapsed">添加网址</span>
      </ElButton>
    </div>

    <!-- 文档列表 -->
    <div class="documents-section" v-if="!collapsed">
      <h3>文档列表</h3>
      <div class="documents-list">
        <div v-for="doc in store.documents" :key="doc.id" class="document-item">
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

        <div v-if="store.documents.length === 0" class="empty-state">
          <p>还没有添加任何文档</p>
          <p class="empty-hint">点击上方按钮添加网址</p>
        </div>
      </div>
    </div>

    <!-- 添加URL对话框 -->
    <ElDialog v-model="showAddDialog" title="添加网址" width="400px">
      <ElInput
        v-model="newUrl"
        placeholder="请输入网址，例如：https://example.com"
        @keyup.enter="handleAddDocument"
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

<style scoped>
.sidebar {
  width: 300px;
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

.documents-section {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
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
    width: 100%;
    transform: translateX(-100%);
  }

  .sidebar.collapsed {
    transform: translateX(0);
    width: 100%;
  }
}
</style>
