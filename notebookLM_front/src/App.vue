<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatArea from './components/ChatArea.vue'
import { useSessionStore } from './stores/session'
import { cleanupSession } from './api/notebook'

const sidebarCollapsed = ref(false)
const sessionStore = useSessionStore()

onMounted(() => {
  sessionStore.initializeSession()
  window.addEventListener('beforeunload', handleBeforeUnload)
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
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
    <!-- 侧边栏 -->
    <Sidebar :collapsed="sidebarCollapsed" @toggle="sidebarCollapsed = !sidebarCollapsed" />

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
}

.main-content {
  flex: 1;
  margin-left: 390px;
  transition: margin-left 0.3s ease;
}

.main-content.sidebar-collapsed {
  margin-left: 80px;
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
