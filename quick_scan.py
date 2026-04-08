"""
Quick Scan with optimized batch historical data loading.
"""

import sys
import os
import time
import logging
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_engine import DataEngine
from src.filters.initial_filter import InitialFilter
from src.pairwise_scorer import PairwiseScorer

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/klines.db"

if not os.path.exists(DB_PATH):
    print(f"DB not found: {DB_PATH}")
    sys.exit(1)

print(f"DB: {DB_PATH} ({os.path.getsize(DB_PATH) / 1024**3:.2f} GB)")
print("=" * 60)

# M1: Data Engine
t0 = time.time()
print("[M1] Initializing DataEngine...")
engine = DataEngine(DB_PATH)

print("[M1] Getting symbols...")
all_symbols = engine.get_all_symbols(interval="1m")
print(f"  Found {len(all_symbols)} unique symbols")

print("[M1] Loading market stats...")
stats = engine.load_market_stats(min_vol=2_000_000)
print(f"  {len(stats)} symbols with vol >= 2M USDT")
t1 = time.time()
print(f"  M1 done: {t1-t0:.1f}s")

# M2: Initial Filter
print("[M2] Running 6-layer filter...")
initial_filter = InitialFilter()
qualified = initial_filter.run(list(stats.keys()), stats)
print(f"  {len(qualified)} symbols passed all filters")
t2 = time.time()
print(f"  M2 done: {t2-t1:.1f}s")

if len(qualified) < 2:
    print("Not enough qualified symbols. Exiting.")
    engine.close()
    sys.exit(0)

# M1: Build Hot Pool
print(f"[M1] Building Hot Pool (5000 bars x {len(qualified)} symbols)...")
hot_pool = engine.build_hot_pool(qualified, limit=5000)
print(f"  Hot Pool: {len(hot_pool)} symbols loaded")
t3 = time.time()
print(f"  Hot Pool done: {t3-t2:.1f}s")

# Batch load historical data (1 SQL query instead of N)
print("[M1] Batch-loading historical data for all symbols (90d)...")
hist_cache = engine.batch_load_historical(qualified, days=90)
# Fallback for symbols not in batch result
for sym in qualified:
    if sym not in hist_cache:
        hp = hot_pool.get(sym)
        if hp:
            hist_cache[sym] = {
                'close': hp['close'],
                'log_close': hp['log_close'],
                'volume': hp['volume'],
            }
print(f"  Historical cache: {len(hist_cache)} symbols")
t4 = time.time()
print(f"  Historical load done: {t4-t3:.1f}s")

def get_hist_cached(sym, days=90):
    return hist_cache.get(sym)

# M3: Pairwise Scorer
print("[M3] Running Pairwise Scorer (10 metrics)...")
scorer = PairwiseScorer()
candidates = scorer.run(qualified, hot_pool, get_historical_data_fn=get_hist_cached)
print(f"  {len(candidates)} pairs passed 10-filter + scoring")
if candidates:
    print("  Top 10 pairs:")
    for p in candidates[:10]:
        print(f"    {p['symbol_a']} <-> {p['symbol_b']} | Score={p['score']} | "
              f"corr={p['corr_mean']} | EG_p={p['EG_p']} | ADF_p={p['ADF_p']} | HL={p['half_life']}")
t5 = time.time()
print(f"  M3 done: {t5-t4:.1f}s")

print("=" * 60)
total = time.time() - t0
print(f"TOTAL TIME: {total:.1f}s")
print(f"Results: {len(qualified)} qualified symbols, {len(candidates)} candidate pairs")

engine.close()
