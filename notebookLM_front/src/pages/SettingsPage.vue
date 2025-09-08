<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { notebookApi } from '@/api/notebook'

// 配置项类型定义
interface ConfigItem {
  key: string
  value: string | number | boolean
  type: 'string' | 'integer' | 'float' | 'boolean'
  description: string
  default_value: string
  is_hot_reload: boolean
}

// 配置数据
const configData = ref<Record<string, ConfigItem>>({})
const configForm = ref<Record<string, any>>({}) // 用于表单绑定的数据
const loading = ref(false)
const saving = ref(false)

/**
 * 获取所有配置项
 */
const fetchConfigs = async () => {
  loading.value = true
  try {
    const response = await notebookApi.getAppConfig()
    if (response.success && response.config) {
      configData.value = response.config
      
      // 初始化表单数据
      const formValues: Record<string, any> = {}
      Object.keys(response.config).forEach(key => {
        formValues[key] = response.config[key].value
      })
      configForm.value = formValues
    } else {
      ElMessage.error('获取配置失败')
    }
  } catch (error) {
    console.error('获取配置失败:', error)
    ElMessage.error('获取配置失败')
  } finally {
    loading.value = false
  }
}

/**
 * 保存配置项
 */
const saveConfig = async () => {
  saving.value = true
  try {
    // 构造要保存的配置数据
    const configToSave: Record<string, any> = {}
    Object.keys(configForm.value).forEach(key => {
      const item = configData.value[key]
      if (item) {
        // 根据类型转换值
        if (item.type === 'integer') {
          configToSave[key] = parseInt(configForm.value[key] as string) || 0
        } else if (item.type === 'float') {
          configToSave[key] = parseFloat(configForm.value[key] as string) || 0
        } else if (item.type === 'boolean') {
          configToSave[key] = configForm.value[key] === true || configForm.value[key] === 'true'
        } else {
          configToSave[key] = configForm.value[key]
        }
      }
    })
    
    const response = await notebookApi.saveAppConfig(configToSave)
    
    if (response.success) {
      ElMessage.success('配置保存成功')
      // 重新加载配置以确保显示最新值
      await fetchConfigs()
    } else {
      ElMessage.error(response.message || '保存失败')
    }
  } catch (error) {
    console.error('保存配置失败:', error)
    ElMessage.error('保存配置失败')
  } finally {
    saving.value = false
  }
}

/**
 * 重置为默认配置
 */
const resetToDefault = async () => {
  try {
    await ElMessageBox.confirm(
      '确定要将所有配置重置为默认值吗？此操作不可撤销。',
      '确认重置',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    
    const response = await notebookApi.resetAppConfig()
    if (response.success) {
      ElMessage.success('配置已重置为默认值')
      // 重新加载配置
      await fetchConfigs()
    } else {
      ElMessage.error(response.message || '重置失败')
    }
  } catch (error) {
    // 用户取消了操作
    console.log('用户取消了重置操作')
  }
}

/**
 * 验证配置
 */
const validateConfig = async () => {
  try {
    const response = await notebookApi.validateAppConfig()
    if (response.success) {
      if (response.valid) {
        ElMessage.success('配置验证通过')
      } else {
        ElMessage.warning('配置存在一些问题：' + response.errors.join(', '))
      }
    } else {
      ElMessage.error('验证失败')
    }
  } catch (error) {
    console.error('验证配置失败:', error)
    ElMessage.error('验证配置失败')
  }
}

// 监听 configData 的变化，同步更新表单数据
watch(configData, () => {
  const formValues: Record<string, any> = {}
  Object.keys(configData.value).forEach(key => {
    formValues[key] = configData.value[key].value
  })
  configForm.value = formValues
}, { immediate: true })

// 组件挂载时获取配置
onMounted(() => {
  fetchConfigs()
})
</script>

<template>
  <div class="settings-page">
    <div class="settings-header">
      <h2>系统设置</h2>
      <p>管理应用程序的各种配置选项</p>
    </div>

    <div class="settings-content">
      <!-- 加载状态 -->
      <div v-if="loading" class="loading-container">
        <el-skeleton :rows="10" animated />
      </div>

      <!-- 配置表单 -->
      <div v-else class="config-form">
        <el-alert
          title="配置热更新"
          type="info"
          description="修改后端配置将实时生效，无需重启服务。部分配置可能需要重启相关服务才能完全生效。"
          show-icon
          class="config-info-alert"
        />

        <!-- 文档处理设置 -->
        <div class="config-section">
          <h3>文档处理设置</h3>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="分块大小 (chunk_size)">
                <el-input 
                  v-model.number="configForm.chunk_size" 
                  type="number"
                  placeholder="文档分块大小"
                />
                <div class="config-description">{{ configData.chunk_size?.description }}</div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="分块重叠大小 (chunk_overlap)">
                <el-input 
                  v-model.number="configForm.chunk_overlap" 
                  type="number"
                  placeholder="分块重叠大小"
                />
                <div class="config-description">{{ configData.chunk_overlap?.description }}</div>
              </el-form-item>
            </el-col>
          </el-row>
          
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="默认嵌入模型 (default_embedding_model)">
                <el-input 
                  v-model="configForm.default_embedding_model" 
                  placeholder="默认嵌入模型名称"
                />
                <div class="config-description">{{ configData.default_embedding_model?.description }}</div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="嵌入维度 (embedding_dimensions)">
                <el-input 
                  v-model.number="configForm.embedding_dimensions" 
                  type="number"
                  placeholder="嵌入向量维度数"
                />
                <div class="config-description">{{ configData.embedding_dimensions?.description }}</div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 搜索功能设置 -->
        <div class="config-section">
          <h3>搜索功能设置</h3>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="RAG Top K (rag_top_k)">
                <el-input 
                  v-model.number="configForm.rag_top_k" 
                  type="number"
                  placeholder="RAG召回Top K"
                />
                <div class="config-description">{{ configData.rag_top_k?.description }}</div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="查询前重排序 (query_top_k_before_rerank)">
                <el-input 
                  v-model.number="configForm.query_top_k_before_rerank" 
                  type="number"
                  placeholder="重排序前查询Top K"
                />
                <div class="config-description">{{ configData.query_top_k_before_rerank?.description }}</div>
              </el-form-item>
            </el-col>
          </el-row>
          
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="重排序后保留 (rag_rerank_top_k)">
                <el-input 
                  v-model.number="configForm.rag_rerank_top_k" 
                  type="number"
                  placeholder="重排序后保留Top K"
                />
                <div class="config-description">{{ configData.rag_rerank_top_k?.description }}</div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="网络搜索结果数量 (web_search_result_count)">
                <el-input 
                  v-model.number="configForm.web_search_result_count" 
                  type="number"
                  placeholder="网络搜索结果数量"
                />
                <div class="config-description">{{ configData.web_search_result_count?.description }}</div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 系统集成设置 -->
        <div class="config-section">
          <h3>系统集成设置</h3>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="LLM服务地址 (llm_service_url)">
                <el-input 
                  v-model="configForm.llm_service_url" 
                  placeholder="LLM服务URL"
                />
                <div class="config-description">{{ configData.llm_service_url?.description }}</div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="嵌入服务地址 (embedding_service_url)">
                <el-input 
                  v-model="configForm.embedding_service_url" 
                  placeholder="嵌入服务URL"
                />
                <div class="config-description">{{ configData.embedding_service_url?.description }}</div>
              </el-form-item>
            </el-col>
          </el-row>
          
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="Qdrant地址 (qdrant_url)">
                <el-input 
                  v-model="configForm.qdrant_url" 
                  placeholder="Qdrant服务URL"
                />
                <div class="config-description">{{ configData.qdrant_url?.description }}</div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Searxng地址 (searxng_query_url)">
                <el-input 
                  v-model="configForm.searxng_query_url" 
                  placeholder="Searxng搜索引擎URL"
                />
                <div class="config-description">{{ configData.searxng_query_url?.description }}</div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 工具功能设置 -->
        <div class="config-section">
          <h3>工具功能设置</h3>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="默认工具模式 (default_tool_mode)">
                <el-select 
                  v-model="configForm.default_tool_mode" 
                  placeholder="选择默认工具模式"
                >
                  <el-option label="关闭 (off)" value="off" />
                  <el-option label="自动 (auto)" value="auto" />
                  <el-option label="JSON函数调用 (json)" value="json" />
                  <el-option label="ReAct (react)" value="react" />
                  <el-option label="Harmony (harmony)" value="harmony" />
                </el-select>
                <div class="config-description">{{ configData.default_tool_mode?.description }}</div>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="最大工具步骤数 (max_tool_steps)">
                <el-input 
                  v-model.number="configForm.max_tool_steps" 
                  type="number"
                  placeholder="最大工具调用步数"
                />
                <div class="config-description">{{ configData.max_tool_steps?.description }}</div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 操作按钮 -->
        <div class="action-buttons">
          <el-button 
            type="primary" 
            @click="saveConfig" 
            :loading="saving"
            size="large"
          >
            保存配置
          </el-button>
          <el-button 
            @click="resetToDefault" 
            type="warning"
            size="large"
          >
            重置为默认值
          </el-button>
          <el-button 
            @click="validateConfig" 
            type="info"
            size="large"
          >
            验证配置
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  padding: 20px;
  height: 100%;
  overflow-y: auto;
}

.settings-header {
  margin-bottom: 30px;
}

.settings-header h2 {
  margin: 0 0 10px 0;
  color: var(--el-text-color-primary);
}

.settings-header p {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.config-section {
  margin-bottom: 30px;
  padding: 20px;
  border-radius: 8px;
  background-color: var(--el-bg-color-overlay);
}

.config-section h3 {
  margin-top: 0;
  margin-bottom: 20px;
  color: var(--el-text-color-primary);
}

.config-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 5px;
}

.action-buttons {
  display: flex;
  gap: 15px;
  margin-top: 30px;
  padding-top: 20px;
  border-top: 1px solid var(--el-border-color);
}

.loading-container {
  min-height: 400px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.config-info-alert {
  margin-bottom: 20px;
}
</style>