#!/bin/bash
# 流式滚动扫描启动脚本
# 每10分钟扫描一次，30分钟覆盖全市场，边扫边推

set -e

# 配置
PROJECT_DIR="/home/ubuntu/strategies/S001-Pro"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
LOG_FILE="$PROJECT_DIR/logs/streaming_scan.log"
PID_FILE="$PROJECT_DIR/.streaming_scan.pid"

# 加载环境变量（Telegram配置）
if [ -f "$PROJECT_DIR/.env" ]; then
    source "$PROJECT_DIR/.env"
fi

# 确保日志目录存在
mkdir -p "$PROJECT_DIR/logs"

# 检查是否已在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "流式扫描已在运行 (PID: $PID)"
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

echo "🚀 启动流式滚动扫描..."
echo "   扫描间隔: 10分钟"
echo "   覆盖目标: 30分钟全市场"
echo "   推送方式: Telegram滚动推送"
echo ""

# 启动流式扫描
cd "$PROJECT_DIR"

if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    echo "✅ Telegram推送已启用"
    nohup "$VENV_PYTHON" -m src.streaming_integration \
        --telegram \
        --token "$TELEGRAM_BOT_TOKEN" \
        --chat "$TELEGRAM_CHAT_ID" \
        >> "$LOG_FILE" 2>&1 &
else
    echo "⚠️ Telegram未配置，仅控制台输出"
    nohup "$VENV_PYTHON" -m src.streaming_integration \
        >> "$LOG_FILE" 2>&1 &
fi

# 保存PID
PID=$!
echo $PID > "$PID_FILE"

echo ""
echo "✅ 流式扫描已启动 (PID: $PID)"
echo "📊 日志: tail -f $LOG_FILE"
echo "🛑 停止: kill $PID"
