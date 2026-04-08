"""
M3 精选模块 - 5分钟周期

职责：对M2输出的候选pair进行5分钟周期的高质量筛选
数据：从1m数据聚合到5m
"""

import numpy as np
from typing import Dict
from src.m3_base import M3SelectorBase


class M3Selector5m(M3SelectorBase):
    """5分钟周期精选器"""
    
    def __init__(self, top_n: int = None):
        super().__init__(timeframe='5m', top_n=top_n)
        
        # 5m特定阈值 (平衡型)
        self.thresholds.update({
            'min_correlation': 0.08,         # 5m: 中位数0.186的43%
            'max_corr_std': 0.30,            # 允许适度波动
            'max_half_life': 80,             # 约6.7小时半衰期
            'min_daily_volume': 2_000_000,
            'coint_pvalue': 0.20,            # 放宽协整要求
            'adf_pvalue': 0.20,              # 放宽ADF要求
        })
    
    def aggregate_data(self, data_1m: Dict) -> Dict:
        """
        5m周期：从1m聚合到5m
        
        Args:
            data_1m: {'log_close': np.array, 'volume': np.array, 'close': np.array}
        
        Returns:
            聚合后的5m数据
        """
        result = {}
        
        # 聚合log_close（取最后一条）
        if 'log_close' in data_1m:
            log_close_1m = data_1m['log_close']
            n_5m = len(log_close_1m) // 5
            if n_5m > 0:
                # 每5个取最后一个
                result['log_close'] = log_close_1m[4::5][:n_5m]
            else:
                result['log_close'] = log_close_1m
        
        # 聚合volume（求和）
        if 'volume' in data_1m:
            volume_1m = data_1m['volume']
            n_5m = len(volume_1m) // 5
            if n_5m > 0:
                result['volume'] = np.array([
                    np.sum(volume_1m[i*5:(i+1)*5])
                    for i in range(n_5m)
                ])
            else:
                result['volume'] = volume_1m
        
        # 聚合close（取最后一条）
        if 'close' in data_1m:
            close_1m = data_1m['close']
            n_5m = len(close_1m) // 5
            if n_5m > 0:
                result['close'] = close_1m[4::5][:n_5m]
            else:
                result['close'] = close_1m
        
        return result
