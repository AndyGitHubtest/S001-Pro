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
