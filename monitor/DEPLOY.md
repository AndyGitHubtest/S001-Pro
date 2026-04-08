# S001-Pro Monitor 部署指南

## 📋 部署方式选择

### 方式一: 本地开发部署 (推荐开发和测试)
```bash
cd ~/S001-Pro/monitor
./deploy.sh
./start_all.sh
```

### 方式二: 一键部署到远程服务器
```bash
# 部署到默认服务器 (43.160.192.48)
./deploy-to-server.sh

# 或指定服务器
./deploy-to-server.sh 你的服务器IP 用户名
```

---

## 🔧 本地开发部署

### 前置要求
- Python 3.11+
- Node.js 18+
- npm 或 yarn

### 步骤

```bash
# 1. 进入目录
cd ~/S001-Pro/monitor

# 2. 运行部署脚本
./deploy.sh

# 3. 启动服务
./start_all.sh
```

### 管理命令

```bash
# 查看状态
./status.sh

# 停止服务
./stop_all.sh

# 重启服务
./restart.sh

# 查看日志
tail -f logs/backend.log
tail -f logs/frontend.log
```

### 访问地址
- **前端**: http://localhost:3000
- **后端API**: http://localhost:8000
- **API文档**: http://localhost:8000/docs

---

## 🚀 服务器部署

### 使用部署脚本

```bash
# 从本地部署到服务器
./deploy-to-server.sh

# 或使用指定参数
./deploy-to-server.sh 43.160.192.48 ubuntu
```

### 手动部署步骤

```bash
# 1. SSH 到服务器
ssh ubuntu@43.160.192.48

# 2. 进入监控目录
cd ~/S001-Pro/monitor

# 3. 运行部署
./deploy.sh

# 4. 启动服务
./start_all.sh

# 5. 或使用 systemd 管理
sudo systemctl start s001-monitor-backend
sudo systemctl start s001-monitor-frontend
```

### systemd 服务管理

```bash
# 查看状态
sudo systemctl status s001-monitor-backend
sudo systemctl status s001-monitor-frontend

# 启动/停止/重启
sudo systemctl start s001-monitor-backend
sudo systemctl stop s001-monitor-backend
sudo systemctl restart s001-monitor-backend

# 开机自启
sudo systemctl enable s001-monitor-backend
sudo systemctl enable s001-monitor-frontend

# 查看日志
sudo journalctl -u s001-monitor-backend -f
sudo journalctl -u s001-monitor-frontend -f
```

---

## ⚙️ 配置说明

### 环境变量

编辑 `.env` 文件:

```bash
# 数据库路径
TRADES_DB_PATH=/Users/andy/S001-Pro/data/trades.db
KLINES_DB_PATH=/Users/andy/S001-Pro/data/klines.db

# 端口
BACKEND_PORT=8000
FRONTEND_PORT=3000

# JWT 密钥 (生产环境请修改)
SECRET_KEY=your-secret-key-here

# 环境
ENVIRONMENT=production
```

### 修改端口

```bash
# 方式1: 环境变量
export BACKEND_PORT=8080
export FRONTEND_PORT=8081
./start_all.sh

# 方式2: 修改 .env 文件
```

---

## 🔒 安全配置

### 1. 修改默认密码

```bash
# 修改后端 JWT 密钥
sed -i 's/s001-pro-monitor-secret-key/你的强密码/g' backend/app/config.py

# 修改登录密码 (默认 admin/admin123)
# 编辑 backend/app/auth.py 中的 users 字典
```

### 2. 防火墙设置

```bash
# 开放端口
sudo ufw allow 3000/tcp  # 前端
sudo ufw allow 8000/tcp  # 后端
```

### 3. Nginx 反向代理 (推荐生产环境)

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 🐛 故障排除

### 后端无法启动

```bash
# 检查依赖
cd backend
source venv/bin/activate
pip install -r requirements.txt

# 检查端口占用
lsof -i :8000

# 查看错误日志
tail -f logs/backend.log
```

### 前端无法访问

```bash
# 重新构建
cd frontend
npm install
npm run build

# 检查端口
lsof -i :3000
```

### WebSocket 连接失败

- 检查防火墙是否放行 WebSocket 端口
- 确保后端服务正常运行
- 查看浏览器控制台网络请求

---

## 📊 性能优化

### 后端优化

```bash
# 使用更多工作进程
uvicorn app.main:app --workers 4

# 或使用 gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

### 前端优化

- 启用 gzip 压缩
- 使用 CDN 加速静态资源
- 配置浏览器缓存

---

## 📝 更新升级

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 停止服务
./stop_all.sh

# 3. 重新部署
./deploy.sh

# 4. 启动服务
./start_all.sh
```

---

## 🆘 获取帮助

```bash
# 查看帮助
./deploy.sh --help

# 查看状态
./status.sh

# 查看日志
tail -f logs/*.log
```
