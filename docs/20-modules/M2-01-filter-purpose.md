# M2.1 InitialFilter 职责

**所属模块**: M2 初筛层  
**版本**: 2.1.0-hardened  
**对应代码**: `src/filters/initial_filter.py`

---

## 一句话描述

对全量交易对进行6层快速过滤，剔除明显不合格的标的，为M3精选提供高质量候选池。

---

## 核心职责

### 1. 流动性过滤

**过滤条件**: 日成交量 ≥ 阈值（默认2,000,000 USDT）

```python
def _filter_liquidity(self, symbols: List[str], stats: Dict) -> List[str]:
    return [s for s in symbols if stats[s]['daily_volume'] >= self.min_volume]
```

**目的**: 剔除低流动性交易对，避免滑点过大

### 2. 价格过滤

**过滤条件**: 
- 最低价格 ≥ 0.01 USDT
- 最高价格 ≤ 100,000 USDT（可选）

**目的**: 剔除价格异常的交易对

### 3. 波动率过滤

**过滤条件**: 历史波动率在合理区间

```python
def _filter_volatility(self, symbols: List[str], stats: Dict) -> List[str]:
    valid = []
    for s in symbols:
        vol = stats[s]['volatility']
        if 0.001 <= vol <= 0.5:  # 0.1% ~ 50%
            valid.append(s)
    return valid
```

**目的**: 剔除波动率过高（风险大）或过低（无套利空间）的标的

### 4. 数据完整性过滤

**过滤条件**: 数据缺失率 ≤ 5%

```python
def _filter_data_quality(self, symbols: List[str], stats: Dict) -> List[str]:
    return [s for s in symbols if stats[s]['missing_rate'] <= 0.05]
```

**目的**: 确保数据质量，避免NA值影响计算

### 5. 黑名单过滤

**过滤条件**: 不在黑名单中

```python
BLACKLIST = [
    "UP/USDT",   # 杠杆代币
    "DOWN/USDT", 
    "BEAR/USDT",
    "BULL/USDT",
]
```

**目的**: 剔除特殊类型代币

### 6. 上市时间过滤

**过滤条件**: 上市时间 ≥ 90天

**目的**: 确保有足够历史数据进行统计分析

---

## 6层过滤流程

```
输入: 全量 symbols (如 200+ 个)
       ↓
┌─────────────────────────────────────┐
│ Layer 1: 流动性过滤                  │
│ 日成交量 ≥ 2M USDT                   │
│ 预计剔除: ~50%                       │
└─────────────────────────────────────┘
       ↓
┌─────────────────────────────────────┐
│ Layer 2: 价格过滤                    │
│ 0.01 ≤ 价格 ≤ 100000                 │
│ 预计剔除: ~5%                        │
└─────────────────────────────────────┘
       ↓
┌─────────────────────────────────────┐
│ Layer 3: 波动率过滤                  │
│ 0.1% ≤ 波动率 ≤ 50%                  │
│ 预计剔除: ~10%                       │
└─────────────────────────────────────┘
       ↓
┌─────────────────────────────────────┐
│ Layer 4: 数据质量过滤                │
│ 缺失率 ≤ 5%                          │
│ 预计剔除: ~5%                        │
└─────────────────────────────────────┘
       ↓
┌─────────────────────────────────────┐
│ Layer 5: 黑名单过滤                  │
│ 剔除杠杆代币等                       │
│ 预计剔除: ~5%                        │
└─────────────────────────────────────┘
       ↓
┌─────────────────────────────────────┐
│ Layer 6: 上市时间过滤                │
│ 上市时间 ≥ 90天                      │
│ 预计剔除: ~10%                       │
└─────────────────────────────────────┘
       ↓
输出: Qualified Pool (如 50-80 个)
```

---

## 核心类

### InitialFilter

```python
class InitialFilter:
    """
    M2初筛模块 - 6层过滤流水线
    
    输入: 全量symbols + market_stats
    输出: 符合条件的symbols列表
    """
    
    def __init__(
        self,
        min_volume: float = 2_000_000,
        min_price: float = 0.01,
        max_price: float = 100_000,
        min_volatility: float = 0.001,
        max_volatility: float = 0.5,
        max_missing_rate: float = 0.05,
        min_listing_days: int = 90,
    ):
        self.min_volume = min_volume
        self.min_price = min_price
        self.max_price = max_price
        self.min_volatility = min_volatility
        self.max_volatility = max_volatility
        self.max_missing_rate = max_missing_rate
        self.min_listing_days = min_listing_days
```

### 核心方法

#### run

```python
def run(
    self,
    symbols: List[str],
    market_stats: Dict[str, Dict]
) -> List[str]
```

**功能**: 执行完整的6层过滤流程

**参数**:
- `symbols`: 全量交易对列表
- `market_stats`: M1输出的市场统计字典

**返回**: 过滤后的交易对列表

**示例**:
```python
from src.filters.initial_filter import InitialFilter

filter = InitialFilter(min_volume=2_000_000)
qualified = filter.run(all_symbols, market_stats)
print(f"初筛结果: {len(qualified)}/{len(all_symbols)}")
```

---

## 配置参数

| 参数 | 默认值 | 说明 | 调整建议 |
|------|--------|------|----------|
| `min_volume` | 2,000,000 | 最小日成交量 | 市场低迷时可降低 |
| `min_price` | 0.01 | 最低价格 | 一般不动 |
| `max_price` | 100,000 | 最高价格 | 一般不动 |
| `min_volatility` | 0.001 | 最小波动率 | 可提高到0.005 |
| `max_volatility` | 0.5 | 最大波动率 | 市场动荡时提高 |
| `max_missing_rate` | 0.05 | 最大缺失率 | 一般不动 |
| `min_listing_days` | 90 | 最小上市天数 | 一般不动 |

---

## 输出示例

```
[InitialFilter] Layer 1 (Liquidity): 200 -> 120
[InitialFilter] Layer 2 (Price): 120 -> 115
[InitialFilter] Layer 3 (Volatility): 115 -> 98
[InitialFilter] Layer 4 (Data Quality): 98 -> 95
[InitialFilter] Layer 5 (Blacklist): 95 -> 92
[InitialFilter] Layer 6 (Listing Time): 92 -> 88
[InitialFilter] Final: 88/200 symbols qualified (44.0%)
```

---

## 性能指标

- **处理速度**: ~1000 symbols/秒
- **内存占用**: O(n)，n为symbol数量
- **输出规模**: 通常为输入的30-50%

---

## 相关文档

- [M2.2 流动性过滤规则](M2-02-liquidity-rules.md)
- [M2.3 价格过滤规则](M2-03-price-rules.md)
- [M3.1 M3Selector 架构](M3-01-selector-arch.md)
- [src/filters/initial_filter.py](../../src/filters/initial_filter.py)
