<template>
  <el-dialog
    :model-value="visible"
    title="向量数据修复"
    :width="isMobile ? '95%' : '800px'"
    :close-on-click-modal="false"
    @update:model-value="handleVisibleUpdate"
    @close="handleClose"
    class="vector-fix-dialog-wrapper"
  >
    <div class="vector-fix-dialog">
      <!-- 加载状态 -->
      <div v-if="loading" class="text-center py-8">
        <el-icon class="animate-spin text-2xl text-blue-500 mb-2">
          <Loading />
        </el-icon>
        <p class="text-gray-600">正在加载集合状态...</p>
      </div>

      <!-- 错误状态 -->
      <div v-else-if="error" class="text-center py-8">
        <el-icon class="text-2xl text-red-500 mb-2">
          <Warning />
        </el-icon>
        <p class="text-red-600 mb-4">{{ error }}</p>
        <el-button @click="loadCollectionsStatus">重试</el-button>
      </div>

      <!-- 主要内容 -->
      <div v-else>
        <!-- 统计信息 -->
        <div v-if="collectionsStatus" class="mb-6">
          <div class="grid gap-4 mb-4" :class="isMobile ? 'grid-cols-2' : 'grid-cols-2 md:grid-cols-4'">
            <div class="bg-blue-50 p-4 rounded-lg text-center">
              <div class="text-2xl font-bold text-blue-600">{{ collectionsStatus.stats.total_collections }}</div>
              <div class="text-sm text-gray-600">总集合数</div>
            </div>
            <div class="bg-orange-50 p-4 rounded-lg text-center">
              <div class="text-2xl font-bold text-orange-600">{{ collectionsStatus.stats.needs_fix }}</div>
              <div class="text-sm text-gray-600">需要修复</div>
            </div>
            <div class="bg-green-50 p-4 rounded-lg text-center">
              <div class="text-2xl font-bold text-green-600">{{ collectionsStatus.stats.total_chunks }}</div>
              <div class="text-sm text-gray-600">总文档块数</div>
            </div>
            <div class="bg-red-50 p-4 rounded-lg text-center">
              <div class="text-2xl font-bold text-red-600">{{ collectionsStatus.stats.missing_vectors }}</div>
              <div class="text-sm text-gray-600">缺失向量数</div>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="flex gap-3 mb-6" :class="{ 'flex-col': isMobile }">
            <el-button
              type="primary"
              :disabled="collectionsStatus.stats.needs_fix === 0 || isFixing"
              :loading="isFixing"
              @click="fixAllCollections"
              :class="{ 'w-full': isMobile }"
            >
              <el-icon><Tools /></el-icon>
              修复所有集合
            </el-button>
            <el-button @click="loadCollectionsStatus" :class="{ 'w-full': isMobile }">
              <el-icon><Refresh /></el-icon>
              刷新状态
            </el-button>
          </div>
        </div>

        <!-- 修复进度 -->
        <div v-if="fixProgress" class="mb-6 p-4 bg-blue-50 rounded-lg">
          <h4 class="font-semibold mb-3 flex items-center">
            <el-icon class="animate-spin mr-2"><Loading /></el-icon>
            修复进度
          </h4>
          
          <div class="space-y-2">
            <div class="flex justify-between text-sm">
              <span>集合进度:</span>
              <span>{{ fixProgress.completed_collections }} / {{ fixProgress.total_collections }}</span>
            </div>
            <el-progress 
              :percentage="Math.round((fixProgress.completed_collections / fixProgress.total_collections) * 100)"
              :stroke-width="8"
            />
            
            <div v-if="fixProgress.total_chunks > 0" class="mt-3">
              <div class="flex justify-between text-sm">
                <span>文档块进度:</span>
                <span>{{ fixProgress.processed_chunks }} / {{ fixProgress.total_chunks }}</span>
              </div>
              <el-progress 
                :percentage="Math.round((fixProgress.processed_chunks / fixProgress.total_chunks) * 100)"
                :stroke-width="6"
                :show-text="false"
              />
            </div>

            <div v-if="fixProgress.current_collection" class="text-sm text-gray-600">
              当前处理: {{ fixProgress.current_collection }}
            </div>

            <div v-if="fixProgress.errors > 0" class="text-sm text-red-600">
              错误次数: {{ fixProgress.errors }}
            </div>
          </div>
        </div>

        <!-- 集合列表 -->
        <div v-if="collectionsStatus">
          <h4 class="font-semibold mb-3">集合详情</h4>
          
          <!-- 桌面端列表显示 -->
          <div v-if="!isMobile" class="space-y-3 max-h-96 overflow-y-auto">
            <div
              v-for="collection in collectionsStatus.collections"
              :key="collection.id"
              class="p-4 border rounded-lg hover:bg-gray-50 transition-colors"
              :class="{
                'border-red-200 bg-red-50': collection.status === 'missing',
                'border-yellow-200 bg-yellow-50': collection.status === 'partial',
                'border-green-200 bg-green-50': collection.status === 'complete'
              }"
            >
              <div class="flex items-start justify-between">
                <div class="flex-1">
                  <div class="flex items-center gap-2 mb-2">
                    <span class="text-lg">
                      {{ getStatusIcon(collection.status) }}
                    </span>
                    <h5 class="font-medium text-gray-900">{{ collection.title }}</h5>
                    <span class="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                      ID: {{ collection.id }}
                    </span>
                  </div>
                  
                  <div class="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <span class="text-gray-600">文档块数:</span>
                      <span class="font-medium ml-1">{{ collection.chunks_count }}</span>
                    </div>
                    <div>
                      <span class="text-gray-600">向量数:</span>
                      <span class="font-medium ml-1">{{ collection.qdrant_count }}</span>
                    </div>
                  </div>

                  <div class="mt-2">
                    <el-tag 
                      :type="getStatusTagType(collection.status)" 
                      size="small"
                    >
                      {{ getStatusText(collection.status) }}
                    </el-tag>
                  </div>
                </div>

                <div class="flex flex-col gap-2 ml-4">
                  <el-button
                    v-if="collection.needs_fix"
                    size="small"
                    type="primary"
                    :disabled="isFixing"
                    @click="fixSingleCollection(collection.id)"
                  >
                    修复
                  </el-button>
                  <el-button
                    size="small"
                    @click="verifyCollection(collection.id)"
                  >
                    验证
                  </el-button>
                </div>
              </div>
            </div>
          </div>

          <!-- 移动端卡片显示 -->
          <div v-else class="mobile-collection-list">
            <div 
              v-if="collectionsStatus.collections.length === 0" 
              class="empty-state"
            >
              暂无集合数据
            </div>
            <div
              v-for="collection in collectionsStatus.collections"
              :key="collection.id"
              class="mobile-collection-card"
              :class="{
                'status-missing': collection.status === 'missing',
                'status-partial': collection.status === 'partial',
                'status-complete': collection.status === 'complete'
              }"
            >
              <div class="card-header">
                <div class="collection-info">
                  <div class="collection-title">
                    <span class="status-icon">{{ getStatusIcon(collection.status) }}</span>
                    {{ collection.title }}
                  </div>
                  <div class="collection-id">ID: {{ collection.id }}</div>
                </div>
                <el-tag 
                  :type="getStatusTagType(collection.status)" 
                  size="small"
                  effect="plain"
                >
                  {{ getStatusText(collection.status) }}
                </el-tag>
              </div>
              
              <div class="card-body">
                <div class="stats-info">
                  <div class="stat-item">
                    <span class="stat-label">文档块数:</span>
                    <span class="stat-value">{{ collection.chunks_count }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">向量数:</span>
                    <span class="stat-value">{{ collection.qdrant_count }}</span>
                  </div>
                </div>
                
                <div class="card-actions">
                  <el-button
                    v-if="collection.needs_fix"
                    size="small"
                    type="primary"
                    :disabled="isFixing"
                    @click="fixSingleCollection(collection.id)"
                    class="action-button"
                  >
                    修复
                  </el-button>
                  <el-button
                    size="small"
                    @click="verifyCollection(collection.id)"
                    class="action-button"
                  >
                    验证
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer" :class="{ 'mobile-footer': isMobile }">
        <el-button @click="handleClose" :class="{ 'w-full': isMobile }">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch, computed, onMounted, onUnmounted } from 'vue'
import { 
  ElDialog, ElButton, ElIcon, ElProgress, ElTag, ElMessage
} from 'element-plus'
import { 
  Loading, Warning, Tools, Refresh
} from '@element-plus/icons-vue'
import { 
  getCollectionsStatus, 
  fixCollection, 
  fixAllCollections as fixAllCollectionsAPI,
  verifyCollection as verifyCollectionAPI,
  pollFixProgress,
  type CollectionsStatusResponse,
  type FixTaskStatus,
  type CollectionStatus
} from '../api/vector-fix'

interface Props {
  visible: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'refresh-collections'): void
}>()

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

// 处理visible状态更新
const handleVisibleUpdate = (value: boolean) => {
  emit('update:visible', value)
}

// 状态管理
const loading = ref(false)
const error = ref('')
const collectionsStatus = ref<CollectionsStatusResponse | null>(null)
const isFixing = ref(false)
const fixProgress = ref<FixTaskStatus | null>(null)

// 监听visible变化
watch(() => props.visible, (newVisible) => {
  if (newVisible) {
    loadCollectionsStatus()
  } else {
    // 重置状态
    fixProgress.value = null
    isFixing.value = false
  }
})

// 加载集合状态
const loadCollectionsStatus = async () => {
  loading.value = true
  error.value = ''
  
  try {
    collectionsStatus.value = await getCollectionsStatus()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
    console.error('加载集合状态失败:', err)
  } finally {
    loading.value = false
  }
}

// 修复单个集合
const fixSingleCollection = async (collectionId: number) => {
  try {
    isFixing.value = true
    const response = await fixCollection(collectionId)
    
    if (response.success && response.task_id) {
      ElMessage.success(response.message)
      
      // 开始轮询进度
      pollFixProgress(
        response.task_id,
        (status) => {
          fixProgress.value = status
        },
        (status) => {
          fixProgress.value = status
          isFixing.value = false
          ElMessage.success('修复完成！')
          loadCollectionsStatus()
          emit('refresh-collections')
        },
        (error) => {
          isFixing.value = false
          fixProgress.value = null
          ElMessage.error(`修复失败: ${error}`)
        }
      )
    } else {
      ElMessage.error(response.message || '修复失败')
      isFixing.value = false
    }
  } catch (err) {
    isFixing.value = false
    ElMessage.error(err instanceof Error ? err.message : '修复失败')
  }
}

// 修复所有集合
const fixAllCollections = async () => {
  try {
    isFixing.value = true
    const response = await fixAllCollectionsAPI()
    
    if (response.success && response.task_id) {
      ElMessage.success(response.message)
      
      // 开始轮询进度
      pollFixProgress(
        response.task_id,
        (status) => {
          fixProgress.value = status
        },
        (status) => {
          fixProgress.value = status
          isFixing.value = false
          ElMessage.success('修复完成！')
          loadCollectionsStatus()
          emit('refresh-collections')
        },
        (error) => {
          isFixing.value = false
          fixProgress.value = null
          ElMessage.error(`修复失败: ${error}`)
        }
      )
    } else {
      ElMessage.error(response.message || '修复失败')
      isFixing.value = false
    }
  } catch (err) {
    isFixing.value = false
    ElMessage.error(err instanceof Error ? err.message : '修复失败')
  }
}

// 验证集合
const verifyCollection = async (collectionId: number) => {
  try {
    const response = await verifyCollectionAPI(collectionId)
    
    if (response.success) {
      const result = response.result
      const statusText = getStatusText(result.status)
      const message = `集合 ${collectionId} 验证结果:\n状态: ${statusText}\n数据库文档块: ${result.db_chunks}\n向量数据: ${result.qdrant_points}`
      
      if (result.status === 'complete') {
        ElMessage.success(message)
      } else {
        ElMessage.warning(message)
      }
    } else {
      ElMessage.error('验证失败')
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '验证失败')
  }
}

// 获取状态图标
const getStatusIcon = (status: string) => {
  switch (status) {
    case 'complete': return '✅'
    case 'missing': return '❌'
    case 'partial': return '⚠️'
    default: return '❓'
  }
}

// 获取状态文本
const getStatusText = (status: string) => {
  switch (status) {
    case 'complete': return '完整'
    case 'missing': return '缺失'
    case 'partial': return '部分缺失'
    default: return '未知'
  }
}

// 获取标签类型
const getStatusTagType = (status: string) => {
  switch (status) {
    case 'complete': return 'success'
    case 'missing': return 'danger'
    case 'partial': return 'warning'
    default: return 'info'
  }
}

// 关闭对话框
const handleClose = () => {
  emit('update:visible', false)
}
</script>

<style scoped>
.vector-fix-dialog {
  min-height: 400px;
}

.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.mobile-footer {
  justify-content: center;
}

/* 移动端集合卡片样式 */
.mobile-collection-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
}

.mobile-collection-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  transition: all 0.2s ease;
}

.mobile-collection-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.mobile-collection-card.status-complete {
  border-left: 4px solid #10b981;
  background-color: #f0fdf4;
}

.mobile-collection-card.status-missing {
  border-left: 4px solid #ef4444;
  background-color: #fef2f2;
}

.mobile-collection-card.status-partial {
  border-left: 4px solid #f59e0b;
  background-color: #fffbeb;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 10px;
  gap: 8px;
}

.collection-info {
  flex: 1;
}

.collection-title {
  font-weight: 600;
  color: #111827;
  font-size: 14px;
  line-height: 1.4;
  margin-bottom: 4px;
  word-break: break-word;
}

.status-icon {
  margin-right: 6px;
}

.collection-id {
  color: #6b7280;
  font-size: 11px;
  font-family: 'Monaco', 'Menlo', monospace;
  background: #f3f4f6;
  padding: 2px 6px;
  border-radius: 4px;
  display: inline-block;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.stats-info {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}

.stat-label {
  color: #6b7280;
  font-size: 11px;
  margin-bottom: 2px;
}

.stat-value {
  color: #111827;
  font-weight: 600;
  font-size: 14px;
}

.card-actions {
  display: flex;
  gap: 8px;
  justify-content: center;
}

.action-button {
  flex: 1;
  max-width: 80px;
}

.empty-state {
  text-align: center;
  color: #9ca3af;
  padding: 40px 20px;
  font-size: 14px;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .vector-fix-dialog-wrapper :deep(.el-dialog) {
    margin: 5vh auto;
  }
  
  .vector-fix-dialog-wrapper :deep(.el-dialog__header) {
    padding: 16px 20px;
  }
  
  .vector-fix-dialog-wrapper :deep(.el-dialog__body) {
    padding: 0 20px 20px;
  }
  
  .vector-fix-dialog-wrapper :deep(.el-dialog__footer) {
    padding: 16px 20px;
  }

  .vector-fix-dialog {
    min-height: 300px;
  }
  
  /* 统计卡片适配 */
  .vector-fix-dialog .grid > div {
    padding: 12px;
  }
  
  .vector-fix-dialog .grid > div .text-2xl {
    font-size: 18px;
  }
  
  .vector-fix-dialog .grid > div .text-sm {
    font-size: 11px;
  }
}

@media (max-width: 480px) {
  .vector-fix-dialog-wrapper :deep(.el-dialog) {
    width: 95% !important;
    margin: 3vh auto;
  }
  
  .mobile-collection-card {
    padding: 10px;
  }
  
  .collection-title {
    font-size: 13px;
  }
  
  .collection-id {
    font-size: 10px;
  }
  
  .stat-label {
    font-size: 10px;
  }
  
  .stat-value {
    font-size: 13px;
  }
  
  /* 统计信息在小屏幕上堆叠显示 */
  .vector-fix-dialog .grid {
    grid-template-columns: 1fr;
    gap: 8px;
  }
  
  .vector-fix-dialog .grid > div {
    padding: 10px;
  }
  
  .vector-fix-dialog .grid > div .text-2xl {
    font-size: 16px;
  }
}
</style>
