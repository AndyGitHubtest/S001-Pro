// 警报管理面板
import { useState, useEffect } from 'react'
// import { api } from '../services/api'
import { wsService } from '../services/websocket'

interface AlertRule {
  id: number
  name: string
  type: string
  condition: string
  threshold: number
  enabled: boolean
  cooldown_minutes: number
  notify_channels: string[]
  created_at: string
}

interface Alert {
  id: number
  rule_name: string
  alert_type: string
  message: string
  severity: string
  triggered_at: string
  resolved_at?: string
}

const alertTypeLabels: Record<string, string> = {
  zscore: 'Z-Score 异常',
  loss: '亏损警报',
  position: '持仓数量',
  server: '服务器状态'
}

const conditionLabels: Record<string, string> = {
  gt: '大于',
  lt: '小于',
  eq: '等于',
  gte: '大于等于',
  lte: '小于等于'
}

const severityColors: Record<string, string> = {
  info: 'bg-blue-500',
  warning: 'bg-yellow-500',
  critical: 'bg-red-500'
}

export function AlertPanel() {
  const [activeTab, setActiveTab] = useState<'rules' | 'history' | 'active'>('rules')
  const [rules, setRules] = useState<AlertRule[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [activeAlerts, setActiveAlerts] = useState<Alert[]>([])
  // const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [newAlert, setNewAlert] = useState<any>(null)

  // 创建表单
  const [createForm, setCreateForm] = useState({
    name: '',
    type: 'zscore',
    condition: 'gt',
    threshold: 0,
    cooldown_minutes: 5,
    notify_channels: ['websocket'] as string[]
  })

  // 加载数据
  useEffect(() => {
    loadRules()
    loadAlerts()
    loadActiveAlerts()

    // 订阅WebSocket警报
    const unsubscribe = wsService.on('alert', (message) => {
      if (message.data) {
        // 收到新警报，刷新列表
        loadActiveAlerts()
        
        // 浏览器通知
        if (Notification.permission === 'granted') {
          new Notification('S001-Pro 警报', {
            body: message.data.message,
            icon: '/favicon.ico'
          })
        }
      }
    })

    // 请求通知权限
    if (Notification.permission === 'default') {
      Notification.requestPermission()
    }

    return () => {
      unsubscribe()
    }
  }, [])

  const loadRules = async () => {
    try {
      const res = await fetch('/api/alerts/rules')
      const data = await res.json()
      setRules(data.data?.rules || [])
    } catch (e) {
      console.error(e)
    }
  }

  const loadAlerts = async () => {
    try {
      const res = await fetch('/api/alerts/history?limit=50')
      const data = await res.json()
      setAlerts(data.data?.alerts || [])
    } catch (e) {
      console.error(e)
    } finally {
      // setLoading(false)
    }
  }

  const loadActiveAlerts = async () => {
    try {
      const res = await fetch('/api/alerts/history?limit=20')
      const data = await res.json()
      setActiveAlerts(data.data?.alerts || [])
    } catch (e) {
      console.error(e)
    }
  }

  // 创建规则
  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const res = await fetch('/api/alerts/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(createForm)
      })
      const data = await res.json()
      if (data.success) {
        setNewAlert({
          name: createForm.name,
          message: `当 ${alertTypeLabels[createForm.type]} ${conditionLabels[createForm.condition]} ${createForm.threshold} 时触发`
        })
        setCreateForm({
          name: '',
          type: 'zscore',
          condition: 'gt',
          threshold: 0,
          cooldown_minutes: 5,
          notify_channels: ['websocket']
        })
        loadRules()
      }
    } catch (e) {
      alert('创建失败')
    }
  }

  // 删除规则
  const handleDeleteRule = async (id: number) => {
    if (!confirm('确定删除这个警报规则？')) return
    try {
      await fetch(`/api/alerts/rules/${id}`, { method: 'DELETE' })
      loadRules()
    } catch (e) {
      alert('删除失败')
    }
  }

  // 切换规则启用状态
  const handleToggleRule = async (id: number) => {
    try {
      await fetch(`/api/alerts/rules/${id}/toggle`, { method: 'POST' })
      loadRules()
    } catch (e) {
      alert('操作失败')
    }
  }

  // 解决警报
  const handleResolve = async (id: number) => {
    try {
      await fetch(`/api/alerts/${id}/resolve`, { method: 'POST' })
      loadActiveAlerts()
    } catch (e) {
      alert('操作失败')
    }
  }

  // 手动触发检查
  const handleManualCheck = async () => {
    try {
      await fetch('/api/alerts/check', { method: 'POST' })
      alert('警报检查已触发')
    } catch (e) {
      alert('触发失败')
    }
  }

  const formatTime = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('zh-CN')
  }

  return (
    <div className="p-6">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold">风控警报</h2>
        <div className="flex gap-2">
          <button
            onClick={handleManualCheck}
            className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
          >
            🔍 立即检查
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg font-medium"
          >
            + 创建警报
          </button>
        </div>
      </div>

      {/* 标签页 */}
      <div className="flex gap-2 mb-6 border-b border-gray-700">
        {[
          { key: 'rules', label: '警报规则', count: rules.length },
          { key: 'active', label: '活跃警报', count: activeAlerts.length },
          { key: 'history', label: '历史记录', count: alerts.length }
        ].map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as any)}
            className={`px-4 py-2 font-medium ${
              activeTab === tab.key
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab.label}
            <span className="ml-2 text-xs bg-gray-700 px-2 py-0.5 rounded-full">
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      {/* 创建弹窗 */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-xl p-6 w-full max-w-md">
            {newAlert ? (
              <div className="space-y-4">
                <div className="bg-green-900/30 border border-green-600/50 rounded-lg p-4">
                  <p className="text-green-400 font-medium mb-2">✓ 警报规则创建成功！</p>
                  <p className="font-medium">{newAlert.name}</p>
                  <p className="text-sm text-gray-400 mt-1">{newAlert.message}</p>
                </div>
                <button
                  onClick={() => { setNewAlert(null); setShowCreate(false) }}
                  className="w-full py-2 bg-blue-600 hover:bg-blue-700 rounded-lg"
                >
                  完成
                </button>
              </div>
            ) : (
              <form onSubmit={handleCreate} className="space-y-4">
                <h3 className="text-lg font-bold">创建警报规则</h3>
                
                <div>
                  <label className="block text-sm text-gray-400 mb-1">规则名称</label>
                  <input
                    type="text"
                    value={createForm.name}
                    onChange={e => setCreateForm({...createForm, name: e.target.value})}
                    placeholder="例如：Z-Score过高警报"
                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg focus:border-blue-500 focus:outline-none"
                    required
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">监控类型</label>
                    <select
                      value={createForm.type}
                      onChange={e => setCreateForm({...createForm, type: e.target.value})}
                      className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg focus:border-blue-500 focus:outline-none"
                    >
                      <option value="zscore">Z-Score 异常</option>
                      <option value="loss">亏损警报</option>
                      <option value="position">持仓数量</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">条件</label>
                    <select
                      value={createForm.condition}
                      onChange={e => setCreateForm({...createForm, condition: e.target.value})}
                      className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg focus:border-blue-500 focus:outline-none"
                    >
                      <option value="gt">大于</option>
                      <option value="lt">小于</option>
                      <option value="gte">大于等于</option>
                      <option value="lte">小于等于</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-sm text-gray-400 mb-1">阈值</label>
                  <input
                    type="number"
                    step="0.01"
                    value={createForm.threshold}
                    onChange={e => setCreateForm({...createForm, threshold: parseFloat(e.target.value)})}
                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg focus:border-blue-500 focus:outline-none"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm text-gray-400 mb-1">冷却时间（分钟）</label>
                  <input
                    type="number"
                    min="1"
                    max="1440"
                    value={createForm.cooldown_minutes}
                    onChange={e => setCreateForm({...createForm, cooldown_minutes: parseInt(e.target.value)})}
                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-sm text-gray-400 mb-1">通知渠道</label>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={createForm.notify_channels.includes('websocket')}
                        onChange={e => {
                          const channels = e.target.checked
                            ? [...createForm.notify_channels, 'websocket']
                            : createForm.notify_channels.filter(c => c !== 'websocket')
                          setCreateForm({...createForm, notify_channels: channels})
                        }}
                      />
                      页面通知
                    </label>
                    <label className="flex items-center gap-2 text-gray-500">
                      <input type="checkbox" disabled />
                      Telegram (开发中)
                    </label>
                  </div>
                </div>

                <div className="flex gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowCreate(false)}
                    className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg"
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    className="flex-1 py-2 bg-red-600 hover:bg-red-700 rounded-lg font-medium"
                  >
                    创建
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* 规则列表 */}
      {activeTab === 'rules' && (
        <div className="space-y-3">
          {rules.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <p className="text-4xl mb-4">🚨</p>
              <p>还没有警报规则</p>
              <p className="text-sm mt-2">创建规则，系统会在异常时自动通知你</p>
            </div>
          ) : (
            rules.map(rule => (
              <div
                key={rule.id}
                className={`bg-gray-800/50 rounded-lg p-4 border ${rule.enabled ? 'border-gray-700' : 'border-gray-700/50 opacity-50'}`}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-medium">{rule.name}</h3>
                      {!rule.enabled && (
                        <span className="text-xs bg-gray-600/30 text-gray-400 px-2 py-0.5 rounded">
                          已禁用
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-400">
                      当 {alertTypeLabels[rule.type]} {conditionLabels[rule.condition]} {rule.threshold}
                    </p>
                    <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                      <span>⏱️ 冷却 {rule.cooldown_minutes} 分钟</span>
                      <span>📢 {rule.notify_channels.join(', ')}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleToggleRule(rule.id)}
                      className={`p-2 rounded-lg ${rule.enabled ? 'bg-yellow-600/30 hover:bg-yellow-600/50' : 'bg-green-600/30 hover:bg-green-600/50'}`}
                      title={rule.enabled ? '禁用' : '启用'}
                    >
                      {rule.enabled ? '⏸️' : '▶️'}
                    </button>
                    <button
                      onClick={() => handleDeleteRule(rule.id)}
                      className="p-2 bg-red-600/30 hover:bg-red-600/50 rounded-lg"
                      title="删除"
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* 活跃警报 */}
      {activeTab === 'active' && (
        <div className="space-y-3">
          {activeAlerts.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <p className="text-4xl mb-4">✅</p>
              <p>没有活跃警报</p>
              <p className="text-sm mt-2">系统运行正常</p>
            </div>
          ) : (
            activeAlerts.map(alert => (
              <div
                key={alert.id}
                className="bg-red-900/20 border border-red-600/30 rounded-lg p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`w-2 h-2 rounded-full ${severityColors[alert.severity]}`} />
                      <span className="font-medium">{alert.rule_name}</span>
                    </div>
                    <p className="text-sm text-gray-300">{alert.message}</p>
                    <p className="text-xs text-gray-500 mt-2">
                      触发时间: {formatTime(alert.triggered_at)}
                    </p>
                  </div>
                  <button
                    onClick={() => handleResolve(alert.id)}
                    className="px-3 py-1 bg-green-600/30 hover:bg-green-600/50 rounded text-sm"
                  >
                    标记已解决
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* 历史记录 */}
      {activeTab === 'history' && (
        <div className="space-y-2">
          {alerts.map(alert => (
            <div
              key={alert.id}
              className="bg-gray-800/30 rounded-lg p-3 border border-gray-700/50 text-sm"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${severityColors[alert.severity]}`} />
                  <span className="font-medium">{alert.rule_name}</span>
                  {alert.resolved_at && (
                    <span className="text-xs bg-green-600/30 text-green-400 px-2 py-0.5 rounded">
                      已解决
                    </span>
                  )}
                </div>
                <span className="text-xs text-gray-500">
                  {formatTime(alert.triggered_at)}
                </span>
              </div>
              <p className="text-gray-400 mt-1 ml-4">{alert.message}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
