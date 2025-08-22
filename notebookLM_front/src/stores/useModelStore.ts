import { ref, reactive } from 'vue'
import { notebookApi, type ModelInfo } from '../api/notebook'

export function useModelStore() {
  // 模型相关状态
  const models = ref<ModelInfo[]>([])
  const selectedModel = ref<string>('')  // 当前选中的模型ID

  const loading = reactive({
    loadingModels: false
  })

  // 获取可用的LLM模型列表
  async function loadModels() {
    loading.loadingModels = true
    try {
      const response = await notebookApi.getModels()
      if (response.success) {
        models.value = response.models ? response.models.filter(model => model.name.indexOf('embedding') === -1) : []
        // 如果还没有选择模型且有可用模型，选择第一个
        if (!selectedModel.value && models.value.length > 0) {
          selectedModel.value = models.value[0].id
        }
      } else {
        console.error('获取模型列表失败')
        models.value = []
      }
    } catch (error) {
      console.error('获取模型列表出错:', error)
      models.value = []
    } finally {
      loading.loadingModels = false
    }
  }

  return {
    // 状态
    models,
    selectedModel,
    loading,
    
    // 方法
    loadModels,
  }
}
