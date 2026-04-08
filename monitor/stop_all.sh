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
