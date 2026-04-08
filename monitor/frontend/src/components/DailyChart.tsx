import { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../services/api'

export default function DailyChart() {
  const [data, setData] = useState<any[]>([])
  const [range, setRange] = useState('7d')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      try {
        const res = await api.getDailyChart(range)
        if (res.success) {
          const chartData = res.data.labels.map((label: string, i: number) => ({
            date: label.slice(5),
            profit: res.data.data[i],
            color: res.data.data[i] >= 0 ? '#00C853' : '#FF5252'
          }))
          setData(chartData)
        }
      } catch (err) {
        console.error('获取每日收益失败:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
  }, [range])

  const ranges = [
    { key: '7d', label: '7天' },
    { key: '30d', label: '30天' }
  ]

  return (
    <div className="bg-bg-secondary rounded-xl border border-border p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-text-primary">每日收益</h3>
        <div className="flex items-center space-x-1">
          {ranges.map(r => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                range === r.key 
                  ? 'bg-info text-white' 
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="h-64">
        {loading ? (
          <div className="h-full flex items-center justify-center">
            <div className="skeleton w-full h-full rounded-lg" />
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2D3748" vertical={false} />
              <XAxis 
                dataKey="date" 
                stroke="#64748B" 
                fontSize={11}
                tickLine={false}
              />
              <YAxis 
                stroke="#64748B" 
                fontSize={11}
                tickLine={false}
                tickFormatter={(value) => `$${value}`}
              />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: '#151A21', 
                  border: '1px solid #2D3748',
                  borderRadius: '8px'
                }}
                itemStyle={{ color: '#FFFFFF' }}
                formatter={(value: number) => [`$${value}`, '当日收益']}
              />
              <Bar 
                dataKey="profit" 
                fill="#00C853"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
