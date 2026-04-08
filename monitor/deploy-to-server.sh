#!/bin/bash
# S001-Pro Monitor 远程部署到服务器脚本
# 用法: ./deploy-to-server.sh [服务器IP] [用户名]

set -e

SERVER_IP=${1:-"43.160.192.48"}
SERVER_USER=${2:-"ubuntu"}
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="/home/$SERVER_USER/S001-Pro/monitor"

echo "═══════════════════════════════════════════════════════════════"
echo "  S001-Pro Monitor 远程部署"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  目标服务器: $SERVER_USER@$SERVER_IP"
echo "  远程目录: $REMOTE_DIR"
echo ""

# 检查 SSH 连接
echo "🔍 检查 SSH 连接..."
if ! ssh -o ConnectTimeout=5 "$SERVER_USER@$SERVER_IP" "echo 'SSH OK'" 2>/dev/null; then
    echo "❌ 无法连接到服务器"
    echo "   请确保:"
    echo "   1. 服务器IP正确"
    echo "   2. SSH 密钥已配置"
    echo "   3. 服务器在线"
    exit 1
fi
echo "  ✓ SSH 连接正常"

# 创建远程目录
echo ""
echo "📁 创建远程目录..."
ssh "$SERVER_USER@$SERVER_IP" "mkdir -p $REMOTE_DIR"

# 同步代码
echo ""
echo "📦 同步代码到服务器..."
rsync -avz --progress \
    --exclude='venv' \
    --exclude='node_modules' \
    --exclude='dist' \
    --exclude='data' \
    --exclude='logs' \
    --exclude='.git' \
    "$LOCAL_DIR/" \
    "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/"

# 在服务器上执行部署
echo ""
echo "🔧 在服务器上执行部署..."
ssh "$SERVER_USER@$SERVER_IP" << EOF
    cd $REMOTE_DIR
    
    # 修改权限
    chmod +x *.sh
    
    # 运行本地部署
    export BACKEND_PORT=8000
    export FRONTEND_PORT=3000
    ./deploy.sh
    
    # 创建 systemd 服务文件 (可选)
    sudo tee /etc/systemd/system/s001-monitor-backend.service > /dev/null << 'SYSTEMD_EOF'
[Unit]
Description=S001-Pro Monitor Backend
After=network.target

[Service]
Type=simple
User=$SERVER_USER
WorkingDirectory=$REMOTE_DIR/backend
Environment=PATH=$REMOTE_DIR/backend/venv/bin
ExecStart=$REMOTE_DIR/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

    sudo tee /etc/systemd/system/s001-monitor-frontend.service > /dev/null << 'SYSTEMD_EOF'
[Unit]
Description=S001-Pro Monitor Frontend
After=network.target

[Service]
Type=simple
User=$SERVER_USER
WorkingDirectory=$REMOTE_DIR/frontend
ExecStart=/usr/bin/npx serve -s dist -l 3000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

    echo ""
    echo "✅ 部署完成!"
    echo ""
    echo "启动服务:"
    echo "  sudo systemctl start s001-monitor-backend"
    echo "  sudo systemctl start s001-monitor-frontend"
    echo ""
    echo "开机自启:"
    echo "  sudo systemctl enable s001-monitor-backend"
    echo "  sudo systemctl enable s001-monitor-frontend"
EOF

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ 远程部署完成!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "🌐 访问地址:"
echo "   前端: http://$SERVER_IP:3000"
echo "   后端: http://$SERVER_IP:8000"
echo ""
echo "📋 服务器管理命令:"
echo "   ssh $SERVER_USER@$SERVER_IP"
echo "   cd $REMOTE_DIR"
echo "   ./status.sh"
echo "   ./restart.sh"
echo ""
echo "🔧 systemd 管理:"
echo "   sudo systemctl status s001-monitor-backend"
echo "   sudo systemctl status s001-monitor-frontend"
echo "   sudo journalctl -u s001-monitor-backend -f"
echo ""
