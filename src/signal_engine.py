"""
信号引擎 (Signal Engine) - 实时 Z-score 计算

职责:
  1. 维护每个配对的价格滑动窗口 (最新 500 根 1m K 线)
  2. 实时计算 spread 和 Z-score (不含未来函数)
  3. 提供 1Hz 级别的 Z 值查询

架构:
  - 启动时从数据库加载历史数据预热
  - 运行时通过 asyncio.gather 并发轮询交易所 ticker
  - 增量更新滑动窗口, Z-score 计算使用前 N-1 个点的统计 (偷看修复)

文档规范: docs/module_signal_engine.md
"""

import numpy as np
import logging
import time
import asyncio
from typing import Dict, Optional, Tuple, List
from collections import deque

logger = logging.getLogger("SignalEngine")

# 配置常量
WINDOW_SIZE = 500        # 滑动窗口大小 (约 8 小时 1m K 线)
Z_WARMUP = 200           # Z-score 统计窗口 (扩窗/滑动)
PRICE_POLL_INTERVAL = 5  # 价格轮询间隔 (秒)
MAX_FETCH_ERRORS = 10    # 连续失败阈值 (超过后告警)


class PairSignal:
    """单个配对的实时信号计算器"""

    def __init__(self, pair_config: Dict, historical_data: Optional[Dict] = None):
        self.pair_config = pair_config
        self.symbol_a = pair_config["symbol_a"]
        self.symbol_b = pair_config["symbol_b"]
        self.beta = pair_config.get("beta", 1.0)
        self.params = pair_config.get("params", {})

        # 价格滑动窗口
        self.close_a = deque(maxlen=WINDOW_SIZE)
        self.close_b = deque(maxlen=WINDOW_SIZE)

        # 状态
        self._ready = False
        self._last_z = 0.0
        self._last_update = 0.0
        self._spread_mean = 0.0
        self._spread_std = 1.0
        self._fetch_errors = 0  # 连续 fetch 失败计数

        # 预热
        if historical_data:
            self._warmup(historical_data)

    def _warmup(self, hist_data: Dict):
        """用历史数据预热滑动窗口"""
        if "close" in hist_data:
            closes = hist_data["close"]
            start_idx = max(0, len(closes) - WINDOW_SIZE)
            for c in closes[start_idx:]:
                self.close_a.append(float(c))

        if "close_b" in hist_data:
            closes = hist_data["close_b"]
            start_idx = max(0, len(closes) - WINDOW_SIZE)
            for c in closes[start_idx:]:
                self.close_b.append(float(c))

        if len(self.close_a) >= Z_WARMUP and len(self.close_b) >= Z_WARMUP:
            self._ready = True
            self._recalculate_stats()
            logger.info(
                f"SignalEngine: warmed up {self.symbol_a}/{self.symbol_b} "
                f"with {len(self.close_a)} bars, ready={self._ready}"
            )

    def _recalculate_stats(self):
        """
        重新计算 spread 均值和标准差 (用于 Z-score)。
        使用前 Z_WARMUP 个数据点, 不包含最新价格 (防未来函数)。
        """
        n = min(len(self.close_a), len(self.close_b))
        if n < Z_WARMUP:
            return

        # 排除最后一个 (最新) 价格点, 防止偷看
        arr_a = np.array(list(self.close_a)[-Z_WARMUP-1:-1], dtype=np.float64) if n > Z_WARMUP else np.array(list(self.close_a)[-Z_WARMUP:], dtype=np.float64)
        arr_b = np.array(list(self.close_b)[-Z_WARMUP-1:-1], dtype=np.float64) if n > Z_WARMUP else np.array(list(self.close_b)[-Z_WARMUP:], dtype=np.float64)

        # 过滤零值 (交易所维护)
        valid_mask = (arr_a > 0) & (arr_b > 0)
        arr_a = arr_a[valid_mask]
        arr_b = arr_b[valid_mask]

        if len(arr_a) < 50:
            return

        log_a = np.log(arr_a)
        log_b = np.log(arr_b)
        spread = log_a - self.beta * log_b

        self._spread_mean = float(np.mean(spread))
        self._spread_std = float(np.std(spread))

        if self._spread_std < 1e-8:
            self._spread_std = 1e-8  # 防止除零

    def update_prices(self, price_a: float, price_b: float):
        """
        更新最新价格。

        原子级流程:
          1. 跳过无效价格
          2. 追加到滑动窗口
          3. 用前 N-1 个点重算 spread 统计 (不含当前点, 防未来函数)
          4. 用当前点计算 Z-score
          5. 重置 fetch 失败计数
        """
        if price_a <= 0 or price_b <= 0:
            self._fetch_errors += 1
            return

        self.close_a.append(price_a)
        self.close_b.append(price_b)
        self._last_update = time.time()
        self._fetch_errors = 0  # 成功获取价格, 重置计数

        n = min(len(self.close_a), len(self.close_b))

        if n >= Z_WARMUP:
            self._ready = True
            # 用前 N-1 个点算统计量 (不含当前点)
            self._recalculate_stats()

            # 用当前价格点计算 Z-score (当前 spread - 历史 mean/std)
            if self._spread_std > 1e-8:
                log_a = np.log(price_a)
                log_b = np.log(price_b)
                spread = log_a - self.beta * log_b
                self._last_z = (spread - self._spread_mean) / self._spread_std

    def get_z(self) -> Tuple[float, bool]:
        """
        获取当前 Z-score。
        返回: (z_value, is_ready)
        """
        return self._last_z, self._ready

    def is_ready(self) -> bool:
        return self._ready

    def stats(self) -> Dict:
        """返回诊断信息"""
        return {
            "symbol_a": self.symbol_a,
            "symbol_b": self.symbol_b,
            "beta": self.beta,
            "bars_a": len(self.close_a),
            "bars_b": len(self.close_b),
            "ready": self._ready,
            "spread_mean": self._spread_mean,
            "spread_std": self._spread_std,
            "current_z": self._last_z,
            "last_update": self._last_update,
            "fetch_errors": self._fetch_errors,
        }


class SignalEngine:
    """
    信号引擎: 管理所有配对的实时 Z-score 计算。

    使用方式:
      1. 初始化: engine = SignalEngine()
      2. 添加配对: engine.add_pair(pair_config, historical_data)
      3. 启动价格轮询: await engine.start_polling(exchange_api)
      4. 获取 Z 值: z, ready = engine.get_z("BTC_ETH")
    """

    def __init__(self):
        self.signals: Dict[str, PairSignal] = {}
        self._polling = False
        self._last_poll_time = 0.0
        self._total_polls = 0
        self._failed_polls = 0

    def add_pair(self, pair_config: Dict, historical_data: Optional[Dict] = None):
        """添加一个配对到信号引擎"""
        pair_key = f"{pair_config['symbol_a']}_{pair_config['symbol_b']}"
        self.signals[pair_key] = PairSignal(pair_config, historical_data)
        logger.info(f"SignalEngine: added {pair_key}")

    def remove_pair(self, pair_key: str):
        """移除一个配对"""
        if pair_key in self.signals:
            del self.signals[pair_key]
            logger.info(f"SignalEngine: removed {pair_key}")

    def get_z(self, pair_key: str) -> Tuple[float, bool]:
        """获取配对的当前 Z-score"""
        if pair_key not in self.signals:
            return 0.0, False
        return self.signals[pair_key].get_z()

    def is_all_ready(self) -> bool:
        """检查所有配对是否就绪"""
        if not self.signals:
            return False
        return all(s.is_ready() for s in self.signals.values())

    def stats(self) -> Dict[str, Dict]:
        """返回所有配对诊断信息"""
        return {pk: s.stats() for pk, s in self.signals.items()}

    def engine_stats(self) -> Dict:
        """返回引擎级诊断"""
        return {
            "total_pairs": len(self.signals),
            "ready_pairs": sum(1 for s in self.signals.values() if s.is_ready()),
            "total_polls": self._total_polls,
            "failed_polls": self._failed_polls,
            "last_poll_time": self._last_poll_time,
        }

    async def update_prices_from_exchange(self, exchange_api):
        """
        从交易所获取最新价格并更新信号。

        FIX API限流: 使用 fetch_tickers 批量获取，替代逐个 fetch_ticker
        原方案: 48个币种 × 60秒 = 2,880请求/分钟 (超过 2,400限制)
        新方案: 1次批量请求/秒 = 60请求/分钟 (安全)
        """
        if not self.signals:
            return

        # 构建所有需要获取的 symbol 列表 (去重)
        symbols_to_fetch = set()
        for signal in self.signals.values():
            symbols_to_fetch.add(signal.symbol_a)
            symbols_to_fetch.add(signal.symbol_b)

        # ═══════════════════════════════════════════════════
        # FIX API限流: 批量获取所有价格 (权重 1)
        # ═══════════════════════════════════════════════════
        try:
            # 转换为 ccxt 格式 symbol (BTC/USDT -> BTC/USDT:USDT)
            # FIX: 避免重复添加 :USDT (配对配置已含 :USDT 后缀)
            ccxt_symbols = [s if ":USDT" in s else s.replace("/USDT", "/USDT:USDT") for s in symbols_to_fetch]
            tickers = await exchange_api.fetch_tickers(ccxt_symbols)

            price_map = {}
            for raw_sym, ticker in tickers.items():
                # 转换回标准格式 (BTC/USDT:USDT -> BTC/USDT)
                std_sym = raw_sym.replace(":USDT", "")
                if ticker and ticker.get("last", 0) > 0:
                    price_map[std_sym] = ticker["last"]

            self._failed_polls = 0  # 成功时重置失败计数

        except Exception as e:
            self._failed_polls += 1
            logger.warning(f"SignalEngine: batch fetch_tickers failed: {e}, failures={self._failed_polls}")

            # 连续失败超过5次，降级为逐个获取
            if self._failed_polls <= 5:
                return

            logger.warning("SignalEngine: switching to fallback individual fetch")
            price_map = await self._fallback_individual_fetch(exchange_api, symbols_to_fetch)

        # 更新所有信号
        updated = 0
        for pair_key, signal in self.signals.items():
            price_a = price_map.get(signal.symbol_a)
            price_b = price_map.get(signal.symbol_b)
            if price_a is not None and price_b is not None:
                signal.update_prices(price_a, price_b)
                updated += 1

        self._total_polls += 1
        logger.debug(f"SignalEngine: updated {updated}/{len(self.signals)} pairs")

    async def _fallback_individual_fetch(self, exchange_api, symbols: set) -> Dict[str, float]:
        """
        降级方案: 逐个获取 (当批量获取失败时)
        添加延迟避免限流
        """
        import asyncio
        price_map = {}

        for sym in symbols:
            try:
                ticker = await exchange_api.fetch_ticker(sym)
                if ticker and ticker.get("last", 0) > 0:
                    price_map[sym] = ticker["last"]
                await asyncio.sleep(0.05)  # 50ms 延迟，控制速率
            except Exception as e:
                logger.debug(f"SignalEngine: fallback fetch failed for {sym}: {e}")

        return price_map

    async def _safe_fetch_ticker(self, exchange_api, symbol: str) -> Optional[Dict]:
        """安全获取单个 ticker, 异常返回 None"""
        try:
            ticker = await exchange_api.fetch_ticker(symbol)
            return ticker
        except Exception as e:
            logger.debug(f"SignalEngine: fetch_ticker failed for {symbol}: {e}")
            self._failed_polls += 1
            return None

    async def warmup_from_exchange(self, exchange_api, limit: int = 500):
        """
        FIX 审计-1: 从交易所获取历史 K 线预热滑动窗口。
        启动时调用, 避免冷启动。
        用 ccxt fetch_ohlcv 获取最近 500 根 1m K 线。
        注意: fetch_ohlcv 是同步方法, 用 asyncio.to_thread 避免阻塞。
        """
        for pair_key, signal in self.signals.items():
            try:
                # 用 to_thread 包装同步调用
                ohlcv_a = await asyncio.to_thread(
                    exchange_api.fetch_ohlcv, signal.symbol_a, "1m", limit=limit
                )
                ohlcv_b = await asyncio.to_thread(
                    exchange_api.fetch_ohlcv, signal.symbol_b, "1m", limit=limit
                )

                if ohlcv_a and ohlcv_b:
                    closes_a = [float(c[4]) for c in ohlcv_a if c[4] > 0]
                    closes_b = [float(c[4]) for c in ohlcv_b if c[4] > 0]

                    hist_data = {"close": closes_a, "close_b": closes_b}
                    signal._warmup(hist_data)
                    logger.info(
                        f"SignalEngine: warmed up {pair_key} from exchange "
                        f"({len(closes_a)}/{len(closes_b)} bars)"
                    )

            except Exception as e:
                logger.warning(f"SignalEngine: warmup failed for {pair_key}: {e}")
