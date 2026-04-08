"""
流式滚动扫描器 (Streaming Scanner)
M0-M5 全链路流式处理，每10-30分钟覆盖全市场

设计理念:
- 流水线架构：数据 → 初筛 → 配对 → 优化 → 推送
- 边扫边推：每发现合格配对立即通知
- 滚动覆盖：持续扫描，不中断
"""

import asyncio
import logging
import numpy as np
import ccxt
from typing import List, Dict, Optional, Callable, AsyncGenerator
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger("StreamingScanner")


@dataclass
class ScanResult:
    """扫描结果数据类"""
    timestamp: float
    symbol_a: str
    symbol_b: str
    stage: str  # 'phase1', 'phase2', 'optimized'
    score: float
    params: Dict
    metrics: Dict


class StreamingPairFinder:
    """
    流式配对发现器
    边扫描币安全市场，边推送符合条件的配对
    """
    
    def __init__(self, notifier=None):
        self.notifier = notifier
        self.exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        
        # 扫描参数
        self.scan_interval = 600  # 10分钟一个周期
        self.lookback_bars = 120  # 最近120根1mK线
        self.coverage_target = 1800  # 30分钟覆盖全市场
        
        # 筛选阈值
        self.thresholds = {
            'min_volume_24h': 5_000_000,  # 500万USDT
            'min_corr': 0.8,
            'min_spread_std': 0.002,
            'min_z_cross_120': 3,
            'min_z_cross_30': 1,
            'min_corr_mean': 0.85,
            'max_corr_std': 0.1,
            'max_half_life': 30,
        }
        
        # 运行时状态
        self.active_symbols = []
        self.scanned_pairs = set()
        self.found_pairs = {}
        self.is_running = False
    
    async def fetch_all_symbols(self) -> List[str]:
        """M0: 获取币安全部永续合约"""
        try:
            markets = await asyncio.to_thread(self.exchange.load_markets)
            symbols = []
            for symbol, market in markets.items():
                if market.get('swap') and symbol.endswith('/USDT:USDT'):
                    # 检查24h成交量
                    try:
                        ticker = await asyncio.to_thread(self.exchange.fetch_ticker, symbol)
                        vol = ticker.get('quoteVolume', 0)
                        if vol >= self.thresholds['min_volume_24h']:
                            symbols.append(symbol.replace(':USDT', ''))
                    except:
                        continue
            logger.info(f"M0: 发现 {len(symbols)} 个合格币种")
            return symbols
        except Exception as e:
            logger.error(f"M0: 获取币种失败: {e}")
            return []
    
    async def fetch_klines(self, symbol: str, limit: int = 120) -> Optional[np.ndarray]:
        """M1: 获取1分钟K线数据"""
        try:
            contract_symbol = symbol.replace('/USDT', '/USDT:USDT')
            ohlcv = await asyncio.to_thread(
                self.exchange.fetch_ohlcv, 
                contract_symbol, 
                '1m', 
                limit=limit
            )
            if len(ohlcv) < limit * 0.8:  # 数据完整性检查
                return None
            closes = np.array([x[4] for x in ohlcv], dtype=np.float64)
            return np.log(closes)
        except Exception as e:
            logger.debug(f"M1: {symbol} 数据获取失败: {e}")
            return None
    
    async def phase1_filter(self, sym_a: str, log_a: np.ndarray, 
                           sym_b: str, log_b: np.ndarray) -> Optional[Dict]:
        """M3-初筛: 快速检查配对质量"""
        n = min(len(log_a), len(log_b))
        if n < 120:
            return None
        
        # 1. 相关系数
        corr = self._fast_corr(log_a[-120:], log_b[-120:])
        if corr <= self.thresholds['min_corr']:
            return None
        
        # 2. Spread统计
        spread = log_a[-120:] - log_b[-120:]
        spread_std = np.std(spread)
        if spread_std <= self.thresholds['min_spread_std']:
            return None
        
        # 3. Z-score穿越次数
        z_cross_120 = self._count_z_crosses(spread, z_threshold=2.0)
        if z_cross_120 < self.thresholds['min_z_cross_120']:
            return None
        
        z_cross_30 = self._count_z_crosses(spread[-30:], z_threshold=2.0)
        if z_cross_30 < self.thresholds['min_z_cross_30']:
            return None
        
        return {
            'symbol_a': sym_a,
            'symbol_b': sym_b,
            'corr': corr,
            'spread_std': spread_std,
            'z_cross_120': z_cross_120,
            'z_cross_30': z_cross_30,
            'log_a': log_a,
            'log_b': log_b
        }
    
    async def phase2_filter(self, p1_result: Dict) -> Optional[Dict]:
        """M3-二筛: 深度质量检查"""
        log_a = p1_result['log_a']
        log_b = p1_result['log_b']
        spread = log_a[-120:] - log_b[-120:]
        
        # 1. 滚动相关系数统计
        corr_mean, corr_std = self._rolling_corr_stats(log_a, log_b)
        if corr_mean <= self.thresholds['min_corr_mean'] or corr_std >= self.thresholds['max_corr_std']:
            return None
        
        # 2. 半衰期
        half_life = self._compute_half_life(spread)
        if half_life >= self.thresholds['max_half_life']:
            return None
        
        # 3. 近期活跃度
        recent_z_cross = self._count_z_crosses(spread[-60:], z_threshold=2.0)
        if recent_z_cross < 2:
            return None
        
        # 评分
        score = (
            0.4 * corr_mean +
            0.3 * (1.0 - corr_std) +
            0.2 * (1.0 / (1.0 + half_life / 10)) +
            0.1 * min(recent_z_cross / 5.0, 1.0)
        )
        
        return {
            'symbol_a': p1_result['symbol_a'],
            'symbol_b': p1_result['symbol_b'],
            'score': score,
            'corr_mean': corr_mean,
            'corr_std': corr_std,
            'half_life': half_life,
            'recent_z_cross': recent_z_cross,
            'corr': p1_result['corr'],
            'spread_std': p1_result['spread_std']
        }
    
    async def optimize_pair(self, p2_result: Dict) -> Optional[Dict]:
        """M4: 快速参数优化"""
        # 简化的参数搜索
        best_pf = 0
        best_params = {'entry': 2.0, 'exit': 0.5, 'stop': 3.5}
        
        # 这里可以接入更复杂的优化逻辑
        # 目前使用默认参数 + 简单评分调整
        
        return {
            **p2_result,
            'params': {
                'z_entry': best_params['entry'],
                'z_exit': best_params['exit'],
                'z_stop': best_params['stop'],
            },
            'execution': {
                'scale_in': [
                    {'layer': 0, 'ratio': 0.3, 'z_threshold': 2.0},
                    {'layer': 1, 'ratio': 0.3, 'z_threshold': 2.5},
                    {'layer': 2, 'ratio': 0.4, 'z_threshold': 3.0},
                ],
                'legs_sync': {
                    'tolerance_ms': 5000,
                    'retry': 3,
                },
            },
            'expected_pf': 1.5 + p2_result['score']  # 预估PF
        }
    
    async def stream_scan(self, callback: Callable[[ScanResult], None] = None):
        """
        流式扫描主循环
        每10分钟启动一轮，30分钟覆盖全市场
        """
        self.is_running = True
        scan_round = 0
        
        while self.is_running:
            scan_round += 1
            start_time = datetime.now()
            logger.info(f"=== 开始第 {scan_round} 轮流式扫描 ===")
            
            # M0: 获取全市场币种
            symbols = await self.fetch_all_symbols()
            if len(symbols) < 2:
                logger.warning("合格币种不足，等待下一轮")
                await asyncio.sleep(60)
                continue
            
            # M1: 批量获取数据（流式）
            logger.info(f"M1: 获取 {len(symbols)} 个币种数据...")
            symbol_data = {}
            
            for i, sym in enumerate(symbols):
                log_close = await self.fetch_klines(sym, self.lookback_bars)
                if log_close is not None:
                    symbol_data[sym] = log_close
                
                # 每10个币种检查一次时间
                if i % 10 == 0:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed > self.coverage_target:
                        logger.warning(f"扫描超时，已处理 {i}/{len(symbols)} 个币种")
                        break
                    await asyncio.sleep(0.1)  # 限速
            
            logger.info(f"M1: 成功获取 {len(symbol_data)} 个币种数据")
            
            # M2-M3-M4: 流式配对扫描
            symbol_list = list(symbol_data.keys())
            total_combinations = len(symbol_list) * (len(symbol_list) - 1)
            processed = 0
            found_phase1 = 0
            found_phase2 = 0
            
            logger.info(f"M3: 开始扫描 {total_combinations} 个配对组合...")
            
            for i, sym_a in enumerate(symbol_list):
                for sym_b in symbol_list[i+1:]:  # 避免重复和自配对
                    processed += 1
                    
                    # 检查是否已扫描过
                    pair_key = f"{sym_a}_{sym_b}"
                    if pair_key in self.scanned_pairs:
                        continue
                    
                    # M3-初筛
                    p1_result = await self.phase1_filter(
                        sym_a, symbol_data[sym_a],
                        sym_b, symbol_data[sym_b]
                    )
                    
                    if p1_result:
                        found_phase1 += 1
                        self.scanned_pairs.add(pair_key)
                        
                        # 🔥 滚动推送：初筛通过
                        if callback:
                            await callback(ScanResult(
                                timestamp=datetime.now().timestamp(),
                                symbol_a=sym_a,
                                symbol_b=sym_b,
                                stage='phase1',
                                score=p1_result['corr'],
                                params={},
                                metrics={
                                    'corr': p1_result['corr'],
                                    'spread_std': p1_result['spread_std'],
                                    'z_cross_120': p1_result['z_cross_120']
                                }
                            ))
                        
                        # M3-二筛（异步）
                        p2_result = await self.phase2_filter(p1_result)
                        if p2_result:
                            found_phase2 += 1
                            
                            # M4-优化
                            opt_result = await self.optimize_pair(p2_result)
                            
                            # 🔥 滚动推送：二筛通过并优化完成
                            if callback:
                                await callback(ScanResult(
                                    timestamp=datetime.now().timestamp(),
                                    symbol_a=sym_a,
                                    symbol_b=sym_b,
                                    stage='optimized',
                                    score=p2_result['score'],
                                    params=opt_result['params'],
                                    metrics={
                                        'corr_mean': p2_result['corr_mean'],
                                        'corr_std': p2_result['corr_std'],
                                        'half_life': p2_result['half_life'],
                                        'expected_pf': opt_result['expected_pf']
                                    }
                                ))
                            
                            # 保存结果
                            self.found_pairs[pair_key] = opt_result
                    
                    # 进度报告（每1000对）
                    if processed % 1000 == 0:
                        progress = processed / total_combinations * 100
                        logger.info(f"进度: {progress:.1f}% | "
                                  f"已处理 {processed} 对 | "
                                  f"初筛通过 {found_phase1} | "
                                  f"二筛通过 {found_phase2}")
                    
                    # 流式间隔，避免阻塞
                    if processed % 100 == 0:
                        await asyncio.sleep(0.01)
            
            # 本轮扫描完成
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"=== 第 {scan_round} 轮扫描完成 ===")
            logger.info(f"耗时: {elapsed:.0f}s | 处理: {processed} 对 | "
                       f"初筛: {found_phase1} | 二筛: {found_phase2} | "
                       f"累计发现: {len(self.found_pairs)} 个优质配对")
            
            # 等待到下一个扫描周期
            sleep_time = max(0, self.scan_interval - elapsed)
            if sleep_time > 0:
                logger.info(f"{sleep_time:.0f}秒后开始下一轮...")
                await asyncio.sleep(sleep_time)
    
    def stop(self):
        """停止扫描"""
        self.is_running = False
        logger.info("流式扫描器已停止")
    
    # ═══════════════════════════════════════════════════
    # 工具函数
    # ═══════════════════════════════════════════════════
    
    def _fast_corr(self, x: np.ndarray, y: np.ndarray) -> float:
        """快速相关系数"""
        x_mean, y_mean = np.mean(x), np.mean(y)
        cov = np.sum((x - x_mean) * (y - y_mean))
        x_var = np.sum((x - x_mean) ** 2)
        y_var = np.sum((y - y_mean) ** 2)
        if x_var < 1e-12 or y_var < 1e-12:
            return 0.0
        return cov / np.sqrt(x_var * y_var)
    
    def _count_z_crosses(self, spread: np.ndarray, z_threshold: float = 2.0) -> int:
        """计算Z-score穿越次数"""
        n = len(spread)
        if n < 2:
            return 0
        
        count = 0
        in_zone = False
        
        for i in range(1, n):
            sub = spread[:i+1]
            mean = np.mean(sub)
            std = np.std(sub) + 1e-12
            z = abs((spread[i] - mean) / std)
            
            if z > z_threshold:
                if not in_zone:
                    count += 1
                    in_zone = True
            else:
                in_zone = False
        
        return count
    
    def _rolling_corr_stats(self, x: np.ndarray, y: np.ndarray, window: int = 120) -> tuple:
        """滚动相关系数统计"""
        n = min(len(x), len(y))
        if n < window:
            return 0.0, 1.0
        
        corrs = []
        for i in range(n - window + 1):
            corr = self._fast_corr(x[i:i+window], y[i:i+window])
            corrs.append(corr)
        
        return np.mean(corrs), np.std(corrs)
    
    def _compute_half_life(self, spread: np.ndarray) -> float:
        """计算半衰期"""
        n = len(spread)
        if n < 60:
            return 999.0
        
        y = spread[1:]
        x = spread[:-1]
        
        x_mean, y_mean = np.mean(x), np.mean(y)
        numerator = np.sum((x - x_mean) * (y - y_mean))
        denominator = np.sum((x - x_mean) ** 2)
        
        if denominator < 1e-12:
            return 999.0
        
        beta = numerator / denominator
        if beta >= 1.0 or beta <= 0:
            return 999.0
        
        return -np.log(2) / np.log(beta)


# ═══════════════════════════════════════════════════
# 使用示例
# ═══════════════════════════════════════════════════

async def example_callback(result: ScanResult):
    """示例回调：打印并推送"""
    msg = f"[{result.stage.upper()}] {result.symbol_a} <-> {result.symbol_b} | Score={result.score:.3f}"
    
    if result.stage == 'phase1':
        print(f"🔍 {msg}")
    elif result.stage == 'optimized':
        print(f"✅ {msg} | Entry={result.params.get('z_entry')} | PF={result.metrics.get('expected_pf', 0):.2f}")
    
    # 这里可以接入 Telegram 推送


async def main():
    """示例运行"""
    scanner = StreamingPairFinder()
    
    try:
        await scanner.stream_scan(callback=example_callback)
    except KeyboardInterrupt:
        scanner.stop()


if __name__ == "__main__":
    asyncio.run(main())
