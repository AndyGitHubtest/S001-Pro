"""
模块三：配对评分 (Pairwise Scorer) - 三层架构版

三层筛选架构:
  第一层（硬过滤）: corr_median ≥ 0.6, cointegration p ≤ 0.1, ADF p ≤ 0.1
  第二层（质量）: half_life ≤ 30, rolling_corr_std ≤ 0.15
  第三层（可交易）: zscore_max ≥ 2, daily_volume ≥ 2M

数据流转:
  Input:  Qualified symbols 列表 (来自 M2 初筛), Hot Pool 数据
  Output: Top 100 配对候选
  去向:   传递给模块四 (Optimizer)
"""

import logging
import numpy as np
from typing import List, Dict, Optional, Tuple
from multiprocessing import Pool

logger = logging.getLogger("PairwiseScorer")

# Numba 加速
try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*args, **kwargs):
        def decorator(f):
            return f
        return decorator


# ═══════════════════════════════════════════════════
# 统计检验函数 (纯NumPy实现,无外部依赖)
# ═══════════════════════════════════════════════════

def adf_test(series: np.ndarray, maxlag: int = 1) -> float:
    """
    简化版ADF单位根检验，返回p-value估计
    基于Dickey-Fuller检验原理
    """
    try:
        if len(series) < 30:
            return 1.0
        
        n = len(series)
        
        # 计算一阶差分
        y = series[1:]
        y_lag = series[:-1]
        
        # 回归: delta_y = alpha + beta * y_lag + epsilon
        y_mean = np.mean(y)
        lag_mean = np.mean(y_lag)
        
        # 计算beta (斜率)
        num = np.sum((y_lag - lag_mean) * (y - y_mean))
        den = np.sum((y_lag - lag_mean) ** 2)
        
        if den < 1e-10:
            return 1.0
        
        beta = num / den
        alpha = y_mean - beta * lag_mean
        
        # 计算残差和t统计量
        residual = y - alpha - beta * y_lag
        rss = np.sum(residual ** 2)
        
        if rss < 1e-10 or n - 2 <= 0:
            return 1.0
        
        se = np.sqrt(rss / (n - 2))
        se_beta = se / np.sqrt(den)
        
        if se_beta < 1e-10:
            return 1.0
        
        t_stat = beta / se_beta
        
        # 简化: t_stat < -2.86 对应 p < 0.05 (ADF临界值)
        # 我们使用线性映射近似p-value
        if t_stat < -3.0:
            p_value = 0.01
        elif t_stat < -2.86:
            p_value = 0.05
        elif t_stat < -2.57:
            p_value = 0.1
        else:
            p_value = 0.5
        
        return p_value
    except Exception:
        return 1.0


def calculate_half_life(spread: np.ndarray) -> float:
    """计算半衰期 (Ornstein-Uhlenbeck过程)"""
    try:
        if len(spread) < 30:
            return 999.0
        
        # Y_t = Y_{t-1} + beta * Y_{t-1} + epsilon
        y_lag = spread[:-1]
        y_diff = np.diff(spread)
        
        # 线性回归: delta_y = alpha + beta * y_lag
        y_lag_mean = np.mean(y_lag)
        y_diff_mean = np.mean(y_diff)
        
        beta = np.sum((y_lag - y_lag_mean) * (y_diff - y_diff_mean)) / (np.sum((y_lag - y_lag_mean) ** 2) + 1e-10)
        
        if beta >= 0:
            return 999.0  # 非均值回归
        
        half_life = -np.log(2) / beta
        return max(0, half_life)
    except Exception:
        return 999.0


def calculate_cointegration_p(log_a: np.ndarray, log_b: np.ndarray) -> float:
    """计算协整性p-value (简化版：对残差做ADF检验)"""
    try:
        if len(log_a) < 30 or len(log_b) < 30:
            return 1.0
        
        # 线性回归: log_a = alpha + beta * log_b + residual
        x_mean = np.mean(log_b)
        y_mean = np.mean(log_a)
        
        beta = np.sum((log_b - x_mean) * (log_a - y_mean)) / (np.sum((log_b - x_mean) ** 2) + 1e-10)
        alpha = y_mean - beta * x_mean
        
        residual = log_a - alpha - beta * log_b
        
        # 对残差做ADF检验
        return adf_test(residual)
    except Exception:
        return 1.0


def calculate_rolling_corr_std(log_a: np.ndarray, log_b: np.ndarray, window: int = 288) -> float:
    """计算滚动相关系数的标准差"""
    try:
        if len(log_a) < window * 2:
            return 999.0
        
        n = len(log_a)
        n_windows = min(20, (n - window) // window)  # 最多20个窗口
        
        corrs = []
        for i in range(n_windows):
            start = i * window
            end = start + window
            a_window = log_a[start:end]
            b_window = log_b[start:end]
            
            if np.std(a_window) > 1e-10 and np.std(b_window) > 1e-10:
                corr = np.corrcoef(a_window, b_window)[0, 1]
                if not np.isnan(corr) and not np.isinf(corr):
                    corrs.append(corr)
        
        if len(corrs) < 3:
            return 999.0
        
        return np.std(corrs)
    except Exception:
        return 999.0


def calculate_zscore_max(spread: np.ndarray) -> float:
    """计算Z-score的最大绝对值"""
    try:
        if len(spread) < 30:
            return 0.0
        
        mean = np.mean(spread)
        std = np.std(spread)
        
        if std < 1e-10:
            return 0.0
        
        z_scores = (spread - mean) / std
        return np.max(np.abs(z_scores))
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════
# 三层筛选工作函数
# ═══════════════════════════════════════════════════

def _process_pair_three_layer(args) -> Optional[Dict]:
    """
    三层筛选工作函数
    Args: (sym_a, sym_b, log_a, log_b, vol_a, vol_b)
    """
    sym_a, sym_b, log_a, log_b, vol_a, vol_b = args
    
    # 对齐数据
    n = min(len(log_a), len(log_b))
    if n < 1000:
        return None
    
    log_a = log_a[:n]
    log_b = log_b[:n]
    
    result = {
        'symbol_a': sym_a,
        'symbol_b': sym_b,
        'layer1_passed': False,
        'layer2_passed': False,
        'layer3_passed': False,
    }
    
    # ═══════════════════════════════════════════════
    # 第一层（硬过滤）
    # ═══════════════════════════════════════════════
    
    # 1. corr_median ≥ 0.6
    try:
        window_size = min(288, n // 4)
        n_windows = min(10, n // window_size)
        corrs = []
        for i in range(n_windows):
            start = i * window_size
            end = start + window_size
            if end <= n:
                a_window = log_a[start:end]
                b_window = log_b[start:end]
                if np.std(a_window) > 1e-10 and np.std(b_window) > 1e-10:
                    corr = np.corrcoef(a_window, b_window)[0, 1]
                    if not np.isnan(corr):
                        corrs.append(corr)
        
        if len(corrs) < 3:
            return None
        
        corr_median = np.median(corrs)
        if corr_median < 0.6:
            return None
        result['corr_median'] = corr_median
    except Exception:
        return None
    
    # 2. cointegration p ≤ 0.1
    coint_p = calculate_cointegration_p(log_a, log_b)
    if coint_p > 0.1:
        return None
    result['coint_p'] = coint_p
    
    # 3. ADF p ≤ 0.1
    spread = log_a - log_b
    adf_p = adf_test(spread)
    if adf_p > 0.1:
        return None
    result['adf_p'] = adf_p
    
    result['layer1_passed'] = True
    
    # ═══════════════════════════════════════════════
    # 第二层（质量）
    # ═══════════════════════════════════════════════
    
    # 4. half_life ≤ 30
    half_life = calculate_half_life(spread)
    if half_life > 30:
        return None
    result['half_life'] = half_life
    
    # 5. rolling_corr_std ≤ 0.15
    corr_std = calculate_rolling_corr_std(log_a, log_b)
    if corr_std > 0.15:
        return None
    result['corr_std'] = corr_std
    
    result['layer2_passed'] = True
    
    # ═══════════════════════════════════════════════
    # 第三层（可交易）
    # ═══════════════════════════════════════════════
    
    # 6. zscore_max ≥ 2
    zscore_max = calculate_zscore_max(spread)
    if zscore_max < 2:
        return None
    result['zscore_max'] = zscore_max
    
    # 7. daily_volume ≥ 2M (USDT)
    if len(vol_a) > 0 and len(vol_b) > 0:
        daily_vol_a = np.mean(vol_a) * 1440  # 1分钟转日
        daily_vol_b = np.mean(vol_b) * 1440
        min_daily_vol = min(daily_vol_a, daily_vol_b)
        if min_daily_vol < 2_000_000:
            return None
        result['daily_volume'] = min_daily_vol
    else:
        return None
    
    result['layer3_passed'] = True
    
    # 综合评分
    result['score'] = (
        0.3 * corr_median +
        0.2 * (1 - coint_p) +
        0.2 * (1 - adf_p) +
        0.1 * max(0, 1 - half_life/30) +
        0.1 * max(0, 1 - corr_std/0.15) +
        0.1 * min(zscore_max/5, 1)
    )
    
    return result


# ═══════════════════════════════════════════════════
# Pairwise Scorer 类
# ═══════════════════════════════════════════════════

class PairwiseScorer:
    def __init__(self):
        # 三层筛选阈值
        self.thresholds = {
            # 第一层（硬过滤）
            'corr_median': 0.6,
            'coint_p': 0.1,
            'adf_p': 0.1,
            # 第二层（质量）
            'half_life': 30,
            'corr_std': 0.15,
            # 第三层（可交易）
            'zscore_max': 2,
            'daily_volume': 2_000_000,
        }
    
    def run(self, symbols: List[str], hot_pool: Dict, get_historical_data_fn=None, n_workers: int = 4) -> List[Dict]:
        """
        三层筛选主函数
        """
        if len(symbols) < 2:
            logger.warning("PairwiseScorer: need >= 2 symbols")
            return []
        
        import itertools
        
        # 准备数据
        pair_args = []
        for sym_a, sym_b in itertools.combinations(symbols, 2):
            if sym_a in hot_pool and sym_b in hot_pool:
                data_a = hot_pool[sym_a]
                data_b = hot_pool[sym_b]
                
                log_a = data_a.get('log_close')
                log_b = data_b.get('log_close')
                vol_a = data_a.get('volume', [])
                vol_b = data_b.get('volume', [])
                
                if log_a is not None and log_b is not None:
                    pair_args.append((sym_a, sym_b, log_a, log_b, vol_a, vol_b))
        
        total_pairs = len(pair_args)
        logger.info(f"PairwiseScorer: {total_pairs} pairs to evaluate with 3-layer filter")
        logger.info(f"  Layer 1 (Hard): corr_median≥{self.thresholds['corr_median']}, coint_p≤{self.thresholds['coint_p']}, adf_p≤{self.thresholds['adf_p']}")
        logger.info(f"  Layer 2 (Quality): half_life≤{self.thresholds['half_life']}, corr_std≤{self.thresholds['corr_std']}")
        logger.info(f"  Layer 3 (Tradable): zscore_max≥{self.thresholds['zscore_max']}, daily_volume≥{self.thresholds['daily_volume']/1e6}M")
        
        if not pair_args:
            return []
        
        # 并行处理
        results = []
        if n_workers > 1 and len(pair_args) > 10:
            with Pool(processes=n_workers) as pool:
                results = pool.map(_process_pair_three_layer, pair_args)
        else:
            results = [_process_pair_three_layer(args) for args in pair_args]
        
        # 过滤None并排序
        valid_results = [r for r in results if r is not None]
        logger.info(f"PairwiseScorer: {len(valid_results)}/{total_pairs} pairs passed 3-layer filter")
        
        if not valid_results:
            logger.warning("PairwiseScorer: no pairs passed 3-layer filter")
            return []
        
        # 按评分排序
        valid_results.sort(key=lambda x: x['score'], reverse=True)
        
        # Top 100 + 单币互斥 (放宽到5个)
        top_100 = []
        coin_counts = {}
        for r in valid_results:
            a = r['symbol_a'].split('/')[0]
            b = r['symbol_b'].split('/')[0]
            cnt_a = coin_counts.get(a, 0)
            cnt_b = coin_counts.get(b, 0)
            if cnt_a < 5 and cnt_b < 5:
                top_100.append(r)
                coin_counts[a] = cnt_a + 1
                coin_counts[b] = cnt_b + 1
                if len(top_100) >= 100:
                    break
        
        logger.info(f"PairwiseScorer: {len(valid_results)} passed, keeping top {len(top_100)}")
        return top_100
