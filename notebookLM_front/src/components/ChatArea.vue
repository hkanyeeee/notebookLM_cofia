<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useNotebookStore, QueryType } from '../stores/notebook'
import { useSessionStore } from '../stores/session'
import { ElSelect, ElOption, ElButton, ElIcon, ElMessage } from 'element-plus'
import { Refresh, Bell, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import NormalChat from './NormalChat.vue'
import DocumentChat from './DocumentChat.vue'
import CollectionChat from './CollectionChat.vue'
import WorkflowDialog from './WorkflowDialog.vue'
import ThemeToggle from './ThemeToggle.vue'

const store = useNotebookStore()
const sessionStore = useSessionStore()

// 工作流对话框状态
const workflowDialogVisible = ref(false)

// 移动端顶栏折叠状态
const headerCollapsed = ref(false)

// 判断是否为移动端
const isMobile = ref(false)

// 检测屏幕尺寸
const checkMobile = () => {
  isMobile.value = window.innerWidth <= 768
}

// 监听窗口大小变化
onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', checkMobile)
})

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

// 处理编辑消息重新发送
async function handleResendEditedMessage(messageId: string) {
  try {
    await store.resendEditedMessage(messageId)
    ElMessage.success('消息已重新发送')
  } catch (error: any) {
    ElMessage.error(error.message || '重新发送失败，请重试')
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
    

  } catch (error) {
    console.warn('初始加载数据失败:', error)
  }
})


</script>

<template>
  <div class="flex flex-col h-full bg-white dark:bg-dark-background">
    <!-- 头部 -->
    <header class="header-container" :class="{ 'header-collapsed': headerCollapsed }">
      <!-- 第一行：标题和按钮 -->
      <div class="header-row">
        <h1 class="header-title">对话</h1>
        <div class="header-actions">
          <!-- 移动端折叠按钮 -->
          <ElButton text @click="headerCollapsed = !headerCollapsed" class="action-btn collapse-btn">
            <ElIcon>
              <ArrowUp v-if="!headerCollapsed" />
              <ArrowDown v-else />
            </ElIcon>
          </ElButton>
          <ThemeToggle :show-dropdown="!isMobile" class="action-btn" />
          <ElButton text @click="handleShowWorkflows" class="action-btn" >
            <ElIcon>
              <Bell />
            </ElIcon>
            <span class="action-text">工作流状态</span>
          </ElButton>
          <ElButton text @click="handleClearMessages" :disabled="store.messages.length === 0" class="action-btn">
            <ElIcon>
              <Refresh />
            </ElIcon>
            <span class="action-text">清空</span>
          </ElButton>
        </div>
      </div>
      
      <!-- 第二行：选择器 -->
      <div class="header-controls">
        <!-- 模型选择器容器 -->
        <div class="model-selector-container" :class="{ 'hidden-when-collapsed': isMobile && headerCollapsed }">
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

        <!-- 问答类型选择器 -->
        <div class="query-type-container" :class="{ 'expanded-when-collapsed': isMobile && headerCollapsed }">
          <ElSelect
            v-model="store.queryType"
            placeholder="选择问答类型"
            class="query-type-select"
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
      </div>


    </header>

    <!-- 主要内容区域 - 根据查询类型渲染不同的子组件 -->
    <div class="flex-1 overflow-hidden">
      <!-- 普通问答模式 -->
      <NormalChat
        v-if="store.queryType === QueryType.NORMAL"
        :messages="store.messages"
        :loading="store.loading.querying"
        :query-type="store.queryType"
        :selected-model="store.selectedModel"
        @send-query="handleSendQuery"
        @start-edit-message="store.startEditMessage"
        @cancel-edit-message="store.cancelEditMessage"
        @update-editing-message="store.updateEditingMessage"
        @resend-edited-message="handleResendEditedMessage"
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

<style scoped>
/* 头部容器 */
.header-container {
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border);
  background-color: var(--color-surface);
  z-index: 10;
  transition: all 0.3s ease;
}

/* 第一行：标题和按钮 */
.header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.header-title {
  margin: 0;
  color: var(--color-text);
  font-size: 1.125rem;
  font-weight: 600;
  white-space: nowrap;
  transition: color 0.3s ease;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.action-btn {
  padding: 8px 12px;
  min-height: 32px;
}

.action-text {
  margin-left: 4px;
}

/* 第二行：选择器 */
.header-controls {
  display: flex;
  gap: 16px;
  margin-bottom: 8px;
}

.model-selector-container {
  flex: 1;
  min-width: 0;
}

.query-type-container {
  flex: 1;
  min-width: 0;
}

.model-select,
.query-type-select {
  width: 100%;
}

/* 提示信息 */
.header-hints {
  min-height: 20px;
}

.hint-text {
  font-size: 0.75rem;
  color: #6b7280;
  line-height: 1.4;
}

.error-hint {
  font-size: 0.75rem;
  color: #dc2626;
  background-color: #fef2f2;
  padding: 8px;
  border-radius: 4px;
  border: 1px solid #fecaca;
  line-height: 1.4;
}

/* 桌面端隐藏折叠按钮 */
@media (min-width: 769px) {
  .collapse-btn {
    display: none !important;
  }
}

/* 大屏幕适配 (1440px以上) */
@media (min-width: 1440px) {
  .header-container {
    padding: 12px 32px;
  }
  
  /* 大屏幕下限制选择器宽度，避免过度拉伸 */
  .header-controls {
    max-width: 800px;
    margin: 0 auto 8px auto;
  }
  
  .model-selector-container,
  .query-type-container {
    max-width: 380px;
  }
}

/* 超大屏幕适配 (2200px以上) */
@media (min-width: 2200px) {
  .header-container {
    padding: 20px 40px;
  }
  
  /* 超大屏幕下进一步限制宽度并居中 */
  .header-controls {
    max-width: 1000px;
  }
  
  .model-selector-container,
  .query-type-container {
    max-width: 480px;
  }
  
  /* 标题和按钮区域也限制最大宽度 */
  .header-row {
    max-width: 1200px;
    margin: 0 auto 12px auto;
  }
  
  /* 提示信息也居中 */
  .header-hints {
    max-width: 1000px;
    margin: 0 auto;
  }
}

/* 移动端适配 */
@media (max-width: 768px) {
  .header-container {
    padding: 12px 16px;
    transition: all 0.3s ease;
  }

  .header-container.header-collapsed {
    padding-bottom: 8px;
  }

  .header-row {
    margin-bottom: 16px;
  }

  .header-title {
    font-size: 1rem;
  }

  .action-btn {
    padding: 6px 8px;
    min-height: 36px;
    transition: opacity 0.3s ease;
  }

  /* 折叠按钮样式 */
  .collapse-btn {
    display: block !important;
  }

  /* 移动端隐藏按钮文字，只显示图标 */
  .action-text {
    display: none;
  }

  /* 折叠时隐藏的元素 */
  .hidden-when-collapsed {
    opacity: 0;
    pointer-events: none;
    max-height: 0;
    overflow: hidden;
    transition: all 0.3s ease;
  }

  .header-controls {
    flex-direction: column;
    gap: 12px;
    margin-bottom: 12px;
    transition: all 0.3s ease;
  }

  .header-container.header-collapsed .header-controls {
    margin-bottom: 8px;
  }

  .model-selector-container,
  .query-type-container {
    width: 100%;
    transition: all 0.3s ease;
  }

  /* 折叠时问答类型选择器占满宽度 */
  .query-type-container.expanded-when-collapsed {
    width: 100% !important;
  }
}

/* 更小的移动设备适配 */
@media (max-width: 480px) {
  .header-container {
    padding: 10px 12px;
  }

  .header-row {
    margin-bottom: 2px;
  }

  .header-actions {
    gap: 4px;
  }

  .action-btn {
    padding: 4px 6px;
    min-height: 32px;
  }

  .header-controls {
    gap: 10px;
    margin-bottom: 10px;
  }
}
</style>