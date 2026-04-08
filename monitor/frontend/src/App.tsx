import { Routes, Route, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import { ShareView } from './pages/ShareView'

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // 检查是否有 token
    const token = localStorage.getItem('token')
    if (token) {
      // TODO: 验证 token 有效性
      setIsAuthenticated(true)
    }
    setLoading(false)
  }, [])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg-primary">
        <div className="text-text-secondary">加载中...</div>
      </div>
    )
  }

  return (
    <Routes>
      <Route 
        path="/login" 
        element={
          isAuthenticated ? 
            <Navigate to="/" replace /> : 
            <Login onLogin={() => setIsAuthenticated(true)} />
        } 
      />
      <Route 
        path="/" 
        element={
          isAuthenticated ? 
            <Dashboard onLogout={() => setIsAuthenticated(false)} /> : 
            <Navigate to="/login" replace />
        } 
      />
      {/* 公开分享页面 - 无需登录 */}
      <Route path="/share/:token" element={<ShareView />} />
    </Routes>
  )
}

export default App
