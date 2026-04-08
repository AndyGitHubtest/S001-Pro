import { useState, useEffect } from 'react'
import { 
  LogOut, RefreshCw, TrendingUp, TrendingDown, 
  Clock, Wallet, Activity, Share2, AlertTriangle
} from 'lucide-react'
import { api } from '../services/api'
import { wsService } from '../services/websocket'
import SummaryCard from '../components/SummaryCard'
import ProfitChart from '../components/ProfitChart'
import DailyChart from '../components/DailyChart'
import PositionsTable from '../components/PositionsTable'
import LogsPanel from '../components/LogsPanel'
import { SharePanel } from '../components/SharePanel'
import { AlertPanel } from '../components/AlertPanel'

interface DashboardProps {
  onLogout: () => void
}

interface SummaryData {
  today_pnl: number
  today_pnl_pct: number
  today_trades: number
  total_positions: number
  running_time: string
  account_equity: number
  server_status: string
  last_update: string
}

export default function Dashboard({ onLogout }: DashboardProps) {
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [activeTab, setActiveTab] = useState<'dashboard' | 'share' | 'alerts'>('dashboard')
  const [wsConnected, setWsConnected] = useState(false)

  const fetchData = async () => {
    try {
      const res = await api.getSummary()
      if (res.success) {
        setSummary(res.data)
      }
    } catch (err) {
      console.error('获取数据失败:', err)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    fetchData()
    
    // 连接 WebSocket
    wsService.connect()
    
    // 订阅 WebSocket 事件
    const unsubConnected = wsService.on('connected', () => {
      setWsConnected(true)
    })
    
    const unsubDisconnected = wsService.on('disconnected', () => {
      setWsConnected(false)
    })
    
    const unsubSummary = wsService.on('summary_update', (msg) => {
      if (msg.data) {
        setSummary(prev => ({ ...prev, ...msg.data }))
      }
    })
    
    // 每5秒刷新作为备用
    const timer = setInterval(fetchData, 5000)
    
    return () => {
      clearInterval(timer)
      unsubConnected()
      unsubDisconnected()
      unsubSummary()
      wsService.disconnect()
    }
  }, [])

  const handleRefresh = () => {
    setRefreshing(true)
    fetchData()
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg-primary">
        <div className="text-text-secondary">加载中...</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Header */}
      <header className="bg-bg-secondary border-b border-border sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center space-x-4">
              <div className="flex items-center">
                <div className="w-3 h-3 rounded-full bg-up animate-pulse-dot mr-2" />
                <span className="text-lg font-bold text-text-primary">S001-Pro</span>
              </div>
              <span className="text-text-muted">|</span>
              <span className="text-sm text-text-secondary">监控面板</span>
            </div>

            <div className="flex items-center space-x-4">
              {/* 标签切换 */}
              <div className="flex bg-gray-800 rounded-lg p-1">
                <button
                  onClick={() => setActiveTab('dashboard')}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                    activeTab === 'dashboard' 
                      ? 'bg-blue-600 text-white' 
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  概览
                </button>
                <button
                  onClick={() => setActiveTab('alerts')}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors flex items-center gap-1 ${
                    activeTab === 'alerts' 
                      ? 'bg-red-600 text-white' 
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  <AlertTriangle className="w-4 h-4" />
                  警报
                </button>
                <button
                  onClick={() => setActiveTab('share')}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors flex items-center gap-1 ${
                    activeTab === 'share' 
                      ? 'bg-blue-600 text-white' 
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  <Share2 className="w-4 h-4" />
                  分享
                </button>
              </div>
              
              {/* WebSocket 连接状态 */}
              <div className="flex items-center text-sm" title={wsConnected ? '实时连接中' : '轮询模式'}>
                <div className={`w-2 h-2 rounded-full mr-2 ${wsConnected ? 'bg-green-500 animate-pulse' : 'bg-yellow-500'}`} />
                <span className={wsConnected ? 'text-green-400' : 'text-yellow-400'}>
                  {wsConnected ? '实时' : '轮询'}
                </span>
              </div>
              <button
                onClick={handleRefresh}
                disabled={refreshing}
                className="p-2 text-text-secondary hover:text-text-primary transition-colors"
              >
                <RefreshCw className={`w-5 h-5 ${refreshing ? 'animate-spin' : ''}`} />
              </button>
              <button
                onClick={onLogout}
                className="p-2 text-text-secondary hover:text-down transition-colors"
              >
                <LogOut className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === 'dashboard' ? (
          <>
            {/* Summary Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <SummaryCard
                title="今日盈亏"
                value={summary ? `$${summary.today_pnl.toLocaleString()}` : '-'}
                change={summary ? `${summary.today_pnl_pct >= 0 ? '+' : ''}${summary.today_pnl_pct}%` : '-'}
                isPositive={summary ? summary.today_pnl >= 0 : true}
                icon={summary ? (summary.today_pnl >= 0 ? TrendingUp : TrendingDown) : Activity}
              />
              <SummaryCard
                title="持仓数量"
                value={summary ? `${summary.total_positions}对` : '-'}
                change={`今日${summary?.today_trades || 0}笔`}
                isPositive={true}
                icon={Activity}
              />
              <SummaryCard
                title="运行时间"
                value={summary?.running_time || '-'}
                change="正常运行"
                isPositive={true}
                icon={Clock}
              />
              <SummaryCard
                title="账户权益"
                value={summary ? `$${summary.account_equity.toLocaleString()}` : '-'}
                change="总资产"
                isPositive={true}
                icon={Wallet}
              />
            </div>

            {/* Charts Row */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
              <div className="lg:col-span-2">
                <ProfitChart />
              </div>
              <div>
                <DailyChart />
              </div>
            </div>

            {/* Positions & Logs */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <PositionsTable />
              <LogsPanel />
            </div>
          </>
        ) : activeTab === 'alerts' ? (
          /* 警报管理面板 */
          <div className="bg-gray-800/50 rounded-xl border border-gray-700">
            <AlertPanel />
          </div>
        ) : (
          /* 分享管理面板 */
          <div className="bg-gray-800/50 rounded-xl border border-gray-700">
            <SharePanel />
          </div>
        )}
      </main>
    </div>
  )
}
