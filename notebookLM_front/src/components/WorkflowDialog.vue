<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElDialog, ElTable, ElTableColumn, ElTag, ElButton, ElIcon, ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { n8nApi, type WorkflowExecution } from '../api/n8n'

// Props
interface Props {
  visible: boolean
  sessionId: string
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
}>()

// 工作流数据
const runningWorkflows = ref<WorkflowExecution[]>([])
const workflowHistory = ref<WorkflowExecution[]>([])
const loadingWorkflows = ref(false)

// 响应式检测
const windowWidth = ref(window.innerWidth)
const isMobile = computed(() => windowWidth.value <= 768)

// 监听窗口大小变化
function handleResize() {
  windowWidth.value = window.innerWidth
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})

// 处理对话框可见性变化
function handleVisibilityChange(value: boolean) {
  emit('update:visible', value)
  
  // 对话框打开时加载数据
  if (value) {
    loadWorkflowStatus()
  }
}

// 加载工作流状态
async function loadWorkflowStatus() {
  try {
    loadingWorkflows.value = true
    
    // 调用API获取工作流执行状态
    const response = await n8nApi.getWorkflowExecutions({
      sessionId: props.sessionId,
      limit: 50
    })
    
    if (response.success) {
      runningWorkflows.value = response.runningWorkflows
      workflowHistory.value = response.workflowHistory
      
      console.log('工作流状态加载成功:', {
        running: runningWorkflows.value.length,
        history: workflowHistory.value.length
      })
    } else {
      ElMessage.error('获取工作流状态失败')
    }
    
  } catch (error: any) {
    console.error('获取工作流状态失败:', error)
    ElMessage.error(error.message || '获取工作流状态失败')
  } finally {
    loadingWorkflows.value = false
  }
}

// 格式化工作流时间
function formatWorkflowTime(timeStr?: string) {
  if (!timeStr) return '-'
  try {
    const date = new Date(timeStr)
    return new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  } catch {
    return timeStr
  }
}

// 获取状态文本
function getStatusText(status: string) {
  const statusMap: Record<string, string> = {
    'running': '执行中',
    'success': '成功',
    'error': '失败',
    'stopped': '已停止'
  }
  return statusMap[status] || status
}

// 获取状态标签类型
function getStatusTagType(status: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  const typeMap: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    'running': 'warning',
    'success': 'success',
    'error': 'danger',
    'stopped': 'info'
  }
  return typeMap[status] || 'info'
}
</script>

<template>
  <ElDialog 
    :model-value="visible" 
    @update:model-value="handleVisibilityChange"
    title="n8n工作流执行状态" 
    :width="isMobile ? '95%' : '85%'"
    max-height="70vh"
    class="workflow-dialog"
  >
    <div class="workflow-status-container" v-loading="loadingWorkflows">
      <div class="workflow-section">
        <h3>正在执行的工作流 ({{ runningWorkflows.length }})</h3>
        
        <!-- 桌面端表格显示 -->
        <ElTable 
          v-if="!isMobile"
          :data="runningWorkflows" 
          style="width: 100%" 
          max-height="200"
          :empty-text="loadingWorkflows ? '加载中...' : '暂无正在执行的工作流'"
        >
          <ElTableColumn prop="executionId" label="执行ID" min-width="200" />
          <ElTableColumn prop="documentName" label="文档名称" width="230" />
          <ElTableColumn prop="status" label="状态" width="100">
            <template #default="{ row }">
              <ElTag type="warning" effect="plain">{{ getStatusText(row.status) }}</ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="startedAt" label="开始时间" width="160">
            <template #default="{ row }">
              {{ formatWorkflowTime(row.startedAt) }}
            </template>
          </ElTableColumn>
        </ElTable>
        
        <!-- 移动端卡片显示 -->
        <div v-else class="mobile-workflow-list">
          <div 
            v-if="runningWorkflows.length === 0" 
            class="empty-state"
          >
            {{ loadingWorkflows ? '加载中...' : '暂无正在执行的工作流' }}
          </div>
          <div 
            v-for="workflow in runningWorkflows" 
            :key="workflow.executionId"
            class="mobile-workflow-card running"
          >
            <div class="card-header">
              <div class="document-name">{{ workflow.documentName || '未知文档' }}</div>
              <ElTag type="warning" effect="plain" size="small">
                {{ getStatusText(workflow.status) }}
              </ElTag>
            </div>
            <div class="card-body">
              <div class="execution-id">执行ID: {{ workflow.executionId }}</div>
              <div class="start-time">开始时间: {{ formatWorkflowTime(workflow.startedAt) }}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="workflow-section">
        <h3 style="margin-top: 20px;">执行历史 ({{ workflowHistory.length }})</h3>
        
        <!-- 桌面端表格显示 -->
        <ElTable 
          v-if="!isMobile"
          :data="workflowHistory" 
          style="width: 100%" 
          max-height="300"
          :empty-text="loadingWorkflows ? '加载中...' : '暂无执行历史'"
        >
          <ElTableColumn prop="executionId" label="执行ID" min-width="200" />
          <ElTableColumn prop="documentName" label="文档名称" width="230" />
          <ElTableColumn prop="status" label="状态" width="100">
            <template #default="{ row }">
              <ElTag 
                :type="getStatusTagType(row.status)" 
                effect="plain"
              >
                {{ getStatusText(row.status) }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="startedAt" label="开始时间" width="160">
            <template #default="{ row }">
              {{ formatWorkflowTime(row.startedAt) }}
            </template>
          </ElTableColumn>
          <ElTableColumn prop="stoppedAt" label="结束时间" width="160">
            <template #default="{ row }">
              {{ formatWorkflowTime(row.stoppedAt) }}
            </template>
          </ElTableColumn>
        </ElTable>
        
        <!-- 移动端卡片显示 -->
        <div v-else class="mobile-workflow-list">
          <div 
            v-if="workflowHistory.length === 0" 
            class="empty-state"
          >
            {{ loadingWorkflows ? '加载中...' : '暂无执行历史' }}
          </div>
          <div 
            v-for="workflow in workflowHistory" 
            :key="workflow.executionId"
            class="mobile-workflow-card history"
          >
            <div class="card-header">
              <div class="document-name">{{ workflow.documentName || '未知文档' }}</div>
              <ElTag 
                :type="getStatusTagType(workflow.status)" 
                effect="plain" 
                size="small"
              >
                {{ getStatusText(workflow.status) }}
              </ElTag>
            </div>
            <div class="card-body">
              <div class="execution-id">执行ID: {{ workflow.executionId }}</div>
              <div class="time-info">
                <div class="start-time">开始: {{ formatWorkflowTime(workflow.startedAt) }}</div>
                <div v-if="workflow.stoppedAt" class="stop-time">
                  结束: {{ formatWorkflowTime(workflow.stoppedAt) }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <template #footer>
      <div class="dialog-footer">
        <ElButton @click="loadWorkflowStatus" :loading="loadingWorkflows">
          <ElIcon><Refresh /></ElIcon>
          刷新
        </ElButton>
        <ElButton @click="handleVisibilityChange(false)">关闭</ElButton>
      </div>
    </template>
  </ElDialog>
</template>

<style scoped>
.workflow-status-container {
  min-height: 300px;
}

.workflow-section h3 {
  color: #111827;
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 16px;
}

.dialog-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

/* 移动端样式 */
.mobile-workflow-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 300px;
  overflow-y: auto;
}

.mobile-workflow-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  transition: all 0.2s ease;
}

.mobile-workflow-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.mobile-workflow-card.running {
  border-left: 4px solid #f59e0b;
}

.mobile-workflow-card.history {
  border-left: 4px solid #6b7280;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
  gap: 8px;
}

.document-name {
  font-weight: 600;
  color: #111827;
  font-size: 14px;
  line-height: 1.4;
  flex: 1;
  word-break: break-word;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.execution-id {
  color: #6b7280;
  font-size: 12px;
  font-family: 'Monaco', 'Menlo', monospace;
  word-break: break-all;
}

.time-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.start-time, .stop-time {
  color: #6b7280;
  font-size: 12px;
}

.empty-state {
  text-align: center;
  color: #9ca3af;
  padding: 40px 20px;
  font-size: 14px;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .workflow-dialog :deep(.el-dialog) {
    margin: 5vh auto;
  }
  
  .workflow-dialog :deep(.el-dialog__header) {
    padding: 16px 20px;
  }
  
  .workflow-dialog :deep(.el-dialog__body) {
    padding: 0 20px 20px;
  }
  
  .workflow-dialog :deep(.el-dialog__footer) {
    padding: 16px 20px;
  }
  
  .workflow-section h3 {
    font-size: 14px;
    margin-bottom: 12px;
  }
  
  .dialog-footer {
    justify-content: center;
  }
  
  .dialog-footer .el-button {
    flex: 1;
    max-width: 120px;
  }
}

@media (max-width: 480px) {
  .workflow-dialog :deep(.el-dialog) {
    width: 95% !important;
    margin: 3vh auto;
  }
  
  .mobile-workflow-card {
    padding: 10px;
  }
  
  .document-name {
    font-size: 13px;
  }
  
  .execution-id {
    font-size: 11px;
  }
  
  .start-time, .stop-time {
    font-size: 11px;
  }
}
</style>
