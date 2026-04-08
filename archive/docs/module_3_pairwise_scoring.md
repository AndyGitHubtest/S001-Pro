# 模块三：配对精选 (M3 Pairwise Selector) - P0 LOCKED

> **职责**: 从M2输出的候选币种中，通过统计指标筛选高质量的配对，输出到M4进行回测优化
> **最后更新**: 2026-04-09 (多周期重构后)
> **版本**: v2.4

---

## 1. 架构概述

### 1.1 三周期并行架构

M3采用**多周期独立运行**架构，同时支持1分钟、5分钟、15分钟三个时间周期的配对筛选：

```
M2输出 (119币种)
    │
    ├──► M3_1m ──► 1m周期配对 (独立筛选)
    │
    ├──► M3_5m ──► 5m周期配对 (独立筛选)
    │
    └──► M3_15m ──► 15m周期配对 (独立筛选)
         
    ↓
{
    '1m': [...],
    '5m': [...], 
    '15m': [...]
} → M4优化器 (各自独立优化)
```

### 1.2 核心文件

| 文件 | 职责 | 说明 |
|------|------|------|
| `src/m3_base.py` | M3SelectorBase | 抽象基类，定义筛选逻辑骨架 |
| `src/m3_1m.py` | M3Selector1m | 1分钟周期筛选器 |
| `src/m3_5m.py` | M3Selector5m | 5分钟周期筛选器 (1m聚合) |
| `src/m3_15m.py` | M3Selector15m | 15分钟周期筛选器 (1m聚合) |
| `src/m3_selector.py` | M3Selector | 统一入口，协调三周期运行 |
| `src/pairwise_scorer.py` | (已弃用) | 旧版单周期实现 |

### 1.3 设计原则

- **独立性**: 三个周期完全独立，无交叉依赖
- **不限制数量**: 默认top_n=None，所有通过筛选的都输出
- **统计导向**: 仅计算统计指标，不进行回测
- **实时聚合**: 5m/15m从1m数据实时聚合，保证数据一致性

---

## 2. 类定义

### 2.1 M3SelectorBase (抽象基类)

```python
class M3SelectorBase(ABC):
    """M3精选模块基类"""
    
    def __init__(self, timeframe: str, top_n: int = None):
        self.timeframe = timeframe  # '1m', '5m', '15m'
        self.top_n = top_n          # None=不限制数量
        
        # 筛选阈值（子类可覆盖）
        self.thresholds = {
            'min_correlation': 0.3,          # 最低相关系数
            'max_corr_std': 0.2,             # 相关系数稳定性
            'coint_pvalue': 0.1,             # 协整性p值上限
            'adf_pvalue': 0.1,               # ADF检验p值上限
            'max_half_life': 30,             # 半衰期上限（bar数）
            'min_zscore_range': 2.0,         # Z-score最小范围
            'min_daily_volume': 2_000_000,   # 最低日成交量
            'max_spread_volatility': 0.05,   # 价差波动率上限
        }
```

### 2.2 三个具体实现类

```python
# 1m周期 - 高灵敏，适合高频信号
class M3Selector1m(M3SelectorBase):
    def __init__(self, top_n: int = None):
        super().__init__('1m', top_n)
        self.thresholds.update({
            'min_correlation': 0.10,
            'max_corr_std': 0.35,
            'max_half_life': 150,
            'coint_pvalue': 0.20,
            'adf_pvalue': 0.20,
        })

# 5m周期 - 平衡型
class M3Selector5m(M3SelectorBase):
    def __init__(self, top_n: int = None):
        super().__init__('5m', top_n)
        self.thresholds.update({
            'min_correlation': 0.08,
            'max_corr_std': 0.30,
            'max_half_life': 80,
            'coint_pvalue': 0.20,
            'adf_pvalue': 0.20,
        })

# 15m周期 - 稳健型
class M3Selector15m(M3SelectorBase):
    def __init__(self, top_n: int = None):
        super().__init__('15m', top_n)
        self.thresholds.update({
            'min_correlation': 0.10,
            'max_corr_std': 0.25,
            'max_half_life': 40,
            'coint_pvalue': 0.15,
            'adf_pvalue': 0.15,
        })
```

### 2.3 M3Selector (统一入口)

```python
class M3Selector:
    """M3精选模块统一入口"""
    
    def __init__(self, top_n: int = None):
        self.selector_1m = M3Selector1m(top_n=top_n)
        self.selector_5m = M3Selector5m(top_n=top_n)
        self.selector_15m = M3Selector15m(top_n=top_n)
    
    def run_all(self, symbols: List[str], hot_pool_1m: Dict) -> Dict[str, List[Dict]]:
        """运行所有三个周期的筛选"""
        results_1m = self.selector_1m.run(symbols, hot_pool_1m)
        results_5m = self.selector_5m.run(symbols, hot_pool_1m)
        results_15m = self.selector_15m.run(symbols, hot_pool_1m)
        
        return {
            '1m': results_1m,
            '5m': results_5m,
            '15m': results_15m,
        }
```

---

## 3. 筛选指标与阈值

### 3.1 公共指标（三周期共用）

| 指标 | 类型 | 说明 |
|------|------|------|
| `min_correlation` | 相关性 | 中位数相关系数，衡量价格联动性 |
| `max_corr_std` | 稳定性 | 相关系数标准差，衡量关系稳定性 |
| `coint_pvalue` | 协整性 | Engle-Granger协整检验p值 |
| `adf_pvalue` | 平稳性 | ADF检验p值，残差均值回归能力 |
| `max_half_life` | 速度 | 半衰期（bar数），回归速度上限 |
| `min_zscore_range` | 波动 | Z-score历史范围，确保有足够波动 |
| `min_daily_volume` | 流动性 | 最低日成交量(USDT) |
| `max_spread_volatility` | 风险 | 价差波动率上限 |

### 3.2 各周期阈值对比

| 参数 | 1m | 5m | 15m | 逻辑说明 |
|------|-----|-----|------|----------|
| `min_correlation` | 0.10 | 0.08 | 0.10 | 高频周期相关性天然较低 |
| `max_corr_std` | 0.35 | 0.30 | 0.25 | 高频允许更大波动 |
| `max_half_life` | 150 | 80 | 40 | 半衰期随周期增长 |
| `coint_pvalue` | 0.20 | 0.20 | 0.15 | 高频放宽协整要求 |
| `adf_pvalue` | 0.20 | 0.20 | 0.15 | 低频更严格 |

---

## 4. 筛选流程

### 4.1 完整流程图

```
所有币对排列 (N*(N-1)/2)
    │
    ▼
┌─────────────────────────────────┐
│ Step 1: 快速过滤                │
│ • 滚动相关系数中位数 >= min_corr│
│ • 相关系数标准差 <= max_std     │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ Step 2: 协整性检验              │
│ • OLS回归获取残差               │
│ • ADF检验残差平稳性             │
│ • p值 <= adf_pvalue             │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ Step 3: 均值回归能力            │
│ • OU过程估计半衰期              │
│ • 半衰期 <= max_half_life       │
│ • Z-score范围 >= min_range      │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ Step 4: 交易性检查              │
│ • 日成交量 >= min_volume        │
│ • 价差波动率 <= max_volatility  │
└────────────┬────────────────────┘
             ▼
        输出配对列表
        (不限制数量)
```

### 4.2 数据聚合逻辑

5m和15m周期从1m数据聚合，保证数据一致性：

```python
# 5m聚合: 每5根1m合成1根5m
def aggregate_to_5m(data_1m):
    """1m -> 5m聚合"""
    return {
        'open': first_of_5,
        'high': max_of_5,
        'low': min_of_5,
        'close': last_of_5,
        'volume': sum_of_5,
    }

# 15m聚合: 每15根1m合成1根15m
def aggregate_to_15m(data_1m):
    """1m -> 15m聚合"""
    return {
        'open': first_of_15,
        'high': max_of_15,
        'low': min_of_15,
        'close': last_of_15,
        'volume': sum_of_15,
    }
```

---

## 5. 输出格式

### 5.1 单个配对输出

```python
{
    'symbol_a': 'BTC/USDT',
    'symbol_b': 'ETH/USDT',
    'timeframe': '5m',           # 所属周期
    
    # 统计指标
    'metrics': {
        'correlation_median': 0.65,
        'correlation_std': 0.15,
        'coint_pvalue': 0.05,
        'adf_pvalue': 0.03,
        'half_life': 25,
        'zscore_range': 3.5,
        'spread_volatility': 0.02,
    },
    
    # 原始数据引用
    'data_ref': {
        'symbol_a': {...},
        'symbol_b': {...},
    }
}
```

### 5.2 M3Selector.run_all() 输出

```python
{
    '1m': [
        {'symbol_a': 'A', 'symbol_b': 'B', 'timeframe': '1m', ...},
        ...
    ],
    '5m': [
        {'symbol_a': 'C', 'symbol_b': 'D', 'timeframe': '5m', ...},
        ...
    ],
    '15m': [
        {'symbol_a': 'E', 'symbol_b': 'F', 'timeframe': '15m', ...},
        ...
    ]
}
```

---

## 6. 与旧版(pairwise_scorer.py)的区别

| 对比项 | 旧版 (v2.3) | 新版 (v2.4) |
|--------|------------|------------|
| 架构 | 单周期 | 多周期并行 |
| 输出限制 | Top 100 | 不限制数量 |
| 核心算法 | Kalman Filter | 滚动相关 + OU半衰期 |
| 文件 | pairwise_scorer.py | m3_*.py 多文件 |
| 评分方式 | 综合评分 | 分层阈值过滤 |
| OS验证 | 有 | 移除 (移至M4) |

---

## 7. 禁止事项

M3严格遵守以下限制：

- ❌ **回测**: M3只输出统计指标，不进行回测 (M4职责)
- ❌ **参数优化**: 不进行参数搜索 (M4职责)
- ❌ **跨周期引用**: 三周期完全独立
- ❌ **联合筛选**: 不跨周期组合配对
- ❌ **交易信号**: 不输出买卖信号 (M6职责)
- ❌ **未来函数**: 只使用当前及历史数据

---

## 8. 调用示例

```python
from src.m3_selector import M3Selector
from src.data_engine import DataEngine

# 初始化
data_engine = DataEngine()
m3 = M3Selector(top_n=None)  # 不限制数量

# 从M2获取候选币种
qualified_symbols = [...]  # 119个币种

# 获取Hot Pool (1m数据)
hot_pool = data_engine.build_hot_pool(qualified_symbols)

# 运行M3筛选
results = m3.run_all(qualified_symbols, hot_pool)

# 输出结果
print(f"1m周期: {len(results['1m'])} pairs")
print(f"5m周期: {len(results['5m'])} pairs")
print(f"15m周期: {len(results['15m'])} pairs")

# 传递给M4
for timeframe, pairs in results.items():
    # M4独立优化每个周期的配对
    optimized = optimizer.optimize(pairs, timeframe=timeframe)
```

---

## 9. 更新记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-04-09 | v2.4 | 多周期重构，拆分为m3_base/1m/5m/15m/selector |
| 2026-04-07 | v2.3 | 旧版pairwise_scorer.py (单周期Kalman) |
