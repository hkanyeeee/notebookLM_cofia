<script setup lang="ts">
import { computed } from 'vue'
import { marked, type Token } from 'marked'
import { InfoFilled, SuccessFilled, WarningFilled, CircleCloseFilled, StarFilled } from '@element-plus/icons-vue'
import { ElIcon } from 'element-plus'

interface Props {
  token: Token
  id?: string
}

const props = defineProps<Props>()

export type AlertType = 'NOTE' | 'TIP' | 'IMPORTANT' | 'WARNING' | 'CAUTION'

export interface AlertData {
  type: AlertType
  text: string
  tokens: Token[]
}

// Alert 样式配置
const alertStyles: Record<AlertType, { border: string; text: string; bg: string; icon: any }> = {
  NOTE: {
    border: 'border-blue-500',
    text: 'text-blue-600',
    bg: 'bg-blue-50',
    icon: InfoFilled
  },
  TIP: {
    border: 'border-green-500',
    text: 'text-green-600',
    bg: 'bg-green-50',
    icon: SuccessFilled
  },
  IMPORTANT: {
    border: 'border-purple-500',
    text: 'text-purple-600',
    bg: 'bg-purple-50',
    icon: StarFilled
  },
  WARNING: {
    border: 'border-yellow-500',
    text: 'text-yellow-600',
    bg: 'bg-yellow-50',
    icon: WarningFilled
  },
  CAUTION: {
    border: 'border-red-500',
    text: 'text-red-600',
    bg: 'bg-red-50',
    icon: CircleCloseFilled
  }
}

// 解析 Alert 数据
const alertData = computed((): AlertData | null => {
  if (props.token.type !== 'blockquote') return null
  
  const regExpStr = `^(?:\\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\\])\\s*?\n*`
  const regExp = new RegExp(regExpStr)
  const matches = props.token.text?.match(regExp)

  if (matches && matches.length) {
    const alertType = matches[1] as AlertType
    const newText = props.token.text.replace(regExp, '')
    const newTokens = marked.lexer(newText)
    return {
      type: alertType,
      text: newText,
      tokens: newTokens
    }
  }
  return null
})

// 当前 Alert 的样式
const currentStyle = computed(() => {
  return alertData.value ? alertStyles[alertData.value.type] : null
})
</script>

<template>
  <div
    v-if="alertData && currentStyle"
    :class="[
      'border-l-4 pl-3 pr-3 py-2 my-2 rounded-r-lg',
      currentStyle.border,
      currentStyle.bg
    ]"
  >
    <!-- 标题栏 -->
    <div :class="['flex items-center gap-2 py-1.5 font-semibold', currentStyle.text]">
      <ElIcon :size="16">
        <component :is="currentStyle.icon" />
      </ElIcon>
      <span class="text-sm">{{ alertData.type }}</span>
    </div>
    
    <!-- 内容 -->
    <div class="pb-1 text-sm text-gray-700">
      <!-- 这里需要递归渲染 tokens，暂时先用简单文本 -->
      <div v-html="marked.parser(alertData.tokens)"></div>
    </div>
  </div>
</template>

<style scoped>
/* Alert 样式已通过 Tailwind 类实现 */
</style>

