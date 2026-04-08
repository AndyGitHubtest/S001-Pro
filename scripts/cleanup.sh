#!/bin/bash
# S001-Pro 系统清理脚本
# 用法: ./scripts/cleanup.sh

set -e

echo "════════════════════════════════════════════════════════════"
echo "S001-Pro 系统清理"
echo "════════════════════════════════════════════════════════════"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# 1. 清理Python缓存
echo "[1/6] 清理Python缓存..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true
find . -type f -name ".DS_Store" -delete 2>/dev/null || true
echo "  ✓ Python缓存已清理"

# 2. 清理日志文件（保留最近7天）
echo "[2/6] 清理日志文件..."
find logs/ -name "*.log" -mtime +7 -delete 2>/dev/null || true
find logs/ -name "scan_*.log" -mtime +3 -delete 2>/dev/null || true
echo "  ✓ 旧日志已清理（保留7天）"

# 3. 清理临时文件
echo "[3/6] 清理临时文件..."
rm -f test_preflight.py debug_*.py *.pyc 2>/dev/null || true
rm -rf src/__pycache__ src/filters/__pycache__ 2>/dev/null || true
echo "  ✓ 临时文件已清理"

# 4. 清理备份文件
echo "[4/6] 清理备份文件..."
rm -rf src.backup.* 2>/dev/null || true
echo "  ✓ 备份文件已清理"

# 5. 清理Git垃圾
echo "[5/6] 清理Git垃圾..."
rm -f .git/gc.log 2>/dev/null || true
echo "  ✓ Git垃圾已清理"

# 6. 显示清理结果
echo "[6/6] 清理结果统计..."
echo ""
echo "目录大小变化:"
echo "  项目总大小: $(du -sh . | cut -f1)"
echo "  日志目录: $(du -sh logs/ 2>/dev/null | cut -f1)"
echo "  数据目录: $(du -sh data/ 2>/dev/null | cut -f1)"
echo ""

echo "════════════════════════════════════════════════════════════"
echo "✓ 清理完成"
echo "════════════════════════════════════════════════════════════"
