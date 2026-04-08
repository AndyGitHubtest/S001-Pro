import { useState, useEffect } from 'react'
import { ArrowUpRight, ArrowDownRight, RefreshCw, Scale, GitCompare } from 'lucide-react'
import { api } from '../services/api'

interface Leg {
  symbol: string
  side: 'long' | 'short'
  entry_price: number
  current_price: number
  size: number
  pnl: number
  pnl_pct: number
}

interface PairPosition {
  pair_id: string
  pair_name: string
  leg_a: Leg
  leg_b: Leg
  hedge_ratio: number  // 对冲比例 1.0 表示 1:1
  spread: number       // 当前价差
  spread_entry: number // 开仓价差
  z_score_current: number
  z_score_entry: number
  total_pnl: number
  total_pnl_pct: number
  max_drawdown: number
  holding_time: string
  status: 'open' | 'closing' | 'liquidating'
}

export default function PositionsTable() {
  const [positions, setPositions] = useState<PairPosition[]>([])
  const [totalPnl, setTotalPnl] = useState(0)
  const [loading, setLoading] = useState(true)

  const fetchPositions = async () => {
    setLoading(true)
    try {
      const res = await api.getPositions()
      if (res.success) {
        // 转换旧格式到新格式（如果有数据）
        const formattedPositions = formatPositions(res.data.positions)
        setPositions(formattedPositions)
        setTotalPnl(res.data.total_pnl || 0)
      }
    } catch (err) {
      console.error('获取持仓失败:', err)
    } finally {
      setLoading(false)
    }
  }

  // 格式化持仓数据 - 适配后端 API 返回格式
  const formatPositions = (rawPositions: any[]): PairPosition[] => {
    if (!rawPositions || rawPositions.length === 0) return []
    
    return rawPositions.map((pos, idx) => {
      // 适配后端 API 返回的格式
      const legA = pos.leg_a || {}
      const legB = pos.leg_b || {}
      
      return {
        pair_id: pos.trade_id || `pair_${idx}`,
        pair_name: pos.pair || `${pos.symbol_a}/${pos.symbol_b}`,
        leg_a: {
          symbol: legA.symbol || pos.symbol_a,
          side: legA.side === 'LONG' ? 'long' : 'short',
          entry_price: legA.price || 0,
          current_price: legA.price || 0,  // TODO: 获取实时价格
          size: legA.amount || 0,
          pnl: legA.pnl || 0,
          pnl_pct: 0
        },
        leg_b: {
          symbol: legB.symbol || pos.symbol_b,
          side: legB.side === 'LONG' ? 'long' : 'short',
          entry_price: legB.price || 0,
          current_price: legB.price || 0,
          size: legB.amount || 0,
          pnl: legB.pnl || 0,
          pnl_pct: 0
        },
        hedge_ratio: 1.0,
        spread: 0,
        spread_entry: 0,
        z_score_current: pos.z_score_current || pos.entry_z || 0,
        z_score_entry: pos.entry_z || 0,
        total_pnl: pos.unrealized_pnl || 0,
        total_pnl_pct: 0,
        max_drawdown: 0,
        holding_time: '--',
        status: pos.status?.toLowerCase() || 'open'
      }
    })
  }

  useEffect(() => {
    fetchPositions()
  }, [])

  // Z-Score 颜色
  const getZScoreColor = (z: number) => {
    const absZ = Math.abs(z)
    if (absZ >= 3) return 'text-red-400'
    if (absZ >= 2.5) return 'text-orange-400'
    if (absZ >= 2) return 'text-yellow-400'
    return 'text-green-400'
  }

  // Z-Score 背景色
  const getZScoreBg = (z: number) => {
    const absZ = Math.abs(z)
    if (absZ >= 3) return 'bg-red-500/10 border-red-500/30'
    if (absZ >= 2.5) return 'bg-orange-500/10 border-orange-500/30'
    if (absZ >= 2) return 'bg-yellow-500/10 border-yellow-500/30'
    return 'bg-green-500/10 border-green-500/30'
  }

  return (
    <div className="bg-bg-secondary rounded-xl border border-border overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div className="flex items-center gap-2">
          <GitCompare className="w-5 h-5 text-text-secondary" />
          <h3 className="text-lg font-semibold text-text-primary">配对持仓</h3>
          <span className="text-xs text-text-muted bg-bg-tertiary px-2 py-0.5 rounded-full">
            统计套利
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-xs text-text-muted">总盈亏</div>
            <div className={`font-mono font-bold ${totalPnl >= 0 ? 'text-up' : 'text-down'}`}>
              {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
            </div>
          </div>
          <button 
            onClick={fetchPositions}
            className="p-2 text-text-secondary hover:text-text-primary transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {loading ? (
          Array.from({length: 2}).map((_, i) => (
            <div key={i} className="skeleton h-32 rounded-lg" />
          ))
        ) : positions.length === 0 ? (
          <div className="text-center py-12 text-text-muted">
            <GitCompare className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>暂无配对持仓</p>
            <p className="text-xs mt-1">等待交易信号...</p>
          </div>
        ) : (
          positions.map((pos) => (
            <div 
              key={pos.pair_id} 
              className={`rounded-lg border p-4 ${getZScoreBg(pos.z_score_current)}`}
            >
              {/* 头部：配对名称和总盈亏 */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <h4 className="font-bold text-text-primary">{pos.pair_name}</h4>
                  <div className="flex items-center gap-1 text-xs text-text-muted">
                    <Scale className="w-3 h-3" />
                    <span>1:{pos.hedge_ratio.toFixed(2)}</span>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`font-mono font-bold ${pos.total_pnl >= 0 ? 'text-up' : 'text-down'}`}>
                    {pos.total_pnl >= 0 ? '+' : ''}${pos.total_pnl.toFixed(2)}
                  </div>
                  <div className={`text-xs ${pos.total_pnl_pct >= 0 ? 'text-up' : 'text-down'}`}>
                    {pos.total_pnl_pct >= 0 ? '+' : ''}{pos.total_pnl_pct.toFixed(2)}%
                  </div>
                </div>
              </div>

              {/* 两条腿并排展示 */}
              <div className="grid grid-cols-2 gap-3 mb-3">
                {/* Leg A */}
                <div className="bg-bg-primary/50 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-text-primary">{pos.leg_a.symbol}</span>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      pos.leg_a.side === 'long' 
                        ? 'bg-up/20 text-up' 
                        : 'bg-down/20 text-down'
                    }`}>
                      {pos.leg_a.side === 'long' ? (
                        <ArrowUpRight className="w-3 h-3 mr-1" />
                      ) : (
                        <ArrowDownRight className="w-3 h-3 mr-1" />
                      )}
                      {pos.leg_a.side === 'long' ? '做多' : '做空'}
                    </span>
                  </div>
                  <div className="space-y-1 text-xs">
                    <div className="flex justify-between">
                      <span className="text-text-muted">开仓</span>
                      <span className="font-mono">${pos.leg_a.entry_price.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-muted">当前</span>
                      <span className="font-mono">${pos.leg_a.current_price.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-muted">盈亏</span>
                      <span className={`font-mono ${pos.leg_a.pnl >= 0 ? 'text-up' : 'text-down'}`}>
                        {pos.leg_a.pnl >= 0 ? '+' : ''}${pos.leg_a.pnl.toFixed(2)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Leg B */}
                <div className="bg-bg-primary/50 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-text-primary">{pos.leg_b.symbol}</span>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      pos.leg_b.side === 'long' 
                        ? 'bg-up/20 text-up' 
                        : 'bg-down/20 text-down'
                    }`}>
                      {pos.leg_b.side === 'long' ? (
                        <ArrowUpRight className="w-3 h-3 mr-1" />
                      ) : (
                        <ArrowDownRight className="w-3 h-3 mr-1" />
                      )}
                      {pos.leg_b.side === 'long' ? '做多' : '做空'}
                    </span>
                  </div>
                  <div className="space-y-1 text-xs">
                    <div className="flex justify-between">
                      <span className="text-text-muted">开仓</span>
                      <span className="font-mono">${pos.leg_b.entry_price.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-muted">当前</span>
                      <span className="font-mono">${pos.leg_b.current_price.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-muted">盈亏</span>
                      <span className={`font-mono ${pos.leg_b.pnl >= 0 ? 'text-up' : 'text-down'}`}>
                        {pos.leg_b.pnl >= 0 ? '+' : ''}${pos.leg_b.pnl.toFixed(2)}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Z-Score 和价差信息 */}
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-bg-primary/30 rounded p-2">
                  <div className="text-xs text-text-muted mb-1">当前 Z-Score</div>
                  <div className={`font-mono font-bold ${getZScoreColor(pos.z_score_current)}`}>
                    {pos.z_score_current.toFixed(2)}
                  </div>
                </div>
                <div className="bg-bg-primary/30 rounded p-2">
                  <div className="text-xs text-text-muted mb-1">开仓 Z-Score</div>
                  <div className="font-mono font-medium text-text-secondary">
                    {pos.z_score_entry.toFixed(2)}
                  </div>
                </div>
                <div className="bg-bg-primary/30 rounded p-2">
                  <div className="text-xs text-text-muted mb-1">持仓时间</div>
                  <div className="font-mono font-medium text-text-secondary">
                    {pos.holding_time}
                  </div>
                </div>
              </div>

              {/* 进度条：Z-Score 可视化 */}
              <div className="mt-3">
                <div className="flex justify-between text-xs text-text-muted mb-1">
                  <span>-3σ</span>
                  <span>0</span>
                  <span>+3σ</span>
                </div>
                <div className="h-2 bg-bg-tertiary rounded-full overflow-hidden relative">
                  {/* 中心线 */}
                  <div className="absolute left-1/2 top-0 bottom-0 w-0.5 bg-text-muted/30" />
                  {/* Z-Score 位置指示器 */}
                  <div 
                    className="absolute top-0 bottom-0 w-3 bg-up rounded-full transform -translate-x-1/2 transition-all"
                    style={{ 
                      left: `${Math.min(Math.max((pos.z_score_current + 3) / 6 * 100, 5), 95)}%`,
                      backgroundColor: pos.z_score_current > 0 ? '#00C853' : '#FF5252'
                    }}
                  />
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
