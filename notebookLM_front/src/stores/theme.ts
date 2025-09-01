import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export type Theme = 'light' | 'dark' | 'auto'

export const useThemeStore = defineStore('theme', () => {
  // 主题状态
  const theme = ref<Theme>('auto')
  const isDarkMode = ref(false)

  // 从 localStorage 加载保存的主题设置
  const loadTheme = () => {
    const savedTheme = localStorage.getItem('theme') as Theme
    if (savedTheme && ['light', 'dark', 'auto'].includes(savedTheme)) {
      theme.value = savedTheme
    } else {
      theme.value = 'auto'
    }
    updateTheme()
  }

  // 检测系统主题偏好
  const getSystemTheme = (): boolean => {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  }

  // 更新主题
  const updateTheme = () => {
    let shouldBeDark = false

    if (theme.value === 'dark') {
      shouldBeDark = true
    } else if (theme.value === 'light') {
      shouldBeDark = false
    } else {
      shouldBeDark = getSystemTheme()
    }

    isDarkMode.value = shouldBeDark
    document.documentElement.classList.toggle('dark', shouldBeDark)
  }

  // 设置主题
  const setTheme = (newTheme: Theme) => {
    theme.value = newTheme
    localStorage.setItem('theme', newTheme)
    updateTheme()
  }

  // 切换主题（在 light 和 dark 之间切换）
  const toggleTheme = () => {
    if (theme.value === 'dark') {
      setTheme('light')
    } else {
      setTheme('dark')
    }
  }

  // 监听系统主题变化
  const setupSystemThemeListener = () => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    
    const handleSystemThemeChange = () => {
      if (theme.value === 'auto') {
        updateTheme()
      }
    }

    mediaQuery.addEventListener('change', handleSystemThemeChange)

    // 返回清理函数
    return () => {
      mediaQuery.removeEventListener('change', handleSystemThemeChange)
    }
  }

  // 监听主题变化
  watch(theme, updateTheme)

  // 初始化主题系统
  const initTheme = () => {
    loadTheme()
    return setupSystemThemeListener()
  }

  return {
    theme,
    isDarkMode,
    setTheme,
    toggleTheme,
    initTheme,
    updateTheme
  }
})
