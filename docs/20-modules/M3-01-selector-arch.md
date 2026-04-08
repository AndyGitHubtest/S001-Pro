# M3.1 M3Selector 架构

**所属模块**: M3 精选层  
**版本**: 2.1.0-hardened  
**对应代码**: `src/m3_selector.py`, `src/m3_base.py`, `src/m3_1m.py`, `src/m3_5m.py`, `src/m3_15m.py`

---

## 一句话描述

对M2输出的候选交易对进行三周期（1m/5m/15m）独立筛选，使用Kalman Filter动态回归和多重统计指标，输出高质量配对列表。

---

## 三周期架构

```
                    ┌─────────────────┐
                    │  M2 初筛输出     │
                    │  (50-80 symbols) │
                    └────────┬────────┘
                             ↓
            ┌────────────────┼────────────────┐
            ↓                ↓                ↓
    ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
    │  M3_1m        │ │  M3_5m        │ │  M3_15m       │
    │  1分钟周期     │ │  5分钟周期     │ │  15分钟周期    │
    │               │ │  (1m聚合)      │ │  (1m聚合)      │
    └───────┬───────┘ └───────┬───────┘ └───────┬───────┘
            ↓                ↓                ↓
    ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
    │  1m配对列表    │ │  5m配对列表    │ │  15m配对列表   │
    │  (Top N)      │ │  (Top N)      │ │  (Top N)      │
    └───────────────┘ └───────────────┘ └───────────────┘
            ↓                ↓                ↓
            └────────────────┼────────────────┘
                             ↓
                    ┌─────────────────┐
                    │  M4 Optimizer    │
                    │  (独立优化各周期) │
                    └─────────────────┘
```

**核心原则**: 三周期完全独立运行，互不干扰

---

## 核心组件

### M3Selector (统一入口)

**文件**: `src/m3_selector.py`

```python
class M3Selector:
    """
    M3精选模块统一入口
    
    同时运行三个周期的筛选器，各自独立输出结果
    默认不限制数量，所有通过筛选的配对都进入M4
    """
    
    def __init__(self, db_path: str = "data/klines.db"):
        self.db_path = db_path
        self.selectors = {
            "1m": M3Selector1m(db_path),
            "5m": M3Selector5m(db_path),
            "15m": M3Selector15m(db_path),
        }
```

**核心方法**:

```python
def run_all(
    self,
    symbols: List[str],
    top_n: Optional[int] = None
) -> Dict[str, List[Dict]]
```
- 同时运行三个周期筛选
- 返回 {timeframe: pairs_list}

```python
def run_single(
    self,
    timeframe: str,
    symbols: List[str],
    top_n: Optional[int] = None
) -> List[Dict]
```
- 运行单个周期筛选
- timeframe: "1m", "5m", "15m"

---

### M3SelectorBase (基类)

**文件**: `src/m3_base.py`

```python
class M3SelectorBase(ABC):
    """
    M3精选模块 - 基础类
    
    抽象基类，定义三周期筛选器的通用接口
    """
    
    def __init__(self, db_path: str, interval: str):
        self.db_path = db_path
        self.interval = interval
        self.data_engine = DataEngine(db_path)
```

**抽象方法**:

```python
@abstractmethod
def aggregate_data(self, df_1m: pd.DataFrame) -> pd.DataFrame:
    """将1m数据聚合到目标周期"""
    pass
```

**通用方法**:

| 方法 | 功能 |
|------|------|
| `calculate_correlation()` | 计算Pearson相关系数 |
| `calculate_cointegration()` | ADF检验协整性 |
| `calculate_half_life()` | 计算均值回归半衰期 |
| `calculate_hurst()` | 计算Hurst指数 |
| `kalman_filter_regression()` | Kalman动态回归 |

---

### M3Selector1m (1分钟周期)

**文件**: `src/m3_1m.py`

```python
class M3Selector1m(M3SelectorBase):
    """
    M3精选模块 - 1分钟周期
    
    直接使用1m数据，无需聚合
    适合捕捉高频套利机会
    """
    
    def __init__(self, db_path: str):
        super().__init__(db_path, "1m")
    
    def aggregate_data(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        # 1m直接使用原始数据
        return df_1m
```

**特点**:
- 直接使用1m K线数据
- 最高频信号
- 对噪声敏感
- 适合高流动性配对

---

### M3Selector5m (5分钟周期)

**文件**: `src/m3_5m.py`

```python
class M3Selector5m(M3SelectorBase):
    """
    M3精选模块 - 5分钟周期
    
    从1m数据聚合到5m
    主要交易周期，平衡信号质量与频率
    """
    
    def __init__(self, db_path: str):
        super().__init__(db_path, "5m")
    
    def aggregate_data(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        # OHLCV聚合
        df_5m = df_1m.resample('5min', on='timestamp').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        })
        return df_5m
```

**特点**:
- 从1m聚合到5m
- 主要交易周期
- 平衡信号与噪声
- 实盘默认使用

---

### M3Selector15m (15分钟周期)

**文件**: `src/m3_15m.py`

```python
class M3Selector15m(M3SelectorBase):
    """
    M3精选模块 - 15分钟周期
    
    从1m数据聚合到15m
    适合捕捉趋势性机会
    """
    
    def __init__(self, db_path: str):
        super().__init__(db_path, "15m")
    
    def aggregate_data(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        # OHLCV聚合
        df_15m = df_1m.resample('15min', on='timestamp').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        })
        return df_15m
```

**特点**:
- 从1m聚合到15m
- 最稳定信号
- 适合趋势判断
- 可作为过滤器

---

## 筛选流程

```
输入: symbol_a, symbol_b, lookback
       ↓
┌─────────────────────────────────────┐
│ Step 1: 加载对齐数据                  │
│ 从M1获取两个symbol的K线               │
└─────────────────────────────────────┘
       ↓
┌─────────────────────────────────────┐
│ Step 2: 数据聚合                      │
│ 1m: 直接使用                          │
│ 5m/15m: resample聚合                  │
└─────────────────────────────────────┘
       ↓
┌─────────────────────────────────────┐
│ Step 3: Kalman Filter回归            │
│ 动态计算hedge ratio                   │
│ 输出spread序列                        │
└─────────────────────────────────────┘
       ↓
┌─────────────────────────────────────┐
│ Step 4: 统计检验                      │
│ - Pearson相关系数                     │
│ - ADF检验(协整性)                     │
│ - 半衰期                              │
│ - Hurst指数                           │
└─────────────────────────────────────┘
       ↓
┌─────────────────────────────────────┐
│ Step 5: 综合评分                      │
│ 多指标加权评分                        │
│ 输出0-1之间的分数                     │
└─────────────────────────────────────┘
       ↓
输出: {symbol_a, symbol_b, score, metrics}
```

---

## 评分指标

| 指标 | 权重 | 理想值 | 说明 |
|------|------|--------|------|
| Pearson相关系数 | 20% | >0.8 | 价格相关性 |
| ADF检验p值 | 25% | <0.05 | 协整性 |
| 半衰期 | 20% | 5-30 | 均值回归速度 |
| Hurst指数 | 15% | <0.5 | 均值回归特性 |
| 回归次数 | 10% | >100 | 统计显著性 |
| 当前Z-score | 10% | | 偏离程度 |

---

## 输出格式

```python
{
    "symbol_a": "BTC/USDT",
    "symbol_b": "ETH/USDT",
    "score": 0.85,
    "metrics": {
        "correlation": 0.92,
        "adf_pvalue": 0.001,
        "half_life": 12.5,
        "hurst": 0.35,
        "regression_count": 450,
        "current_z": 1.2
    },
    "timeframe": "5m",
    "kalman_beta": 0.15
}
```

---

## 禁止事项

M3模块**禁止**:
- ❌ 回测（M4职责）
- ❌ 参数优化（M4职责）
- ❌ 跨周期引用（周期独立）
- ❌ 联合筛选（各周期独立）
- ❌ 交易信号（M6职责）
- ❌ 使用未来函数

---

## 相关文档

- [M3.2 1分钟周期筛选](M3-02-1m-selection.md)
- [M3.3 5分钟周期筛选](M3-03-5m-selection.md)
- [M3.4 15分钟周期筛选](M3-04-15m-selection.md)
- [M3.5 Kalman Filter实现](M3-05-kalman-impl.md)
- [M3.6 配对评分算法](M3-06-scoring-algo.md)
- [M4.1 Optimizer职责](M4-01-optimizer-purpose.md)
