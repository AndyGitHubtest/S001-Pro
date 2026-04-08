#!/bin/bash
# S001-Pro 重启重置脚本 - 每次启动前清空状态

set -e

echo "=========================================="
echo "S001-Pro 重启重置"
echo "=========================================="

# 1. 清空配对配置
echo "[1/4] 清空配对配置..."
echo '{"pairs": [], "version": "2.0", "generated_at": ""}' > /home/ubuntu/strategies/S001-Pro/config/pairs_v2.json

# 2. 清空状态文件
echo "[2/4] 清空状态文件..."
echo '{}' > /home/ubuntu/strategies/S001-Pro/data/state.json 2>/dev/null || true

# 3. 清空恢复数据
echo "[3/4] 清空恢复数据..."
rm -f /home/ubuntu/strategies/S001-Pro/data/recovery/*.json 2>/dev/null || true

# 4. 清理缓存
echo "[4/4] 清理 Python 缓存..."
cd /home/ubuntu/strategies/S001-Pro
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "=========================================="
echo "重置完成，启动服务..."
echo "=========================================="

# 启动服务
sudo systemctl start trading-s001.service

# 等待并显示状态
sleep 3
sudo systemctl status trading-s001.service --no-pager
