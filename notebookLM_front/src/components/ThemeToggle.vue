<template>
  <div class="theme-toggle-container">
    
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
        class="theme-toggle-btn"
        :class="{ 'dark-mode': themeStore.isDarkMode }"
      >
        <ElIcon :class="{ 'rotating': isToggling }">
          <component :is="currentIcon" />
        </ElIcon>
      </ElButton>
      <template #dropdown>
        <ElDropdownMenu class="theme-dropdown-menu">
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
.theme-toggle-container {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.theme-toggle-btn,
.theme-dropdown-btn {
  padding: 8px;
  border-radius: 8px;
  transition: all 0.3s ease;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 40px;
  min-height: 40px;
}

.theme-toggle-btn:hover,
.theme-dropdown-btn:hover {
  background-color: var(--color-hover);
  color: var(--color-text);
}

.theme-toggle-btn.dark-mode,
.theme-dropdown-btn.dark-mode {
  color: var(--color-text-secondary);
}

.theme-toggle-btn.dark-mode:hover,
.theme-dropdown-btn.dark-mode:hover {
  color: var(--color-text);
  background-color: var(--color-hover);
}

.rotating {
  animation: rotate 0.3s ease-in-out;
}

/* 图标居中对齐 */
.theme-toggle-btn .el-icon,
.theme-dropdown-btn .el-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  width: 16px;
  height: 16px;
}

@keyframes rotate {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(180deg);
  }
}

/* Dropdown menu styles */
:deep(.theme-dropdown-menu) {
  min-width: 140px;
}

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

/* Dark mode dropdown styles */
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
