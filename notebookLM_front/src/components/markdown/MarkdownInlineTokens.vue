<script setup lang="ts">
import { computed } from 'vue'
import type { Token } from 'marked'
import { unescapeHtml } from '../../utils/markdown'
import KatexRenderer from './KatexRenderer.vue'
import HTMLToken from './HTMLToken.vue'

interface Props {
  tokens: Token[]
  id?: string
}

const props = defineProps<Props>()
</script>

<template>
  <template v-for="(token, idx) in tokens" :key="`${id}-inline-${idx}`">
    <!-- Escape -->
    <template v-if="token.type === 'escape'">
      {{ unescapeHtml(token.text) }}
    </template>

    <!-- HTML Token -->
    <HTMLToken
      v-else-if="token.type === 'html'"
      :token="token"
      :id="`${id}-html-${idx}`"
    />

    <!-- Link -->
    <a
      v-else-if="token.type === 'link'"
      :href="token.href"
      :title="token.title"
      target="_blank"
      rel="nofollow noopener noreferrer"
      class="text-indigo-600 hover:underline"
    >
      <MarkdownInlineTokens
        v-if="token.tokens"
        :tokens="token.tokens"
        :id="`${id}-link-${idx}`"
      />
      <template v-else>{{ token.text }}</template>
    </a>

    <!-- Image -->
    <img
      v-else-if="token.type === 'image'"
      :src="token.href"
      :alt="token.text"
      :title="token.title"
      class="max-w-full h-auto my-2 rounded-lg"
      loading="lazy"
      referrerpolicy="no-referrer"
    />

    <!-- Strong (Bold) -->
    <strong v-else-if="token.type === 'strong'">
      <MarkdownInlineTokens
        :tokens="token.tokens"
        :id="`${id}-strong-${idx}`"
      />
    </strong>

    <!-- Em (Italic) -->
    <em v-else-if="token.type === 'em'">
      <MarkdownInlineTokens
        :tokens="token.tokens"
        :id="`${id}-em-${idx}`"
      />
    </em>

    <!-- Codespan (Inline Code) -->
    <code
      v-else-if="token.type === 'codespan'"
      class="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-sm font-mono text-red-600 dark:text-red-400"
    >
      {{ token.text }}
    </code>

    <!-- Line Break -->
    <br v-else-if="token.type === 'br'" />

    <!-- Del (Strikethrough) -->
    <del v-else-if="token.type === 'del'">
      <MarkdownInlineTokens
        :tokens="token.tokens"
        :id="`${id}-del-${idx}`"
      />
    </del>

    <!-- Inline KaTeX -->
    <KatexRenderer
      v-else-if="token.type === 'inlineKatex' && token.text"
      :content="token.text"
      :display-mode="false"
    />

    <!-- Text -->
    <template v-else-if="token.type === 'text'">
      <MarkdownInlineTokens
        v-if="token.tokens"
        :tokens="token.tokens"
        :id="`${id}-text-${idx}`"
      />
      <template v-else>{{ unescapeHtml(token.text) }}</template>
    </template>

    <!-- Fallback -->
    <template v-else>
      {{ token.text || '' }}
    </template>
  </template>
</template>

<style scoped>
/* 样式通过 Tailwind 类实现 */
</style>

