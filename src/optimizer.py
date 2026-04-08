"""
模块四：回测优化 (Optimizer) - P0 LOCKED (Numba 加速)

数据流转:
  Input:
    1. Candidates (Top 100 List, 来自模块三)
    2. History Data (90 天全量 K 线, 来自模块一)
  Output: Whitelist (List[Dict]), Top 30
  去向: 传递给模块五 (Persistence)

搜索:
  分层启发式 + IS/OS切分: Phase1+2用81%数据(IS)训练, 最优参数用19%(OS)验证
  硬门槛: PF>=1.5 / MaxDD<=20% / TradeCount>=10
  五维评分: P(30%), R(20%), S(15%), E(15%), St(10%)
  IS/OS切分: 前81%训练参数, 后19%验证 (防过拟合, OS的PF<1.0淘汰)

加速:
  - Numba @njit JIT 编译: 单次回测 ~0.01s
  - 多进程并行: 4 核同时跑
  - 提前终止: 回测前 50% 数据交易数不足2笔 -> 跳过

文档规范: docs/module_4_optimizer.md
"""

import numpy as np
import logging
import urllib.request
import urllib.parse
from typing import List, Dict, Optional, Callable, Tuple
from multiprocessing import Pool, cpu_count

logger = logging.getLogger("Optimizer")

# ──────────────────────────────────────────────
# 回测配置常量
# ──────────────────────────────────────────────
Z_WARMUP = 200              # Z-score 扩窗预热根数
IS_RATIO = 0.81             # IS/OS 切分比例 (前 67% 训练, 后 33% 验证)
MIN_TRADES_HARD_GATE = 10   # 硬门槛: 90天最少交易数
MAX_DD_HARD_GATE = 0.20     # 硬门槛: 最大回撤
MIN_PF_HARD_GATE = 1.5      # 硬门槛: 最小盈利因子 (亏1必赚1.5)
MIN_PF_OS_GATE = 1.5        # OS 验证门槛: PF>=1.5 才放行 (只保留有利润的)
COST_PER_LEG = 0.0005       # 单腿成本 (手续费0.05% + 滑点0.05%)
COST_ROUND_TRIP = COST_PER_LEG * 4  # 4腿总成本 = 0.2%


# ═══════════════════════════════════════════════════
# Numba JIT 编译回测核心
# ═══════════════════════════════════════════════════
try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*args, **kwargs):
        def decorator(f):
            return f
        return decorator


@njit(cache=True)
def _backtest_core(
    log_a: np.ndarray,
    log_b: np.ndarray,
    beta: float,
    z_entry: float,
    z_exit: float,
    z_stop: float,
    init_capital: float,
    cost_pct: float,
    early_abort_check: int = 0,
):
    """
    Numba JIT 回测核心。纯数值计算，无 Python 对象。
    返回 tuple: (n_trades, wins, losses, gross_profit, gross_loss, max_dd, final_equity, early_abort)
    """
    n = min(len(log_a), len(log_b))
    if n < 300:
        return (0, 0, 0, 0.0, 0.0, 0.0, init_capital, 1)

    spread = log_a[:n] - beta * log_b[:n]
    warmup = Z_WARMUP
    if n < warmup + 100:
        return (0, 0, 0, 0.0, 0.0, 0.0, init_capital, 1)

    # Welford 增量 Z-score
    z_series = np.zeros(n)
    count = 0
    mean = 0.0
    M2 = 0.0
    for i in range(warmup, n):
        x = spread[i]
        count += 1
        delta = x - mean
        mean += delta / count
        delta2 = x - mean
        M2 += delta * delta2
        variance = M2 / count if count > 0 else 0.0
        std = variance ** 0.5
        if std < 1e-8:
            z_series[i] = 0.0
        else:
            z_series[i] = (spread[i] - mean) / std

    # 状态机回测
    equity = init_capital
    peak_equity = init_capital
    max_dd = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    wins = 0
    losses = 0
    trade_count = 0

    position = 0
    direction = 0
    entry_price_a = 0.0
    entry_price_b = 0.0

    # Early abort checkpoint
    if early_abort_check > 0:
        checkpoint = min(warmup + early_abort_check, n)
    else:
        checkpoint = n

    for i in range(warmup, n):
        z = z_series[i]
        abs_z = abs(z)

        if position == 0:
            if z >= z_entry:
                direction = -1
                entry_price_a = np.exp(log_a[i])
                entry_price_b = np.exp(log_b[i])
                position = 1
            elif z <= -z_entry:
                direction = 1
                entry_price_a = np.exp(log_a[i])
                entry_price_b = np.exp(log_b[i])
                position = 1

        elif position == 1:
            exit_price_a = np.exp(log_a[i])
            exit_price_b = np.exp(log_b[i])
            pnl = 0.0

            notional = init_capital / 2.0
            qty_a = notional / (entry_price_a + 1e-15)
            qty_b = notional / (entry_price_b + 1e-15)

            if direction == 1:
                pnl = (exit_price_a - entry_price_a) * qty_a + (entry_price_b - exit_price_b) * qty_b
            else:
                pnl = (entry_price_a - exit_price_a) * qty_a + (exit_price_b - entry_price_b) * qty_b

            # 扣除 4 腿成本
            total_cost = cost_pct * 4 * notional
            pnl -= total_cost

            # 检查出场条件
            if abs_z >= z_stop or (direction == -1 and z <= z_exit) or (direction == 1 and z >= -z_exit):
                position = 0
                direction = 0

                equity += pnl
                trade_count += 1

                if pnl > 0:
                    gross_profit += pnl
                    wins += 1
                else:
                    gross_loss += abs(pnl)
                    losses += 1

                if equity > peak_equity:
                    peak_equity = equity
                dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
                if dd > max_dd:
                    max_dd = dd

        # Early abort: 到 checkpoint 时交易数不足 2 笔，提前终止
        if i == checkpoint and trade_count < 2:
            return (trade_count, wins, losses, gross_profit, gross_loss, max_dd, equity, 1)

    return (trade_count, wins, losses, gross_profit, gross_loss, max_dd, equity, 0)


class PairBacktester:
    """
    单配对回测引擎 (Numba JIT 加速)。
    """

    @staticmethod
    def run(
        log_close_a: np.ndarray,
        log_close_b: np.ndarray,
        beta: float,
        z_entry: float,
        z_exit: float,
        z_stop: float,
        init_capital: float = 10000.0,
        cost_pct: float = COST_PER_LEG,
        early_abort: bool = True,
    ) -> Dict:
        """
        执行回测。
        early_abort: 回测前 50% 数据交易数 < 2 时提前终止
        """
        n = min(len(log_close_a), len(log_close_b))
        if n < 300:
            return None

        warmup = Z_WARMUP
        if n < warmup + 100:
            return None

        early_check = int(n * 0.5) if early_abort else 0

        n_trades, wins, losses, gross_profit, gross_loss, max_dd, final_equity, aborted = _backtest_core(
            log_close_a, log_close_b, beta, z_entry, z_exit, z_stop,
            init_capital, cost_pct, early_check
        )

        if n_trades == 0:
            return None

        win_rate = wins / n_trades
        pf = gross_profit / (gross_loss + 1e-8)
        net_profit = final_equity - init_capital

        if n_trades > 1:
            avg_pnl = net_profit / n_trades
            std_pnl = (gross_profit + gross_loss) / (n_trades + 1e-8) * 0.5
            sharpe = avg_pnl / (std_pnl + 1e-8) * (n_trades ** 0.5)
        else:
            sharpe = 0

        return {
            'net_profit': net_profit,
            'max_drawdown': max_dd,
            'n_trades': n_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'profit_factor': pf,
            'sharpe': sharpe,
            'final_equity': final_equity,
            'aborted': aborted,
        }


# ═══════════════════════════════════════════════════
# 多进程并行优化器
# ═══════════════════════════════════════════════════

def _optimize_single_pair(args):
    """
    单对配对的参数优化 (用于多进程)。
    独立函数，便于 pickle。

    IS/OS 切分:
      Phase1+2: 用前 67% 数据 (IS) 搜索最优参数
      OS 验证: 用后 33% 数据 (OS) 验证最优参数, PF<1.0 淘汰
    """
    idx, total, sym_a, sym_b, beta, log_a, log_b = args

    n = min(len(log_a), len(log_b))
    if n < 300:
        return None

    # IS/OS 切分
    is_end = int(n * IS_RATIO)
    log_a_is = log_a[:is_end]
    log_b_is = log_b[:is_end]
    log_a_os = log_a[is_end:]
    log_b_os = log_b[is_end:]

    if len(log_a_is) < 300 or len(log_a_os) < 300:
        return None

    best_score = -999.0
    best_params = None
    best_is_stats = None

    # ═══════════════════════════════════════════════════
    # Phase 1: 粗扫 entry 甜点区 (IS 数据)
    # ═══════════════════════════════════════════════════
    phase1_results = []

    entries_p1 = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    for e in entries_p1:
        x = 0.5
        s = e + 1.0

        stats = PairBacktester.run(log_a_is, log_b_is, beta, e, x, s, early_abort=True)
        # 修复HIGH-001: 使用常量 MIN_TRADES_HARD_GATE (10笔) 而非硬编码3
        if stats is None or stats['n_trades'] < MIN_TRADES_HARD_GATE:
            continue

        sc = _score_result(stats)
        if sc > -1.0:
            phase1_results.append((sc, e, stats))

    phase1_results.sort(key=lambda r: r[0], reverse=True)
    top3_entries = phase1_results[:3]

    if not top3_entries:
        return None

    # ═══════════════════════════════════════════════════
    # Phase 2: 精细搜索 (IS 数据)
    # ═══════════════════════════════════════════════════
    fine_range = 0.3
    fine_exits = [0.3, 0.8, 1.3]
    fine_stop_offsets = [0.5, 1.0, 1.5]

    for _, best_e, _ in top3_entries:
        e_min = max(2.0, round(best_e - fine_range, 1))
        e_max = min(7.0, round(best_e + fine_range, 1))
        fine_entries = []
        e_val = e_min
        while e_val <= e_max + 1e-9:
            fine_entries.append(round(e_val, 1))
            e_val += 0.1

        for e in fine_entries:
            for x in fine_exits:
                for offset in fine_stop_offsets:
                    s = round(e + offset, 1)

                    if x >= e or s <= e:
                        continue

                    stats = PairBacktester.run(log_a_is, log_b_is, beta, e, x, s, early_abort=True)
                    # 修复HIGH-001: 使用常量 MIN_TRADES_HARD_GATE (10笔)
                    if stats is None or stats['n_trades'] < MIN_TRADES_HARD_GATE:
                        continue

                    sc = _score_result(stats)
                    if sc > best_score:
                        best_score = sc
                        best_params = {'z_entry': e, 'z_exit': x, 'z_stop': s}
                        best_is_stats = stats

    if best_params is None:
        return None

    # ═══════════════════════════════════════════════════
    # OS 验证: 用最优参数跑 OS 数据, PF<1.0 淘汰
    # ═══════════════════════════════════════════════════
    os_stats = PairBacktester.run(
        log_a_os, log_b_os, beta,
        best_params['z_entry'], best_params['z_exit'], best_params['z_stop'],
        early_abort=False
    )

    if os_stats is None:
        return None

    os_pf = os_stats.get('profit_factor', 0)
    if os_pf < MIN_PF_OS_GATE:
        return None

    logger.info(f"Optimizer: {sym_a}/{sym_b} Score={best_score:.3f} Params={best_params} "
               f"IS:PF={best_is_stats.get('profit_factor',0):.2f} DD={best_is_stats.get('max_drawdown',0):.1%} N={best_is_stats.get('n_trades',0)} | "
               f"OS:PF={os_pf:.2f} DD={os_stats.get('max_drawdown',0):.1%} N={os_stats.get('n_trades',0)}")

    return {
        'symbol_a': sym_a,
        'symbol_b': sym_b,
        'beta': beta,
        'params': best_params,
        'z_entry': best_params['z_entry'],
        'z_exit': best_params['z_exit'],
        'z_stop': best_params['z_stop'],
        'score': round(best_score, 4),
        'is_stats': {
            'profit_factor': best_is_stats.get('profit_factor', 0),
            'max_drawdown': best_is_stats.get('max_drawdown', 0),
            'n_trades': best_is_stats.get('n_trades', 0),
            'win_rate': best_is_stats.get('win_rate', 0),
            'sharpe': best_is_stats.get('sharpe', 0),
            'net_profit': best_is_stats.get('net_profit', 0),
        },
        'os_stats': {
            'profit_factor': os_stats.get('profit_factor', 0),
            'max_drawdown': os_stats.get('max_drawdown', 0),
            'n_trades': os_stats.get('n_trades', 0),
            'win_rate': os_stats.get('win_rate', 0),
            'sharpe': os_stats.get('sharpe', 0),
            'net_profit': os_stats.get('net_profit', 0),
        },
    }


def _score_result(stats: Dict) -> float:
    """硬门槛过滤 + 评分"""
    if stats['profit_factor'] < MIN_PF_HARD_GATE:
        return -1.0
    if stats['max_drawdown'] > MAX_DD_HARD_GATE:
        return -1.0
    if stats['n_trades'] < MIN_TRADES_HARD_GATE:
        return -1.0

    return _six_dim_score(stats)


def _six_dim_score(stats: Dict) -> float:
    """
    五维加权评分 (归一化 0~1):
    P(30%): min(NetProfit/50%, 1.0)
    R(20%): max(0, 1 - MaxDD/20%)
    S(15%): min(Sharpe/2.0, 1.0)
    E(15%): min(log(N+1)/log(101), 1.0)
    St(10%): min((WR-40%)/20%, 1.0)
    """
    net_profit_pct = stats.get('net_profit', 0) / 10000.0
    p = min(max(net_profit_pct / 0.5, 0), 1.0)

    max_dd = stats.get('max_drawdown', 0)
    r = max(0, 1 - (max_dd / 0.20))

    sharpe = stats.get('sharpe', 0)
    s = min(max(sharpe / 2.0, 0), 1.0)

    n_trades = stats.get('n_trades', 0)
    e = min(np.log(n_trades + 1) / np.log(101), 1.0)

    wr = stats.get('win_rate', 0)
    st = min(max((wr - 0.4) / 0.2, 0), 1.0)

    score = 0.30 * p + 0.20 * r + 0.15 * s + 0.15 * e + 0.10 * st
    return score


# ==============================================
# Telegram 扫描结果推送 (同步, 无外部依赖)
# ==============================================

def _send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """同步发送 Telegram 消息 (urllib)"""
    url = "https://api.telegram.org/bot{}/sendMessage".format(bot_token)
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logging.getLogger("Optimizer").error("TG notify failed: %s", e)
        return False


def format_scan_notification(whitelist, total_candidates=0,
                              elapsed_sec=0, scan_id=""):
    """格式化扫描结果为 Telegram HTML 消息 (<=4096字符)"""
    n = len(whitelist)
    lines = [
        "📊 S001-Pro 扫描完成 {}".format(scan_id),
        "━━━━━━━━━━━━━━━━━━━━",
        "配对数: <b>{}</b> / 候选 {}".format(n, total_candidates),
        "耗时: <b>{:.0f}秒</b> ({:.1f}分钟)".format(elapsed_sec, elapsed_sec/60),
        "",
        "🏆 <b>Top {} 配对</b>".format(min(n, 30)),
        "",
    ]

    for i, p in enumerate(whitelist[:30], 1):
        sym_a = p.get("symbol_a", "?")
        sym_b = p.get("symbol_b", "?")
        e = p.get("z_entry", 0)
        x = p.get("z_exit", 0)
        s = p.get("z_stop", 0)
        score = p.get("score", 0)
        stats = p.get("is_stats", {})
        pf = stats.get("profit_factor", 0)
        dd = stats.get("max_drawdown", 0)
        trades = stats.get("n_trades", 0)
        wr = stats.get("win_rate", 0)
        pnl = stats.get("net_profit", 0)

        lines.append(
            "<b>#{:2d}</b> {}/{}  Score={:.3f}"
            "  E={:.1f} X={:.1f} S={:.1f}"
            "  PF={:.2f} DD={:.0%} N={} WR={:.0%} PnL=${:.0f}".format(
                i, sym_a, sym_b, score, e, x, s, pf, dd, trades, wr, pnl
            )
        )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ 以上为回测结果, 不构成投资建议")

    msg = "\n".join(lines)

    if len(msg) > 4000:
        lines_short = lines[:6]
        for i, p in enumerate(whitelist[:20], 1):
            sym_a = p.get("symbol_a", "?")
            sym_b = p.get("symbol_b", "?")
            score = p.get("score", 0)
            stats = p.get("is_stats", {})
            pf = stats.get("profit_factor", 0)
            dd = stats.get("max_drawdown", 0)
            trades = stats.get("n_trades", 0)
            pnl = stats.get("net_profit", 0)
            lines_short.append(
                "<b>#{:2d}</b> {}/{}  Score={:.3f}  PF={:.2f} DD={:.0%} N={} PnL=${:.0f}".format(
                    i, sym_a, sym_b, score, pf, dd, trades, pnl
                )
            )
        lines_short.append("")
        lines_short.append("━━━━━━━━━━━━━━━━━━━━")
        lines_short.append("⚠️ 以上为回测结果, 不构成投资建议")
        msg = "\n".join(lines_short)

    return msg


def notify_scan_results(whitelist, bot_token, chat_id,
                        total_candidates=0, elapsed_sec=0,
                        scan_id="") -> bool:
    """扫描完成后推送 Top 30 到 Telegram"""
    if not bot_token or not chat_id:
        logging.getLogger("Optimizer").warning("TG notify skipped: no token/chat_id")
        return False

    if not whitelist:
        msg = "📊 S001-Pro 扫描完成\n\n❌ 无有效配对, 本次扫描未产出结果"
        return _send_telegram_message(bot_token, chat_id, msg)

    msg = format_scan_notification(whitelist, total_candidates, elapsed_sec, scan_id)
    return _send_telegram_message(bot_token, chat_id, msg)


class ParamOptimizer:
    """
    分层启发式搜索: Phase1 粗扫 entry 甜点区 + Phase2 Top3 精细搜索 + IS/OS验证。
    目的: 在合理时间内(0.1步长)找到最优参数, 并用样本外数据验证防过拟合。

    Phase1: entry 2.0~6.0 (0.5步长), exit=0.5固定, stop=entry+1.0 -> 9次 (IS数据)
    Phase2: 围绕 Top3 entry, +-0.3范围 0.1步长 (IS数据)
      - entry: +-0.3 (0.1步长, ~7个)
      - exit: [0.3, 0.8, 1.3] (止盈3档)
      - stop_offset: [0.5, 1.0, 1.5] (止损offset 3档)
    Phase2 per top: ~63次, 3个top = ~189次 (IS数据)
    OS验证: 最优参数跑后33%数据, PF>=1.0才放行
    总计: ~200次/对 (Numba 加速后 100对约 2-5 分钟)
    """

    def __init__(self, is_ratio: float = IS_RATIO, n_workers: int = None):
        self.is_ratio = is_ratio
        if n_workers is None:
            n_workers = min(cpu_count(), 4)
        self.n_workers = n_workers

    def run(
        self,
        candidates: List[Dict],
        get_historical_data_fn: Callable,
    ) -> List[Dict]:
        """
        对每个候选配对执行参数搜索 (IS/OS 切分)。
        返回按 IS 分数降序的 Top 30 白名单 (单币最多 5 对)。
        """
        if not candidates:
            return []

        tasks = []
        for i, cand in enumerate(candidates):
            sym_a = cand.get('symbol_a', '')
            sym_b = cand.get('symbol_b', '')
            beta = cand.get('beta', 1.0)

            hist_a = get_historical_data_fn(sym_a, days=90)
            hist_b = get_historical_data_fn(sym_b, days=90)

            if hist_a is None or hist_b is None:
                continue

            log_a = hist_a['log_close']
            log_b = hist_b['log_close']

            n = min(len(log_a), len(log_b))
            if n < 300:
                continue

            tasks.append((i, len(candidates), sym_a, sym_b, beta,
                         log_a[:n], log_b[:n]))

        if not tasks:
            return []

        logger.info(f"Optimizer: {len(tasks)} pairs to optimize, using {self.n_workers} workers (IS/OS={self.is_ratio:.0%})")

        # 多进程并行执行
        if self.n_workers > 1 and len(tasks) > 1:
            with Pool(processes=self.n_workers) as pool:
                results = pool.map(_optimize_single_pair, tasks)
        else:
            results = [_optimize_single_pair(t) for t in tasks]

        # 过滤 None
        results = [r for r in results if r is not None]

        # 全局排名 (按 IS score)
        results.sort(key=lambda x: x['score'], reverse=True)

        # 回测完成后选 Top 30 (按评分排名)
        # M4优化全部配对，但只返回评分最高的30对给M5
        top_30 = self._filter_top_30(results, max_per_coin=3)
        logger.info(f"Optimizer: optimized {len(results)} pairs, selected Top {len(top_30)} for M5")
        return top_30

    def _filter_top_30(self, results: List[Dict], max_per_coin: int = 3) -> List[Dict]:
        """
        截取 Top 30, 单币最多 max_per_coin 对
        M4优化全部配对，但只返回评分最高的30对给M5
        """
        final = []
        coin_counts = {}

        for pair in results:
            sym_a = pair.get('symbol_a', '')
            sym_b = pair.get('symbol_b', '')

            cnt_a = coin_counts.get(sym_a, 0)
            cnt_b = coin_counts.get(sym_b, 0)

            # 单币限制：每个币种最多出现3次（防止过度集中）
            if cnt_a < max_per_coin and cnt_b < max_per_coin:
                final.append(pair)
                coin_counts[sym_a] = cnt_a + 1
                coin_counts[sym_b] = cnt_b + 1

                if len(final) >= 30:
                    break

        return final
