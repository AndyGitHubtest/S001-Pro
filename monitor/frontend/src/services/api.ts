// API 服务
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://43.160.192.48:3000'

// 统一请求封装
async function request(endpoint: string, options?: RequestInit) {
  const url = `${API_BASE_URL}${endpoint}`
  const token = localStorage.getItem('token')
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...options?.headers as Record<string, string>
  }
  
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  
  try {
    const response = await fetch(url, {
      ...options,
      headers
    })
    
    if (!response.ok) {
      if (response.status === 401) {
        localStorage.removeItem('token')
        throw new Error('登录已过期，请重新登录')
      }
      throw new Error(`请求失败: ${response.status}`)
    }
    
    return await response.json()
  } catch (error) {
    console.error('API请求错误:', error)
    throw error
  }
}

export const api = {
  // 登录
  async login(username: string, password: string) {
    const response = await request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password })
    })
    if (response.success && response.data?.token) {
      localStorage.setItem('token', response.data.token)
    }
    return response
  },

  // 获取汇总数据
  async getSummary() {
    return request('/api/summary')
  },

  // 获取持仓
  async getPositions() {
    return request('/api/positions')
  },

  // 获取收益曲线
  async getProfitChart(range: string = '30d') {
    return request(`/api/charts/profit?range=${range}`)
  },

  // 获取每日收益
  async getDailyChart(range: string = '7d') {
    return request(`/api/charts/daily?range=${range}`)
  },

  // 获取持仓分布
  async getHoldingsChart() {
    return request('/api/charts/holdings')
  },

  // 获取日志
  async getLogs(level: string = 'ALL') {
    return request(`/api/logs?level=${level}`)
  },

  // ============ 分享功能 ============
  
  // 创建分享链接
  async createShare(name: string, expireDays: number = 7, password?: string) {
    return request('/api/shares', {
      method: 'POST',
      body: JSON.stringify({ name, expire_days: expireDays, password })
    })
  },

  // 获取分享列表
  async getShares() {
    return request('/api/shares')
  },

  // 删除分享
  async deleteShare(shareId: number) {
    return request(`/api/shares/${shareId}`, { method: 'DELETE' })
  },

  // 启用/禁用分享
  async toggleShare(shareId: number) {
    return request(`/api/shares/${shareId}/toggle`, { method: 'POST' })
  },

  // 访问分享页面（公开接口）
  async accessShare(token: string, password?: string) {
    const url = password 
      ? `/share/${token}?password=${encodeURIComponent(password)}`
      : `/share/${token}`
    return request(url)
  }
}
