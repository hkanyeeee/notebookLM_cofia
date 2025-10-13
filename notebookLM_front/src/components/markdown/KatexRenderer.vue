<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'

interface Props {
  content: string
  displayMode?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  displayMode: false
})

const htmlContent = ref<string>('')
const renderToString = ref<((tex: string, options?: any) => string) | null>(null)

onMounted(async () => {
  try {
    // 动态加载 KaTeX
    const [katexModule] = await Promise.all([
      import('katex') as Promise<any>,
      import('katex/contrib/mhchem') as Promise<any>,
      import('katex/dist/katex.min.css') as Promise<any>
    ])
    renderToString.value = katexModule.default.renderToString
    render()
  } catch (error) {
    console.error('Failed to load KaTeX:', error)
  }
})

watch(() => [props.content, props.displayMode], () => {
  if (renderToString.value) {
    render()
  }
})

function render() {
  if (!renderToString.value || !props.content) return
  try {
    htmlContent.value = renderToString.value(props.content, {
      displayMode: props.displayMode,
      throwOnError: false
    })
  } catch (error) {
    console.error('KaTeX render error:', error)
    htmlContent.value = props.content
  }
}
</script>

<template>
  <span v-if="htmlContent" v-html="htmlContent"></span>
</template>

<style scoped>
/* KaTeX 渲染的内容样式在全局 CSS 中定义 */
</style>

