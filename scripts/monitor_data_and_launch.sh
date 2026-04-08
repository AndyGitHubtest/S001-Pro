#!/bin/bash
# S001-Pro 数据监控与自动启动脚本
# 用法: 由cron定时执行

set -e

PROJECT_ROOT="/home/ubuntu/strategies/S001-Pro"
DATA_DB="/home/ubuntu/projects/data-core/data/klines.db"
LOG_FILE="$PROJECT_ROOT/logs/auto_launch.log"
TG_BOT_TOKEN="${TG_BOT_TOKEN:-}"
TG_CHAT_ID="${TG_CHAT_ID:-}"

# 发送Telegram通知
send_tg() {
    local message="$1"
    if [ -n "$TG_BOT_TOKEN" ] && [ -n "$TG_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot$TG_BOT_TOKEN/sendMessage" \
            -d "chat_id=$TG_CHAT_ID" \
            -d "text=$message" \
            -d "parse_mode=Markdown" > /dev/null 2>&1 || true
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') $message" >> "$LOG_FILE"
}

# 检查数据状态
check_data() {
    cd /home/ubuntu/projects/data-core
    source venv/bin/activate
    
    python3 << 'PYEOF'
import sqlite3
import sys

conn = sqlite3.connect('data/klines.db')
c = conn.cursor()

c.execute('SELECT COUNT(*) FROM klines')
total = c.fetchone()[0]

c.execute('SELECT COUNT(DISTINCT symbol) FROM klines')
symbols = c.fetchone()[0]

c.execute('SELECT MAX(ts) FROM klines')
max_ts = c.fetchone()[0]

# 检查最近1小时是否有新数据
import time
current_ts = int(time.time() * 1000)
hours_since_update = (current_ts - max_ts) / (1000 * 3600)

conn.close()

# 输出状态
print(f"RECORDS:{total}")
print(f"SYMBOLS:{symbols}")
print(f"HOURS_SINCE_UPDATE:{hours_since_update:.1f}")

# 判断数据是否就绪: >500万记录, >40币种, <2小时未更新
if total > 5000000 and symbols >= 40 and hours_since_update < 2:
    print("STATUS:READY")
else:
    print("STATUS:NOT_READY")
PYEOF
}

# 检查是否已经在运行
check_running() {
    if pgrep -f "src.main" > /dev/null; then
        echo "RUNNING:yes"
    else
        echo "RUNNING:no"
    fi
}

# 启动实盘
launch_live() {
    cd "$PROJECT_ROOT"
    
    # 先运行扫描获取配对
    send_tg "🔄 数据已就绪，开始扫描配对..."
    
    source venv/bin/activate
    python run_scan.py --top 30 > logs/scan_launch.log 2>&1
    
    if [ ! -f "config/pairs_v2.json" ]; then
        send_tg "❌ 扫描失败，无配对配置"
        return 1
    fi
    
    PAIR_COUNT=$(grep -c '"signal_id"' config/pairs_v2.json 2>/dev/null || echo "0")
    send_tg "✅ 扫描完成，找到 $PAIR_COUNT 对交易对"
    
    # 启动实盘
    send_tg "🚀 启动实盘交易..."
    
    # 使用systemd服务启动
    sudo systemctl restart trading-s001.service 2>/dev/null || {
        # 如果没有systemd服务，直接启动
        nohup python -m src.main > logs/live_trading.log 2>&1 &
    }
    
    sleep 5
    
    if pgrep -f "src.main" > /dev/null; then
        send_tg "✅ S001-Pro 实盘已启动！\n📊 交易对: $PAIR_COUNT 对\n⏰ 启动时间: $(date '+%Y-%m-%d %H:%M:%S')"
        return 0
    else
        send_tg "❌ 启动失败，请检查日志"
        return 1
    fi
}

# 主流程
main() {
    echo "$(date) 检查数据状态..." >> "$LOG_FILE"
    
    # 检查数据
    DATA_STATUS=$(check_data)
    RECORDS=$(echo "$DATA_STATUS" | grep "RECORDS:" | cut -d: -f2)
    SYMBOLS=$(echo "$DATA_STATUS" | grep "SYMBOLS:" | cut -d: -f2)
    STATUS=$(echo "$DATA_STATUS" | grep "STATUS:" | cut -d: -f2)
    
    RUNNING=$(check_running | cut -d: -f2)
    
    echo "Records: $RECORDS, Symbols: $SYMBOLS, Status: $STATUS, Running: $RUNNING" >> "$LOG_FILE"
    
    # 如果数据就绪且未运行，启动实盘
    if [ "$STATUS" = "READY" ] && [ "$RUNNING" = "no" ]; then
        send_tg "📊 数据同步完成！\n• 记录数: $RECORDS\n• 币种数: $SYMBOLS\n准备启动实盘..."
        launch_live
    elif [ "$STATUS" = "READY" ] && [ "$RUNNING" = "yes" ]; then
        echo "数据就绪，但实盘已在运行，跳过" >> "$LOG_FILE"
    else
        echo "数据未就绪，继续等待..." >> "$LOG_FILE"
    fi
}

main "$@"
