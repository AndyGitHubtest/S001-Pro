import { useState, useEffect } from 'react'
import { ScrollText, Info, AlertCircle, CheckCircle, XCircle } from 'lucide-react'
import { api } from '../services/api'

interface Log {
  timestamp: string
  level: string
  message: string
  source: string
}

const levelConfig: Record<string, { icon: any; color: string; bg: string }> = {
  INFO: { icon: Info, color: 'text-info', bg: 'bg-info/10' },
  ORDER: { icon: CheckCircle, color: 'text-up', bg: 'bg-up/10' },
  WARNING: { icon: AlertCircle, color: 'text-warning', bg: 'bg-warning/10' },
  ERROR: { icon: XCircle, color: 'text-down', bg: 'bg-down/10' }
}

export default function LogsPanel() {
  const [logs, setLogs] = useState<Log[]>([])
  const [level, setLevel] = useState('ALL')
  const [loading, setLoading] = useState(true)

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const res = await api.getLogs(level)
      if (res.success) {
        setLogs(res.data.logs)
      }
    } catch (err) {
      console.error('获取日志失败:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchLogs()
    const timer = setInterval(fetchLogs, 5000)
    return () => clearInterval(timer)
  }, [level])

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('zh-CN', { hour12: false })
  }

  const levels = [
    { key: 'ALL', label: '全部' },
    { key: 'INFO', label: '信息' },
    { key: 'ORDER', label: '订单' },
    { key: 'ERROR', label: '错误' }
  ]

  return (
    <div className="bg-bg-secondary rounded-xl border border-border overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div className="flex items-center space-x-2">
          <ScrollText className="w-5 h-5 text-info" />
          <h3 className="text-lg font-semibold text-text-primary">实时日志</h3>
        </div>
        <div className="flex items-center space-x-1">
          {levels.map(l => (
            <button
              key={l.key}
              onClick={() => setLevel(l.key)}
              className={`px-3 py-1 text-xs rounded-lg transition-colors ${
                level === l.key 
                  ? 'bg-info text-white' 
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-tertiary'
              }`}
            >
              {l.label}
            </button>
          ))}
        </div>
      </div>

      <div className="h-80 overflow-y-auto p-2 space-y-1">
        {loading && logs.length === 0 ? (
          Array.from({length: 5}).map((_, i) => (
            <div key={i} className="skeleton h-12 rounded-lg" />
          ))
        ) : logs.length === 0 ? (
          <div className="h-full flex items-center justify-center text-text-muted">
            暂无日志
          </div>
        ) : (
          logs.map((log, idx) => {
            const config = levelConfig[log.level] || levelConfig.INFO
            const Icon = config.icon
            
            return (
              <div 
                key={idx} 
                className="flex items-start space-x-3 p-3 rounded-lg hover:bg-bg-tertiary/50 transition-colors"
              >
                <div className={`p-1 rounded ${config.bg}`}>
                  <Icon className={`w-4 h-4 ${config.color}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center space-x-2 mb-1">
                    <span className="text-xs text-text-muted font-mono">
                      {formatTime(log.timestamp)}
                    </span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${config.bg} ${config.color}`}>
                      {log.level}
                    </span>
                    <span className="text-xs text-text-muted">{log.source}</span>
                  </div>
                  <p className="text-sm text-text-primary truncate">{log.message}</p>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
