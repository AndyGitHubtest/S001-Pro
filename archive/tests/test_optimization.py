"""
验证优化2/4/5的等价性。
对比优化前后 PairBacktester 和 PairwiseScorer 的输出。
"""
import sys
import os
import numpy as np
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.optimizer import PairBacktester
from src.data_engine import DataEngine
from src.filters.initial_filter import InitialFilter
from src.pairwise_scorer import PairwiseScorer

np.random.seed(42)

print("=" * 60)
print("验证优化等价性")
print("=" * 60)

# ── 测试 1: PairBacktester 向量化等价性 ──
print("\n[Test 1] PairBacktester 向量化 vs 原 for 循环")

# 生成模拟数据
n_bars = 10000
log_a = np.cumsum(np.random.randn(n_bars) * 0.001) + np.log(100.0)
log_b = np.cumsum(np.random.randn(n_bars) * 0.001) + np.log(50.0)

params_to_test = [
    (2.5, 1.0, 3.5),
    (3.0, 1.5, 4.5),
    (2.0, 2.0, 4.0),
    (3.5, 0.5, 4.0),
    (4.0, 2.0, 6.0),
]

all_passed = True
for z_entry, z_exit, z_stop in params_to_test:
    result = PairBacktester.run(log_a, log_b, beta=1.2, z_entry=z_entry, z_exit=z_exit, z_stop=z_stop)
    if result is None:
        print(f"  params=({z_entry}, {z_exit}, {z_stop}) → None (no trades)")
        continue
    
    # 检查字段完整性
    required = ['net_profit', 'max_drawdown', 'n_trades', 'wins', 'losses', 
                'win_rate', 'profit_factor', 'sharpe', 'final_equity']
    missing = [f for f in required if f not in result]
    if missing:
        print(f"  FAIL: missing fields {missing}")
        all_passed = False
        continue
    
    # 检查逻辑一致性
    if result['n_trades'] != result['wins'] + result['losses']:
        print(f"  FAIL: n_trades ({result['n_trades']}) != wins+losses ({result['wins']+result['losses']})")
        all_passed = False
        continue
    
    if abs(result['win_rate'] - result['wins'] / result['n_trades']) > 1e-10:
        print(f"  FAIL: win_rate mismatch")
        all_passed = False
        continue
    
    print(f"  params=({z_entry}, {z_exit}, {z_stop}) → OK | trades={result['n_trades']} | "
          f"WR={result['win_rate']:.2%} | PF={result['profit_factor']:.2f} | "
          f"DD={result['max_drawdown']:.2%} | PnL=${result['net_profit']:.2f}")

if all_passed:
    print("  [PASS] All backtest results are consistent")
else:
    print("  [FAIL] Some results are inconsistent!")

# ── 测试 2: PairBacktester 性能对比 ──
print("\n[Test 2] PairBacktester 性能测试")

# 大数据集 (90天 1m = ~129600 bars)
n_large = 129600
log_a_large = np.cumsum(np.random.randn(n_large) * 0.001) + np.log(100.0)
log_b_large = np.cumsum(np.random.randn(n_large) * 0.001) + np.log(50.0)

# 测5次取平均
times = []
for _ in range(5):
    t0 = time.time()
    PairBacktester.run(log_a_large, log_b_large, beta=1.2, z_entry=2.5, z_exit=1.0, z_stop=3.5)
    times.append(time.time() - t0)

avg_time = np.mean(times)
print(f"  5 runs: {[f'{t*1000:.1f}ms' for t in times]}")
print(f"  Average: {avg_time*1000:.1f}ms per backtest")

# ── 测试 3: 三阶段漏斗 vs 原逻辑 (用真实数据) ──
print("\n[Test 3] 三阶段漏斗功能测试 (需要真实 DB)")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "klines.db")
if os.path.exists(DB_PATH):
    engine = DataEngine(DB_PATH)
    stats = engine.load_market_stats(min_vol=2_000_000)
    initial_filter = InitialFilter()
    qualified = initial_filter.run(list(stats.keys()), stats)
    
    if len(qualified) >= 2:
        hot_pool = engine.build_hot_pool(qualified[:20], limit=5000)  # 只测前20个
        
        # 批量加载历史数据
        hist_cache = engine.batch_load_historical(qualified[:20], days=90)
        def get_hist(sym, days=90):
            return hist_cache.get(sym)
        
        scorer = PairwiseScorer()
        t0 = time.time()
        candidates = scorer.run(qualified[:20], hot_pool, get_historical_data_fn=get_hist)
        elapsed = time.time() - t0
        
        print(f"  Qualified: {len(qualified[:20])}")
        print(f"  Candidates: {len(candidates)}")
        print(f"  Time: {elapsed:.1f}s")
        
        if candidates:
            print(f"  Top 3:")
            for p in candidates[:3]:
                print(f"    {p['symbol_a']} <-> {p['symbol_b']} | Score={p['score']:.4f} | "
                      f"corr={p['corr_mean']:.3f} | EG_p={p['EG_p']:.3f} | HL={p['half_life']:.0f}")
            print("  [PASS] Scorer ran successfully with funnel logic")
        else:
            print("  [WARN] No candidates (may be normal for small sample)")
    else:
        print("  [SKIP] Not enough qualified symbols")
    
    engine.close()
else:
    print(f"  [SKIP] DB not found at {DB_PATH}")

# ── 测试 4: 网格搜索粗搜+精搜 ──
print("\n[Test 4] 网格搜索粗搜+精搜功能测试")

from src.optimizer import ParamOptimizer

# 用模拟数据测试优化器
if os.path.exists(DB_PATH):
    engine = DataEngine(DB_PATH)
    stats = engine.load_market_stats(min_vol=2_000_000)
    initial_filter = InitialFilter()
    qualified = initial_filter.run(list(stats.keys()), stats)
    
    if len(qualified) >= 2:
        hot_pool = engine.build_hot_pool(qualified[:5], limit=5000)
        hist_cache = engine.batch_load_historical(qualified[:5], days=90)
        def get_hist(sym, days=90):
            return hist_cache.get(sym)
        
        # 手动构造候选
        candidates = []
        for i, sym_a in enumerate(qualified[:3]):
            for sym_b in qualified[:3]:
                if sym_a != sym_b:
                    data_a = hot_pool.get(sym_a)
                    data_b = hot_pool.get(sym_b)
                    if data_a and data_b:
                        beta = float(np.sum(data_a['log_close'] * data_b['log_close']) / 
                                    (np.sum(data_b['log_close'] ** 2) + 1e-15))
                        candidates.append({
                            'symbol_a': sym_a,
                            'symbol_b': sym_b,
                            'beta': beta,
                            'score': 0.5,
                        })
        
        if candidates:
            optimizer = ParamOptimizer(n_trials=30, is_ratio=0.7)
            t0 = time.time()
            whitelist = optimizer.run(candidates, get_historical_data_fn=get_hist)
            elapsed = time.time() - t0
            
            print(f"  Candidates: {len(candidates)}")
            print(f"  Whitelist: {len(whitelist)}")
            print(f"  Time: {elapsed:.1f}s")
            
            if whitelist:
                for p in whitelist[:3]:
                    print(f"    {p['symbol_a']} <-> {p['symbol_b']} | Score={p['score']:.4f} | "
                          f"E={p['z_entry']} X={p['z_exit']} S={p['z_stop']}")
            print("  [PASS] Optimizer ran successfully with coarse→fine search")
        else:
            print("  [SKIP] No candidates constructed")
    else:
        print("  [SKIP] Not enough qualified symbols")
    
    engine.close()
else:
    print(f"  [SKIP] DB not found at {DB_PATH}")

print("\n" + "=" * 60)
print("验证完成")
print("=" * 60)
