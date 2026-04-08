"""
模块二：初筛模块 (Initial Filter) - P0 LOCKED

数据流转:
  Input:  全量 symbols 列表 (List[str]), market_stats 字典 (Module 1)
  Output: Qualified Pool (List[str]), 预计 100-150 个币种
  去向:   传递给模块三 (Pairwise Scoring)

六重过滤防线: 执行顺序严格 1->7，任一命中立即剔除 (Break on Fail)。

文档规范: docs/module_2_initial_filter.md
"""

import logging
from typing import List, Dict

logger = logging.getLogger("InitialFilter")

# 稳定币
STABLECOINS = {'USDC', 'FDUSD', 'TUSD', 'DAI', 'BUSD', 'EUR', 'GBP', 'USTC'}

# [已废弃] 黑名单限制已取消 - 允许所有通过流动性和数据完整性检查的币参与


class InitialFilter:
    def __init__(self):
        self.stats_passed: int = 0
        self.stats_filtered: int = 0

    def run(self, symbols: List[str], stats_db: Dict) -> List[str]:
        """
        遍历 symbols，应用 6 重过滤逻辑。
        返回通过过滤的列表。
        """
        qualified = []
        for sym in symbols:
            if self._check(sym, stats_db.get(sym, {})):
                qualified.append(sym)

        logger.info(f"InitialFilter: {len(symbols)} -> {len(qualified)} assets passed 7-filter pipeline.")
        return qualified

    def _check(self, symbol: str, stats: Dict) -> bool:
        """
        串行执行 6 道防线，任一命中立即剔除。
        """
        base = symbol.split('/')[0]

        # ── 过滤器 1: 稳定币剔除 ──
        if base in STABLECOINS:
            return False

        # ── 过滤器 2: [已取消] 黑名单限制 ──

        # ── 过滤器 3: 流动性门槛 ──
        # FIX BUG-004: 提高到500万U，per_leg=5000U时避免滑点风险
        vol = stats.get('vol_24h_usdt', 0)
        if vol < 5_000_000:
            return False

        # ── 过滤器 4: 数据完整度 ──
        count = stats.get('kline_count', 0)
        if count < 120_000:
            return False

        # ── 过滤器 5: 僵尸/刷量盘 ──
        close = stats.get('close', 1)
        high_24h = stats.get('high_24h', close)
        low_24h = stats.get('low_24h', close)
        if close > 0:
            range_pct = (high_24h - low_24h) / close
            if range_pct < 0.0015:
                return False

        # ── 过滤器 6: 异常波动拦截 ──
        # A: 价格过低
        if close < 0.0005:
            return False

        # B: ATR/Close > 0.12
        atr = stats.get('atr_14', 0)
        if close > 0 and (atr / close) > 0.12:
            return False

        # C: Kurtosis > 10
        kurtosis = stats.get('kurtosis', 0)
        if kurtosis > 10:
            return False

        return True