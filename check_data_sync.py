#!/usr/bin/env python3
"""检查数据同步状态"""
import sqlite3
from datetime import datetime

db_path = '/home/ubuntu/projects/data-core/data/klines.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("="*60)
print("S001-Pro 数据同步状态检查")
print("="*60)

# 最新K线时间
cursor.execute("SELECT MAX(ts) FROM klines WHERE interval='1m'")
max_ts = cursor.fetchone()[0]
dt = datetime.fromtimestamp(max_ts/1000)
print(f"\n最新K线时间: {dt} (UTC)")
print(f"时间戳: {max_ts}")

# 计算时差
now = datetime.now().timestamp()
delay_minutes = (now - max_ts/1000) / 60
print(f"数据延迟: {delay_minutes:.1f} 分钟")

# 状态判断
if delay_minutes < 5:
    status = "✅ 数据实时"
elif delay_minutes < 60:
    status = "⚠️  数据略有延迟"
else:
    status = "❌ 数据严重滞后"
print(f"状态: {status}")

# 统计币种数
cursor.execute("SELECT COUNT(DISTINCT symbol) FROM klines WHERE interval='1m'")
symbols = cursor.fetchone()[0]
print(f"\n币种总数: {symbols}")

# 统计最近1小时有多少条数据
cursor.execute("SELECT COUNT(*) FROM klines WHERE interval='1m' AND ts > ?", (max_ts - 3600000,))
hour_count = cursor.fetchone()[0]
print(f"最近1小时K线数: {hour_count}")

# 检查market_stats表
try:
    cursor.execute("SELECT COUNT(*) FROM market_stats")
    stats_count = cursor.fetchone()[0]
    print(f"\nmarket_stats 记录数: {stats_count}")
except:
    print("\nmarket_stats 表不存在或为空")

conn.close()
print("\n" + "="*60)
