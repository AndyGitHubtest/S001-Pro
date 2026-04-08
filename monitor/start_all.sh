#!/bin/bash
cd "/Users/andy/S001-Pro/monitor"
mkdir -p logs

echo "启动 S001-Pro Monitor..."

# 检查是否已在运行
if [ -f logs/backend.pid ] && kill -0 $(cat logs/backend.pid) 2>/dev/null; then
    echo "⚠️ 后端已在运行 (PID: $(cat logs/backend.pid))"
else
    echo "🚀 启动后端..."
    cd backend
    source venv/bin/activate
    nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 > ../logs/backend.log 2>&1 &
    echo $! > ../logs/backend.pid
    cd ..
    echo "   ✓ 后端启动在端口 8000"
fi

# 启动前端
if [ -f logs/frontend.pid ] && kill -0 $(cat logs/frontend.pid) 2>/dev/null; then
    echo "⚠️ 前端已在运行 (PID: $(cat logs/frontend.pid))"
else
    echo "🚀 启动前端..."
    cd frontend
    nohup npx serve -s dist -l 3000 > ../logs/frontend.log 2>&1 &
    echo $! > ../logs/frontend.pid
    cd ..
    echo "   ✓ 前端启动在端口 3000"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  服务已启动"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  🌐 前端访问: http://localhost:3000"
echo "  🔌 后端API: http://localhost:8000"
echo "  📖 API文档: http://localhost:8000/docs"
echo ""
echo "  查看日志:"
echo "    tail -f logs/backend.log"
echo "    tail -f logs/frontend.log"
echo ""
