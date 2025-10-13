<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import type katex from 'katex'

interface Props {
  content: string
  displayMode?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  displayMode: false
})

const htmlContent = ref<string>('')
const renderToString = ref<typeof katex.renderToString | null>(null)

onMounted(async () => {
  try {
    // 动态加载 KaTeX
    const [katexModule] = await Promise.all([
      import('katex'),
      import('katex/contrib/mhchem'),
      import('katex/dist/katex.min.css')
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

