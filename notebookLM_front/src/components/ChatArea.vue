<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useNotebookStore, QueryType } from '../stores/notebook'
import { useSessionStore } from '../stores/session'
import { ElSelect, ElOption, ElButton, ElIcon, ElMessage } from 'element-plus'
import { Refresh, Bell } from '@element-plus/icons-vue'
import NormalChat from './NormalChat.vue'
import DocumentChat from './DocumentChat.vue'
import CollectionChat from './CollectionChat.vue'
import WorkflowDialog from './WorkflowDialog.vue'

const store = useNotebookStore()
const sessionStore = useSessionStore()

// 工作流对话框状态
const workflowDialogVisible = ref(false)

// 发送查询 - 统一处理所有子组件的查询
async function handleSendQuery(query: string) {
  try {
    const result = await store.sendQuery(query)
    
    // 根据问答类型显示不同的提示信息
    if (result && result.success) {
      switch (store.queryType) {
        case QueryType.NORMAL:
          ElMessage.success('正在为您生成回答...')
          break
        case QueryType.DOCUMENT:
          ElMessage.success('正在基于文档生成回答...')
          break
        case QueryType.COLLECTION:
          ElMessage.success(`找到 ${result.total_found || 0} 个相关结果`)
          break
      }
    }
  } catch (error: any) {
    ElMessage.error(error.message || '查询失败，请重试')
  }
}

// 清空对话
function handleClearMessages() {
  store.clearMessages()
  ElMessage.success('对话已清空')
}

// 显示工作流状态
function handleShowWorkflows() {
  workflowDialogVisible.value = true
}

// 触发Agentic Ingest - Collection模式使用
async function handleTriggerAgenticIngest() {
  try {
    const result = await store.triggerAgenticIngest()
    if (result.success) {
      ElMessage.success(`成功触发Agentic Ingest：${result.document_name}`)
    }
  } catch (error: any) {
    ElMessage.error(error.message || 'Agentic Ingest失败')
  }
}

// 组件挂载时加载collection列表和模型列表
onMounted(async () => {
  try {
    await Promise.all([
      store.loadCollections(),
      store.loadModels()
    ])
  } catch (error) {
    console.warn('初始加载数据失败:', error)
  }
})
</script>

<template>
  <div class="chat-area">
    <!-- 头部 -->
    <header class="chat-header">
      <div class="header-left">
        <h1>对话</h1>
        <div class="model-selector">
          <ElSelect
            v-model="store.selectedModel"
            placeholder="选择模型"
            class="model-select"
            :loading="store.loading.loadingModels"
            clearable
            filterable
          >
            <ElOption
              v-for="model in store.models"
              :key="model.id"
              :label="model.name"
              :value="model.id"
            />
          </ElSelect>
        </div>
      </div>

      <div class="query-type-selector-wrapper">
        <ElSelect
          v-model="store.queryType"
          placeholder="选择问答类型"
          class="query-type-selector"
        >
          <ElOption
            label="普通问答"
            :value="QueryType.NORMAL"
          />
          <ElOption
            label="文档问答"
            :value="QueryType.DOCUMENT"
          />
          <ElOption
            label="Collection问答"
            :value="QueryType.COLLECTION"
          />
        </ElSelect>
      </div>
      
      <div class="header-actions">
        <ElButton text @click="handleShowWorkflows">
          <ElIcon>
            <Bell />
          </ElIcon>
          <span>工作流状态</span>
        </ElButton>
        <ElButton text @click="handleClearMessages" :disabled="store.messages.length === 0">
          <ElIcon>
            <Refresh />
          </ElIcon>
          清空对话
        </ElButton>
      </div>
    </header>

    <!-- 主要内容区域 - 根据查询类型渲染不同的子组件 -->
    <div class="chat-content">
      <!-- 普通问答模式 -->
      <NormalChat
        v-if="store.queryType === QueryType.NORMAL"
        :messages="store.messages"
        :loading="store.loading.querying"
        @send-query="handleSendQuery"
      />

      <!-- 文档问答模式 -->
      <DocumentChat
        v-else-if="store.queryType === QueryType.DOCUMENT"
        :messages="store.messages"
        :documents="store.documents"
        :loading="store.loading.querying"
        :ingestion-status="store.ingestionStatus"
        :topic-input="store.topicInput"
        :generating="store.generating"
        :candidate-urls="store.candidateUrls"
        @send-query="handleSendQuery"
        @generate-candidates-from-topic="store.generateCandidatesFromTopic"
        @add-candidate="store.addCandidate"
        @update:topic-input="(value) => store.topicInput = value"
      />

      <!-- Collection问答模式 -->
      <CollectionChat
        v-else-if="store.queryType === QueryType.COLLECTION"
        :messages="store.messages"
        :collections="store.collections"
        :selected-collection="store.selectedCollection"
        :loading="store.loading.querying"
        :loading-collections="store.loading.loadingCollections"
        :collection-query-results="store.collectionQueryResults"
        :agentic-ingest-url="store.agenticIngestUrl"
        :triggering-agentic-ingest="store.loading.triggeringAgenticIngest"
        :should-use-web-search="store.shouldUseWebSearch"
        @send-query="handleSendQuery"
        @update:selected-collection="(value: string | null) => store.selectedCollection = value || ''"
        @update:agentic-ingest-url="(value) => store.agenticIngestUrl = value"
        @trigger-agentic-ingest="handleTriggerAgenticIngest"
        @clear-collection-results="store.clearCollectionResults"
      />
    </div>

    <!-- 查询类型选择器 -->
    <!-- <div class="query-type-selector-container">
      <div class="query-type-selector-wrapper">
        <ElSelect
          v-model="store.queryType"
          placeholder="选择问答类型"
          class="query-type-selector"
        >
          <ElOption
            label="普通问答"
            :value="QueryType.NORMAL"
          />
          <ElOption
            label="文档问答"
            :value="QueryType.DOCUMENT"
          />
          <ElOption
            label="Collection问答"
            :value="QueryType.COLLECTION"
          />
        </ElSelect>
      </div>
    </div> -->

    <!-- 工作流状态对话框 -->
    <WorkflowDialog
      v-model:visible="workflowDialogVisible"
      :session-id="sessionStore.sessionId || ''"
    />
  </div>
</template>

<style scoped>
.chat-area {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: white;
}

.chat-header {
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: white;
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 24px;
}

.chat-header h1 {
  margin: 0;
  color: #111827;
  font-size: 20px;
  font-weight: 600;
  white-space: nowrap;
}

.model-selector {
  margin-left: 24px;
}

.model-select {
  width: 200px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.chat-content {
  flex: 1;
  overflow: hidden;
}

.query-type-selector-container {
  padding: 12px 24px;
  border-top: 1px solid #e5e7eb;
  background: white;
}

.query-type-selector-wrapper {
  display: flex;
  justify-content: center;
  width: 300px;
}

.query-type-selector {
  width: 300px;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .chat-header {
    padding: 16px;
    flex-direction: column;
    gap: 16px;
    align-items: stretch;
  }

  .header-left {
    flex-direction: column;
    gap: 16px;
    align-items: stretch;
  }

  .header-actions {
    align-self: center;
  }

  .query-type-selector-container {
    padding: 16px;
  }
}
</style>