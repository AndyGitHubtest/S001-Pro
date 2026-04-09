"""
S001-Pro Main Runtime: Full Pipeline Integration

流程:
  Phase A (扫描优化, 周期性):
    M1 DataEngine -> M2 InitialFilter -> M3 PairwiseScorer -> M4 Optimizer -> M5 Persistence
  Phase B (实盘监控, 持续循环):
    M8 ConfigManager (加载配置 + 热重载)
    M6 Runtime (状态机驱动, 信号检测, 下单执行)
    M7 Monitor (PnL 追踪, 报警)
    SignalEngine (实时 Z-score 计算)
    M9 LoggerManager (结构化日志)

文档规范: docs/ROADMAP.md (Phase 5)
"""

import asyncio
import json
import logging
import os
import sys
import time
from typing import Dict, Optional, List

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入自诊断模块
from src.diagnostics import (
    diag_step, diag_state, diag_error, diag_progress, diag_timeout,
    DiagTimer, ProgressTracker, enable_diagnostics
)

from src.data_engine import DataEngine
from src.filters.initial_filter import InitialFilter
from src.m3_selector import M3Selector
from src.optimizer import ParamOptimizer
from src.persistence import Persistence
from src.config_manager import ConfigManager
from src.runtime import Runtime
from src.monitor_logger import Monitor, LoggerManager, TradeRecord
from src.signal_engine import SignalEngine


def setup_logging(log_dir: str = "logs", log_level: str = "INFO"):
    """初始化日志系统 (M9)"""
    os.makedirs(log_dir, exist_ok=True)
    logger_manager = LoggerManager(log_dir=log_dir)

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )

    return logger_manager


def load_config(config_dir: str = "config") -> ConfigManager:
    """加载配置管理器 (M8)"""
    cm = ConfigManager(config_dir=config_dir)
    cm.load_and_validate()
    return cm


def run_scan_and_optimize(
    db_path: str,
    min_vol: float = 2_000_000,
    top_scan_count: int = 100,
    top_final_count: int = 30,
    max_per_coin: int = 5,
) -> tuple:
    """
    执行完整扫描 + 优化流水线 (M1 -> M2 -> M3 -> M4 -> M5)。
    返回 (whitelist, total_candidates, elapsed_sec)。
    """
    import time as _time
    _t0 = _time.time()
    logger = logging.getLogger("Pipeline")
    
    diag_step(1, "开始扫描优化流水线", db_path=db_path, min_vol=min_vol)
    logger.info("=" * 60)
    logger.info("PHASE A: Scan & Optimization Pipeline Starting")
    logger.info("=" * 60)

    # M1: Data Engine
    diag_step(2, "初始化数据引擎")
    logger.info("[M1] Initializing DataEngine...")
    engine = DataEngine(db_path)
    all_symbols = engine.get_all_symbols(interval="1m")
    diag_state("total_symbols", len(all_symbols))
    logger.info(f"[M1] Found {len(all_symbols)} symbols in database")

    # M1: Load market stats
    diag_step(3, "加载市场统计")
    logger.info("[M1] Loading market stats...")
    market_stats = engine.load_market_stats(min_vol=min_vol)
    diag_state("qualified_by_volume", len(market_stats))
    logger.info(f"[M1] {len(market_stats)} symbols meet liquidity filter (>{min_vol/1e6:.0f}M)")

    # M2: Initial Filter
    diag_step(4, "执行初筛过滤")
    logger.info("[M2] Running Initial Filter (6-layer pipeline)...")
    initial_filter = InitialFilter()
    qualified = initial_filter.run(list(market_stats.keys()), market_stats)
    diag_state("passed_m2_filter", len(qualified))
    logger.info(f"[M2] {len(qualified)} symbols passed all 6 filters")

    if len(qualified) < 2:
        logger.warning("[M2] Not enough qualified symbols for pairing. Exiting.")
        engine.close()
        elapsed = _time.time() - _t0
        return ([], 0, elapsed)

    diag_step(3, "构建Hot Pool数据池", symbol_count=len(qualified))
    # M1: Build Hot Pool
    logger.info("[M1] Building Hot Pool (5000 bars per symbol)...")
    hot_pool = engine.build_hot_pool(qualified, limit=5000)
    diag_state("hot_pool_size", len(hot_pool))
    logger.info(f"[M1] Hot Pool built for {len(hot_pool)} symbols")

    # M1: Batch load 90d historical data
    logger.info("[M1] Batch-loading 90d historical data for all qualified symbols...")
    hist_cache = engine.batch_load_historical(qualified, days=90)
    for sym in qualified:
        if sym not in hist_cache:
            hp = hot_pool.get(sym)
            if hp:
                hist_cache[sym] = {
                    'close': hp['close'],
                    'log_close': hp['log_close'],
                    'volume': hp['volume'],
                }
    logger.info(f"[M1] Historical cache: {len(hist_cache)} symbols")

    # M3: Multi-Timeframe Selector (三周期独立运行)
    diag_step(5, "执行M3配对精选")
    logger.info("[M3] Running M3 Multi-Timeframe Selector (1m/5m/15m)...")
    m3_selector = M3Selector()  # 默认不限制数量，所有通过筛选的都进入M4
    
    # 运行所有周期（各自独立，从1m数据聚合）
    m3_results = m3_selector.run_all(qualified, hot_pool)
    
    total_m3 = sum(len(v) for v in m3_results.values())
    diag_state("m3_results", {"1m": len(m3_results['1m']), "5m": len(m3_results['5m']), 
                               "15m": len(m3_results['15m']), "total": total_m3})
    logger.info(f"[M3] Results: 1m={len(m3_results['1m'])}, 5m={len(m3_results['5m'])}, 15m={len(m3_results['15m'])}, total={total_m3}")
    
    if total_m3 == 0:
        logger.warning("[M3] No pairs passed any timeframe screening. Exiting.")
        engine.close()
        elapsed = _time.time() - _t0
        return ({}, len(qualified), elapsed)
    
    # M4: Optimizer (每个周期独立优化)
    diag_step(6, "执行M4参数优化")
    logger.info("[M4] Running Parameter Optimizer for each timeframe...")
    optimizer = ParamOptimizer()
    
    all_whitelists = {}
    with ProgressTracker(total=3, operation="M4优化", report_every=1) as pt:
        for timeframe in ['1m', '5m', '15m']:
            candidates = m3_results[timeframe]
            if not candidates:
                logger.info(f"[M4] {timeframe}: no candidates to optimize")
                pt.update()
                continue
                
            logger.info(f"[M4] {timeframe}: optimizing {len(candidates)} pairs...")
            whitelist = optimizer.run(candidates, get_historical_data_fn=engine.get_historical_data)
            all_whitelists[timeframe] = whitelist
            diag_state(f"m4_{timeframe}_optimized", len(whitelist))
            logger.info(f"[M4] {timeframe}: {len(whitelist)} pairs optimized")
            pt.update()
    
    total_m4 = sum(len(v) for v in all_whitelists.values())
    diag_state("total_m4_optimized", total_m4)
    logger.info(f"[M4] Total optimized: {total_m4} pairs")

    # M5: Persistence (保存所有周期的结果)
    diag_step(7, "保存M5结果")
    logger.info("[M5] Saving results to config/pairs_multi_timeframe.json...")
    persistence = Persistence()
    git_hash = _get_git_hash()
    
    # 合并所有周期的结果
    combined_results = {
        'git_hash': git_hash,
        'timestamp': _time.strftime('%Y-%m-%d %H:%M:%S'),
        '1m': all_whitelists.get('1m', []),
        '5m': all_whitelists.get('5m', []),
        '15m': all_whitelists.get('15m', []),
    }
    
    # 保存到统一文件
    import json
    try:
        with open("config/pairs_multi_timeframe.json", 'w') as f:
            json.dump(combined_results, f, indent=2)
        logger.info(f"[M5] Saved multi-timeframe results successfully")
        diag_state("saved_multi_timeframe", True)
        
        # 同时保存兼容性格式（取5m作为主要输出）
        if '5m' in all_whitelists and all_whitelists['5m']:
            persistence.save(all_whitelists['5m'], "config/pairs_v2.json", git_hash=git_hash)
            logger.info(f"[M5] Saved 5m results to pairs_v2.json for compatibility")
        
        # 打印各周期Top3
        for tf in ['1m', '5m', '15m']:
            if tf in all_whitelists and all_whitelists[tf]:
                logger.info(f"[M5] {tf} Top3:")
                for p in all_whitelists[tf][:3]:
                    logger.info(f"     {p['symbol_a']} <-> {p['symbol_b']} | Score={p.get('score', 0):.3f}")
                    
    except Exception as e:
        diag_error("M5保存结果", e, combined_results_count=len(combined_results))
        logger.error(f"[M5] Failed to save results: {e}")

    elapsed = _time.time() - _t0
    diag_step(8, "扫描优化流水线完成", total_pairs=total_m4, elapsed_sec=f"{elapsed:.1f}")
    engine.close()
    logger.info(f"Pipeline complete: {total_m4} pairs across 3 timeframes, {elapsed:.0f}s")
    return (all_whitelists, total_m3, elapsed)


def _get_git_hash() -> str:
    """获取当前 git commit hash"""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


# ──────────────────────────────────────────────
# Exchange API 适配器 (ccxt 封装, 异步化)
# ──────────────────────────────────────────────

class ExchangeApi:
    """
    交易所 API 适配器 (ccxt 封装)。

    所有同步 ccxt 调用都用 asyncio.to_thread 包装, 防止阻塞事件循环。
    支持 Binance USDT 永续合约。
    """

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        self.logger = logging.getLogger("ExchangeApi")
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self._client = None

    def _get_client(self):
        """懒初始化 ccxt 客户端"""
        if self._client is None:
            import ccxt
            config = {
                'apiKey': self.api_key,
                'secret': self.api_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'},
            }
            if self.testnet:
                config['testnet'] = True
                config['urls'] = {
                    'api': {
                        'public': 'https://testnet.binancefuture.com/fapi/v1',
                        'private': 'https://testnet.binancefuture.com/fapi/v1',
                    }
                }
            self._client = ccxt.binance(config)
        return self._client

    async def place_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        qty: float,
        price: float = None,
        post_only: bool = False,
        reduce_only: bool = False,
    ) -> Dict:
        """
        下单 (async, to_thread 包装防止阻塞)。
        """
        client = self._get_client()
        params = {}
        if post_only:
            params['postOnly'] = True
        if reduce_only:
            params['reduceOnly'] = True

        # FIX P0: 市价单不传price参数，限价单才传
        # FIX P1: 低价币(价格<0.1)强制用市价单，避免Limit price too low错误
        def _do_order():
            if order_type.lower() == 'market' or (price is not None and price < 0.1):
                return client.create_order(symbol, order_type, side, qty, None, params)
            else:
                return client.create_order(symbol, order_type, side, qty, price, params)

        try:
            order = await asyncio.to_thread(_do_order)
            return order
        except Exception as e:
            self.logger.error(f"ExchangeApi: place_order failed for {symbol}: {e}")
            raise

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤单 (async)"""
        client = self._get_client()

        def _do_cancel():
            client.cancel_order(order_id, symbol)
            return True

        try:
            return await asyncio.to_thread(_do_cancel)
        except Exception as e:
            logger.warning(f"ExchangeApi: cancel_order failed: {e}")
            return False

    async def cancel_all_orders(self, symbol: str) -> bool:
        """撤销指定交易对的所有挂单 (async)"""
        client = self._get_client()

        def _do_cancel_all():
            if hasattr(client, 'cancel_all_orders'):
                client.cancel_all_orders(symbol)
            else:
                orders = client.fetch_open_orders(symbol)
                for o in orders:
                    try:
                        client.cancel_order(o['id'], symbol)
                    except Exception as cancel_err:
                        logger.warning(f"ExchangeApi: cancel_order {o['id']} failed: {cancel_err}")
            return True

        try:
            return await asyncio.to_thread(_do_cancel_all)
        except Exception as e:
            logger.warning(f"ExchangeApi: cancel_all_orders failed: {e}")
            return False

    async def fetch_order(self, order_id: str, symbol: str) -> Dict:
        """查询订单状态 (async)"""
        client = self._get_client()

        def _do_fetch():
            return client.fetch_order(order_id, symbol)

        try:
            order = await asyncio.to_thread(_do_fetch)
            return order
        except Exception as e:
            logger.warning(f"ExchangeApi: fetch_order failed: {e}")
            raise

    async def fetch_ticker(self, symbol: str) -> Dict:
        """获取最新 ticker 价格 (async)"""
        client = self._get_client()

        def _do_ticker():
            return client.fetch_ticker(symbol)

        try:
            ticker = await asyncio.to_thread(_do_ticker)
            return ticker
        except Exception as e:
            logger.warning(f"ExchangeApi: fetch_ticker failed for {symbol}: {e}")
            raise

    async def fetch_tickers(self, symbols: List[str] = None) -> Dict[str, Dict]:
        """
        批量获取 ticker 价格 (async)

        FIX: SignalEngine 需要批量获取价格，减少 API 调用次数

        Args:
            symbols: 交易对列表，如 ["BTC/USDT:USDT", "ETH/USDT:USDT"]
                    如果为 None，返回所有交易对

        Returns:
            {symbol: ticker_dict, ...}
        """
        client = self._get_client()

        def _do_tickers():
            if symbols:
                return client.fetch_tickers(symbols)
            else:
                return client.fetch_tickers()

        try:
            tickers = await asyncio.to_thread(_do_tickers)
            return tickers
        except Exception as e:
            self.logger.warning(f"ExchangeApi: fetch_tickers failed: {e}")
            raise

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 500) -> List:
        """获取历史 K 线 (同步方法, 用于预热, 调用方需用 to_thread 包装)"""
        client = self._get_client()
        try:
            ohlcv = client.fetch_ohlcv(symbol, timeframe, limit=limit)
            return ohlcv
        except Exception as e:
            logger.warning(f"ExchangeApi: fetch_ohlcv failed for {symbol}: {e}")
            return []

    async def get_positions(self) -> Optional[List[Dict]]:
        """
        查询所有持仓 (async)。
        
        FIX BUG-003: 返回Optional[List]，失败时返回None而非[]
        调用方必须区分: None=查询失败(应保持现状), []=无持仓
        
        返回: [{"symbol": "BTC/USDT:USDT", "positionAmt": 0.001, "side": "long"}, ...]
               None表示查询失败
        """
        client = self._get_client()

        def _do_positions():
            positions = client.fetch_positions()
            result = []
            for pos in positions:
                amt = pos.get('contracts', 0) or pos.get('positionAmt', 0)
                if amt and float(amt) != 0:
                    result.append({
                        'symbol': pos.get('symbol', ''),
                        'positionAmt': float(amt),
                        'side': 'long' if float(amt) > 0 else 'short',
                    })
            return result

        try:
            return await asyncio.to_thread(_do_positions)
        except Exception as e:
            logger.warning(f"ExchangeApi: get_positions failed: {e}")
            return None  # FIX BUG-003: 返回None表示失败，不是[]


class TradingSystem:
    """
    完整交易系统: 集成所有模块, 管理生命周期。
    """

    def __init__(
        self,
        db_path: str = "data/klines.db",
        config_dir: str = "config",
        log_dir: str = "logs",
        dry_run: bool = False,
        scan_interval_hours: float = 1.0,  # 每小时扫描一次
        check_interval_sec: float = 1.0,
    ):
        # 启用诊断系统
        enable_diagnostics(True)
        diag_step(1, "初始化交易系统", mode="DRY_RUN" if dry_run else "LIVE")
        
        self.db_path = db_path
        self.dry_run = dry_run
        self.scan_interval_hours = scan_interval_hours
        self.check_interval_sec = check_interval_sec
        
        # FIX BUG-007: SIGTERM优雅退出标志
        self._shutdown_requested = False
        
        # FIX BUG-010: 保存主事件循环引用，用于线程安全的热重载
        self._main_loop = None

        # 初始化模块 (必须在setup_signal_handlers之前)
        self.logger_manager = setup_logging(log_dir)
        self.logger = logging.getLogger("TradingSystem")
        
        diag_step(2, "加载配置管理器")
        self.config_manager = load_config(config_dir)
        
        # 信号处理 (依赖config_manager)
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """FIX BUG-007: 设置信号处理，支持优雅退出"""
        import signal
        
        def _handle_signal(signum, frame):
            self.logger.info(f"Received signal {signum}, requesting graceful shutdown...")
            self._shutdown_requested = True
        
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        # FIX P1-5: 从配置读取本金, 不再硬编码
        risk_config = self.config_manager.config.get("risk", {})
        self.capital = risk_config.get("initial_capital", 10000.0)

        # FIX: 初始化 ExchangeApi (从配置读取 API key)
        exchange_config = self.config_manager.config.get("exchange", {})
        self.exchange_api = ExchangeApi(
            api_key=exchange_config.get("api_key", ""),
            api_secret=exchange_config.get("api_secret", ""),
            testnet=exchange_config.get("testnet", False),
        )

        # FIX: 初始化 Telegram Notifier
        notif_config = self.config_manager.config.get("notifications", {})
        notifier = None
        if notif_config.get("enabled") and notif_config.get("telegram_bot_token"):
            from src.monitor_logger import TelegramNotifier
            notifier = TelegramNotifier(
                bot_token=notif_config["telegram_bot_token"],
                chat_id=notif_config["telegram_chat_id"],
            )

        self.monitor = Monitor(
            notifier=notifier,
            stats_path="data/daily_stats.json",
        )
        self.signal_engine = SignalEngine()
        self.runtime = Runtime(
            config_manager=self.config_manager,
            exchange_api=self.exchange_api if not self.dry_run else None,
            monitor=self.monitor,
        )
        self._last_price_update = 0.0

    async def run(self):
        """主循环: 周期扫描 + 持续监控"""
        # FIX BUG-010: 保存主事件循环引用
        import asyncio
        self._main_loop = asyncio.get_running_loop()
        
        self.logger.info("S001-Pro Trading System Starting...")
        self.logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        self.logger.info(f"Capital: ${self.capital:,.0f}")

        # 初始化 Monitor
        self.monitor.initialize(self.capital)

        # 启动 Runtime
        await self.runtime.start()

        # FIX 审计-1: 信号引擎预热 (从交易所获取 500 根历史 K 线)
        if self.exchange_api:
            self.logger.info("SignalEngine: warming up from exchange (500 bars)...")
            pairs_data = self.config_manager.pairs_data.get("pairs", [])
            for pair_config in pairs_data:
                pair_key = f"{pair_config['symbol_a']}_{pair_config['symbol_b']}"
                if pair_key not in self.signal_engine.signals:
                    self.signal_engine.add_pair(pair_config)
            # 预热
            await self.signal_engine.warmup_from_exchange(self.exchange_api)
            ready_count = sum(1 for s in self.signal_engine.signals.values() if s.is_ready())
            self.logger.info(f"SignalEngine: {ready_count}/{len(self.signal_engine.signals)} pairs ready after warmup")

        # 配置热重载回调
        self.config_manager.watch_config(self._on_config_change)

        try:
            scan_counter = 0
            results = None
            total_cands = 0
            scan_elapsed = 0
            while True:
                scan_counter += 1
                
                # FIX P0: 跳过首次扫描，直接使用现有配置
                # 原因: run_scan_and_optimize 会卡住导致进程无响应
                if scan_counter == 1:
                    self.logger.info("[WORKAROUND] 首次启动跳过扫描，使用现有配对配置")
                    self.logger.info(f"[WORKAROUND] 已加载 {len(self.config_manager.pairs_data.get('pairs', []))} 对配置")
                else:
                    # A. 周期扫描优化 (带超时保护)
                    self.logger.info(f"Running scan & optimization (every {self.scan_interval_hours}h)...")
                    try:
                        # FIX: 添加10分钟超时，防止扫描卡住
                        results, total_cands, scan_elapsed = await asyncio.wait_for(
                            asyncio.to_thread(run_scan_and_optimize, self.db_path),
                            timeout=600  # 10分钟超时
                        )
                        self.logger.info(f"Scan complete: {len(results)} pairs ready ({scan_elapsed:.0f}s, {total_cands} candidates)")
                    except asyncio.TimeoutError:
                        self.logger.error("[TIMEOUT] 扫描超时(10分钟)，跳过本次扫描")
                        results = None
                        total_cands = 0
                        scan_elapsed = 0
                    except Exception as e:
                        self.logger.error(f"[ERROR] 扫描失败: {e}")
                        results = None
                        total_cands = 0
                        scan_elapsed = 0

                if results:
                    # Push Top 30 to Telegram
                    _notif = self.config_manager.config.get("notifications", {})
                    _tg_token = _notif.get("telegram_bot_token", "")
                    _tg_chat = _notif.get("telegram_chat_id", "")
                    if _tg_token and _tg_chat:
                        try:
                            from src.optimizer import notify_scan_results
                            # FIX: 使用 asyncio.to_thread 避免阻塞事件循环
                            await asyncio.to_thread(
                                notify_scan_results,
                                whitelist=results,
                                bot_token=_tg_token,
                                chat_id=_tg_chat,
                                total_candidates=total_cands,
                                elapsed_sec=scan_elapsed,
                                scan_id="({:.0f}min)".format(scan_elapsed / 60),
                            )
                        except Exception as _e:
                            self.logger.error("TG scan notify failed: %s", _e)
                else:
                    self.logger.warning("Scan produced no results, using existing config")
                    _notif = self.config_manager.config.get("notifications", {})
                    _tg_token = _notif.get("telegram_bot_token", "")
                    _tg_chat = _notif.get("telegram_chat_id", "")
                    if _tg_token and _tg_chat:
                        try:
                            from src.optimizer import notify_scan_results
                            # FIX: 使用 asyncio.to_thread 避免阻塞事件循环
                            await asyncio.to_thread(
                                notify_scan_results,
                                whitelist=[],
                                bot_token=_tg_token,
                                chat_id=_tg_chat,
                                total_candidates=total_cands,
                                elapsed_sec=scan_elapsed,
                                scan_id="({:.0f}min)".format(scan_elapsed / 60),
                            )
                        except Exception as _e:
                            self.logger.error("TG scan notify failed: %s", _e)

                # B. 持续监控循环
                scan_interval = self.scan_interval_hours * 3600
                next_scan_time = time.time() + scan_interval

                while time.time() < next_scan_time:
                    # FIX BUG-007: 检查退出标志
                    if self._shutdown_requested:
                        self.logger.info("Shutdown flag set, breaking main loop")
                        break
                    
                    # 对接实时价格信号
                    await self._check_all_signals()
                    await asyncio.sleep(self.check_interval_sec)
                
                # FIX BUG-007: 检查退出标志，决定是否继续下一轮扫描
                if self._shutdown_requested:
                    break

        except KeyboardInterrupt:
            self.logger.info("Shutdown requested by user (KeyboardInterrupt)")
        except Exception as e:
            self.logger.critical(f"Unhandled exception: {e}", exc_info=True)
        finally:
            await self._shutdown()

    async def _check_all_signals(self):
        """
        遍历所有活跃配对, 检查信号。

        原子级流程:
          1. 每 5 秒轮询一次交易所价格 (并发获取所有 ticker)
          2. 更新 SignalEngine 的滑动窗口
          3. 同步更新 Runtime 的价格缓存 (用于精确下单)
          4. 遍历 Runtime 所有监控的配对 (含 IDLE 状态)
          5. 获取 Z-score, 调用 Runtime.check_signals 驱动状态机
          6. 每 5 分钟更新 Monitor 账户权益
        """
        # 轮询价格 (限频)
        now = time.time()
        if now - self._last_price_update >= 5.0:
            await self._update_all_prices()
            self._last_price_update = now

        # FIX P1: 每 5 分钟更新 Monitor 账户权益
        if not hasattr(self, '_last_account_update'):
            self._last_account_update = 0.0
        if now - self._last_account_update >= 300.0:  # 5 分钟
            if self.exchange_api:
                try:
                    positions = await self.exchange_api.get_positions()
                    # FIX BUG-003: 检查查询是否失败
                    if positions is None:
                        logger.warning("TradingSystem: get_positions failed, skipping account update")
                    else:
                        # Sum up unrealized PnL if available
                        total_unrealized = sum(float(p.get('unrealizedProfit', 0)) for p in positions)
                        equity = self.capital + self.monitor.daily_pnl + total_unrealized
                        self.monitor.update_account(equity)
                        self._last_account_update = now
                except Exception as e:
                    self.logger.debug(f"Account update failed: {e}")

        # 遍历 Runtime 所有监控的配对 (不仅是有持仓的)
        for pair_key in list(self.runtime.positions.keys()):
            z, ready = self.signal_engine.get_z(pair_key)
            if not ready:
                continue

            await self.runtime.check_signals(pair_key, z)

    async def _update_all_prices(self):
        """
        从交易所获取所有监控配对的价格并更新信号引擎 + Runtime 价格缓存。

        FIX P1: 同步更新 Runtime._price_cache, 确保下单数量计算使用最新价格。
        """
        if self.exchange_api is None:
            return

        # 确保 SignalEngine 中有所有配对
        pairs_data = self.config_manager.pairs_data.get("pairs", [])
        for pair_config in pairs_data:
            pair_key = f"{pair_config['symbol_a']}_{pair_config['symbol_b']}"
            if pair_key not in self.signal_engine.signals:
                self.signal_engine.add_pair(pair_config)

        # 批量获取价格 (SignalEngine 内部用 asyncio.gather 并发)
        await self.signal_engine.update_prices_from_exchange(self.exchange_api)

        # FIX: 同步更新 Runtime 价格缓存 (用于 _calculate_quantity)
        symbols_to_cache = set()
        for pair_config in pairs_data:
            symbols_to_cache.add(pair_config.get("symbol_a", ""))
            symbols_to_cache.add(pair_config.get("symbol_b", ""))

        for sym in symbols_to_cache:
            if not sym:
                continue
            signal = None
            for ps in self.signal_engine.signals.values():
                if ps.symbol_a == sym or ps.symbol_b == sym:
                    signal = ps
                    break
            if signal:
                # 从 SignalEngine 的 deque 取最新价格
                if signal.close_a:
                    self.runtime._price_cache[sym] = float(signal.close_a[-1])

    async def _shutdown(self):
        """优雅关闭"""
        self.logger.info("Shutting down...")
        self.runtime.stop()

        # FIX: 保存最终状态
        try:
            await self.runtime._save_state()
        except Exception as e:
            self.logger.error(f"Runtime: failed to save final state: {e}")

        # FIX: 发送每日报告
        try:
            self.monitor.send_daily_report()
        except Exception as e:
            self.logger.error(f"Monitor: failed to send daily report: {e}")

        self.logger.info("Shutdown complete")

    def _on_config_change(self, event_type: str, data: Dict):
        """热重载回调 - FIX BUG-010: 在线程中安全地调度协程"""
        if event_type == "pairs_updated":
            self.logger.info(f"ConfigManager: pairs updated, reloading Runtime...")
            # FIX BUG-010: 使用保存的主事件循环引用，避免在线程中调用 get_running_loop()
            import asyncio
            if self._main_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self.runtime.handle_hot_reload(data), 
                    self._main_loop
                )
                self.logger.info("Hot reload scheduled successfully")
            else:
                # 主循环尚未初始化，记录警告
                self.logger.warning("Cannot schedule hot reload: main loop not initialized yet")


def main():
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="S001-Pro Statistical Arbitrage Trading System")
    parser.add_argument("--mode", choices=["scan", "trade", "full"], default="full",
                        help="scan: 仅扫描优化, trade: 仅监控, full: 完整流程")
    parser.add_argument("--db", default="data/klines.db", help="数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="Dry Run 模式 (不发单)")
    parser.add_argument("--scan-interval", type=float, default=4.0, help="扫描间隔 (小时)")
    args = parser.parse_args()

    if args.mode == "scan":
        results, _tc, _se = run_scan_and_optimize(args.db)
        # results 现在是字典 { '1m': [...], '5m': [...], '15m': [...] }
        if isinstance(results, dict):
            total = sum(len(v) for v in results.values())
            print(f"\nScan complete: {total} pairs across 3 timeframes")
            for tf in ['1m', '5m', '15m']:
                if tf in results and results[tf]:
                    print(f"\n  [{tf}] {len(results[tf])} pairs:")
                    for p in results[tf][:3]:
                        print(f"    {p['symbol_a']} <-> {p['symbol_b']} | Score={p.get('score', 0):.3f}")
        else:
            print(f"\nScan complete: {len(results)} pairs")
            for p in results[:5]:
                print(f"  {p['symbol_a']} <-> {p['symbol_b']} | Score={p.get('score', 0):.3f}")
    elif args.mode == "trade":
        system = TradingSystem(db_path=args.db, dry_run=args.dry_run)
        asyncio.run(system.run())
    else:
        system = TradingSystem(
            db_path=args.db,
            dry_run=args.dry_run,
            scan_interval_hours=args.scan_interval,
        )
        asyncio.run(system.run())


if __name__ == "__main__":
    main()