#!/bin/bash
# 极速扫描启动脚本

cd ~/S001-Pro
source venv/bin/activate

echo "========================================"
echo "S001-Pro 极速扫描器 (3分钟目标)"
echo "========================================"

# 运行极速扫描
python3 fast_scanner.py

# 检查结果
if [ -f pairs_fast.json ]; then
    pairs_count=$(python3 -c "import json; print(len(json.load(open('pairs_fast.json'))['pairs']))")
    echo ""
    echo "✅ 极速扫描完成!"
    echo "产出配对: $pairs_count 个"
    
    # 询问是否覆盖pairs_v2.json
    if [ "$pairs_count" -gt 5 ]; then
        cp pairs_fast.json config/pairs_v2.json
        echo "✅ 已更新 pairs_v2.json"
        
        # 重启交易服务
        sudo systemctl restart trading-s001
        echo "✅ 交易服务已重启"
    else
        echo "⚠️ 配对数量不足($pairs_count)，未更新配置"
    fi
else
    echo "❌ 扫描失败，未产出 pairs_fast.json"
fi
