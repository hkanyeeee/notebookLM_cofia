<template>
  <div class="ingest-task-monitor">
    <!-- 任务列表 -->
    <div v-if="tasks.length > 0" class="task-list">
      <div class="task-list-header">
        <h3 class="task-list-title">
          <i class="fas fa-tasks"></i>
          摄取任务监控 ({{ tasks.length }})
        </h3>
        <button 
          v-if="tasks.some(task => isTaskCompleted(task.status))"
          @click="clearCompletedTasks"
          class="clear-all-btn"
          title="清理所有已完成的任务"
        >
          <i class="fas fa-broom"></i>
          清理完成的任务
        </button>
      </div>
      
      <div class="task-items">
        <div 
          v-for="task in tasks" 
          :key="task.task_id"
          class="task-item"
          :class="getTaskStatusClass(task.status)"
        >
          <!-- 任务头部 -->
          <div class="task-header">
            <div class="task-info">
              <h4 class="task-name">{{ task.document_name }}</h4>
              <span class="task-url">{{ truncateUrl(task.parent_url) }}</span>
            </div>
            
            <div class="task-status">
              <span class="status-badge" :class="getTaskStatusClass(task.status)">
                <i :class="getTaskStatusIcon(task.status)"></i>
                {{ getTaskStatusText(task.status) }}
              </span>
              
              <!-- 删除/关闭按钮：进行中也允许删除 -->
              <button 
                @click="confirmRemoveTask(task)"
                class="remove-btn enhanced"
                :title="isTaskCompleted(task.status) ? '关闭任务' : '删除进行中的任务'"
              >
                <i class="fas fa-times"></i>
                <span class="remove-text">{{ isTaskCompleted(task.status) ? '关闭' : '删除' }}</span>
              </button>
            </div>
          </div>
          
          <!-- 进度条 -->
          <div class="task-progress">
            <div class="progress-bar">
              <div 
                class="progress-fill" 
                :style="{ width: `${task.progress_percentage}%` }"
                :class="getProgressClass(task.status)"
              ></div>
            </div>
            
            <div class="progress-text">
              <span class="progress-stats">
                {{ task.completed_sub_docs }} / {{ task.total_sub_docs }} 完成
                <span v-if="task.failed_sub_docs > 0" class="failed-count">
                  ({{ task.failed_sub_docs }} 失败)
                </span>
              </span>
              <span class="progress-percent">{{ Math.round(task.progress_percentage) }}%</span>
            </div>
          </div>
          
          <!-- 子文档详情（可展开） -->
          <div v-if="expandedTasks.has(task.task_id)" class="task-details">
            <div class="sub-docs">
              <h5>子文档处理详情:</h5>
              <div class="sub-doc-list">
                <div 
                  v-for="subDoc in task.sub_docs" 
                  :key="subDoc.url"
                  class="sub-doc-item"
                  :class="getTaskStatusClass(subDoc.status)"
                >
                  <div class="sub-doc-info">
                    <i :class="getTaskStatusIcon(subDoc.status)"></i>
                    <span class="sub-doc-url">{{ truncateUrl(subDoc.url) }}</span>
                  </div>
                  <div class="sub-doc-status">
                    <span class="status-text">{{ getTaskStatusText(subDoc.status) }}</span>
                    <span v-if="subDoc.error" class="error-text" :title="subDoc.error">
                      <i class="fas fa-exclamation-triangle"></i>
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          
          <!-- 展开/收起按钮 -->
          <div class="task-actions">
            <button 
              @click="toggleTaskExpansion(task.task_id)"
              class="expand-btn"
            >
              <i :class="expandedTasks.has(task.task_id) ? 'fas fa-chevron-up' : 'fas fa-chevron-down'"></i>
              {{ expandedTasks.has(task.task_id) ? '收起' : '详情' }}
            </button>
            
            <!-- 时间信息 -->
            <div class="task-time">
              <span v-if="task.started_at">
                开始: {{ formatTime(task.started_at) }}
              </span>
              <span v-if="task.completed_at">
                完成: {{ formatTime(task.completed_at) }}
              </span>
            </div>
          </div>
          
          <!-- 错误信息 -->
          <div v-if="task.error" class="task-error">
            <i class="fas fa-exclamation-circle"></i>
            <span>{{ task.error }}</span>
          </div>
        </div>
      </div>
    </div>
    
    <!-- 空状态 -->
    <div v-else class="empty-state">
      <i class="fas fa-inbox"></i>
      <p>暂无活跃的摄取任务</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { 
  listIngestTasks, 
  deleteIngestTask, 
  createIngestProgressStream,
  type IngestTaskStatus,
  TaskStatus 
} from '../api/ingest'

// 响应式数据
const tasks = ref<IngestTaskStatus[]>([])
const expandedTasks = ref<Set<string>>(new Set())
const eventSources = ref<Map<string, EventSource>>(new Map())

// 轮询定时器
let pollTimer: number | null = null

// 组件挂载时开始监控
onMounted(async () => {
  await loadTasks()
  startMonitoring()
})

// 组件卸载时清理资源
onUnmounted(() => {
  stopMonitoring()
})

// 加载任务列表
async function loadTasks() {
  try {
    tasks.value = await listIngestTasks()
    
    // 为运行中的任务创建流式监控
    for (const task of tasks.value) {
      if (task.status === TaskStatus.RUNNING) {
        startTaskMonitoring(task.task_id)
      }
    }
  } catch (error) {
    console.error('加载任务列表失败:', error)
  }
}

// 开始监控
function startMonitoring() {
  // 每30秒刷新一次任务列表
  pollTimer = setInterval(loadTasks, 30000)
}

// 停止监控
function stopMonitoring() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  
  // 关闭所有EventSource连接
  for (const [taskId, eventSource] of eventSources.value) {
    eventSource.close()
  }
  eventSources.value.clear()
}

// 为特定任务开始流式监控
function startTaskMonitoring(taskId: string) {
  if (eventSources.value.has(taskId)) {
    return // 已经在监控中
  }
  
  const eventSource = createIngestProgressStream(taskId)
  
  eventSource.onmessage = (event) => {
    try {
      const status: IngestTaskStatus = JSON.parse(event.data)
      updateTaskStatus(status)
    } catch (error) {
      console.error('解析任务状态失败:', error)
    }
  }
  
  eventSource.onerror = (error) => {
    console.error(`任务 ${taskId} 监控连接错误:`, error)
    eventSource.close()
    eventSources.value.delete(taskId)
  }
  
  eventSources.value.set(taskId, eventSource)
}

// 更新任务状态
async function updateTaskStatus(updatedTask: IngestTaskStatus) {
  const index = tasks.value.findIndex(task => task.task_id === updatedTask.task_id)
  if (index !== -1) {
    tasks.value[index] = updatedTask
    
    // 如果任务完成，关闭监控连接
    if (updatedTask.status === TaskStatus.COMPLETED || 
        updatedTask.status === TaskStatus.PARTIALLY_COMPLETED || 
        updatedTask.status === TaskStatus.FAILED) {
      const eventSource = eventSources.value.get(updatedTask.task_id)
      if (eventSource) {
        eventSource.close()
        eventSources.value.delete(updatedTask.task_id)
      }
    }
  }
}

// 判断任务是否已完成（可以关闭）
function isTaskCompleted(status: TaskStatus): boolean {
  return status === TaskStatus.COMPLETED || 
         status === TaskStatus.PARTIALLY_COMPLETED || 
         status === TaskStatus.FAILED
}

// 移除任务
async function removeTask(taskId: string) {
  try {
    await deleteIngestTask(taskId)
    
    // 从本地列表中移除
    tasks.value = tasks.value.filter(task => task.task_id !== taskId)
    expandedTasks.value.delete(taskId)
    
    // 关闭监控连接
    const eventSource = eventSources.value.get(taskId)
    if (eventSource) {
      eventSource.close()
      eventSources.value.delete(taskId)
    }
    ElMessage.success('任务已移除')
  } catch (error) {
    console.error('移除任务失败:', error)
  }
}

// 删除前确认：进行中给出提示
function confirmRemoveTask(task: IngestTaskStatus) {
  if (task.status === TaskStatus.RUNNING || task.status === TaskStatus.PENDING) {
    const ok = window.confirm('确定要删除进行中的任务吗？这将仅移除监控项，不会中断后台处理。')
    if (!ok) return
  }
  removeTask(task.task_id)
}

// 批量清理所有完成的任务
async function clearCompletedTasks() {
  const completedTasks = tasks.value.filter(task => isTaskCompleted(task.status))
  
  for (const task of completedTasks) {
    try {
      await removeTask(task.task_id)
    } catch (error) {
      console.error(`移除任务 ${task.task_id} 失败:`, error)
    }
  }
}

// 切换任务展开状态
function toggleTaskExpansion(taskId: string) {
  if (expandedTasks.value.has(taskId)) {
    expandedTasks.value.delete(taskId)
  } else {
    expandedTasks.value.add(taskId)
  }
}

// 获取任务状态样式类
function getTaskStatusClass(status: TaskStatus): string {
  const classMap = {
    [TaskStatus.PENDING]: 'status-pending',
    [TaskStatus.RUNNING]: 'status-running',
    [TaskStatus.COMPLETED]: 'status-completed',
    [TaskStatus.PARTIALLY_COMPLETED]: 'status-partially-completed',
    [TaskStatus.FAILED]: 'status-failed'
  }
  return classMap[status] || ''
}

// 获取任务状态图标
function getTaskStatusIcon(status: TaskStatus): string {
  const iconMap = {
    [TaskStatus.PENDING]: 'fas fa-clock',
    [TaskStatus.RUNNING]: 'fas fa-spinner fa-spin',
    [TaskStatus.COMPLETED]: 'fas fa-check-circle',
    [TaskStatus.PARTIALLY_COMPLETED]: 'fas fa-exclamation-circle',
    [TaskStatus.FAILED]: 'fas fa-times-circle'
  }
  return iconMap[status] || 'fas fa-question-circle'
}

// 获取任务状态文本
function getTaskStatusText(status: TaskStatus): string {
  const textMap = {
    [TaskStatus.PENDING]: '等待中',
    [TaskStatus.RUNNING]: '处理中',
    [TaskStatus.COMPLETED]: '已完成',
    [TaskStatus.PARTIALLY_COMPLETED]: '部分成功',
    [TaskStatus.FAILED]: '失败'
  }
  return textMap[status] || '未知'
}

// 获取进度条样式类
function getProgressClass(status: TaskStatus): string {
  const classMap = {
    [TaskStatus.PENDING]: 'progress-pending',
    [TaskStatus.RUNNING]: 'progress-running',
    [TaskStatus.COMPLETED]: 'progress-completed',
    [TaskStatus.PARTIALLY_COMPLETED]: 'progress-partially-completed',
    [TaskStatus.FAILED]: 'progress-failed'
  }
  return classMap[status] || ''
}

// 截断URL显示
function truncateUrl(url: string, maxLength: number = 50): string {
  if (url.length <= maxLength) return url
  return url.substring(0, maxLength - 3) + '...'
}

// 格式化时间
function formatTime(timeStr: string): string {
  const date = new Date(timeStr)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>

<style scoped>
.ingest-task-monitor {
  padding: 16px;
  background: var(--color-background);
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  position: sticky;
  top: 0;
  z-index: 5;
  background: linear-gradient(
    to bottom,
    color-mix(in oklab, var(--color-background) 90%, transparent),
    color-mix(in oklab, var(--color-background) 70%, transparent)
  );
  backdrop-filter: saturate(140%) blur(2px);
  padding: 6px 0;
}

.task-list-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 1.1em;
  font-weight: 600;
  color: var(--color-text);
  margin: 0;
}

.clear-all-btn {
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: white;
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.85em;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(239, 68, 68, 0.2);
}

.clear-all-btn:hover {
  background: linear-gradient(135deg, #dc2626, #b91c1c);
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(239, 68, 68, 0.3);
}

.task-items {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 16px;
  transition: transform 0.15s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  box-shadow: 0 1px 2px var(--color-shadow);
}

.task-item:hover {
  transform: translateY(-1px);
  border-color: var(--color-border-light);
  box-shadow: 0 6px 16px var(--color-shadow);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.task-info h4 {
  margin: 0 0 4px 0;
  font-size: 1em;
  font-weight: 600;
  color: var(--color-text);
}

.task-url {
  font-size: 0.85em;
  color: var(--color-text-secondary);
  font-family: monospace;
}

.task-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 9999px;
  font-size: 0.85em;
  font-weight: 500;
  border: 1px solid color-mix(in oklab, currentColor 30%, transparent);
}

.status-pending { color: #f59e0b; background: #fef3c7; }
.status-running { color: #3b82f6; background: #dbeafe; }
.status-completed { color: #10b981; background: #d1fae5; }
.status-partially-completed { color: #f59e0b; background: #fef3c7; }
.status-failed { color: #ef4444; background: #fee2e2; }

.remove-btn {
  background: none;
  border: none;
  color: var(--color-text-3);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  gap: 4px;
}

.remove-btn:hover {
  color: var(--color-text);
  background: var(--color-surface-light);
}

/* 增强版关闭按钮样式 */
.remove-btn.enhanced {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
  padding: 6px 10px;
  border-radius: 5px;
  font-size: 0.8em;
  font-weight: 500;
  border: 1px solid rgba(245, 158, 11, 0.3);
  box-shadow: 0 1px 3px rgba(245, 158, 11, 0.2);
}

.remove-btn.enhanced:hover {
  background: linear-gradient(135deg, #d97706, #b45309);
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(245, 158, 11, 0.3);
  color: white;
}

.remove-text {
  font-size: 0.85em;
}

.task-progress {
  margin-bottom: 12px;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: var(--color-surface-light);
  border-radius: 6px;
  border: 1px solid var(--color-border);
  overflow: hidden;
  margin-bottom: 6px;
}

.progress-fill {
  height: 100%;
  transition: width 0.3s ease;
  border-radius: 6px;
}

.progress-pending { background: #f59e0b; }
.progress-running { 
  background: linear-gradient(90deg, #3b82f6, #1d4ed8);
  animation: progress-shimmer 2s infinite;
}
.progress-completed { background: #10b981; }
.progress-partially-completed { 
  background: linear-gradient(90deg, #10b981, #f59e0b);
}
.progress-failed { background: #ef4444; }

@keyframes progress-shimmer {
  0% { opacity: 1; }
  50% { opacity: 0.7; }
  100% { opacity: 1; }
}

.progress-text {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85em;
  color: var(--color-text-secondary);
}

.failed-count {
  color: #ef4444;
  font-weight: 500;
}

.task-details {
  border-top: 1px solid var(--color-border);
  padding-top: 12px;
  margin-top: 12px;
}

.sub-docs h5 {
  margin: 0 0 8px 0;
  font-size: 0.9em;
  color: var(--color-text-2);
}

.sub-doc-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
  padding-right: 4px;
}

.sub-doc-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 8px;
  background: var(--color-surface);
  border-radius: 6px;
  border: 1px solid var(--color-border);
  font-size: 0.85em;
}

.sub-doc-info {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.sub-doc-url {
  font-family: monospace;
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sub-doc-status {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.status-text {
  font-size: 0.8em;
}

.error-text {
  color: #ef4444;
}

.task-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
}

.expand-btn {
  background: none;
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85em;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s ease;
}

.expand-btn:hover {
  border-color: var(--color-border-light);
  color: var(--color-text);
}

.task-time {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-size: 0.75em;
  color: var(--color-text-muted);
}

.task-error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 8px;
  background: #fee2e2;
  color: #dc2626;
  border-radius: 4px;
  font-size: 0.85em;
}

.empty-state {
  text-align: center;
  padding: 40px;
  color: var(--color-text-muted);
  border: 1px dashed var(--color-border);
  border-radius: 12px;
  background: var(--color-surface);
}

.empty-state i {
  font-size: 2em;
  margin-bottom: 12px;
  display: block;
}

@media (max-width: 768px) {
  .task-header {
    flex-direction: column;
    gap: 8px;
  }

  .task-status {
    align-self: flex-start;
  }

  .task-actions {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
}
</style>
