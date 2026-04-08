// 分享管理面板
import { useState, useEffect } from 'react'
import { api } from '../services/api'

interface Share {
  id: number
  token: string
  name: string
  created_at: string
  expires_at: string | null
  has_password: boolean
  is_active: boolean
  view_count: number
  last_viewed_at: string | null
  share_url: string
}

export function SharePanel() {
  const [shares, setShares] = useState<Share[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({
    name: '',
    expireDays: 7,
    password: ''
  })
  const [newShare, setNewShare] = useState<any>(null)

  // 加载分享列表
  useEffect(() => {
    loadShares()
  }, [])

  const loadShares = async () => {
    try {
      const res = await api.getShares()
      setShares(res.data.shares)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  // 创建分享
  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const res = await api.createShare(
        createForm.name,
        createForm.expireDays,
        createForm.password || undefined
      )
      setNewShare(res.data)
      setCreateForm({ name: '', expireDays: 7, password: '' })
      loadShares()
    } catch (e) {
      alert('创建失败')
    }
  }

  // 删除分享
  const handleDelete = async (id: number) => {
    if (!confirm('确定删除这个分享链接？')) return
    try {
      await api.deleteShare(id)
      loadShares()
    } catch (e) {
      alert('删除失败')
    }
  }

  // 切换启用状态
  const handleToggle = async (id: number) => {
    try {
      await api.toggleShare(id)
      loadShares()
    } catch (e) {
      alert('操作失败')
    }
  }

  // 复制链接
  const copyLink = (url: string) => {
    navigator.clipboard.writeText(window.location.origin + url)
    alert('链接已复制到剪贴板')
  }

  // 格式化日期
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('zh-CN')
  }

  // 计算剩余天数
  const getRemainingDays = (expiresAt: string | null) => {
    if (!expiresAt) return '永久'
    const days = Math.ceil((new Date(expiresAt).getTime() - Date.now()) / 86400000)
    return days > 0 ? `${days}天` : '已过期'
  }

  if (loading) {
    return <div className="p-8 text-center text-gray-400">加载中...</div>
  }

  return (
    <div className="p-6">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold">分享管理</h2>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium"
        >
          + 创建分享
        </button>
      </div>

      {/* 创建弹窗 */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-bold mb-4">创建分享链接</h3>
            
            {newShare ? (
              <div className="space-y-4">
                <div className="bg-green-900/30 border border-green-600/50 rounded-lg p-4">
                  <p className="text-green-400 font-medium mb-2">✓ 分享链接创建成功！</p>
                  <p className="text-sm text-gray-400 mb-3">复制下方链接发送给朋友：</p>
                  <div className="bg-gray-900 rounded p-3 break-all text-sm font-mono text-blue-400">
                    {newShare.full_url}
                  </div>
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() => copyLink(newShare.share_url)}
                    className="flex-1 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg"
                  >
                    复制链接
                  </button>
                  <button
                    onClick={() => { setNewShare(null); setShowCreate(false) }}
                    className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg"
                  >
                    完成
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleCreate} className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">分享名称</label>
                  <input
                    type="text"
                    value={createForm.name}
                    onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                    placeholder="例如：给投资人的查看链接"
                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg focus:border-blue-500 focus:outline-none"
                    required
                  />
                </div>
                
                <div>
                  <label className="block text-sm text-gray-400 mb-1">有效期</label>
                  <select
                    value={createForm.expireDays}
                    onChange={(e) => setCreateForm({ ...createForm, expireDays: Number(e.target.value) })}
                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg focus:border-blue-500 focus:outline-none"
                  >
                    <option value={7}>7天</option>
                    <option value={30}>30天</option>
                    <option value={90}>90天</option>
                    <option value={0}>永久</option>
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm text-gray-400 mb-1">
                    访问密码 <span className="text-gray-600">(可选)</span>
                  </label>
                  <input
                    type="text"
                    value={createForm.password}
                    onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                    placeholder="留空表示无需密码"
                    className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg focus:border-blue-500 focus:outline-none"
                  />
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
                    className="flex-1 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium"
                  >
                    创建
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* 分享列表 */}
      {shares.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="text-4xl mb-4">📤</p>
          <p>还没有创建分享链接</p>
          <p className="text-sm mt-2">点击上方按钮创建，让朋友查看你的交易表现</p>
        </div>
      ) : (
        <div className="space-y-3">
          {shares.map((share) => (
            <div
              key={share.id}
              className={`bg-gray-800/50 rounded-lg p-4 border ${share.is_active ? 'border-gray-700' : 'border-gray-700/50 opacity-60'}`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    <h3 className="font-medium">{share.name}</h3>
                    {share.has_password && (
                      <span className="text-xs bg-yellow-600/30 text-yellow-400 px-2 py-0.5 rounded">
                        🔒 密码保护
                      </span>
                    )}
                    {!share.is_active && (
                      <span className="text-xs bg-gray-600/30 text-gray-400 px-2 py-0.5 rounded">
                        已禁用
                      </span>
                    )}
                  </div>
                  
                  <div className="flex items-center gap-4 text-sm text-gray-400">
                    <span>📊 访问 {share.view_count} 次</span>
                    <span>⏱️ 剩余 {getRemainingDays(share.expires_at)}</span>
                    {share.last_viewed_at && (
                      <span>👁️ 最近访问 {formatDate(share.last_viewed_at)}</span>
                    )}
                  </div>
                  
                  <div className="mt-2 text-xs text-gray-500">
                    创建于 {formatDate(share.created_at)}
                  </div>
                </div>
                
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => copyLink(share.share_url)}
                    className="p-2 bg-gray-700 hover:bg-gray-600 rounded-lg"
                    title="复制链接"
                  >
                    📋
                  </button>
                  <button
                    onClick={() => handleToggle(share.id)}
                    className={`p-2 rounded-lg ${share.is_active ? 'bg-yellow-600/30 hover:bg-yellow-600/50' : 'bg-green-600/30 hover:bg-green-600/50'}`}
                    title={share.is_active ? '禁用' : '启用'}
                  >
                    {share.is_active ? '⏸️' : '▶️'}
                  </button>
                  <button
                    onClick={() => handleDelete(share.id)}
                    className="p-2 bg-red-600/30 hover:bg-red-600/50 rounded-lg"
                    title="删除"
                  >
                    🗑️
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
