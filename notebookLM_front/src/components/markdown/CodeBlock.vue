<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElIcon } from 'element-plus'
import { DocumentCopy, Check } from '@element-plus/icons-vue'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-light.css'

interface Props {
  lang: string
  code: string
  id?: string
}

const props = defineProps<Props>()

const copied = ref(false)
const highlightedCode = ref('')

// 语言标签显示
const displayLang = computed(() => {
  if (!props.lang) return 'text'
  return props.lang.toLowerCase()
})

onMounted(() => {
  highlightCode()
})

// 监听 code 和 lang 的变化，重新高亮
watch(() => [props.code, props.lang], () => {
  highlightCode()
}, { immediate: true })

function highlightCode() {
  if (!props.code) {
    highlightedCode.value = ''
    return
  }

  try {
    if (props.lang && hljs.getLanguage(props.lang)) {
      highlightedCode.value = hljs.highlight(props.code, { language: props.lang }).value
    } else {
      highlightedCode.value = hljs.highlightAuto(props.code).value
    }
  } catch (error) {
    console.warn('Highlight error:', error)
    // 如果高亮失败，直接显示原始代码
    highlightedCode.value = escapeHtml(props.code)
  }
}

function escapeHtml(text: string): string {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(props.code)
    copied.value = true
    ElMessage.success('代码已复制')
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (error) {
    ElMessage.error('复制失败')
  }
}
</script>

<template>
  <div class="code-block-wrapper group relative my-2">
    <!-- 顶部栏：语言标签和复制按钮 -->
    <div class="code-header flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-gray-800 rounded-t-lg border-b border-gray-200 dark:border-gray-700">
      <span class="text-xs text-gray-600 dark:text-gray-400 font-mono">{{ displayLang }}</span>
      <button
        @click="copyCode"
        class="copy-btn flex items-center gap-1 px-2 py-1 text-xs text-gray-600 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors rounded"
        :class="{ 'text-green-600 dark:text-green-400': copied }"
      >
        <ElIcon v-if="!copied"><DocumentCopy /></ElIcon>
        <ElIcon v-else><Check /></ElIcon>
        <span>{{ copied ? '已复制' : '复制' }}</span>
      </button>
    </div>
    
    <!-- 代码内容 -->
    <pre class="code-content m-0 p-4 overflow-x-auto bg-gray-50 dark:bg-gray-800 rounded-b-lg"><code v-html="highlightedCode" class="hljs"></code></pre>
  </div>
</template>

<style scoped>
.code-block-wrapper {
  margin: 1rem 0;
  border-radius: 0.5rem;
  overflow: hidden;
  border: 1px solid #e5e7eb;
}

html.dark .code-block-wrapper {
  border-color: #374151;
}

.code-content {
  margin: 0;
  padding: 1rem;
  overflow-x: auto;
}

.code-content code {
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  line-height: 1.5;
}

.copy-btn {
  opacity: 0.7;
}

.copy-btn:hover {
  opacity: 1;
  background-color: rgba(79, 70, 229, 0.1);
}

/* 自定义滚动条 */
.code-content::-webkit-scrollbar {
  height: 8px;
}

.code-content::-webkit-scrollbar-track {
  background: #f3f4f6;
}

.code-content::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 4px;
}

.code-content::-webkit-scrollbar-thumb:hover {
  background: #9ca3af;
}

/* 暗色模式滚动条 */
html.dark .code-content::-webkit-scrollbar-track {
  background: #1f2937;
}

html.dark .code-content::-webkit-scrollbar-thumb {
  background: #4b5563;
}

html.dark .code-content::-webkit-scrollbar-thumb:hover {
  background: #6b7280;
}
</style>

