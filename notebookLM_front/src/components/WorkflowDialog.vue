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
    max-height="70%"
    class="workflow-dialog"
  >
    <div class="min-h-[300px]" v-loading="loadingWorkflows">
      <div class="workflow-section">
        <h3 class="mt-4 text-gray-900 text-[16px] font-semibold mb-4">正在执行的工作流 ({{ runningWorkflows.length }})</h3>
        
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
        <div v-else class="flex flex-col gap-3 max-h-[300px] overflow-y-auto">
          <div 
            v-if="runningWorkflows.length === 0" 
            class="text-center text-gray-400 py-10 text-[14px]"
          >
            {{ loadingWorkflows ? '加载中...' : '暂无正在执行的工作流' }}
          </div>
          <div 
            v-for="workflow in runningWorkflows" 
            :key="workflow.executionId"
            class="bg-white border border-gray-200 rounded-lg p-3 transition-all hover:border-gray-300 hover:shadow border-l-4 border-l-amber-500"
          >
            <div class="card-header">
              <div class="document-name text-gray-900 font-semibold text-[14px] leading-tight flex-1 break-words">{{ workflow.documentName || '未知文档' }}</div>
              <ElTag type="warning" effect="plain" size="small">
                {{ getStatusText(workflow.status) }}
              </ElTag>
            </div>
            <div class="card-body">
              <div class="execution-id text-gray-500 text-[12px] font-mono break-all">执行ID: {{ workflow.executionId }}</div>
              <div class="start-time text-gray-500 text-[12px]">开始时间: {{ formatWorkflowTime(workflow.startedAt) }}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="workflow-section">
        <h3 class="mt-5 text-gray-900 text-[16px] font-semibold mb-4">执行历史 ({{ workflowHistory.length }})</h3>
        
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
        <div v-else class="flex flex-col gap-3 max-h-[300px] overflow-y-auto">
          <div 
            v-if="workflowHistory.length === 0" 
            class="text-center text-gray-400 py-10 text-[14px]"
          >
            {{ loadingWorkflows ? '加载中...' : '暂无执行历史' }}
          </div>
          <div 
            v-for="workflow in workflowHistory" 
            :key="workflow.executionId"
            class="bg-white border border-gray-200 rounded-lg p-3 transition-all hover:border-gray-300 hover:shadow border-l-4 border-l-gray-500"
          >
            <div class="card-header">
              <div class="document-name text-gray-900 font-semibold text-[14px] leading-tight flex-1 break-words">{{ workflow.documentName || '未知文档' }}</div>
              <ElTag 
                :type="getStatusTagType(workflow.status)" 
                effect="plain" 
                size="small"
              >
                {{ getStatusText(workflow.status) }}
              </ElTag>
            </div>
            <div class="card-body">
              <div class="execution-id text-gray-500 text-[12px] font-mono break-all">执行ID: {{ workflow.executionId }}</div>
              <div class="time-info flex flex-col gap-0.5">
                <div class="start-time text-gray-500 text-[12px]">开始: {{ formatWorkflowTime(workflow.startedAt) }}</div>
                <div v-if="workflow.stoppedAt" class="stop-time text-gray-500 text-[12px]">结束: {{ formatWorkflowTime(workflow.stoppedAt) }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <template #footer>
      <div class="flex gap-2 justify-end">
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
/* 保留仅 Element Plus 深度选择器相关的移动端间距适配 */
@media (max-width: 768px) {
  .workflow-dialog :deep(.el-dialog) { margin: 5% auto; }
  .workflow-dialog :deep(.el-dialog__header) { padding: 16px 20px; }
  .workflow-dialog :deep(.el-dialog__body) { padding: 0 20px 20px; }
  .workflow-dialog :deep(.el-dialog__footer) { padding: 16px 20px; }
}

@media (max-width: 480px) {
  .workflow-dialog :deep(.el-dialog) { width: 95% !important; margin: 3% auto; }
}
</style>
