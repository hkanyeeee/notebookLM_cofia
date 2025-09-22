<template>
  <div class="flex items-center justify-center gap-1">
    
    <!-- 主题选择下拉菜单 -->
    <ElDropdown
      v-if="showDropdown"
      trigger="click"
      placement="bottom-end"
      @command="handleThemeChange"
    >
      <ElButton
        text
        @click="toggleTheme"
        class="p-2 rounded-lg transition-all text-[var(--color-text-secondary)] min-w-10 min-h-10 hover:bg-[var(--color-hover)] hover:text-[var(--color-text)]"
        :class="{ 'dark-mode': themeStore.isDarkMode }"
      >
        <ElIcon :class="{ 'animate-[rotate_0.3s_ease-in-out]': isToggling }">
          <component :is="currentIcon" />
        </ElIcon>
      </ElButton>
      <template #dropdown>
        <ElDropdownMenu class="min-w-[140px]">
          <ElDropdownItem command="light" :class="{ active: themeStore.theme === 'light' }">
            <ElIcon><Sunny /></ElIcon>
            <span>浅色模式</span>
          </ElDropdownItem>
          <ElDropdownItem command="dark" :class="{ active: themeStore.theme === 'dark' }">
            <ElIcon><Moon /></ElIcon>
            <span>深色模式</span>
          </ElDropdownItem>
          <ElDropdownItem command="auto" :class="{ active: themeStore.theme === 'auto' }">
            <ElIcon><Monitor /></ElIcon>
            <span>跟随系统</span>
          </ElDropdownItem>
        </ElDropdownMenu>
      </template>
    </ElDropdown>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useThemeStore } from '../stores/theme'
import type { Theme } from '../stores/theme'
import {
  ElButton,
  ElIcon,
  ElDropdown,
  ElDropdownMenu,
  ElDropdownItem
} from 'element-plus'
import {
  Sunny,
  Moon,
  Monitor,
} from '@element-plus/icons-vue'

interface Props {
  showDropdown?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showDropdown: false
})

const themeStore = useThemeStore()
const isToggling = ref(false)

// 当前图标
const currentIcon = computed(() => {
  if (themeStore.theme === 'auto') {
    return Monitor
  }
  return themeStore.isDarkMode ? Moon : Sunny
})

// 切换主题
const toggleTheme = () => {
  if (props.showDropdown) return
  
  isToggling.value = true
  themeStore.toggleTheme()
  
  // 动画效果
  setTimeout(() => {
    isToggling.value = false
  }, 300)
}

// 处理主题变更
const handleThemeChange = (theme: Theme) => {
  isToggling.value = true
  themeStore.setTheme(theme)
  
  setTimeout(() => {
    isToggling.value = false
  }, 300)
}
</script>

<style scoped>
/* 细粒度的 el-dropdown 定制保留使用 :deep 选择器 */
:deep(.el-dropdown-menu__item) {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  transition: all 0.2s ease;
}

:deep(.el-dropdown-menu__item.active) {
  color: var(--el-color-primary);
  background-color: rgba(79, 70, 229, 0.1);
}

:deep(.el-dropdown-menu__item.active .el-icon) {
  color: var(--el-color-primary);
}

html.dark :deep(.el-dropdown-menu) {
  background-color: var(--color-surface);
  border-color: var(--color-border);
}

html.dark :deep(.el-dropdown-menu__item) {
  color: var(--color-text-secondary);
}

html.dark :deep(.el-dropdown-menu__item:hover) {
  background-color: var(--color-surface-light);
  color: var(--color-text);
}

html.dark :deep(.el-dropdown-menu__item.active) {
  color: #6366f1;
  background-color: rgba(99, 102, 241, 0.2);
}
</style>
