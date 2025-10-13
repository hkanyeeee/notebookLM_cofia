<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import DOMPurify from 'dompurify'
import type { Token } from 'marked'

interface Props {
  token: Token
  id?: string
}

const props = defineProps<Props>()

const sanitizedHtml = ref<string>('')

onMounted(() => {
  if (props.token.type === 'html' && props.token.text) {
    sanitizedHtml.value = DOMPurify.sanitize(props.token.text)
  }
})

// 检测是否包含特定 HTML 标签
const isVideo = computed(() => sanitizedHtml.value.includes('<video'))
const isAudio = computed(() => sanitizedHtml.value.includes('<audio'))
const isYouTube = computed(() => sanitizedHtml.value.includes('youtube.com/embed'))
const isIframe = computed(() => sanitizedHtml.value.includes('<iframe'))
const isStatus = computed(() => sanitizedHtml.value.includes('<status'))
const isBr = computed(() => sanitizedHtml.value.match(/<br\s*\/?>/) !== null)

// 提取 video src
const videoSrc = computed(() => {
  const match = sanitizedHtml.value.match(/<video[^>]*>([\s\S]*?)<\/video>/)
  return match ? match[1].replaceAll('&amp;', '&') : null
})

// 提取 audio src
const audioSrc = computed(() => {
  const match = sanitizedHtml.value.match(/<audio[^>]*>([\s\S]*?)<\/audio>/)
  return match ? match[1].replaceAll('&amp;', '&') : null
})

// 提取 YouTube ID
const youtubeId = computed(() => {
  const match = sanitizedHtml.value.match(
    /<iframe\s+[^>]*src="https:\/\/www\.youtube\.com\/embed\/([a-zA-Z0-9_-]{11})(?:\?[^"]*)?"[^>]*><\/iframe>/
  )
  return match ? match[1] : null
})

// 提取通用 iframe src
const iframeSrc = computed(() => {
  const match = sanitizedHtml.value.match(/<iframe\s+[^>]*src="([^"]+)"[^>]*><\/iframe>/)
  return match ? match[1] : null
})

// 提取 status 信息
const statusInfo = computed(() => {
  const match = sanitizedHtml.value.match(/<status title="([^"]+)" done="(true|false)" ?\/>/)
  if (match) {
    return {
      title: match[1],
      done: match[2] === 'true'
    }
  }
  return null
})
</script>

<template>
  <template v-if="token.type === 'html'">
    <!-- Video -->
    <video
      v-if="isVideo && videoSrc"
      class="w-full my-2"
      :src="videoSrc"
      title="Video player"
      controls
      referrerpolicy="strict-origin-when-cross-origin"
    ></video>

    <!-- Audio -->
    <audio
      v-else-if="isAudio && audioSrc"
      class="w-full my-2"
      :src="audioSrc"
      title="Audio player"
      controls
    ></audio>

    <!-- YouTube Embed -->
    <iframe
      v-else-if="isYouTube && youtubeId"
      class="w-full aspect-video my-2 rounded-lg"
      :src="`https://www.youtube.com/embed/${youtubeId}`"
      title="YouTube video player"
      frameborder="0"
      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
      referrerpolicy="strict-origin-when-cross-origin"
      allowfullscreen
    ></iframe>

    <!-- Generic Iframe -->
    <iframe
      v-else-if="isIframe && iframeSrc && !isYouTube"
      class="w-full my-2 rounded-lg"
      :src="iframeSrc"
      title="Embedded content"
      frameborder="0"
      sandbox="allow-scripts allow-downloads"
      referrerpolicy="strict-origin-when-cross-origin"
      style="min-height: 400px;"
    ></iframe>

    <!-- Status Message -->
    <div
      v-else-if="isStatus && statusInfo"
      class="flex flex-col justify-center -space-y-0.5"
    >
      <div
        :class="[
          'text-gray-500 dark:text-gray-400 line-clamp-1 text-wrap',
          { 'shimmer': !statusInfo.done }
        ]"
      >
        {{ statusInfo.title }}
      </div>
    </div>

    <!-- Line Break -->
    <br v-else-if="isBr" />

    <!-- Fallback: 直接渲染纯文本 -->
    <span v-else>{{ token.text }}</span>
  </template>
</template>

<style scoped>
/* Shimmer 动画用于加载状态 */
.shimmer {
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0) 0%,
    rgba(255, 255, 255, 0.2) 50%,
    rgba(255, 255, 255, 0) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
}

@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}
</style>

