<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatArea from './components/ChatArea.vue'
import { useSessionStore } from './stores/session'
import { useThemeStore } from './stores/theme'
import { useNotebookStore, QueryType } from './stores/notebook'
import { cleanupSession } from './api/notebook'
import { ElButton, ElIcon } from 'element-plus'
import { Menu } from '@element-plus/icons-vue'

const sidebarCollapsed = ref(false)
const mobileMenuOpen = ref(false) // 移动端侧边栏显示状态
const sessionStore = useSessionStore()
const themeStore = useThemeStore()
const notebookStore = useNotebookStore()

// 检查是否为移动端
const isMobile = ref(window.innerWidth <= 768)

// 折叠的响应式阈值（小屏默认折叠）
const COLLAPSE_BREAKPOINT = 1024
const isSmallScreen = ref(window.innerWidth <= COLLAPSE_BREAKPOINT)

// 仅在跨越阈值时，才根据屏幕大小自动切换折叠状态，避免覆盖用户手动操作
const syncCollapseWithScreen = () => {
  const newIsSmall = window.innerWidth <= COLLAPSE_BREAKPOINT
  if (newIsSmall !== isSmallScreen.value) {
    // 小屏一律折叠；大屏根据当前问答模式设置默认展开/收起
    if (newIsSmall) {
      sidebarCollapsed.value = true
    } else {
      applySidebarByMode()
    }
    isSmallScreen.value = newIsSmall
  }
}

// 根据当前问答模式设置桌面端侧边栏：
// - 普通/Collection：收起
// - 文档：展开
const applySidebarByMode = () => {
  if (isMobile.value) return
  const type = notebookStore.queryType
  const currentType = typeof type === 'object' && 'value' in type ? (type as any).value : type
  if (currentType === QueryType.DOCUMENT) {
    sidebarCollapsed.value = false
  } else {
    sidebarCollapsed.value = true
  }
}

// 模式切换时在桌面端联动侧边栏展开/收起
watch(
  () => notebookStore.queryType,
  () => {
    if (!isSmallScreen.value) {
      applySidebarByMode()
    }
  }
)

// 拖拽相关状态
const isDragging = ref(false)
const buttonPosition = ref({ 
  bottom: 200, 
  right: 20 
})
const dragStart = ref({ x: 0, y: 0 })

// 处理窗口大小变化
const handleResize = () => {
  isMobile.value = window.innerWidth <= 768
  // 当从移动端切换到桌面端时，关闭移动端菜单
  if (!isMobile.value) {
    mobileMenuOpen.value = false
  }
  // 根据屏幕大小变化自动同步折叠状态（仅在跨越阈值时生效）
  syncCollapseWithScreen()
}

// 切换移动端侧边栏
const toggleMobileSidebar = () => {
  if (!isDragging.value) {
    mobileMenuOpen.value = !mobileMenuOpen.value
  }
}

// 拖拽开始
const handleTouchStart = (e: TouchEvent) => {
  isDragging.value = false
  const touch = e.touches[0]
  dragStart.value = { x: touch.clientX, y: touch.clientY }
}

// 拖拽过程
const handleTouchMove = (e: TouchEvent) => {
  e.preventDefault()
  const touch = e.touches[0]
  const deltaX = dragStart.value.x - touch.clientX
  const deltaY = dragStart.value.y - touch.clientY
  
  // 判断是否开始拖拽（移动距离超过阈值）
  if (!isDragging.value && (Math.abs(deltaX) > 10 || Math.abs(deltaY) > 10)) {
    isDragging.value = true
  }
  
  if (isDragging.value) {
    // 更新按钮位置，确保不超出屏幕边界
    const windowWidth = window.innerWidth
    const windowHeight = window.innerHeight
    const buttonSize = 48
    
    let newRight = buttonPosition.value.right + deltaX
    let newBottom = buttonPosition.value.bottom + deltaY
    
    // 边界检查
    newRight = Math.max(10, Math.min(windowWidth - buttonSize - 10, newRight))
    newBottom = Math.max(10, Math.min(windowHeight - buttonSize - 10, newBottom))
    
    buttonPosition.value = { right: newRight, bottom: newBottom }
    dragStart.value = { x: touch.clientX, y: touch.clientY }
  }
}

// 拖拽结束
const handleTouchEnd = () => {
  setTimeout(() => {
    isDragging.value = false
  }, 100)
}

// 鼠标拖拽支持
const handleMouseStart = (e: MouseEvent) => {
  isDragging.value = false
  dragStart.value = { x: e.clientX, y: e.clientY }
  document.addEventListener('mousemove', handleMouseMove)
  document.addEventListener('mouseup', handleMouseEnd)
}

const handleMouseMove = (e: MouseEvent) => {
  const deltaX = dragStart.value.x - e.clientX
  const deltaY = dragStart.value.y - e.clientY
  
  if (!isDragging.value && (Math.abs(deltaX) > 5 || Math.abs(deltaY) > 5)) {
    isDragging.value = true
  }
  
  if (isDragging.value) {
    const windowWidth = window.innerWidth
    const windowHeight = window.innerHeight
    const buttonSize = 48
    
    let newRight = buttonPosition.value.right + deltaX
    let newBottom = buttonPosition.value.bottom + deltaY
    
    newRight = Math.max(10, Math.min(windowWidth - buttonSize - 10, newRight))
    newBottom = Math.max(10, Math.min(windowHeight - buttonSize - 10, newBottom))
    
    buttonPosition.value = { right: newRight, bottom: newBottom }
    dragStart.value = { x: e.clientX, y: e.clientY }
  }
}

const handleMouseEnd = () => {
  document.removeEventListener('mousemove', handleMouseMove)
  document.removeEventListener('mouseup', handleMouseEnd)
  setTimeout(() => {
    isDragging.value = false
  }, 100)
}

// 主题清理函数
let themeCleanup: (() => void) | null = null

onMounted(() => {
  sessionStore.initializeSession()
  
  // 初始化主题系统
  themeCleanup = themeStore.initTheme()
  
  window.addEventListener('beforeunload', handleBeforeUnload)
  window.addEventListener('resize', handleResize)

  // 初始根据屏幕大小设置折叠状态
  sidebarCollapsed.value = window.innerWidth <= COLLAPSE_BREAKPOINT
  isSmallScreen.value = sidebarCollapsed.value
  // 如果是桌面端，按当前问答模式设置默认展开/收起
  if (!isSmallScreen.value) {
    applySidebarByMode()
  }
})

onBeforeUnmount(() => {
  // 清理主题监听器
  if (themeCleanup) {
    themeCleanup()
  }
  
  window.removeEventListener('beforeunload', handleBeforeUnload)
  window.removeEventListener('resize', handleResize)
})

const handleBeforeUnload = (event: BeforeUnloadEvent) => {
  const sessionId = sessionStore.getSessionId()
  if (sessionId) {
    // 使用 navigator.sendBeacon 来确保请求在页面关闭前能被发送
    cleanupSession(sessionId)
  }
}
</script>

<template>
  <div class="flex h-full relative transition-colors duration-300 bg-light-background dark:bg-dark-background">
    <!-- 桌面端侧边栏 -->
    <Sidebar 
      v-if="!isMobile" 
      :collapsed="sidebarCollapsed" 
      @toggle="sidebarCollapsed = !sidebarCollapsed" 
    />

    <!-- 移动端侧边栏 -->
    <Sidebar 
      v-if="isMobile" 
      :collapsed="false" 
      @toggle="toggleMobileSidebar"
      class="transform -translate-x-full transition-transform duration-300 z-[101]"
      :class="{ 'translate-x-0': mobileMenuOpen }"
    />

    <!-- 移动端触发按钮 -->
    <ElButton
      v-if="isMobile && !mobileMenuOpen"
      @click="toggleMobileSidebar"
      @touchstart="handleTouchStart"
      @touchmove="handleTouchMove"
      @touchend="handleTouchEnd"
      @mousedown="handleMouseStart"
      type="primary"
      circle
      size="large"
      class="fixed z-[100] w-12 h-12 shadow-md transition-transform duration-200 select-none touch-none"
      :class="[ isDragging ? 'scale-110 shadow-xl opacity-90' : 'hover:scale-105 hover:shadow-lg' ]"
      :style="{ 
        bottom: buttonPosition.bottom + 'px', 
        right: buttonPosition.right + 'px' 
      }"
    >
      <ElIcon>
        <Menu />
      </ElIcon>
    </ElButton>

    <!-- 移动端遮罩层 -->
    <div 
      v-if="isMobile && mobileMenuOpen" 
      class="fixed inset-0 bg-black/50 dark:bg-black/70 z-50 transition-colors duration-300"
      @click="toggleMobileSidebar"
    ></div>

    <!-- 主内容区域 -->
    <main class="flex-1 ml-0 transition-[margin-left] duration-300" :class="[ sidebarCollapsed ? 'md:ml-20' : 'md:ml-[390px]' ]">
      <ChatArea />
    </main>
  </div>
</template>

<style scoped>
</style>
