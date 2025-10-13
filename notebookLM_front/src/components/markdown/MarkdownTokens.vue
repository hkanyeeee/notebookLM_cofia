<script setup lang="ts">
import { computed } from 'vue'
import type { Token } from 'marked'
import { ElIcon, ElTooltip } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import MarkdownInlineTokens from './MarkdownInlineTokens.vue'
import CodeBlock from './CodeBlock.vue'
import KatexRenderer from './KatexRenderer.vue'
import HTMLToken from './HTMLToken.vue'
import AlertRenderer from './AlertRenderer.vue'
import { exportTableToCSV } from '../../utils/markdown'

interface Props {
  tokens: Token[]
  id?: string
  top?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  top: true
})

// 检查是否为 Alert 块
function isAlert(token: Token): boolean {
  if (token.type !== 'blockquote') return false
  const regExpStr = `^(?:\\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\\])`
  return new RegExp(regExpStr).test(token.text || '')
}

// 表头组件
function headerComponent(depth: number) {
  return `h${depth}`
}

// 导出表格
function handleExportTable(token: Token, tokenIdx: number) {
  exportTableToCSV(token, props.id || 'table', tokenIdx)
}
</script>

<template>
  <template v-for="(token, tokenIdx) in tokens" :key="`${id}-${tokenIdx}`">
    <!-- Horizontal Rule -->
    <hr v-if="token.type === 'hr'" class="my-4 border-gray-200 dark:border-gray-700" />

    <!-- Heading -->
    <component
      v-else-if="token.type === 'heading'"
      :is="headerComponent(token.depth)"
      class="my-3 font-semibold text-gray-900 dark:text-gray-100"
      dir="auto"
    >
      <MarkdownInlineTokens
        :tokens="token.tokens"
        :id="`${id}-${tokenIdx}-h`"
      />
    </component>

    <!-- Code Block -->
    <CodeBlock
      v-else-if="token.type === 'code' && token.raw.includes('```')"
      :id="`${id}-${tokenIdx}`"
      :lang="token.lang || ''"
      :code="token.text"
    />

    <!-- Plain Code (no fence) -->
    <pre
      v-else-if="token.type === 'code'"
      class="bg-gray-100 dark:bg-gray-800 p-3 rounded my-2 overflow-x-auto"
    ><code>{{ token.text }}</code></pre>

    <!-- Table -->
    <div v-else-if="token.type === 'table'" class="relative w-full group mb-2 overflow-x-auto">
      <table class="w-full text-sm text-left border-collapse my-2">
        <thead class="text-xs uppercase bg-gray-50 dark:bg-gray-800">
          <tr>
            <th
              v-for="(header, headerIdx) in token.header"
              :key="`${id}-${tokenIdx}-header-${headerIdx}`"
              scope="col"
              class="px-3 py-2 border-b border-gray-200 dark:border-gray-700"
              :style="token.align[headerIdx] ? `text-align: ${token.align[headerIdx]}` : ''"
            >
              <MarkdownInlineTokens
                :tokens="header.tokens"
                :id="`${id}-${tokenIdx}-header-${headerIdx}`"
              />
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, rowIdx) in token.rows"
            :key="`${id}-${tokenIdx}-row-${rowIdx}`"
            class="bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800"
          >
            <td
              v-for="(cell, cellIdx) in row"
              :key="`${id}-${tokenIdx}-row-${rowIdx}-cell-${cellIdx}`"
              class="px-3 py-2"
              :style="token.align[cellIdx] ? `text-align: ${token.align[cellIdx]}` : ''"
            >
              <MarkdownInlineTokens
                :tokens="cell.tokens"
                :id="`${id}-${tokenIdx}-row-${rowIdx}-${cellIdx}`"
              />
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Export Button -->
      <div class="absolute top-1 right-1.5 z-20 invisible group-hover:visible">
        <ElTooltip content="导出为 CSV" placement="top">
          <button
            class="p-1 rounded-lg bg-white dark:bg-gray-800 shadow-sm hover:shadow transition"
            @click.stop="handleExportTable(token, tokenIdx)"
          >
            <ElIcon :size="14"><Download /></ElIcon>
          </button>
        </ElTooltip>
      </div>
    </div>

    <!-- Blockquote / Alert -->
    <AlertRenderer
      v-else-if="token.type === 'blockquote' && isAlert(token)"
      :token="token"
      :id="`${id}-${tokenIdx}`"
    />

    <blockquote
      v-else-if="token.type === 'blockquote'"
      class="border-l-4 border-gray-300 dark:border-gray-600 pl-4 py-1 my-2 text-gray-700 dark:text-gray-300"
      dir="auto"
    >
      <MarkdownTokens
        :tokens="token.tokens"
        :id="`${id}-${tokenIdx}`"
        :top="false"
      />
    </blockquote>

    <!-- List -->
    <ol
      v-else-if="token.type === 'list' && token.ordered"
      :start="token.start || 1"
      class="list-decimal list-outside ml-6 my-2 space-y-1"
      dir="auto"
    >
      <li
        v-for="(item, itemIdx) in token.items"
        :key="`${id}-${tokenIdx}-${itemIdx}`"
        class="text-start"
      >
        <MarkdownTokens
          :tokens="item.tokens"
          :id="`${id}-${tokenIdx}-${itemIdx}`"
          :top="token.loose"
        />
      </li>
    </ol>

    <ul
      v-else-if="token.type === 'list' && !token.ordered"
      class="list-disc list-outside ml-6 my-2 space-y-1"
      dir="auto"
    >
      <li
        v-for="(item, itemIdx) in token.items"
        :key="`${id}-${tokenIdx}-${itemIdx}`"
        class="text-start"
        :class="{ 'flex gap-2': item.task }"
      >
        <input
          v-if="item.task"
          type="checkbox"
          :checked="item.checked"
          class="mt-1"
          disabled
        />
        <MarkdownTokens
          :tokens="item.tokens"
          :id="`${id}-${tokenIdx}-${itemIdx}`"
          :top="token.loose"
        />
      </li>
    </ul>

    <!-- HTML -->
    <HTMLToken
      v-else-if="token.type === 'html'"
      :token="token"
      :id="`${id}-${tokenIdx}`"
    />

    <!-- Paragraph -->
    <p
      v-else-if="token.type === 'paragraph'"
      class="my-2"
      dir="auto"
    >
      <MarkdownInlineTokens
        :tokens="token.tokens"
        :id="`${id}-${tokenIdx}-p`"
      />
    </p>

    <!-- Text (top-level or nested) -->
    <p v-else-if="token.type === 'text' && top" class="my-2">
      <MarkdownInlineTokens
        v-if="token.tokens"
        :tokens="token.tokens"
        :id="`${id}-${tokenIdx}-t`"
      />
      <template v-else>{{ token.text }}</template>
    </p>

    <MarkdownInlineTokens
      v-else-if="token.type === 'text' && token.tokens"
      :tokens="token.tokens"
      :id="`${id}-${tokenIdx}-p`"
    />

    <template v-else-if="token.type === 'text'">
      {{ token.text }}
    </template>

    <!-- Block KaTeX -->
    <KatexRenderer
      v-else-if="token.type === 'blockKatex' && token.text"
      :content="token.text"
      :display-mode="true"
    />

    <!-- Inline KaTeX (fallback) -->
    <KatexRenderer
      v-else-if="token.type === 'inlineKatex' && token.text"
      :content="token.text"
      :display-mode="false"
    />

    <!-- Space -->
    <div v-else-if="token.type === 'space'" class="my-2" />

    <!-- Unknown Token (Debug) -->
    <template v-else>
      <!-- {{ console.log('Unknown token:', token) }} -->
    </template>
  </template>
</template>

<style scoped>
/* 样式主要通过 Tailwind 类实现 */
</style>

