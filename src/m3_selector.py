"""
M3 精选模块 - 统一入口

三周期独立运行：
  - M3_1m: 1分钟周期筛选
  - M3_5m: 5分钟周期筛选（1m聚合）
  - M3_15m: 15分钟周期筛选（1m聚合）

每个周期：
  - 独立运行
  - 独立筛选
  - 独立输出
  - 独立进入M4

禁止：
  - 回测（M4职责）
  - 参数优化
  - 跨周期引用数据
  - 多周期联合筛选
  - 输出交易信号
  - 未来函数
"""

import logging
from typing import List, Dict
from src.m3_1m import M3Selector1m
from src.m3_5m import M3Selector5m
from src.m3_15m import M3Selector15m

logger = logging.getLogger("M3Selector")


class M3Selector:
    """
    M3精选模块统一入口
    
    同时运行三个周期的筛选器，各自独立输出结果
    默认不限制数量，所有通过筛选的配对都进入M4
    """
    
    def __init__(self, top_n: int = None):
        """
        Args:
            top_n: None表示不限制数量，所有通过筛选的都输出
                  如果设置数字，则每个周期只输出Top N
        """
        self.top_n = top_n
        
        # 初始化三个周期的筛选器
        self.selector_1m = M3Selector1m(top_n=top_n)
        self.selector_5m = M3Selector5m(top_n=top_n)
        self.selector_15m = M3Selector15m(top_n=top_n)
        
        limit_str = "unlimited" if top_n is None else f"top_{top_n}"
        logger.info(f"M3Selector initialized with {limit_str} output")
    
    def run_all(self, symbols: List[str], hot_pool_1m: Dict) -> Dict[str, List[Dict]]:
        """
        运行所有三个周期的筛选
        
        Args:
            symbols: M2输出的候选币种列表
            hot_pool_1m: 1分钟数据池
        
        Returns:
            {
                '1m': [...],   # 1m周期Top N配对
                '5m': [...],   # 5m周期Top N配对
                '15m': [...],  # 15m周期Top N配对
            }
        """
        logger.info(f"M3Selector: running all timeframes for {len(symbols)} symbols")
        
        # 独立运行三个周期（无交叉依赖！）
        results_1m = self.selector_1m.run(symbols, hot_pool_1m)
        results_5m = self.selector_5m.run(symbols, hot_pool_1m)
        results_15m = self.selector_15m.run(symbols, hot_pool_1m)
        
        results = {
            '1m': results_1m,
            '5m': results_5m,
            '15m': results_15m,
        }
        
        # 汇总日志
        total = sum(len(v) for v in results.values())
        logger.info(f"M3Selector complete: 1m={len(results_1m)}, 5m={len(results_5m)}, 15m={len(results_15m)}, total={total}")
        
        return results
    
    def run_single(self, timeframe: str, symbols: List[str], hot_pool_1m: Dict) -> List[Dict]:
        """
        运行单个周期的筛选
        
        Args:
            timeframe: '1m', '5m', '15m'
            symbols: M2输出的候选币种列表
            hot_pool_1m: 1分钟数据池
        
        Returns:
            该周期的Top N配对列表
        """
        if timeframe == '1m':
            return self.selector_1m.run(symbols, hot_pool_1m)
        elif timeframe == '5m':
            return self.selector_5m.run(symbols, hot_pool_1m)
        elif timeframe == '15m':
            return self.selector_15m.run(symbols, hot_pool_1m)
        else:
            logger.error(f"Unknown timeframe: {timeframe}")
            return []


# 兼容性：保持旧的导入方式
def get_m3_selector(top_n: int = None) -> M3Selector:
    """工厂函数：获取M3Selector实例"""
    return M3Selector(top_n=top_n)
