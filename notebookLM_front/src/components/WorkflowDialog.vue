<script setup lang="ts">
import { ref } from 'vue'
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
    width="85%" 
    max-height="70vh"
  >
    <div class="workflow-status-container" v-loading="loadingWorkflows">
      <div class="workflow-section">
        <h3>正在执行的工作流 ({{ runningWorkflows.length }})</h3>
        <ElTable 
          :data="runningWorkflows" 
          style="width: 100%" 
          max-height="200"
          :empty-text="loadingWorkflows ? '加载中...' : '暂无正在执行的工作流'"
        >
          <ElTableColumn prop="executionId" label="执行ID" width="180" />
          <ElTableColumn prop="documentName" label="文档名称" min-width="250" />
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
      </div>

      <div class="workflow-section">
        <h3 style="margin-top: 20px;">执行历史 ({{ workflowHistory.length }})</h3>
        <ElTable 
          :data="workflowHistory" 
          style="width: 100%" 
          max-height="300"
          :empty-text="loadingWorkflows ? '加载中...' : '暂无执行历史'"
        >
          <ElTableColumn prop="executionId" label="执行ID" width="180" />
          <ElTableColumn prop="documentName" label="文档名称" min-width="250" />
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
</style>
