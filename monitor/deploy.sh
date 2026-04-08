#!/bin/bash
# S001-Pro Monitor 一键部署脚本
# 直接部署到服务器，无需 Docker

set -e

echo "═══════════════════════════════════════════════════════════════"
echo "  S001-Pro Monitor 部署脚本"
echo "═══════════════════════════════════════════════════════════════"

# 配置
BACKEND_PORT=${BACKEND_PORT:-8000}
FRONTEND_PORT=${FRONTEND_PORT:-3000}
INSTALL_DIR=${INSTALL_DIR:-"$HOME/S001-Pro/monitor"}
PYTHON_CMD=${PYTHON_CMD:-"python3"}

echo ""
echo "📋 部署配置:"
echo "  后端端口: $BACKEND_PORT"
echo "  前端端口: $FRONTEND_PORT"
echo "  安装目录: $INSTALL_DIR"
echo ""

# 检查环境
echo "🔍 检查环境..."

# 检查 Python
if ! command -v $PYTHON_CMD &> /dev/null; then
    echo "❌ Python3 未安装"
    exit 1
fi
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
echo "  ✓ Python: $PYTHON_VERSION"

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js 未安装"
    echo "   请安装 Node.js 18+ (https://nodejs.org/)"
    exit 1
fi
NODE_VERSION=$(node --version)
echo "  ✓ Node.js: $NODE_VERSION"

# 检查 npm
if ! command -v npm &> /dev/null; then
    echo "❌ npm 未安装"
    exit 1
fi
echo "  ✓ npm: $(npm --version)"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  开始部署"
echo "═══════════════════════════════════════════════════════════════"

# 进入目录
cd "$INSTALL_DIR"

# ========== 部署后端 ==========
echo ""
echo "📦 [1/4] 部署后端服务..."
cd backend

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "  创建 Python 虚拟环境..."
    $PYTHON_CMD -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "  安装 Python 依赖..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "  ✓ 后端依赖安装完成"

# 创建数据目录
mkdir -p data

# 创建启动脚本
cat > start.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000} --reload
EOF
chmod +x start.sh

cat > start_production.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
# 生产模式：后台运行 + 日志文件
nohup uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000} --workers 2 > ../logs/backend.log 2>&1 &
echo $! > ../logs/backend.pid
echo "Backend started on port ${BACKEND_PORT:-8000}"
EOF
chmod +x start_production.sh

cd ..

# ========== 部署前端 ==========
echo ""
echo "📦 [2/4] 部署前端应用..."
cd frontend

# 安装依赖
echo "  安装 npm 依赖..."
npm install -q

# 构建
echo "  构建前端应用..."
npm run build 2>&1 | tail -5

echo "  ✓ 前端构建完成"

# 创建启动脚本
cd ..
mkdir -p logs

cat > start_frontend.sh << EOF
#!/bin/bash
cd "$(pwd)/frontend"
# 使用 npx serve 提供静态文件
npx serve -s dist -l ${FRONTEND_PORT:-3000} > ../logs/frontend.log 2>&1 &
echo \$! > ../logs/frontend.pid
echo "Frontend started on port ${FRONTEND_PORT:-3000}"
EOF
chmod +x start_frontend.sh

# ========== 创建管理脚本 ==========
echo ""
echo "📦 [3/4] 创建管理脚本..."

# 启动全部
cat > start_all.sh << EOF
#!/bin/bash
cd "$(pwd)"
mkdir -p logs

echo "启动 S001-Pro Monitor..."

# 检查是否已在运行
if [ -f logs/backend.pid ] && kill -0 \$(cat logs/backend.pid) 2>/dev/null; then
    echo "⚠️ 后端已在运行 (PID: \$(cat logs/backend.pid))"
else
    echo "🚀 启动后端..."
    cd backend
    source venv/bin/activate
    nohup uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000} --workers 2 > ../logs/backend.log 2>&1 &
    echo \$! > ../logs/backend.pid
    cd ..
    echo "   ✓ 后端启动在端口 ${BACKEND_PORT:-8000}"
fi

# 启动前端
if [ -f logs/frontend.pid ] && kill -0 \$(cat logs/frontend.pid) 2>/dev/null; then
    echo "⚠️ 前端已在运行 (PID: \$(cat logs/frontend.pid))"
else
    echo "🚀 启动前端..."
    cd frontend
    nohup npx serve -s dist -l ${FRONTEND_PORT:-3000} > ../logs/frontend.log 2>&1 &
    echo \$! > ../logs/frontend.pid
    cd ..
    echo "   ✓ 前端启动在端口 ${FRONTEND_PORT:-3000}"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  服务已启动"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  🌐 前端访问: http://localhost:${FRONTEND_PORT:-3000}"
echo "  🔌 后端API: http://localhost:${BACKEND_PORT:-8000}"
echo "  📖 API文档: http://localhost:${BACKEND_PORT:-8000}/docs"
echo ""
echo "  查看日志:"
echo "    tail -f logs/backend.log"
echo "    tail -f logs/frontend.log"
echo ""
EOF
chmod +x start_all.sh

# 停止全部
cat > stop_all.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"

echo "停止 S001-Pro Monitor..."

if [ -f logs/backend.pid ]; then
    PID=$(cat logs/backend.pid)
    if kill -0 $PID 2>/dev/null; then
        kill $PID
        echo "  ✓ 后端已停止 (PID: $PID)"
    fi
    rm -f logs/backend.pid
fi

if [ -f logs/frontend.pid ]; then
    PID=$(cat logs/frontend.pid)
    if kill -0 $PID 2>/dev/null; then
        kill $PID
        echo "  ✓ 前端已停止 (PID: $PID)"
    fi
    rm -f logs/frontend.pid
fi

echo "  ✓ 所有服务已停止"
EOF
chmod +x stop_all.sh

# 查看状态
cat > status.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════════════"
echo "  S001-Pro Monitor 运行状态"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# 后端状态
if [ -f logs/backend.pid ]; then
    PID=$(cat logs/backend.pid)
    if kill -0 $PID 2>/dev/null; then
        echo "  🟢 后端: 运行中 (PID: $PID)"
    else
        echo "  🔴 后端: 已停止 (PID文件残留)"
    fi
else
    echo "  🔴 后端: 未启动"
fi

# 前端状态
if [ -f logs/frontend.pid ]; then
    PID=$(cat logs/frontend.pid)
    if kill -0 $PID 2>/dev/null; then
        echo "  🟢 前端: 运行中 (PID: $PID)"
    else
        echo "  🔴 前端: 已停止 (PID文件残留)"
    fi
else
    echo "  🔴 前端: 未启动"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
EOF
chmod +x status.sh

# 重启脚本
cat > restart.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
./stop_all.sh
echo ""
sleep 2
./start_all.sh
EOF
chmod +x restart.sh

# ========== 环境变量配置 ==========
echo ""
echo "📦 [4/4] 创建环境配置..."

cat > .env << EOF
# S001-Pro Monitor 环境配置
# 数据库路径 (默认使用 S001-Pro/data)
TRADES_DB_PATH=/Users/andy/S001-Pro/data/trades.db
KLINES_DB_PATH=/Users/andy/S001-Pro/data/klines.db

# 服务端口
BACKEND_PORT=8000
FRONTEND_PORT=3000

# JWT 密钥 (生产环境请修改)
SECRET_KEY=s001-pro-monitor-secret-key-change-in-production

# 环境 (development/production)
ENVIRONMENT=production
EOF

echo "  ✓ 环境配置已创建"

# ========== 完成 ==========
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ 部署完成!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "📁 安装位置: $INSTALL_DIR"
echo ""
echo "🚀 快速开始:"
echo "   cd $INSTALL_DIR"
echo "   ./start_all.sh       # 启动所有服务"
echo "   ./stop_all.sh        # 停止所有服务"
echo "   ./status.sh          # 查看运行状态"
echo "   ./restart.sh         # 重启服务"
echo ""
echo "🌐 访问地址:"
echo "   前端: http://localhost:${FRONTEND_PORT:-3000}"
echo "   后端: http://localhost:${BACKEND_PORT:-8000}"
echo ""
echo "📖 管理命令:"
echo "   查看后端日志: tail -f logs/backend.log"
echo "   查看前端日志: tail -f logs/frontend.log"
echo ""
