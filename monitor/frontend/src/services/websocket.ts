// WebSocket 服务
const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'

export type WebSocketMessage = {
  type: string
  data?: any
  timestamp?: string
}

export type WebSocketCallback = (message: WebSocketMessage) => void

class WebSocketService {
  private ws: WebSocket | null = null
  private token: string | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 3000
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null
  private listeners: Map<string, WebSocketCallback[]> = new Map()
  private isConnecting = false

  // 连接WebSocket
  connect(token?: string): void {
    if (this.isConnecting || this.ws?.readyState === WebSocket.OPEN) {
      return
    }

    this.isConnecting = true
    this.token = token || localStorage.getItem('token')
    
    const wsUrl = token 
      ? `${WS_BASE_URL}/ws/share/${token}`  // 公开分享连接
      : `${WS_BASE_URL}/ws?token=${this.token}`  // 认证连接

    try {
      this.ws = new WebSocket(wsUrl)

      this.ws.onopen = () => {
        console.log('WebSocket connected')
        this.isConnecting = false
        this.reconnectAttempts = 0
        this.startHeartbeat()
        this.emit('connected', {})
      }

      this.ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data)
          this.handleMessage(message)
        } catch (e) {
          console.error('WebSocket message parse error:', e)
        }
      }

      this.ws.onclose = () => {
        console.log('WebSocket disconnected')
        this.isConnecting = false
        this.stopHeartbeat()
        this.emit('disconnected', {})
        this.attemptReconnect()
      }

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        this.isConnecting = false
        this.emit('error', { error })
      }
    } catch (e) {
      console.error('WebSocket connection error:', e)
      this.isConnecting = false
      this.attemptReconnect()
    }
  }

  // 断开连接
  disconnect(): void {
    this.stopHeartbeat()
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.reconnectAttempts = this.maxReconnectAttempts  // 阻止自动重连
  }

  // 尝试重连
  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.log('Max reconnection attempts reached')
      this.emit('reconnect_failed', {})
      return
    }

    this.reconnectAttempts++
    console.log(`Reconnecting... attempt ${this.reconnectAttempts}`)

    setTimeout(() => {
      this.connect(this.token || undefined)
    }, this.reconnectDelay * this.reconnectAttempts)
  }

  // 启动心跳
  private startHeartbeat(): void {
    this.heartbeatInterval = setInterval(() => {
      this.send({ type: 'ping' })
    }, 30000)  // 每30秒发送一次心跳
  }

  // 停止心跳
  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
      this.heartbeatInterval = null
    }
  }

  // 发送消息
  send(message: WebSocketMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    }
  }

  // 处理接收到的消息
  private handleMessage(message: WebSocketMessage): void {
    // 根据消息类型分发
    this.emit(message.type, message.data)
    
    // 同时触发通用消息事件
    this.emit('message', message)
  }

  // 订阅事件
  on(event: string, callback: WebSocketCallback): () => void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, [])
    }
    this.listeners.get(event)!.push(callback)

    // 返回取消订阅函数
    return () => {
      const callbacks = this.listeners.get(event)
      if (callbacks) {
        const index = callbacks.indexOf(callback)
        if (index > -1) {
          callbacks.splice(index, 1)
        }
      }
    }
  }

  // 触发事件
  private emit(event: string, data: any): void {
    const callbacks = this.listeners.get(event)
    if (callbacks) {
      callbacks.forEach(callback => {
        try {
          callback({ type: event, data, timestamp: new Date().toISOString() })
        } catch (e) {
          console.error('WebSocket callback error:', e)
        }
      })
    }
  }

  // 获取连接状态
  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

// 导出单例
export const wsService = new WebSocketService()

// Hook for React组件
export function useWebSocket() {
  return wsService
}
