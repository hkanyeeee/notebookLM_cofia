import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { v4 as uuidv4 } from 'uuid'

const SESSION_ID_KEY = 'notebooklm_session_id'

export const useSessionStore = defineStore('session', () => {
  const sessionId = ref<string | null>(sessionStorage.getItem(SESSION_ID_KEY))

  function initializeSession() {
    if (!sessionId.value) {
      const newId = uuidv4()
      sessionId.value = newId
      sessionStorage.setItem(SESSION_ID_KEY, newId)
      console.log(`New session initialized: ${newId}`)
    } else {
      console.log(`Session restored: ${sessionId.value}`)
    }
  }

  function getSessionId(): string | null {
    return sessionId.value
  }

  function clearSession() {
    if (sessionId.value) {
      console.log(`Clearing session: ${sessionId.value}`)
      sessionStorage.removeItem(SESSION_ID_KEY)
      sessionId.value = null
    }
  }

  return {
    sessionId: computed(() => sessionId.value),
    initializeSession,
    getSessionId,
    clearSession
  }
})
