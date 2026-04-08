#!/usr/bin/env python3
"""
M3参数渐进式扫描工具

从极宽松到严格，逐步扫描，找到最佳参数组合
"""

import json
import sys
sys.path.insert(0, '/home/ubuntu/S001-Pro')

from src.data_engine import DataEngine
from src.filters.initial_filter import InitialFilter
from src.m3_selector import M3Selector

def run_scan_with_params(params_1m, params_5m, params_15m):
    """使用指定参数运行扫描"""
    engine = DataEngine()
    
    # M1
    stats = engine.load_market_stats(min_vol=5_000_000)
    
    # M2
    qualified = InitialFilter().run(list(stats.keys()), stats)
    
    # Build Hot Pool
    hot_pool = {}
    for sym in qualified:
        hist = engine.get_historical_data(sym, days=30)
        if hist:
            hot_pool[sym] = hist
    
    # Create selector with custom params
    selector = M3Selector()
    
    # Override thresholds
    for key, val in params_1m.items():
        selector.selector_1m.thresholds[key] = val
    for key, val in params_5m.items():
        selector.selector_5m.thresholds[key] = val
    for key, val in params_15m.items():
        selector.selector_15m.thresholds[key] = val
    
    # Run
    results = selector.run_all(qualified, hot_pool)
    
    engine.close()
    
    return {
        '1m': len(results['1m']),
        '5m': len(results['5m']),
        '15m': len(results['15m']),
        'total': sum(len(v) for v in results.values())
    }

# 参数扫描范围：从极宽松(Level 1)到严格(Level 5)
param_levels = {
    'Level_1_极宽松': {
        '1m': {'min_correlation': 0.05, 'coint_pvalue': 0.30, 'max_half_life': 200},
        '5m': {'min_correlation': 0.05, 'coint_pvalue': 0.30, 'max_half_life': 100},
        '15m': {'min_correlation': 0.05, 'coint_pvalue': 0.30, 'max_half_life': 60},
    },
    'Level_2_宽松': {
        '1m': {'min_correlation': 0.08, 'coint_pvalue': 0.25, 'max_half_life': 180},
        '5m': {'min_correlation': 0.08, 'coint_pvalue': 0.25, 'max_half_life': 90},
        '15m': {'min_correlation': 0.08, 'coint_pvalue': 0.25, 'max_half_life': 50},
    },
    'Level_3_中等': {
        '1m': {'min_correlation': 0.10, 'coint_pvalue': 0.20, 'max_half_life': 150},
        '5m': {'min_correlation': 0.10, 'coint_pvalue': 0.20, 'max_half_life': 80},
        '15m': {'min_correlation': 0.10, 'coint_pvalue': 0.20, 'max_half_life': 45},
    },
    'Level_4_偏严': {
        '1m': {'min_correlation': 0.12, 'coint_pvalue': 0.15, 'max_half_life': 120},
        '5m': {'min_correlation': 0.12, 'coint_pvalue': 0.15, 'max_half_life': 60},
        '15m': {'min_correlation': 0.12, 'coint_pvalue': 0.15, 'max_half_life': 36},
    },
    'Level_5_严格': {
        '1m': {'min_correlation': 0.15, 'coint_pvalue': 0.10, 'max_half_life': 100},
        '5m': {'min_correlation': 0.15, 'coint_pvalue': 0.10, 'max_half_life': 50},
        '15m': {'min_correlation': 0.15, 'coint_pvalue': 0.10, 'max_half_life': 30},
    },
}

print("=" * 70)
print("M3参数渐进式扫描")
print("=" * 70)
print()

results_summary = []

for level_name, params in param_levels.items():
    print(f"\n正在扫描: {level_name}")
    print(f"  1m: corr≥{params['1m']['min_correlation']}, coint≤{params['1m']['coint_pvalue']}, HL≤{params['1m']['max_half_life']}")
    print(f"  5m: corr≥{params['5m']['min_correlation']}, coint≤{params['5m']['coint_pvalue']}, HL≤{params['5m']['max_half_life']}")
    print(f"  15m: corr≥{params['15m']['min_correlation']}, coint≤{params['15m']['coint_pvalue']}, HL≤{params['15m']['max_half_life']}")
    
    try:
        result = run_scan_with_params(params['1m'], params['5m'], params['15m'])
        print(f"  → 产出: 1m={result['1m']}, 5m={result['5m']}, 15m={result['15m']}, total={result['total']}")
        
        results_summary.append({
            'level': level_name,
            'params': params,
            'output': result
        })
    except Exception as e:
        print(f"  → 错误: {e}")

print("\n" + "=" * 70)
print("扫描结果汇总")
print("=" * 70)

for r in results_summary:
    level = r['level']
    out = r['output']
    print(f"\n{level}:")
    print(f"  产出: 1m={out['1m']:3d}, 5m={out['5m']:3d}, 15m={out['15m']:3d}, total={out['total']:3d}")

# 推荐最佳参数
print("\n" + "=" * 70)
print("推荐参数")
print("=" * 70)

# 寻找产出在10-50之间的最佳平衡点
best_level = None
for r in results_summary:
    total = r['output']['total']
    if 10 <= total <= 50:
        best_level = r
        break

if best_level:
    print(f"\n推荐: {best_level['level']}")
    print(f"总产出: {best_level['output']['total']} pairs (1m={best_level['output']['1m']}, 5m={best_level['output']['5m']}, 15m={best_level['output']['15m']})")
    print("\n参数设置:")
    for tf in ['1m', '5m', '15m']:
        p = best_level['params'][tf]
        print(f"  {tf}: corr≥{p['min_correlation']}, coint≤{p['coint_pvalue']}, HL≤{p['max_half_life']}")
else:
    # 如果没有落在10-50之间，推荐产出最接近30的
    closest = min(results_summary, key=lambda x: abs(x['output']['total'] - 30))
    print(f"\n推荐: {closest['level']} (最接近理想产出30)")
    print(f"总产出: {closest['output']['total']} pairs")

# 保存结果
with open('param_scan_results.json', 'w') as f:
    json.dump(results_summary, f, indent=2)
print("\n详细结果已保存至: param_scan_results.json")
