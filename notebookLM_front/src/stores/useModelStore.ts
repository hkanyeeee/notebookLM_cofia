import { ref, reactive, watch } from 'vue'
import { notebookApi, type ModelInfo } from '../api/notebook'
import { ElMessage } from 'element-plus'

// 普通问答模式限制使用的模型
const NORMAL_CHAT_MODEL = 'openai/gpt-oss-20b'

// 从本地存储读取保存的模型选择
function getStoredSelectedModel(): string {
  try {
    return localStorage.getItem('selected_model') || ''
  } catch {
    return ''
  }
}

// 保存模型选择到本地存储
function storeSelectedModel(modelId: string) {
  try {
    localStorage.setItem('selected_model', modelId)
  } catch {
    // 忽略存储错误
  }
}

export function useModelStore() {
  // 模型相关状态
  const models = ref<ModelInfo[]>([])
  const selectedModel = ref<string>(getStoredSelectedModel())  // 从本地存储恢复模型选择
  const hasInitialized = ref<boolean>(false)  // 标记是否已初始化
  const normalChatModelError = ref<string>('') // 普通问答模式模型错误信息

  const loading = reactive({
    loadingModels: false
  })

  // 验证普通问答模式所需的模型是否存在
  function validateNormalChatModel(): boolean {
    const model = models.value.find(m => m.id === NORMAL_CHAT_MODEL)
    if (!model) {
      normalChatModelError.value = `普通问答模式所需的模型 "${NORMAL_CHAT_MODEL}" 不存在，请联系管理员配置该模型。`
      ElMessage.error(normalChatModelError.value)
      return false
    }
    normalChatModelError.value = ''
    return true
  }

  // 强制选择普通问答模式的模型
  function forceSelectNormalChatModel() {
    if (validateNormalChatModel()) {
      selectedModel.value = NORMAL_CHAT_MODEL
    }
  }

  // 监听模型选择变化，自动保存到本地存储
  watch(selectedModel, (newValue) => {
    if (newValue) {
      storeSelectedModel(newValue)
    }
  })

  // 获取可用的LLM模型列表
  async function loadModels() {
    loading.loadingModels = true
    try {
      const response = await notebookApi.getModels()
      if (response.success) {
        models.value = response.models ? response.models.filter(model => model.name.indexOf('embedding') === -1) : []
        
        // 只在第一次初始化时或者当前选择的模型不在列表中时才自动选择
        if (!hasInitialized.value || 
            (selectedModel.value && !models.value.find(m => m.id === selectedModel.value))) {
          
          if (models.value.length > 0) {
            // 如果之前保存的模型还在列表中，继续使用
            const storedModel = getStoredSelectedModel()
            if (storedModel && models.value.find(m => m.id === storedModel)) {
              selectedModel.value = storedModel
            } else {
              // 否则选择第一个模型，但只在真正需要时
              selectedModel.value = models.value[0].id
            }
          }
          hasInitialized.value = true
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
    normalChatModelError,
    
    // 方法
    loadModels,
    validateNormalChatModel,
    forceSelectNormalChatModel,
    
    // 常量
    NORMAL_CHAT_MODEL,
  }
}
