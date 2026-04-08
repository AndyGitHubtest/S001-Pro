#!/usr/bin/env python3
"""
极速扫描器 - 3分钟目标

核心优化:
1. 分层漏斗: 相关性 → OLS → 快速协整 → 轻量回测
2. 算法替换: Kalman→OLS, ADF→简化t-test
3. 并行处理: 8核多进程
4. 数据预加载: 内存缓存
"""

import numpy as np
import pandas as pd
import asyncio
import json
import logging
import time
from typing import List, Dict, Tuple, Optional
from multiprocessing import Pool, cpu_count
from dataclasses import dataclass
import ccxt.async_support as ccxt

# Numba加速
try:
    from numba import njit, prange
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*args, **kwargs):
        def decorator(f): return f
        return decorator
    prange = range

logger = logging.getLogger("FastScanner")


@dataclass
class FastPairScore:
    """配对评分结果"""
    symbol_a: str
    symbol_b: str
    corr: float
    beta: float
    r2: float
    adf_tstat: float
    pf: float
    score: float


@njit(cache=True, fastmath=True)
def _fast_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """向量化快速相关系数"""
    n = len(x)
    if n < 2:
        return 0.0
    
    mean_x = np.mean(x)
    mean_y = np.mean(y)
    
    num = np.sum((x - mean_x) * (y - mean_y))
    den_x = np.sum((x - mean_x) ** 2)
    den_y = np.sum((y - mean_y) ** 2)
    
    if den_x == 0 or den_y == 0:
        return 0.0
    
    return num / np.sqrt(den_x * den_y)


@njit(cache=True, fastmath=True)
def _fast_ols_beta(x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    """
    快速OLS回归: y = beta * x + alpha
    返回: (beta, r2)
    """
    n = len(x)
    if n < 2:
        return 0.0, 0.0
    
    # 计算均值
    mean_x = np.mean(x)
    mean_y = np.mean(y)
    
    # 计算协方差和方差
    cov = np.sum((x - mean_x) * (y - mean_y))
    var_x = np.sum((x - mean_x) ** 2)
    var_y = np.sum((y - mean_y) ** 2)
    
    if var_x == 0:
        return 0.0, 0.0
    
    beta = cov / var_x
    
    # 计算R²
    ss_res = np.sum((y - mean_y - beta * (x - mean_x)) ** 2)
    ss_tot = var_y
    
    r2 = 1.0 - ss_res / (ss_tot + 1e-10)
    
    return beta, r2


@njit(cache=True, fastmath=True)
def _fast_adf_tstat(spread: np.ndarray) -> float:
    """
    简化版ADF检验 - 只计算t-statistic
    假设: 使用一阶差分自回归
    """
    n = len(spread)
    if n < 10:
        return 0.0
    
    # 计算一阶差分
    dy = np.diff(spread)
    y_lag = spread[:-1]
    
    # OLS回归: dy = gamma * y_lag + epsilon
    mean_dy = np.mean(dy)
    mean_y = np.mean(y_lag)
    
    cov = np.sum((y_lag - mean_y) * (dy - mean_dy))
    var_y = np.sum((y_lag - mean_y) ** 2)
    
    if var_y == 0:
        return 0.0
    
    gamma = cov / var_y
    
    # 计算残差标准误
    residuals = dy - mean_dy - gamma * (y_lag - mean_y)
    se = np.sqrt(np.sum(residuals ** 2) / (n - 2)) / np.sqrt(var_y)
    
    if se == 0:
        return 0.0
    
    t_stat = gamma / se
    return t_stat


@njit(cache=True, fastmath=True)
def _fast_backtest_pf(
    log_a: np.ndarray,
    log_b: np.ndarray,
    beta: float,
    z_entry: float = 2.0,
    z_exit: float = 0.5,
    cost_pct: float = 0.0005
) -> float:
    """
    超轻量回测 - 只返回Profit Factor
    """
    n = len(log_a)
    if n < 100:
        return 0.0
    
    # 计算spread
    spread = log_a - beta * log_b
    
    # 计算rolling z-score (简化版，使用固定窗口)
    window = min(100, n // 4)
    z_scores = np.zeros(n)
    
    for i in range(window, n):
        window_data = spread[i-window:i]
        mean = np.mean(window_data)
        std = np.std(window_data) + 1e-10
        z_scores[i] = (spread[i] - mean) / std
    
    # 简单回测逻辑
    position = 0
    gross_profit = 0.0
    gross_loss = 0.0
    
    for i in range(window, n):
        z = z_scores[i]
        
        if position == 0:
            if z > z_entry:
                position = -1  # Short spread
            elif z < -z_entry:
                position = 1  # Long spread
        else:
            # 检查退出条件
            exit_long = position == 1 and (z > -z_exit or z < -z_entry - 1.0)
            exit_short = position == -1 and (z < z_exit or z > z_entry + 1.0)
            
            if exit_long or exit_short:
                # 计算收益
                pnl = position * (z_scores[i] - z_scores[i-1]) * 0.01  # 简化计算
                pnl -= cost_pct * 2  # 双边成本
                
                if pnl > 0:
                    gross_profit += pnl
                else:
                    gross_loss += -pnl
                
                position = 0
    
    if gross_loss < 1e-10:
        return 2.0 if gross_profit > 0 else 0.0
    
    return gross_profit / gross_loss


def _evaluate_pair_fast(args) -> Optional[FastPairScore]:
    """
    评估单个配对 (用于多进程)
    """
    sym_a, sym_b, log_a, log_b = args
    
    try:
        # 1. 快速相关性
        corr = _fast_correlation(log_a, log_b)
        if abs(corr) < 0.85:
            return None
        
        # 2. 快速OLS
        beta, r2 = _fast_ols_beta(log_b, log_a)  # y=price_a, x=price_b
        if r2 < 0.7:
            return None
        
        # 3. 快速协整检验
        spread = log_a - beta * log_b
        adf_tstat = _fast_adf_tstat(spread)
        if adf_tstat > -2.5:  # 不拒绝单位根，非协整
            return None
        
        # 4. 轻量回测
        pf = _fast_backtest_pf(log_a, log_b, beta)
        if pf < 1.2:
            return None
        
        # 5. 综合评分
        score = (
            abs(corr) * 0.2 +
            r2 * 0.3 +
            min(abs(adf_tstat) / 5.0, 1.0) * 0.2 +
            min(pf / 3.0, 1.0) * 0.3
        )
        
        return FastPairScore(
            symbol_a=sym_a,
            symbol_b=sym_b,
            corr=corr,
            beta=beta,
            r2=r2,
            adf_tstat=adf_tstat,
            pf=pf,
            score=score
        )
    
    except Exception as e:
        return None


class FastScanner:
    """极速扫描器"""
    
    def __init__(
        self,
        min_vol: float = 5_000_000,  # 500万U流动性
        max_pairs: int = 30,
        n_workers: int = None,
    ):
        self.min_vol = min_vol
        self.max_pairs = max_pairs
        self.n_workers = n_workers or min(cpu_count(), 8)
        self.data_cache = {}  # 币种数据缓存
        
    async def fetch_market_data(self) -> Dict[str, pd.DataFrame]:
        """获取市场数据 (并行)"""
        logger.info("[FastScanner] Fetching market data...")
        t0 = time.time()
        
        # 使用ccxt获取币安数据
        exchange = ccxt.binance({'enableRateLimit': True})
        
        # 获取所有永续合约
        markets = await exchange.load_markets()
        symbols = [
            s for s in markets.keys()
            if s.endswith('/USDT:USDT') and markets[s].get('active', False)
        ]
        
        logger.info(f"[FastScanner] Found {len(symbols)} perpetual contracts")
        
        # 获取24h成交量数据
        tickers = await exchange.fetch_tickers(symbols)
        
        # 筛选流动性充足的币种
        qualified = []
        for symbol, ticker in tickers.items():
            vol = ticker.get('quoteVolume', 0)
            if vol >= self.min_vol:
                qualified.append(symbol)
        
        logger.info(f"[FastScanner] {len(qualified)} symbols meet liquidity filter")
        
        # 获取K线数据 (并行，但限制并发)
        semaphore = asyncio.Semaphore(10)  # 最多10个并发
        
        async def fetch_ohlcv_safe(symbol):
            async with semaphore:
                try:
                    ohlcv = await exchange.fetch_ohlcv(
                        symbol, 
                        timeframe='1m', 
                        limit=5000  # 约3.5天数据
                    )
                    if len(ohlcv) >= 1000:  # 至少1000根K线
                        df = pd.DataFrame(
                            ohlcv, 
                            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                        )
                        return symbol, df
                except Exception as e:
                    pass
                return symbol, None
        
        # 批量获取
        tasks = [fetch_ohlcv_safe(s) for s in qualified[:100]]  # 只取前100
        results = await asyncio.gather(*tasks)
        
        data = {sym: df for sym, df in results if df is not None}
        
        await exchange.close()
        
        elapsed = time.time() - t0
        logger.info(f"[FastScanner] Data fetched: {len(data)} symbols in {elapsed:.1f}s")
        
        return data
    
    def scan(self, data: Dict[str, pd.DataFrame]) -> List[FastPairScore]:
        """执行极速扫描"""
        logger.info("[FastScanner] Starting fast scan...")
        t0 = time.time()
        
        symbols = list(data.keys())
        n = len(symbols)
        
        logger.info(f"[FastScanner] Level 1: Correlation filtering ({n} symbols)")
        
        # Level 1: 相关性矩阵 (向量化)
        price_matrix = np.array([data[s]['close'].values[-1000:] for s in symbols])
        log_matrix = np.log(price_matrix)
        
        # 计算相关性矩阵
        corr_matrix = np.corrcoef(log_matrix)
        
        # 筛选高相关性配对
        pairs_to_check = []
        for i in range(n):
            for j in range(i+1, n):
                if abs(corr_matrix[i, j]) > 0.85:
                    pairs_to_check.append((
                        symbols[i],
                        symbols[j],
                        log_matrix[i],
                        log_matrix[j]
                    ))
        
        logger.info(f"[FastScanner] Level 1 passed: {len(pairs_to_check)} pairs (|corr|>0.85)")
        
        if not pairs_to_check:
            return []
        
        # Level 2-4: 多进程并行评估
        logger.info(f"[FastScanner] Level 2-4: Parallel evaluation ({self.n_workers} workers)")
        
        with Pool(processes=self.n_workers) as pool:
            results = pool.map(_evaluate_pair_fast, pairs_to_check)
        
        # 过滤None并排序
        valid_results = [r for r in results if r is not None]
        valid_results.sort(key=lambda x: x.score, reverse=True)
        
        elapsed = time.time() - t0
        logger.info(f"[FastScanner] Scan complete: {len(valid_results)} pairs in {elapsed:.1f}s")
        
        return valid_results[:self.max_pairs]
    
    def to_whitelist_format(self, results: List[FastPairScore]) -> List[Dict]:
        """转换为pairs_v2.json格式"""
        whitelist = []
        for r in results:
            whitelist.append({
                'symbol_a': r.symbol_a,
                'symbol_b': r.symbol_b,
                'beta': r.beta,
                'params': {
                    'z_entry': 2.0,
                    'z_exit': 0.5,
                    'z_stop': 3.0,
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
                'score': r.score,
                'metrics': {
                    'corr': r.corr,
                    'r2': r.r2,
                    'adf_tstat': r.adf_tstat,
                    'pf': r.pf,
                }
            })
        return whitelist


async def main():
    """CLI入口"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    scanner = FastScanner(
        min_vol=5_000_000,
        max_pairs=30,
        n_workers=8
    )
    
    total_t0 = time.time()
    
    # 1. 获取数据
    data = await scanner.fetch_market_data()
    
    if len(data) < 10:
        logger.error("Not enough data fetched")
        return
    
    # 2. 扫描
    results = scanner.scan(data)
    
    # 3. 输出
    whitelist = scanner.to_whitelist_format(results)
    
    # 保存
    output = {
        'meta': {
            'version': '2.0-fast',
            'pairs_count': len(whitelist),
            'generated_at': pd.Timestamp.now().isoformat(),
            'scanner': 'FastScanner'
        },
        'pairs': whitelist
    }
    
    with open('pairs_fast.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    total_elapsed = time.time() - total_t0
    
    print("\n" + "="*60)
    print(f"极速扫描完成!")
    print(f"总用时: {total_elapsed:.1f}秒 ({total_elapsed/60:.1f}分钟)")
    print(f"产出配对: {len(whitelist)}个")
    print("="*60)
    
    for i, p in enumerate(whitelist[:5], 1):
        print(f"{i}. {p['symbol_a']} <-> {p['symbol_b']} | Score={p['score']:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
