#!/bin/bash
# S001-Pro 服务器彻底重建脚本
# 执行：在服务器上运行 bash rebuild_server.sh

set -e  # 遇到错误立即退出

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     S001-Pro 服务器彻底重建脚本                                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

PROJECT_DIR="/home/ubuntu/strategies/S001-Pro-New"
GITHUB_REPO="https://github.com/AndyGitHubtest/S001-Pro.git"
DATA_SOURCE="/home/ubuntu/projects/data-core/data"

echo "════════════════════════════════════════════════════════════════"
echo "Phase 1: 彻底清理残留"
echo "════════════════════════════════════════════════════════════════"

# 1.1 停止所有进程
echo "[1/10] 停止所有S001相关进程..."
pkill -9 -f "S001" 2>/dev/null || true
pkill -9 -f "s001" 2>/dev/null || true
pkill -9 -f "src.main" 2>/dev/null || true
pkill -9 -f "uvicorn" 2>/dev/null || true
sleep 2
echo "✅ 进程已停止"

# 1.2 清理定时任务
echo "[2/10] 清理crontab中的S001任务..."
crontab -l 2>/dev/null | grep -v "S001\|s001" | crontab - 2>/dev/null || true
echo "✅ crontab已清理"

# 1.3 停止并删除系统服务
echo "[3/10] 停止并删除systemd服务..."
for service in s001-guardian s001-monitor-backend s001-monitor-frontend s001-sync scan-fast-s001 scan-s001 streaming-s001 trading-s001; do
    sudo systemctl stop ${service}.service 2>/dev/null || true
    sudo systemctl disable ${service}.service 2>/dev/null || true
    sudo rm -f /etc/systemd/system/${service}.service 2>/dev/null || true
    sudo rm -f /etc/systemd/system/${service}.timer 2>/dev/null || true
done
sudo systemctl daemon-reload 2>/dev/null || true
echo "✅ 系统服务已清理"

# 1.4 删除旧目录
echo "[4/10] 删除旧项目目录..."
rm -rf /home/ubuntu/S001-Pro 2>/dev/null || true
rm -rf /home/ubuntu/S001-Pro.backup.* 2>/dev/null || true
rm -rf /home/ubuntu/strategies/S001-Pro 2>/dev/null || true
echo "✅ 旧目录已删除"

# 1.5 清理临时文件
echo "[5/10] 清理/tmp下的S001文件..."
rm -rf /tmp/s001* 2>/dev/null || true
rm -rf /tmp/S001* 2>/dev/null || true
rm -f /tmp/trading-S001.lock 2>/dev/null || true
rm -f /tmp/s001_watchdog.pid 2>/dev/null || true
echo "✅ 临时文件已清理"

# 1.6 清理systemd timer标记
echo "[6/10] 清理systemd timer标记..."
sudo rm -f /var/lib/systemd/timers/stamp-*s001* 2>/dev/null || true
echo "✅ timer标记已清理"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "Phase 2: 创建新项目"
echo "════════════════════════════════════════════════════════════════"

# 2.1 创建项目目录
echo "[7/10] 创建新项目目录: ${PROJECT_DIR}..."
mkdir -p ${PROJECT_DIR}
cd ${PROJECT_DIR}
echo "✅ 目录已创建"

# 2.2 从GitHub克隆代码
echo "[8/10] 从GitHub克隆最新代码..."
git clone ${GITHUB_REPO} . 2>&1 | tail -5
echo "✅ 代码已克隆"

# 2.3 链接数据目录
echo "[9/10] 链接数据目录..."
mkdir -p data
if [ -f "${DATA_SOURCE}/klines.db" ]; then
    ln -sf ${DATA_SOURCE}/klines.db data/klines.db
    echo "✅ 数据已链接 (${DATA_SOURCE}/klines.db)"
else
    echo "⚠️ 数据源不存在，将使用空数据库"
    touch data/klines.db
fi

# 2.4 创建必要目录
echo "[10/10] 创建必要目录结构..."
mkdir -p logs data/recovery
touch data/state.json
touch data/daily_stats.json
echo "✅ 目录结构已创建"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "Phase 3: 环境配置"
echo "════════════════════════════════════════════════════════════════"

# 3.1 创建虚拟环境
echo "[1/3] 创建Python虚拟环境..."
python3 -m venv venv
source venv/bin/activate
echo "✅ 虚拟环境已创建"

# 3.2 安装依赖
echo "[2/3] 安装依赖包..."
pip install --upgrade pip -q
pip install "numpy>=1.24,<2.1" numba pandas pyyaml ccxt aiohttp python-telegram-bot -q 2>&1 | tail -3
echo "✅ 核心依赖已安装"

# 3.3 语法检查
echo "[3/3] 验证安装..."
python3 -c "import numpy; import ccxt; print(f'numpy: {numpy.__version__}')" 2>&1
echo "✅ 验证通过"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "重建完成!"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "项目路径: ${PROJECT_DIR}"
echo "数据链接: ${PROJECT_DIR}/data/klines.db -> ${DATA_SOURCE}/klines.db"
echo ""
echo "下一步:"
echo "1. 配置API: nano ${PROJECT_DIR}/config/base.yaml"
echo "2. 配置配对: nano ${PROJECT_DIR}/config/pairs_v2.json"
echo "3. 启动实盘: cd ${PROJECT_DIR} && source venv/bin/activate && python3 -m src.main --mode trade"
echo ""
echo "════════════════════════════════════════════════════════════════"
