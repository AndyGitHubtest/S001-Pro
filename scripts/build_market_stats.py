#!/usr/bin/env python3
"""
Build market_stats table from klines data.
Computes: vol_24h_usdt, high_24h, low_24h, close, kline_count, atr_14, kurtosis, first_ts
for each symbol.
"""

import sqlite3
import numpy as np
import time
import sys

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/klines.db"

print(f"Building market_stats from: {DB_PATH}")
conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA synchronous=NORMAL;")
c = conn.cursor()

# Create market_stats table if not exists
c.execute("""
    CREATE TABLE IF NOT EXISTS market_stats (
        symbol TEXT PRIMARY KEY,
        vol_24h_usdt REAL,
        high_24h REAL,
        low_24h REAL,
        close REAL,
        kline_count INTEGER,
        atr_14 REAL,
        kurtosis REAL,
        first_ts INTEGER
    )
""")

# Get all symbols
c.execute("SELECT DISTINCT symbol FROM klines WHERE interval='1m'")
symbols = [row[0] for row in c.fetchall()]
print(f"Found {len(symbols)} symbols")

t0 = time.time()
imported = 0

for i, sym in enumerate(symbols):
    # Get kline count
    c.execute("SELECT COUNT(*) FROM klines WHERE symbol=? AND interval='1m'", (sym,))
    kline_count = c.fetchone()[0]

    if kline_count == 0:
        continue

    # Get first timestamp
    c.execute("SELECT MIN(ts) FROM klines WHERE symbol=? AND interval='1m'", (sym,))
    first_ts = c.fetchone()[0]

    # Get latest 1440 rows (24h of 1m data)
    c.execute("""
        SELECT high, low, close, volume
        FROM klines
        WHERE symbol=? AND interval='1m'
        ORDER BY ts DESC
        LIMIT 1440
    """, (sym,))
    rows = c.fetchall()

    if not rows:
        continue

    highs = np.array([r[0] for r in rows if r[0] is not None], dtype=np.float64)
    lows = np.array([r[1] for r in rows if r[1] is not None], dtype=np.float64)
    closes = np.array([r[2] for r in rows if r[2] is not None], dtype=np.float64)
    volumes = np.array([r[3] for r in rows if r[3] is not None], dtype=np.float64)

    if len(highs) == 0:
        continue

    high_24h = float(np.max(highs))
    low_24h = float(np.min(lows))
    close = float(closes[-1])

    # Volume in USDT (approx: volume * close)
    vol_24h = float(np.sum(volumes * closes))

    # ATR_14
    atr = 0.0
    if len(closes) >= 15:
        trues = np.maximum(highs[1:] - lows[1:],
                   np.maximum(np.abs(highs[1:] - closes[:-1]),
                              np.abs(lows[1:] - closes[:-1])))
        atr = float(np.mean(trues[-14:])) if len(trues) >= 14 else 0.0

    # Kurtosis of returns
    kurt = 0.0
    if len(closes) >= 100:
        returns = np.diff(np.log(closes + 1e-15))
        if len(returns) > 3:
            kurt = float(np.mean(((returns - np.mean(returns)) / (np.std(returns) + 1e-15)) ** 4) - 3)

    c.execute("""
        INSERT OR REPLACE INTO market_stats
        (symbol, vol_24h_usdt, high_24h, low_24h, close, kline_count, atr_14, kurtosis, first_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sym, vol_24h, high_24h, low_24h, close, kline_count, atr, kurt, first_ts))

    if (i + 1) % 100 == 0:
        conn.commit()
        elapsed = time.time() - t0
        print(f"  Processed {i+1}/{len(symbols)} ({(i+1)/len(symbols)*100:.0f}%) - {elapsed:.1f}s")

conn.commit()

# Verify
c.execute("SELECT COUNT(*) FROM market_stats")
print(f"\nmarket_stats: {c.fetchone()[0]} rows")
c.execute("SELECT symbol, vol_24h_usdt, kline_count FROM market_stats ORDER BY vol_24h_usdt DESC LIMIT 5")
print("Top 5 by volume:")
for row in c.fetchall():
    print(f"  {row[0]}: vol={row[1]:.0f}, count={row[2]}")

conn.close()
print(f"Done in {time.time()-t0:.1f}s")
