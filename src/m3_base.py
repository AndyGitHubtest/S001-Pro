"""
M3 精选模块 - 基础类

职责：对M2输出的候选pair进行高质量筛选
禁止：回测、参数优化、跨周期引用、联合筛选、交易信号、未来函数

三周期独立运行：
  - M3_1m: 1分钟周期筛选
  - M3_5m: 5分钟周期筛选（1m聚合）
  - M3_15m: 15分钟周期筛选（1m聚合）
"""

import logging
import numpy as np
from typing import List, Dict, Optional, Tuple
from abc import ABC, abstractmethod

logger = logging.getLogger("M3Selector")


class M3SelectorBase(ABC):
    """M3精选模块基类"""
    
    def __init__(self, timeframe: str, top_n: int = None):
        """
        Args:
            timeframe: '1m', '5m', '15m'
            top_n: None表示不限制数量，所有通过筛选的都输出
        """
        self.timeframe = timeframe
        self.top_n = top_n
        self.logger = logging.getLogger(f"M3Selector.{timeframe}")
        
        # 筛选阈值（子类可覆盖）
        self.thresholds = {
            # 结构稳定性
            'min_correlation': 0.3,          # 最低相关系数
            'max_corr_std': 0.2,             # 相关系数标准差上限
            'coint_pvalue': 0.1,             # 协整性p值上限
            'adf_pvalue': 0.1,               # ADF检验p值上限
            
            # 均值回归能力
            'max_half_life': 30,             # 半衰期上限（bar数）
            'min_zscore_range': 2.0,         # Z-score最小范围
            
            # 交易性
            'min_daily_volume': 2_000_000,   # 最低日成交量(USDT)
            'max_spread_volatility': 0.05,   # 价差波动率上限
        }
    
    @abstractmethod
    def aggregate_data(self, data_1m: Dict) -> Dict:
        """
        从1m数据聚合到目标周期
        
        Args:
            data_1m: {'log_close': np.array, 'volume': np.array, 'close': np.array}
        
        Returns:
            聚合后的数据
        """
        pass
    
    def calculate_correlation(self, log_a: np.ndarray, log_b: np.ndarray) -> Tuple[float, float]:
        """
        计算滚动相关系数及稳定性
        
        Returns:
            (corr_median, corr_std)
        """
        n = len(log_a)
        if n < 100:
            return 0.0, 999.0
        
        # 计算滚动相关系数
        window = min(100, n // 5)
        n_windows = (n - window) // window
        
        corrs = []
        for i in range(min(n_windows, 20)):  # 最多20个窗口
            start = i * window
            end = start + window
            a_window = log_a[start:end]
            b_window = log_b[start:end]
            
            if np.std(a_window) > 1e-10 and np.std(b_window) > 1e-10:
                corr = np.corrcoef(a_window, b_window)[0, 1]
                if not np.isnan(corr):
                    corrs.append(corr)
        
        if len(corrs) < 3:
            return 0.0, 999.0
        
        return np.median(corrs), np.std(corrs)
    
    def calculate_cointegration(self, log_a: np.ndarray, log_b: np.ndarray) -> float:
        """
        简化协整性检验：对残差做ADF检验
        
        Returns:
            p-value (越小越协整)
        """
        try:
            if len(log_a) < 30:
                return 1.0
            
            # 线性回归: log_a = alpha + beta * log_b + residual
            x_mean, y_mean = np.mean(log_b), np.mean(log_a)
            beta = np.sum((log_b - x_mean) * (log_a - y_mean)) / (np.sum((log_b - x_mean) ** 2) + 1e-10)
            alpha = y_mean - beta * x_mean
            residual = log_a - alpha - beta * log_b
            
            # 简化ADF: 检验残差是否均值回归
            y_lag = residual[:-1]
            y_diff = np.diff(residual)
            
            if len(y_lag) < 10:
                return 1.0
            
            y_lag_mean = np.mean(y_lag)
            y_diff_mean = np.mean(y_diff)
            
            beta_ou = np.sum((y_lag - y_lag_mean) * (y_diff - y_diff_mean)) / (np.sum((y_lag - y_lag_mean) ** 2) + 1e-10)
            
            # beta_ou < 0 表示均值回归
            if beta_ou >= 0:
                return 1.0
            
            # 简单的p-value估计
            t_stat = beta_ou / (np.std(y_diff) / np.sqrt(len(y_lag)) + 1e-10)
            
            if t_stat < -3.0:
                return 0.01
            elif t_stat < -2.86:
                return 0.05
            elif t_stat < -2.57:
                return 0.1
            else:
                return 0.5
                
        except Exception:
            return 1.0
    
    def calculate_half_life(self, spread: np.ndarray) -> float:
        """
        计算Ornstein-Uhlenbeck半衰期
        
        Returns:
            半衰期（bar数）
        """
        try:
            if len(spread) < 30:
                return 999.0
            
            y_lag = spread[:-1]
            y_diff = np.diff(spread)
            
            y_lag_mean = np.mean(y_lag)
            y_diff_mean = np.mean(y_diff)
            
            beta = np.sum((y_lag - y_lag_mean) * (y_diff - y_diff_mean)) / (np.sum((y_lag - y_lag_mean) ** 2) + 1e-10)
            
            if beta >= 0:
                return 999.0  # 非均值回归
            
            half_life = -np.log(2) / beta
            return max(0, half_life)
            
        except Exception:
            return 999.0
    
    def calculate_zscore_stats(self, spread: np.ndarray) -> Dict:
        """
        计算Z-score统计量
        
        Returns:
            {'mean': float, 'std': float, 'max': float, 'min': float, 'range': float}
        """
        if len(spread) < 30:
            return {'mean': 0, 'std': 1, 'max': 0, 'min': 0, 'range': 0}
        
        mean = np.mean(spread)
        std = np.std(spread)
        
        if std < 1e-10:
            return {'mean': mean, 'std': std, 'max': 0, 'min': 0, 'range': 0}
        
        z_scores = (spread - mean) / std
        
        return {
            'mean': mean,
            'std': std,
            'max': np.max(z_scores),
            'min': np.min(z_scores),
            'range': np.max(z_scores) - np.min(z_scores)
        }
    
    def calculate_spread_volatility(self, spread: np.ndarray) -> float:
        """计算价差波动率（标准差/均值）"""
        if len(spread) < 10:
            return 999.0
        
        mean = np.mean(spread)
        std = np.std(spread)
        
        if abs(mean) < 1e-10:
            return 999.0
        
        return std / abs(mean)
    
    def evaluate_pair(self, sym_a: str, sym_b: str, data_a: Dict, data_b: Dict) -> Optional[Dict]:
        """
        评估单个配对
        
        Returns:
            包含评分的字典，或None（未通过筛选）
        """
        # 聚合数据
        agg_a = self.aggregate_data(data_a)
        agg_b = self.aggregate_data(data_b)
        
        log_a = agg_a.get('log_close')
        log_b = agg_b.get('log_close')
        vol_a = agg_a.get('volume', [])
        vol_b = agg_b.get('volume', [])
        
        if log_a is None or log_b is None:
            return None
        
        n = min(len(log_a), len(log_b))
        if n < 50:
            return None
        
        log_a = log_a[:n]
        log_b = log_b[:n]
        
        result = {
            'symbol_a': sym_a,
            'symbol_b': sym_b,
            'timeframe': self.timeframe,
        }
        
        # ═══════════════════════════════════════════════════
        # 第一层：结构稳定性筛选
        # ═══════════════════════════════════════════════════
        
        # 1. 相关系数
        corr_median, corr_std = self.calculate_correlation(log_a, log_b)
        if corr_median < self.thresholds['min_correlation']:
            return None
        if corr_std > self.thresholds['max_corr_std']:
            return None
        
        result['corr_median'] = corr_median
        result['corr_std'] = corr_std
        
        # 2. 协整性检验
        coint_p = self.calculate_cointegration(log_a, log_b)
        if coint_p > self.thresholds['coint_pvalue']:
            return None
        
        result['coint_p'] = coint_p
        
        # 3. 价差ADF检验（简化版）
        spread = log_a - log_b
        adf_p = self.calculate_cointegration(log_a, log_b)  # 复用协整检验
        if adf_p > self.thresholds['adf_pvalue']:
            return None
        
        result['adf_p'] = adf_p
        
        # ═══════════════════════════════════════════════════
        # 第二层：均值回归能力筛选
        # ═══════════════════════════════════════════════════
        
        # 4. 半衰期
        half_life = self.calculate_half_life(spread)
        if half_life > self.thresholds['max_half_life']:
            return None
        
        result['half_life'] = half_life
        
        # 5. Z-score范围
        zscore_stats = self.calculate_zscore_stats(spread)
        if zscore_stats['range'] < self.thresholds['min_zscore_range']:
            return None
        
        result['zscore_range'] = zscore_stats['range']
        result['zscore_max'] = zscore_stats['max']
        result['zscore_min'] = zscore_stats['min']
        
        # ═══════════════════════════════════════════════════
        # 第三层：交易性筛选
        # ═══════════════════════════════════════════════════
        
        # 6. 日成交量
        if len(vol_a) > 0 and len(vol_b) > 0:
            # 根据timeframe计算日bar数
            bars_per_day = {'1m': 1440, '5m': 288, '15m': 96}.get(self.timeframe, 1440)
            daily_vol_a = np.mean(vol_a) * bars_per_day
            daily_vol_b = np.mean(vol_b) * bars_per_day
            min_daily_vol = min(daily_vol_a, daily_vol_b)
            
            if min_daily_vol < self.thresholds['min_daily_volume']:
                return None
            
            result['daily_volume'] = min_daily_vol
        else:
            return None
        
        # 7. 价差波动率
        spread_vol = self.calculate_spread_volatility(spread)
        if spread_vol > self.thresholds['max_spread_volatility']:
            return None
        
        result['spread_volatility'] = spread_vol
        
        # ═══════════════════════════════════════════════════
        # 综合评分（无回测！）
        # ═══════════════════════════════════════════════════
        
        result['score'] = (
            0.25 * corr_median +
            0.15 * (1 - coint_p) +
            0.15 * (1 - adf_p) +
            0.15 * max(0, 1 - half_life / self.thresholds['max_half_life']) +
            0.15 * min(zscore_stats['range'] / 5, 1) +
            0.15 * (1 - spread_vol / self.thresholds['max_spread_volatility'])
        )
        
        return result
    
    def run(self, symbols: List[str], hot_pool_1m: Dict) -> List[Dict]:
        """
        主入口：对候选pair进行筛选
        
        Args:
            symbols: M2输出的候选币种列表
            hot_pool_1m: 1分钟数据池
        
        Returns:
            Top N配对列表
        """
        if len(symbols) < 2:
            self.logger.warning(f"M3.{self.timeframe}: need >= 2 symbols")
            return []
        
        import itertools
        
        # 评估所有配对
        results = []
        total = 0
        
        for sym_a, sym_b in itertools.combinations(symbols, 2):
            if sym_a in hot_pool_1m and sym_b in hot_pool_1m:
                total += 1
                result = self.evaluate_pair(
                    sym_a, sym_b,
                    hot_pool_1m[sym_a],
                    hot_pool_1m[sym_b]
                )
                if result:
                    results.append(result)
        
        self.logger.info(f"M3.{self.timeframe}: {len(results)}/{total} pairs passed")
        
        if not results:
            return []
        
        # 按评分排序
        results.sort(key=lambda x: x['score'], reverse=True)
        
        # 默认不过滤数量，所有通过筛选的都输出到M4
        # 单币互斥限制也移除，让M4做最终决定
        if self.top_n is None:
            self.logger.info(f"M3.{self.timeframe}: all {len(results)} passed pairs go to M4")
            return results
        
        # 如果设置了top_n，才进行数量和单币互斥限制
        top_n = []
        coin_counts = {}
        
        for r in results:
            a = r['symbol_a'].split('/')[0]
            b = r['symbol_b'].split('/')[0]
            cnt_a = coin_counts.get(a, 0)
            cnt_b = coin_counts.get(b, 0)
            
            if cnt_a < 3 and cnt_b < 3:
                top_n.append(r)
                coin_counts[a] = cnt_a + 1
                coin_counts[b] = cnt_b + 1
                
                if len(top_n) >= self.top_n:
                    break
        
        self.logger.info(f"M3.{self.timeframe}: selected top {len(top_n)} pairs")
        return top_n
