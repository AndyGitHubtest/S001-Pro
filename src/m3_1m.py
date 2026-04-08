"""
M3 精选模块 - 1分钟周期

职责：对M2输出的候选pair进行1分钟周期的高质量筛选
数据：直接使用1m数据，无需聚合
"""

import numpy as np
from typing import Dict
from src.m3_base import M3SelectorBase


class M3Selector1m(M3SelectorBase):
    """1分钟周期精选器"""
    
    def __init__(self, top_n: int = None):
        super().__init__(timeframe='1m', top_n=top_n)
        
        # 1m特定阈值 (平衡型)
        self.thresholds.update({
            'min_correlation': 0.10,         # 1m: 中位数0.286的35%
            'max_corr_std': 0.35,            # 允许较大波动
            'max_half_life': 150,            # 约2.5小时半衰期
            'min_daily_volume': 2_000_000,
            'coint_pvalue': 0.20,            # 放宽协整要求
            'adf_pvalue': 0.20,              # 放宽ADF要求
        })
    
    def aggregate_data(self, data_1m: Dict) -> Dict:
        """
        1m周期：直接使用原始数据，无需聚合
        
        Args:
            data_1m: {'log_close': np.array, 'volume': np.array, 'close': np.array}
        
        Returns:
            直接使用输入数据
        """
        return data_1m
