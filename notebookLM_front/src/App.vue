<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatArea from './components/ChatArea.vue'
import { useSessionStore } from './stores/session'
import { cleanupSession } from './api/notebook'
import { ElButton, ElIcon } from 'element-plus'
import { Menu } from '@element-plus/icons-vue'

const sidebarCollapsed = ref(false)
const mobileMenuOpen = ref(false) // 移动端侧边栏显示状态
const sessionStore = useSessionStore()

// 检查是否为移动端
const isMobile = ref(window.innerWidth <= 768)

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

onMounted(() => {
  sessionStore.initializeSession()
  window.addEventListener('beforeunload', handleBeforeUnload)
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
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
  <div class="app-container">
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
      :class="{ 'mobile-sidebar-visible': mobileMenuOpen }"
      @toggle="toggleMobileSidebar" 
      class="mobile-sidebar"
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
      class="mobile-menu-trigger"
      :class="{ 'dragging': isDragging }"
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
      class="mobile-overlay"
      @click="toggleMobileSidebar"
    ></div>

    <!-- 主内容区域 -->
    <main class="main-content" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
      <ChatArea />
    </main>
  </div>
</template>

<style scoped>
.app-container {
  display: flex;
  height: 100%;
  background-color: #fafafa;
  position: relative;
}

.main-content {
  flex: 1;
  margin-left: 390px;
  transition: margin-left 0.3s ease;
}

.main-content.sidebar-collapsed {
  margin-left: 80px;
}

/* 移动端触发按钮 */
.mobile-menu-trigger {
  position: fixed;
  z-index: 100;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  width: 48px;
  height: 48px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  user-select: none;
  touch-action: none; /* 防止默认的触摸行为 */
}

.mobile-menu-trigger:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.mobile-menu-trigger.dragging {
  transform: scale(1.1);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3);
  opacity: 0.9;
}

/* 移动端侧边栏 */
.mobile-sidebar {
  transform: translateX(-100%);
  transition: transform 0.3s ease;
  z-index: 101;
}

.mobile-sidebar.mobile-sidebar-visible {
  transform: translateX(0);
}

/* 移动端遮罩层 */
.mobile-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  z-index: 50;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .app-container {
    /* Safari移动端适配 - 使用百分比避免滚动条问题 */
    height: 100%;
  }

  .main-content {
    margin-left: 0;
    /* 确保在移动端占满整个容器 */
    width: 100%;
    max-width: 100vw;
    overflow-x: hidden;
  }

  .main-content.sidebar-collapsed {
    margin-left: 0;
  }
}
</style>
