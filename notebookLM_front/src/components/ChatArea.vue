<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
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
    // 只有当模型列表为空时才加载模型，避免重复加载
    const loadPromises = [store.loadCollections()]
    
    if (store.models.length === 0) {
      loadPromises.push(store.loadModels())
    }
    
    await Promise.all(loadPromises)
    
    // 如果当前是普通问答模式，强制选择指定模型
    if (store.queryType === QueryType.NORMAL) {
      store.forceSelectNormalChatModel()
    }
  } catch (error) {
    console.warn('初始加载数据失败:', error)
  }
})

// 监听问答类型变化
watch(() => store.queryType, (newType) => {
  if (newType === QueryType.NORMAL) {
    // 切换到普通问答模式时，强制选择指定模型
    store.forceSelectNormalChatModel()
  }
})
</script>

<template>
  <div class="flex flex-col h-screen bg-white">
    <!-- 头部 -->
    <header class="p-5 border-b border-gray-200 flex items-center justify-between bg-white z-10">
      <div class="flex items-center gap-6">
        <h1 class="m-0 text-gray-900 text-lg font-semibold whitespace-nowrap">对话</h1>
        <div class="ml-6">
          <ElSelect
            v-model="store.selectedModel"
            placeholder="选择模型"
            class="w-50"
            :loading="store.loading.loadingModels"
            :disabled="store.queryType === QueryType.NORMAL"
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
          
          <!-- 普通问答模式提示 -->
          <div 
            v-if="store.queryType === QueryType.NORMAL" 
            class="text-xs text-gray-500 mt-1 leading-1.4"
          >
            普通问答模式使用 {{ store.NORMAL_CHAT_MODEL }}
          </div>
          
          <!-- 模型错误提示 -->
          <div 
            v-if="store.normalChatModelError" 
            class="text-xs text-red-600 mt-1 leading-1.4 bg-red-50 p-2 rounded border border-red-200"
          >
            {{ store.normalChatModelError }}
          </div>
        </div>
      </div>

      <div class="flex gap-3 w-50">
        <ElSelect
          v-model="store.queryType"
          placeholder="选择问答类型"
          class="w-50"
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
      
      <div class="flex gap-3">
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
    <div class="flex-1 overflow-hidden">
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
    <!-- <div class="p-3 border-t border-gray-200 bg-white">
      <div class="flex justify-center w-75">
        <ElSelect
          v-model="store.queryType"
          placeholder="选择问答类型"
          class="w-75"
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