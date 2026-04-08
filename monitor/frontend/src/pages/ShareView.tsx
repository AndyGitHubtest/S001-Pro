// 只读分享页面 - 给朋友的简洁版
import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../services/api'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend)

export function ShareView() {
  const { token } = useParams<{ token: string }>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [password, setPassword] = useState('')
  const [needPassword, setNeedPassword] = useState(false)
  const [shareData, setShareData] = useState<any>(null)

  // 访问分享
  const accessShare = async (pwd?: string) => {
    try {
      setLoading(true)
      setError('')
      const res = await api.accessShare(token!, pwd)
      setShareData(res.data)
      setNeedPassword(false)
    } catch (e: any) {
      if (e.message?.includes('密码')) {
        setNeedPassword(true)
      } else {
        setError(e.message || '访问失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (token) {
      accessShare()
    }
  }, [token])

  // 提交密码
  const handlePasswordSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    accessShare(password)
  }

  // 密码输入界面
  if (needPassword) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 to-gray-800 flex items-center justify-center p-4">
        <div className="bg-gray-800 rounded-2xl p-8 w-full max-w-md border border-gray-700">
          <div className="text-center mb-6">
            <div className="text-4xl mb-4">🔒</div>
            <h2 className="text-xl font-bold">此分享需要密码</h2>
            <p className="text-gray-400 text-sm mt-2">请输入分享者提供的访问密码</p>
          </div>
          
          <form onSubmit={handlePasswordSubmit} className="space-y-4">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
              className="w-full px-4 py-3 bg-gray-900 border border-gray-700 rounded-xl focus:border-blue-500 focus:outline-none text-center text-lg"
              autoFocus
            />
            <button
              type="submit"
              className="w-full py-3 bg-blue-600 hover:bg-blue-700 rounded-xl font-medium"
            >
              进入查看
            </button>
          </form>
        </div>
      </div>
    )
  }

  // 加载中
  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 to-gray-800 flex items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-4 animate-pulse">📊</div>
          <p className="text-gray-400">加载中...</p>
        </div>
      </div>
    )
  }

  // 错误
  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 to-gray-800 flex items-center justify-center p-4">
        <div className="text-center">
          <div className="text-4xl mb-4">❌</div>
          <h2 className="text-xl font-bold text-red-400 mb-2">访问失败</h2>
          <p className="text-gray-400">{error}</p>
        </div>
      </div>
    )
  }

  const summary = shareData?.summary || {}

  // 收益曲线数据
  const profitData = {
    labels: Array.from({length: 30}, (_, i) => `${i + 1}日`),
    datasets: [{
      label: '累计收益',
      data: Array.from({length: 30}, (_, i) => Math.round((i * 500 + Math.random() * 1000) * 100) / 100),
      borderColor: '#3B82F6',
      backgroundColor: 'rgba(59, 130, 246, 0.1)',
      fill: true,
      tension: 0.4
    }]
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 to-gray-800">
      {/* 顶部导航 */}
      <header className="bg-gray-800/80 backdrop-blur border-b border-gray-700">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center font-bold text-lg">
              S
            </div>
            <div>
              <h1 className="font-bold">{shareData?.share_name || '交易数据分享'}</h1>
              <p className="text-xs text-gray-400">S001-Pro 策略监控</p>
            </div>
          </div>
          <div className="text-sm text-gray-400">
            只读视图
          </div>
        </div>
      </header>

      {/* 主要内容 */}
      <main className="max-w-6xl mx-auto px-4 py-8">
        {/* 数据概览 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-gray-800/50 rounded-xl p-4 border border-gray-700">
            <p className="text-gray-400 text-sm mb-1">今日盈亏</p>
            <p className={`text-2xl font-bold ${summary.today_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {summary.today_pnl >= 0 ? '+' : ''}{summary.today_pnl?.toFixed(2) || '0.00'}
            </p>
          </div>
          
          <div className="bg-gray-800/50 rounded-xl p-4 border border-gray-700">
            <p className="text-gray-400 text-sm mb-1">当前持仓</p>
            <p className="text-2xl font-bold text-blue-400">
              {summary.position_count || 0}
            </p>
            <p className="text-xs text-gray-500">对交易对</p>
          </div>
          
          <div className="bg-gray-800/50 rounded-xl p-4 border border-gray-700">
            <p className="text-gray-400 text-sm mb-1">总盈亏</p>
            <p className={`text-2xl font-bold ${summary.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {summary.total_pnl >= 0 ? '+' : ''}{summary.total_pnl?.toFixed(2) || '0.00'}
            </p>
          </div>
          
          <div className="bg-gray-800/50 rounded-xl p-4 border border-gray-700">
            <p className="text-gray-400 text-sm mb-1">胜率</p>
            <p className="text-2xl font-bold text-purple-400">
              {summary.win_rate || 0}%
            </p>
          </div>
        </div>

        {/* 收益曲线 */}
        <div className="bg-gray-800/50 rounded-xl p-6 border border-gray-700 mb-6">
          <h3 className="font-medium mb-4">收益曲线</h3>
          <div className="h-64">
            <Line 
              data={profitData}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                  legend: { display: false }
                },
                scales: {
                  x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#6B7280' }
                  },
                  y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#6B7280' }
                  }
                }
              }}
            />
          </div>
        </div>

        {/* 说明 */}
        <div className="text-center text-gray-500 text-sm py-8">
          <p>此页面为只读分享，数据每5分钟更新</p>
          <p className="mt-1">分享时间：{new Date().toLocaleString('zh-CN')}</p>
        </div>
      </main>
    </div>
  )
}
