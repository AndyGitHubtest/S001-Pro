#!/usr/bin/env python3
"""
S001-Pro Walk-Forward 回测脚本

用法: PYTHONPATH=. python3 run_backtest.py

对 config/pairs_v2.json 中的每个配对:
1. 加载 90 天 1分钟 K 线数据
2. 用 optimizer 中的 PairBacktester 跑实际参数
3. 汇总统计: 总 PnL, Sharpe, MaxDD, WinRate, 交易数, PF
"""
import json
import time
import logging
import numpy as np
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s'
)

from src.data_engine import DataEngine
from src.optimizer import PairBacktester

def run_walkforward_backtest(db_path: str = "data/klines.db", capital: float = 10000.0):
    # 加载配对列表
    with open("config/pairs_v2.json") as f:
        config = json.load(f)

    pairs = config.get("pairs", [])
    if not pairs:
        print("ERROR: No pairs in config/pairs_v2.json")
        return

    print(f"=== S001-Pro Walk-Forward Backtest ===")
    print(f"Pairs: {len(pairs)}")
    print(f"Capital per pair: ${capital:,.0f}")
    print(f"Cost per leg: 0.05% (fee + slippage)")
    print()

    engine = DataEngine(db_path)

    results = []
    t0 = time.time()

    for i, p in enumerate(pairs):
        sym_a = p["symbol_a"]  # e.g. "ALGO/USDT"
        sym_b = p["symbol_b"]  # e.g. "CTSI/USDT"
        beta = p.get("beta", 1.0)
        params = p.get("params", {})
        z_entry = params.get("z_entry", 2.5)
        z_exit = params.get("z_exit", 0.3)
        z_stop = params.get("z_stop", 4.0)

        # 加载历史数据
        hist_a = engine.get_historical_data(sym_a, days=90)
        hist_b = engine.get_historical_data(sym_b, days=90)

        if hist_a is None or hist_b is None:
            print(f"  [{i+1}/{len(pairs)}] {sym_a}/{sym_b}: SKIP (no data)")
            continue

        log_a = hist_a["log_close"]
        log_b = hist_b["log_close"]

        # 跑回测
        stats = PairBacktester.run(log_a, log_b, beta, z_entry, z_exit, z_stop,
                                   init_capital=capital, cost_pct=0.0005)

        if stats is None:
            print(f"  [{i+1}/{len(pairs)}] {sym_a}/{sym_b}: SKIP (no trades)")
            continue

        results.append({
            "symbol_a": sym_a,
            "symbol_b": sym_b,
            "beta": beta,
            "z_entry": z_entry,
            "z_exit": z_exit,
            "z_stop": z_stop,
            "net_profit": stats["net_profit"],
            "max_drawdown": stats["max_drawdown"],
            "n_trades": stats["n_trades"],
            "win_rate": stats["win_rate"],
            "profit_factor": stats["profit_factor"],
            "sharpe": stats["sharpe"],
            "wins": stats["wins"],
            "losses": stats["losses"],
        })

        print(f"  [{i+1:2d}/{len(pairs)}] {sym_a:>14}/{sym_b:<14} "
              f"PF={stats['profit_factor']:.2f} DD={stats['max_drawdown']:.1%} "
              f"N={stats['n_trades']:>3} WR={stats['win_rate']:.0%} "
              f"PnL=${stats['net_profit']:>8.0f} Sharpe={stats['sharpe']:.2f}")

    engine.close()

    elapsed = time.time() - t0
    print()
    print(f"=== Backtest Complete ({elapsed:.0f}s) ===")
    print()

    if not results:
        print("No results!")
        return

    # 汇总统计
    total_pnl = sum(r["net_profit"] for r in results)
    avg_dd = np.mean([r["max_drawdown"] for r in results])
    max_dd = max(r["max_drawdown"] for r in results)
    total_trades = sum(r["n_trades"] for r in results)
    avg_wr = np.mean([r["win_rate"] for r in results])
    avg_pf = np.mean([r["profit_factor"] for r in results])

    # 组合 Sharpe (所有交易 PnL 合并)
    all_pnls = []
    for r in results:
        # 用净PnL / 交易数近似
        if r["n_trades"] > 0:
            all_pnls.append(r["net_profit"] / r["n_trades"])

    if len(all_pnls) > 1:
        avg_pnl = np.mean(all_pnls)
        std_pnl = np.std(all_pnls)
        combo_sharpe = avg_pnl / (std_pnl + 1e-8) * np.sqrt(len(all_pnls))
    else:
        combo_sharpe = 0

    # 分类统计
    profitable = sum(1 for r in results if r["net_profit"] > 0)
    losing = sum(1 for r in results if r["net_profit"] <= 0)
    high_pf = sum(1 for r in results if r["profit_factor"] >= 1.5)
    low_dd = sum(1 for r in results if r["max_drawdown"] <= 0.10)

    print("=== Portfolio Summary ===")
    print(f"  Pairs traded:     {len(results)} / {len(pairs)}")
    print(f"  Total Net PnL:    ${total_pnl:>10,.0f}  (per pair ${total_pnl/len(results):,.0f})")
    print(f"  Total Trades:     {total_trades}")
    print(f"  Avg Win Rate:     {avg_wr:.1%}")
    print(f"  Avg Profit Factor:{avg_pf:.2f}")
    print(f"  Max Drawdown:     {max_dd:.1%}")
    print(f"  Avg Drawdown:     {avg_dd:.1%}")
    print(f"  Combo Sharpe:     {combo_sharpe:.2f}")
    print()
    print("=== Distribution ===")
    print(f"  Profitable pairs: {profitable} ({profitable/len(results):.0%})")
    print(f"  Losing pairs:     {losing} ({losing/len(results):.0%})")
    print(f"  PF >= 1.5:        {high_pf} ({high_pf/len(results):.0%})")
    print(f"  DD <= 10%:        {low_dd} ({low_dd/len(results):.0%})")
    print()

    # Top 5 and Bottom 5
    results_sorted = sorted(results, key=lambda x: x["net_profit"], reverse=True)
    print("=== Top 5 Pairs ===")
    for i, r in enumerate(results_sorted[:5], 1):
        print(f"  {i}. {r['symbol_a']}/{r['symbol_b']}  "
              f"PnL=${r['net_profit']:>8,.0f} PF={r['profit_factor']:.2f} "
              f"DD={r['max_drawdown']:.1%} N={r['n_trades']} WR={r['win_rate']:.0%}")

    print()
    print("=== Bottom 5 Pairs ===")
    for i, r in enumerate(results_sorted[-5:], 1):
        print(f"  {i}. {r['symbol_a']}/{r['symbol_b']}  "
              f"PnL=${r['net_profit']:>8,.0f} PF={r['profit_factor']:.2f} "
              f"DD={r['max_drawdown']:.1%} N={r['n_trades']} WR={r['win_rate']:.0%}")

    # 按 entry_z 分组
    print()
    print("=== By Entry Z ===")
    for e_val in sorted(set(r["z_entry"] for r in results)):
        grp = [r for r in results if r["z_entry"] == e_val]
        pnl = sum(r["net_profit"] for r in grp)
        pf = np.mean([r["profit_factor"] for r in grp])
        wr = np.mean([r["win_rate"] for r in grp])
        n = sum(r["n_trades"] for r in grp)
        print(f"  Entry={e_val:.1f}: {len(grp)} pairs, PnL=${pnl:,.0f}, PF={pf:.2f}, WR={wr:.0%}, N={n}")

    # 按 exit_z 分组
    print()
    print("=== By Exit Z ===")
    for x_val in sorted(set(r["z_exit"] for r in results)):
        grp = [r for r in results if r["z_exit"] == x_val]
        pnl = sum(r["net_profit"] for r in grp)
        pf = np.mean([r["profit_factor"] for r in grp])
        wr = np.mean([r["win_rate"] for r in grp])
        n = sum(r["n_trades"] for r in grp)
        print(f"  Exit={x_val:.1f}: {len(grp)} pairs, PnL=${pnl:,.0f}, PF={pf:.2f}, WR={wr:.0%}, N={n}")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "data/klines.db"
    run_walkforward_backtest(db)
