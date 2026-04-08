#!/usr/bin/env python3
"""S001-Pro 完整扫描测试"""
import time
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')

from src.main import run_scan_and_optimize

print('=== S001-Pro Scan Start ===')
t0 = time.time()

whitelist, total_cands, elapsed = run_scan_and_optimize('data/klines.db')

print(f'\n=== Results ===')
print(f'Total candidates from scorer: {total_cands}')
print(f'Whitelist pairs: {len(whitelist)}')
print(f'Elapsed: {elapsed:.0f}s ({elapsed/60:.1f}min)')

if whitelist:
    print('\nTop 10:')
    for i, p in enumerate(whitelist[:10], 1):
        stats = p.get('is_stats', {})
        print(f'  #{i:2d} {p["symbol_a"]:>10}/{p["symbol_b"]:<10} Score={p["score"]:.3f}  E={p["z_entry"]:.1f} X={p["z_exit"]:.1f} S={p["z_stop"]:.1f}  PF={stats.get("profit_factor",0):.2f} DD={stats.get("max_drawdown",0):.0%} N={stats.get("n_trades",0)}')
    
    # Test TG notification
    from src.optimizer import format_scan_notification
    msg = format_scan_notification(whitelist, total_cands, elapsed, '(test)')
    print(f'\n=== Telegram Message Preview (first 1000 chars) ===')
    print(msg[:1000])
else:
    print('No pairs found!')

print(f'\n=== Done in {elapsed:.0f}s ===')
sys.exit(0)
