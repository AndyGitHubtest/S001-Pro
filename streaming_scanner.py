#!/usr/bin/env python3
"""
流式配对监控系统 - Streaming Pair Scanner

核心架构:
1. 常驻内存: 所有币种数据缓存在内存中
2. 增量更新: WebSocket实时接收K线，或每10秒轮询
3. 定时重算: 每10分钟全量扫描产出Top 30
4. 自动推送: 配对更新时推送到Telegram
5. 零停机: 热更新pairs_v2.json， trading服务自动重载

数据流:
Binance WebSocket → 内存缓存 → 每10分钟触发扫描 → 
Top 30配对 → 对比旧列表 → 有变化则推送TG → 更新pairs_v2.json
"""

import asyncio
import json
import logging
import time
import os
import signal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
import numpy as np
import ccxt.async_support as ccxt
from multiprocessing import Pool, cpu_count

# Numba加速
try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*args, **kwargs):
        def decorator(f): return f
        return decorator

logger = logging.getLogger("StreamingScanner")


@dataclass
class SymbolData:
    """币种数据缓存"""
    symbol: str
    closes: deque = field(default_factory=lambda: deque(maxlen=5000))  # 约3.5天
    volumes: deque = field(default_factory=lambda: deque(maxlen=5000))
    timestamps: deque = field(default_factory=lambda: deque(maxlen=5000))
    last_update: float = 0.0
    
    def add_kline(self, timestamp: int, close: float, volume: float):
        """添加K线数据"""
        self.closes.append(close)
        self.volumes.append(volume)
        self.timestamps.append(timestamp)
        self.last_update = time.time()
    
    def get_log_prices(self, min_bars: int = 1000) -> Optional[np.ndarray]:
        """获取对数价格数组"""
        if len(self.closes) < min_bars:
            return None
        return np.log(np.array(list(self.closes)[-5000:]))
    
    @property
    def current_price(self) -> float:
        return self.closes[-1] if self.closes else 0.0
    
    @property
    def volume_24h(self) -> float:
        """24h成交量估算 (最近1440根1分钟K线)"""
        recent_volumes = list(self.volumes)[-1440:]
        return sum(recent_volumes) * self.current_price if recent_volumes else 0.0


@njit(cache=True, fastmath=True)
def _fast_metrics(log_a: np.ndarray, log_b: np.ndarray) -> Tuple[float, float, float, float]:
    """
    快速计算配对指标
    返回: (corr, beta, r2, adf_tstat)
    """
    n = min(len(log_a), len(log_b))
    if n < 100:
        return 0.0, 0.0, 0.0, 0.0
    
    # 使用最近1000个点
    a = log_a[-1000:]
    b = log_b[-1000:]
    
    # 相关性
    mean_a = np.mean(a)
    mean_b = np.mean(b)
    cov = np.sum((a - mean_a) * (b - mean_b))
    var_a = np.sum((a - mean_a) ** 2)
    var_b = np.sum((b - mean_b) ** 2)
    
    if var_a == 0 or var_b == 0:
        return 0.0, 0.0, 0.0, 0.0
    
    corr = cov / np.sqrt(var_a * var_b)
    
    # OLS Beta
    beta = cov / var_a
    
    # R²
    residuals = b - mean_b - beta * (a - mean_a)
    ss_res = np.sum(residuals ** 2)
    ss_tot = var_b
    r2 = 1.0 - ss_res / (ss_tot + 1e-10)
    
    # 简化ADF
    spread = b - beta * a
    if len(spread) < 10:
        return corr, beta, r2, 0.0
    
    dy = np.diff(spread)
    y_lag = spread[:-1]
    mean_dy = np.mean(dy)
    mean_y = np.mean(y_lag)
    cov_dy = np.sum((y_lag - mean_y) * (dy - mean_dy))
    var_y = np.sum((y_lag - mean_y) ** 2)
    
    if var_y == 0:
        return corr, beta, r2, 0.0
    
    gamma = cov_dy / var_y
    residuals = dy - mean_dy - gamma * (y_lag - mean_y)
    se = np.sqrt(np.sum(residuals ** 2) / (len(dy) - 2)) / np.sqrt(var_y)
    adf_tstat = gamma / (se + 1e-10)
    
    return corr, beta, r2, adf_tstat


@njit(cache=True, fastmath=True)
def _fast_backtest(log_a: np.ndarray, log_b: np.ndarray, beta: float) -> float:
    """快速回测计算Profit Factor"""
    n = min(len(log_a), len(log_b))
    if n < 200:
        return 0.0
    
    spread = log_a - beta * log_b
    
    # 计算Z-score
    window = 100
    z_scores = np.zeros(n)
    
    for i in range(window, n):
        s = spread[i-window:i]
        m = np.mean(s)
        std = np.std(s) + 1e-10
        z_scores[i] = (spread[i] - m) / std
    
    # 简单回测
    position = 0
    gross_profit = 0.0
    gross_loss = 0.0
    entry_z = 0.0
    
    for i in range(window, n):
        z = z_scores[i]
        
        if position == 0:
            if abs(z) > 2.0:
                position = 1 if z < 0 else -1
                entry_z = z
        else:
            # 出场条件：回归0.5或反向突破3.0
            exit_signal = (position == 1 and z > -0.5) or (position == -1 and z < 0.5)
            stop_loss = abs(z) > 3.0 and (z * entry_z) > 0
            
            if exit_signal or stop_loss:
                pnl = position * (z - entry_z) * 0.01
                if pnl > 0:
                    gross_profit += pnl
                else:
                    gross_loss += -pnl
                position = 0
    
    if gross_loss < 1e-10:
        return 2.0 if gross_profit > 0 else 0.0
    
    return gross_profit / gross_loss


def _evaluate_pair(args) -> Optional[Dict]:
    """评估单个配对（多进程用）"""
    sym_a, sym_b, log_a, log_b = args
    
    try:
        corr, beta, r2, adf_tstat = _fast_metrics(log_a, log_b)
        
        # 快速过滤
        if abs(corr) < 0.80 or r2 < 0.6 or adf_tstat > -2.0:
            return None
        
        # 回测
        pf = _fast_backtest(log_a, log_b, beta)
        if pf < 1.2:
            return None
        
        # 综合评分
        score = (
            abs(corr) * 0.25 +
            r2 * 0.25 +
            min(abs(adf_tstat) / 4.0, 1.0) * 0.25 +
            min(pf / 2.0, 1.0) * 0.25
        )
        
        # FIX: 标准化 symbol 格式，去掉 :USDT 后缀（M2 阶段统一格式）
        std_sym_a = sym_a.replace(':USDT', '') if ':USDT' in sym_a else sym_a
        std_sym_b = sym_b.replace(':USDT', '') if ':USDT' in sym_b else sym_b

        # 计算参数
        z_entry = 2.0
        z_exit = 0.5
        z_stop = 3.0

        # FIX: 添加完整的止盈止损配置
        scale_out_triggers = [
            {'trigger_z': round(z_entry * 0.6, 2), 'ratio': 0.3, 'type': 'limit', 'post_only': True},   # TP1: 60% of entry
            {'trigger_z': round(z_exit, 2), 'ratio': 0.4, 'type': 'limit', 'post_only': True},           # TP2: z_exit
            {'trigger_z': 0.0, 'ratio': 0.3, 'type': 'market', 'post_only': False},                       # TP3: 0轴市价
        ]
        stop_loss_trigger = {'trigger_z': round(z_stop + 0.3, 2), 'type': 'market', 'post_only': False}

        return {
            'symbol_a': std_sym_a,
            'symbol_b': std_sym_b,
            'beta': float(beta),
            'params': {
                'z_entry': z_entry,
                'z_exit': z_exit,
                'z_stop': z_stop,
            },
            'execution': {
                'scale_in': [
                    {'layer': 0, 'ratio': 0.3, 'z_threshold': 2.0},
                    {'layer': 1, 'ratio': 0.3, 'z_threshold': 2.5},
                    {'layer': 2, 'ratio': 0.4, 'z_threshold': 3.0},
                ],
                'scale_out': scale_out_triggers,
                'stop_loss': stop_loss_trigger,
                'legs_sync': {
                    'tolerance_ms': 5000,
                    'retry': 3,
                },
            },
            'score': float(score),
            'metrics': {
                'corr': float(corr),
                'r2': float(r2),
                'adf_tstat': float(adf_tstat),
                'pf': float(pf),
            }
        }
    except Exception as e:
        return None


class StreamingScanner:
    """流式配对扫描器"""
    
    def __init__(
        self,
        min_vol: float = 5_000_000,
        scan_interval: int = 600,  # 10分钟
        max_pairs: int = 30,
        n_workers: int = None,
    ):
        self.min_vol = min_vol
        self.scan_interval = scan_interval
        self.max_pairs = max_pairs
        self.n_workers = n_workers or min(cpu_count(), 8)
        
        # 内存缓存
        self.data_cache: Dict[str, SymbolData] = {}
        self.symbols: List[str] = []
        
        # 当前最优配对
        self.current_top_pairs: List[Dict] = []
        self.last_scan_time = 0.0
        
        # 运行状态
        self._running = False
        self._shutdown = False
        
        # TG通知
        self.tg_token = os.getenv('TG_BOT_TOKEN', '')
        self.tg_chat_id = os.getenv('TG_CHAT_ID', '')
    
    async def initialize_data(self):
        """初始化加载所有币种数据"""
        logger.info("[StreamingScanner] Initializing data cache...")
        
        exchange = ccxt.binance({'enableRateLimit': True})
        
        # 获取所有永续合约
        markets = await exchange.load_markets()
        all_symbols = [
            s for s in markets.keys()
            if s.endswith('/USDT:USDT') and markets[s].get('active', False)
        ]
        
        logger.info(f"[StreamingScanner] Found {len(all_symbols)} perpetual contracts")
        
        # 批量获取K线数据（最近5000根1分钟）
        semaphore = asyncio.Semaphore(20)
        
        async def fetch_symbol(symbol):
            async with semaphore:
                try:
                    ohlcv = await exchange.fetch_ohlcv(
                        symbol, 
                        timeframe='1m', 
                        limit=5000
                    )
                    if len(ohlcv) >= 1000:
                        data = SymbolData(symbol=symbol)
                        for candle in ohlcv:
                            data.add_kline(candle[0], candle[4], candle[5])
                        return symbol, data
                except Exception as e:
                    pass
                return symbol, None
        
        # 并发获取
        tasks = [fetch_symbol(s) for s in all_symbols[:150]]  # 前150个
        results = await asyncio.gather(*tasks)
        
        for sym, data in results:
            if data:
                self.data_cache[sym] = data
        
        await exchange.close()
        
        # 筛选流动性充足的
        self.symbols = [
            s for s, d in self.data_cache.items()
            if d.volume_24h >= self.min_vol
        ]
        
        logger.info(f"[StreamingScanner] Initialized: {len(self.symbols)} symbols in cache")
    
    def scan_pairs(self) -> List[Dict]:
        """扫描配对（全量重算）"""
        logger.info(f"[StreamingScanner] Starting scan with {len(self.symbols)} symbols...")
        t0 = time.time()
        
        # 准备数据
        symbol_data = []
        log_prices = {}
        
        for sym in self.symbols:
            log_p = self.data_cache[sym].get_log_prices()
            if log_p is not None:
                log_prices[sym] = log_p
                symbol_data.append(sym)
        
        n = len(symbol_data)
        logger.info(f"[StreamingScanner] {n} symbols have sufficient data")
        
        # 生成所有配对
        pairs_to_check = []
        for i in range(n):
            for j in range(i+1, n):
                sym_a = symbol_data[i]
                sym_b = symbol_data[j]
                pairs_to_check.append((
                    sym_a, sym_b,
                    log_prices[sym_a],
                    log_prices[sym_b]
                ))
        
        logger.info(f"[StreamingScanner] Evaluating {len(pairs_to_check)} pairs with {self.n_workers} workers")
        
        # 多进程并行评估
        with Pool(processes=self.n_workers) as pool:
            results = pool.map(_evaluate_pair, pairs_to_check)
        
        # 过滤并排序
        valid = [r for r in results if r is not None]
        valid.sort(key=lambda x: x['score'], reverse=True)
        
        elapsed = time.time() - t0
        logger.info(f"[StreamingScanner] Scan complete: {len(valid)} valid pairs in {elapsed:.1f}s")
        
        return valid[:self.max_pairs]
    
    async def send_telegram_notification(self, new_pairs: List[Dict], removed_pairs: List[Dict]):
        """发送TG通知"""
        if not self.tg_token or not self.tg_chat_id:
            return
        
        try:
            import aiohttp
            
            message = "🔄 *配对列表更新*\n\n"
            message += f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            if new_pairs:
                message += "✅ *新增配对:*\n"
                for p in new_pairs[:5]:
                    message += f"  • {p['symbol_a'].split('/')[0]} / {p['symbol_b'].split('/')[0]} | Score: {p['score']:.3f}\n"
                message += "\n"
            
            if removed_pairs:
                message += "❌ *移除配对:*\n"
                for p in removed_pairs[:5]:
                    message += f"  • {p['symbol_a'].split('/')[0]} / {p['symbol_b'].split('/')[0]}\n"
                message += "\n"
            
            message += f"📊 当前Top {len(self.current_top_pairs)} 配对已更新"
            
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={
                    'chat_id': self.tg_chat_id,
                    'text': message,
                    'parse_mode': 'Markdown'
                })
        except Exception as e:
            logger.error(f"Failed to send TG notification: {e}")
    
    def save_pairs(self, pairs: List[Dict]):
        """保存配对到文件"""
        output = {
            'meta': {
                'version': '2.0-streaming',
                'pairs_count': len(pairs),
                'generated_at': datetime.now().isoformat(),
                'scanner': 'StreamingScanner'
            },
            'pairs': pairs
        }
        
        # 原子写入
        tmp_file = 'config/pairs_v2.json.tmp'
        final_file = 'config/pairs_v2.json'
        
        with open(tmp_file, 'w') as f:
            json.dump(output, f, indent=2)
        
        os.replace(tmp_file, final_file)
        logger.info(f"[StreamingScanner] Saved {len(pairs)} pairs to {final_file}")
    
    async def run_scan_cycle(self):
        """执行一次扫描周期"""
        logger.info("[StreamingScanner] ====== Starting scan cycle ======")
        
        # 扫描配对
        new_pairs = self.scan_pairs()
        
        # 对比旧列表
        old_symbols = {(p['symbol_a'], p['symbol_b']) for p in self.current_top_pairs}
        new_symbols = {(p['symbol_a'], p['symbol_b']) for p in new_pairs}
        
        added = [p for p in new_pairs if (p['symbol_a'], p['symbol_b']) not in old_symbols]
        removed = [p for p in self.current_top_pairs if (p['symbol_a'], p['symbol_b']) not in new_symbols]
        
        # 更新当前列表
        self.current_top_pairs = new_pairs
        self.last_scan_time = time.time()
        
        # 保存到文件
        self.save_pairs(new_pairs)
        
        # 发送通知（如果有变化）
        if added or removed:
            await self.send_telegram_notification(added, removed)
        
        logger.info(f"[StreamingScanner] Cycle complete: +{len(added)} -{len(removed)} pairs")
    
    async def incremental_update(self):
        """增量更新价格数据（每10秒）"""
        exchange = ccxt.binance({'enableRateLimit': True})
        
        while self._running and not self._shutdown:
            try:
                # 获取最新价格
                tickers = await exchange.fetch_tickers(self.symbols[:100])
                
                for sym, ticker in tickers.items():
                    if sym in self.data_cache:
                        last_price = ticker.get('last', 0)
                        volume = ticker.get('quoteVolume', 0)
                        timestamp = ticker.get('timestamp', int(time.time() * 1000))
                        
                        if last_price > 0:
                            self.data_cache[sym].add_kline(timestamp, last_price, volume)
                
                # 每10秒更新一次
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"Incremental update error: {e}")
                await asyncio.sleep(10)
        
        await exchange.close()
    
    async def scan_scheduler(self):
        """扫描调度器（每10分钟）"""
        while self._running and not self._shutdown:
            try:
                await self.run_scan_cycle()
                
                # 等待到下一次扫描
                await asyncio.sleep(self.scan_interval)
                
            except Exception as e:
                logger.error(f"Scan scheduler error: {e}")
                await asyncio.sleep(60)
    
    async def run(self):
        """主入口"""
        logger.info("="*60)
        logger.info("Streaming Scanner Starting...")
        logger.info("="*60)
        
        self._running = True
        
        # 初始化数据
        await self.initialize_data()
        
        if len(self.symbols) < 10:
            logger.error("Not enough symbols initialized!")
            return
        
        # 首次扫描
        await self.run_scan_cycle()
        
        # 启动两个任务
        tasks = [
            asyncio.create_task(self.incremental_update()),
            asyncio.create_task(self.scan_scheduler()),
        ]
        
        # 等待信号
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        
        self._running = False
        logger.info("[StreamingScanner] Shutdown complete")
    
    def shutdown(self):
        """优雅关闭"""
        logger.info("[StreamingScanner] Shutdown requested...")
        self._shutdown = True


def main():
    """CLI入口"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    scanner = StreamingScanner(
        min_vol=5_000_000,
        scan_interval=600,  # 10分钟
        max_pairs=30,
        n_workers=8
    )
    
    # 信号处理
    def signal_handler(signum, frame):
        scanner.shutdown()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # 运行
    try:
        asyncio.run(scanner.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
