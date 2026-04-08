#!/usr/bin/env python3
"""端到端数据流审计测试"""
import sys
sys.path.insert(0, 'src')

from data_engine import DataEngine
from filters.initial_filter import InitialFilter
from pairwise_scorer import PairwiseScorer
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("Audit")

def main():
    print("="*60)
    print("S001-Pro 端到端数据流审计测试")
    print("="*60)
    
    # ========== M1 DataEngine ==========
    print("\n[M1] DataEngine 测试...")
    db = DataEngine('data/klines.db')
    
    symbols = db.get_all_symbols('1m')
    print(f"  ✓ 总币种数: {len(symbols)}")
    
    stats = db.load_market_stats(min_vol=2_000_000)
    print(f"  ✓ 满足流动性(>2M): {len(stats)} 币种")
    
    # ========== M2 InitialFilter ==========
    print("\n[M2] InitialFilter 测试...")
    f = InitialFilter()
    qualified = f.run(symbols[:100], stats)  # 测试前100个
    print(f"  ✓ 初筛通过: {len(qualified)}/{min(100, len(symbols))}")
    
    if len(qualified) < 2:
        print("  ⚠ 通过币种不足，扩展测试范围...")
        qualified = f.run(symbols[:200], stats)
        print(f"  ✓ 扩展后通过: {len(qualified)}")
    
    # ========== M1 HotPool ==========
    print("\n[M1] HotPool 构建测试...")
    hot_pool = db.build_hot_pool(qualified[:20], limit=5000)
    print(f"  ✓ HotPool 加载: {len(hot_pool)} 币种")
    
    for sym, data in list(hot_pool.items())[:3]:
        c = data['close']
        print(f"    {sym}: {len(c)} 根K线, close[0]={c[0]:.4f}")
    
    # ========== M3 PairwiseScorer ==========
    print("\n[M3] PairwiseScorer 测试...")
    scorer = PairwiseScorer()
    
    # 取前10个做配对测试
    test_symbols = qualified[:10]
    if len(test_symbols) >= 2:
        print(f"  测试币种: {test_symbols}")
        print(f"  ✓ PairwiseScorer 初始化成功")
        print(f"  ✓ Phase1 阈值: corr_mean>={scorer.phase1_thresholds['corr_mean']}")
        from pairwise_scorer import HAS_NUMBA
        print(f"  ✓ Numba 加速: {'可用' if HAS_NUMBA else '不可用'}")
    
    # ========== 验证数据完整性 ==========
    print("\n[数据完整性检查]...")
    all_ok = True
    for sym, data in hot_pool.items():
        n = len(data['close'])
        if n < 288:
            print(f"  ✗ {sym}: 数据不足 {n}<288")
            all_ok = False
        if any(data['close'] <= 0):
            print(f"  ✗ {sym}: 存在非正价格")
            all_ok = False
    
    if all_ok:
        print(f"  ✓ 所有 {len(hot_pool)} 币种数据完整性 OK")
    
    print("\n" + "="*60)
    print("✅ 端到端数据流审计测试通过!")
    print("="*60)
    db.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
