<template>
  <div class="audio-toggle-container">
    <ElTooltip
      :content="audioEnabled ? '关闭提示音' : '开启提示音'"
      placement="bottom"
      effect="dark"
    >
      <ElButton
        text
        @click="toggleAudio"
        class="audio-toggle-btn"
        :class="{ 'audio-disabled': !audioEnabled }"
      >
        <ElIcon :class="{ 'pulsing': isToggling }">
          <component :is="currentIcon" />
        </ElIcon>
      </ElButton>
    </ElTooltip>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessageStore } from '../stores/useMessageStore'
import {
  ElButton,
  ElIcon,
  ElTooltip
} from 'element-plus'
import {
  Bell,
  MuteNotification
} from '@element-plus/icons-vue'

const messageStore = useMessageStore()
const audioEnabled = ref(true)
const isToggling = ref(false)

// 当前图标
const currentIcon = computed(() => {
  return audioEnabled.value ? Bell : MuteNotification
})

// 切换音频开关
const toggleAudio = async () => {
  isToggling.value = true
  
  try {
    audioEnabled.value = !audioEnabled.value
    messageStore.setAudioEnabled(audioEnabled.value)
    
    // 如果开启音频，尝试初始化音频管理器
    if (audioEnabled.value) {
      await messageStore.initializeAudioManager()
    }
    
    console.log(`提示音已${audioEnabled.value ? '开启' : '关闭'}`)
  } catch (error) {
    console.warn('切换音频状态时发生错误:', error)
    // 如果出错，恢复到之前的状态
    audioEnabled.value = !audioEnabled.value
  } finally {
    // 动画效果
    setTimeout(() => {
      isToggling.value = false
    }, 300)
  }
}

// 组件挂载时获取当前音频状态
onMounted(() => {
  try {
    const audioStatus = messageStore.getAudioStatus()
    audioEnabled.value = audioStatus.isEnabled
  } catch (error) {
    console.warn('获取音频状态失败:', error)
  }
})
</script>

<style scoped>
.audio-toggle-container {
  display: flex;
  align-items: center;
  justify-content: center;
}

.audio-toggle-btn {
  padding: 8px;
  border-radius: 8px;
  transition: all 0.3s ease;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  min-height: 32px;
}

.audio-toggle-btn:hover {
  background-color: var(--color-hover);
  color: var(--color-text);
}

.audio-toggle-btn.audio-disabled {
  color: var(--color-text-muted);
  opacity: 0.6;
}

.audio-toggle-btn.audio-disabled:hover {
  color: var(--color-text-secondary);
  opacity: 0.8;
}

.pulsing {
  animation: pulse 0.3s ease-in-out;
}

/* 图标居中对齐 */
.audio-toggle-btn .el-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  width: 16px;
  height: 16px;
}

@keyframes pulse {
  0% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.1);
  }
  100% {
    transform: scale(1);
  }
}

/* 音频状态指示 */
.audio-toggle-btn::after {
  content: '';
  position: absolute;
  top: 6px;
  right: 6px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--el-color-success);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.audio-toggle-btn:not(.audio-disabled)::after {
  opacity: 1;
}

/* 暗色主题适配 */
html.dark .audio-toggle-btn {
  color: var(--color-text-secondary);
}

html.dark .audio-toggle-btn:hover {
  color: var(--color-text);
  background-color: var(--color-hover);
}

html.dark .audio-toggle-btn.audio-disabled {
  color: var(--color-text-muted);
}
</style>
