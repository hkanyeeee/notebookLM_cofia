/**
 * 音频管理器 - 解决浏览器自动播放策略限制
 * 支持浏览器在后台或页面失去焦点时播放提示音
 */

export class AudioManager {
  private audioContext: AudioContext | null = null
  private audioBuffer: AudioBuffer | null = null
  private htmlAudio: HTMLAudioElement | null = null
  private isInitialized = false
  private hasUserInteracted = false
  private isEnabled = true
  private volume = 0.5
  private notificationPermission: NotificationPermission = 'default'
  
  private static instance: AudioManager | null = null

  constructor() {
    // 初始化通知权限状态
    if ('Notification' in window) {
      this.notificationPermission = Notification.permission
    }
    
    // 监听用户交互事件，用于预授权音频播放
    this.setupUserInteractionListeners()
    
    // 监听页面可见性变化
    this.setupVisibilityListeners()
  }

  static getInstance(): AudioManager {
    if (!AudioManager.instance) {
      AudioManager.instance = new AudioManager()
    }
    return AudioManager.instance
  }

  /**
   * 设置用户交互监听器，在首次交互时预加载音频
   */
  private setupUserInteractionListeners() {
    const interactionEvents = ['click', 'keydown', 'touchstart', 'mousedown']
    
    const handleUserInteraction = () => {
      if (!this.hasUserInteracted) {
        this.hasUserInteracted = true
        this.preloadAudio()
        
        // 移除监听器，只需要执行一次
        interactionEvents.forEach(event => {
          document.removeEventListener(event, handleUserInteraction, true)
        })
      }
    }
    
    interactionEvents.forEach(event => {
      document.addEventListener(event, handleUserInteraction, true)
    })
  }

  /**
   * 设置页面可见性监听器
   */
  private setupVisibilityListeners() {
    document.addEventListener('visibilitychange', () => {
      // 当页面变为不可见时，确保音频能够播放
      if (document.hidden && this.hasUserInteracted) {
        this.prepareForBackgroundPlayback()
      }
    })
  }

  /**
   * 预加载音频资源
   */
  private async preloadAudio() {
    try {
      // 方法1: 预加载 HTML Audio 元素
      await this.initializeHTMLAudio()
      
      // 方法2: 预加载 AudioContext (更可靠的后台播放)
      await this.initializeAudioContext()
      
      this.isInitialized = true
      console.log('音频预加载完成')
    } catch (error) {
      console.warn('音频预加载失败:', error)
    }
  }

  /**
   * 初始化 HTML Audio 元素
   */
  private async initializeHTMLAudio(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.htmlAudio = new Audio('/audio/notification.mp3')
        this.htmlAudio.volume = this.volume
        this.htmlAudio.preload = 'auto'
        
        this.htmlAudio.addEventListener('canplaythrough', () => resolve(), { once: true })
        this.htmlAudio.addEventListener('error', reject, { once: true })
        
        // 尝试预加载
        this.htmlAudio.load()
      } catch (error) {
        reject(error)
      }
    })
  }

  /**
   * 初始化 AudioContext 和音频缓冲区
   */
  private async initializeAudioContext(): Promise<void> {
    try {
      // 创建 AudioContext
      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
      
      // 如果 AudioContext 处于 suspended 状态，尝试恢复
      if (this.audioContext.state === 'suspended') {
        await this.audioContext.resume()
      }
      
      // 加载音频文件
      const response = await fetch('/audio/notification.mp3')
      const arrayBuffer = await response.arrayBuffer()
      this.audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer)
      
      console.log('AudioContext 初始化成功')
    } catch (error) {
      console.warn('AudioContext 初始化失败:', error)
      this.audioContext = null
    }
  }

  /**
   * 为后台播放做准备
   */
  private prepareForBackgroundPlayback() {
    // 确保 AudioContext 处于运行状态
    if (this.audioContext && this.audioContext.state !== 'running') {
      this.audioContext.resume().catch(console.warn)
    }
  }

  /**
   * 播放通知音
   */
  async playNotification(): Promise<boolean> {
    if (!this.isEnabled) {
      return false
    }

    let playSuccess = false

    // 如果用户还未交互，显示通知作为替代
    if (!this.hasUserInteracted) {
      this.showNotification('消息完成', '您的问答已经处理完成')
      return false
    }

    // 方法1: 使用 AudioContext (最可靠的后台播放)
    if (this.audioContext && this.audioBuffer) {
      try {
        await this.playWithAudioContext()
        playSuccess = true
        console.log('使用 AudioContext 播放成功')
      } catch (error) {
        console.warn('AudioContext 播放失败:', error)
      }
    }

    // 方法2: 使用 HTML Audio 元素作为备选
    if (!playSuccess && this.htmlAudio) {
      try {
        await this.playWithHTMLAudio()
        playSuccess = true
        console.log('使用 HTML Audio 播放成功')
      } catch (error) {
        console.warn('HTML Audio 播放失败:', error)
      }
    }

    // 如果音频播放失败，显示浏览器通知作为补充
    if (!playSuccess) {
      this.showNotification('消息完成', '您的问答已经处理完成')
    }

    return playSuccess
  }

  /**
   * 使用 AudioContext 播放音频
   */
  private async playWithAudioContext(): Promise<void> {
    if (!this.audioContext || !this.audioBuffer) {
      throw new Error('AudioContext or buffer not available')
    }

    // 确保 AudioContext 处于运行状态
    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume()
    }

    const source = this.audioContext.createBufferSource()
    const gainNode = this.audioContext.createGain()
    
    source.buffer = this.audioBuffer
    gainNode.gain.value = this.volume
    
    source.connect(gainNode)
    gainNode.connect(this.audioContext.destination)
    
    source.start(0)
    
    // 返回 Promise
    return new Promise((resolve, reject) => {
      source.addEventListener('ended', () => resolve(), { once: true })
      source.addEventListener('error', reject, { once: true })
    })
  }

  /**
   * 使用 HTML Audio 元素播放音频
   */
  private async playWithHTMLAudio(): Promise<void> {
    if (!this.htmlAudio) {
      throw new Error('HTML Audio not available')
    }

    // 重置播放位置
    this.htmlAudio.currentTime = 0
    
    // 尝试播放
    await this.htmlAudio.play()
  }

  /**
   * 显示浏览器通知
   */
  private showNotification(title: string, body: string) {
    // 如果不支持通知或权限不足，直接返回
    if (!('Notification' in window)) {
      console.log('浏览器不支持通知')
      return
    }

    if (this.notificationPermission === 'granted') {
      try {
        const notification = new Notification(title, {
          body,
          icon: '/favicon.png',
          badge: '/favicon.png',
          silent: false,
          requireInteraction: false,
          tag: 'message-complete'
        })

        // 3秒后自动关闭
        setTimeout(() => {
          notification.close()
        }, 3000)

        console.log('显示通知成功')
      } catch (error) {
        console.warn('显示通知失败:', error)
      }
    } else if (this.notificationPermission === 'default') {
      // 请求通知权限
      Notification.requestPermission().then(permission => {
        this.notificationPermission = permission
        if (permission === 'granted') {
          this.showNotification(title, body)
        }
      })
    }
  }

  /**
   * 设置音量 (0.0 - 1.0)
   */
  setVolume(volume: number) {
    this.volume = Math.max(0, Math.min(1, volume))
    if (this.htmlAudio) {
      this.htmlAudio.volume = this.volume
    }
  }

  /**
   * 启用/禁用音频播放
   */
  setEnabled(enabled: boolean) {
    this.isEnabled = enabled
  }

  /**
   * 获取当前状态
   */
  getStatus() {
    return {
      isInitialized: this.isInitialized,
      hasUserInteracted: this.hasUserInteracted,
      isEnabled: this.isEnabled,
      volume: this.volume,
      hasAudioContext: !!this.audioContext,
      hasHTMLAudio: !!this.htmlAudio,
      notificationPermission: this.notificationPermission
    }
  }

  /**
   * 手动初始化 (用于用户明确要求启用音频时)
   */
  async initialize() {
    if (!this.hasUserInteracted) {
      this.hasUserInteracted = true
    }
    await this.preloadAudio()
  }

  /**
   * 销毁实例，释放资源
   */
  destroy() {
    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }
    if (this.htmlAudio) {
      this.htmlAudio.src = ''
      this.htmlAudio = null
    }
    this.audioBuffer = null
    this.isInitialized = false
  }
}

// 导出单例实例
export const audioManager = AudioManager.getInstance()
