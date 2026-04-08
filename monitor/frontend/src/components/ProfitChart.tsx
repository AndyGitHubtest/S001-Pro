import { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Download } from 'lucide-react'
import { api } from '../services/api'

export default function ProfitChart() {
  const [data, setData] = useState<any[]>([])
  const [range, setRange] = useState('30d')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      try {
        const res = await api.getProfitChart(range)
        if (res.success) {
          const chartData = res.data.labels.map((label: string, i: number) => ({
            date: label.slice(5), // 去掉年份
            profit: res.data.data[i]
          }))
          setData(chartData)
        }
      } catch (err) {
        console.error('获取收益曲线失败:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [range])

  const ranges = [
    { key: '7d', label: '7天' },
    { key: '30d', label: '30天' },
    { key: '90d', label: '90天' },
    { key: 'all', label: '全部' }
  ]

  return (
    <div className="bg-bg-secondary rounded-xl border border-border p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-text-primary">收益曲线</h3>
        <div className="flex items-center space-x-2">
          {ranges.map(r => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={`px-3 py-1 text-sm rounded-lg transition-colors ${
                range === r.key 
                  ? 'bg-info text-white' 
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-tertiary'
              }`}
            >
              {r.label}
            </button>
          ))}
          <button className="p-2 text-text-secondary hover:text-text-primary transition-colors ml-2">
            <Download className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="h-64">
        {loading ? (
          <div className="h-full flex items-center justify-center">
            <div className="skeleton w-full h-full rounded-lg" />
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2D3748" />
              <XAxis 
                dataKey="date" 
                stroke="#64748B" 
                fontSize={12}
                tickLine={false}
              />
              <YAxis 
                stroke="#64748B" 
                fontSize={12}
                tickLine={false}
                tickFormatter={(value) => `$${value}`}
              />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: '#151A21', 
                  border: '1px solid #2D3748',
                  borderRadius: '8px'
                }}
                itemStyle={{ color: '#448AFF' }}
                formatter={(value: number) => [`$${value}`, '累计收益']}
              />
              <Line 
                type="monotone" 
                dataKey="profit" 
                stroke="#448AFF" 
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: '#448AFF' }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
