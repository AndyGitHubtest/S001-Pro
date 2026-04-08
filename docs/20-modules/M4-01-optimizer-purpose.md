# M4.1 Optimizer 职责

**所属模块**: M4 优化层  
**版本**: 2.1.0-hardened  
**对应代码**: `src/optimizer.py`

---

## 一句话描述

对M3输出的候选配对进行Walk-Forward参数优化，使用Numba加速回测，找到最优交易参数组合。

---

## 核心职责

### 1. 分层启发式搜索

**Phase 1: 粗扫 (Coarse Search)**
```
entry: 2.0~6.0 (步长0.5)  → 9种组合
exit: 固定0.5
stop: entry+1.0
```

**Phase 2: 精搜 (Fine Search)**
```
取Phase1 Top3
entry: ±0.5范围 (步长0.1)  → ~10种组合
exit: 0.1~1.0 (步长0.1)     → 10种组合
stop: entry+0.5~entry+2.0   → 多种组合
```

**总搜索空间**:
- Phase1: ~9次回测
- Phase2: ~300次回测
- 总计: ~309次回测/配对

### 2. Walk-Forward验证

```
数据分割:
┌─────────────────────────────────────────────────────┐
│  IS数据 (In-Sample)      │  OS数据 (Out-of-Sample) │
│  前70天                  │  后20天                  │
│  用于参数优化             │  用于验证防过拟合        │
└─────────────────────────────────────────────────────┘
```

**验证逻辑**:
1. 在IS数据上优化参数
2. 在OS数据上验证表现
3. OS表现达标才采纳

### 3. Numba加速回测

```python
@njit(cache=True)
def _backtest_core(
    spread: np.ndarray,
    entry: float,
    exit: float,
    stop: float,
    max_hold: int
) -> Tuple[float, int, int]:
    """
    Numba JIT编译的回测核心
    比纯Python快100x+
    """
```

### 4. 参数边界约束

| 参数 | 范围 | 步长 | 说明 |
|------|------|------|------|
| z_entry | 2.0~6.0 | Phase1: 0.5, Phase2: 0.1 | 进场阈值 |
| z_exit | 0.1~1.0 | 0.1 | 出场阈值 |
| z_stop | entry+0.5~entry+2.0 | 0.5 | 止损阈值 |
| max_hold | 10~100 | 10 | 最大持仓时间 |

---

## 核心类

### ParamOptimizer

```python
class ParamOptimizer:
    """
    M4参数优化器
    
    分层启发式搜索 + Walk-Forward验证
    """
    
    def __init__(
        self,
        db_path: str = "data/klines.db",
        is_days: int = 70,
        os_days: int = 20,
        min_pf: float = 1.5,
        min_win_rate: float = 0.45,
    ):
        self.db_path = db_path
        self.is_days = is_days      # IS数据天数
        self.os_days = os_days      # OS数据天数
        self.min_pf = min_pf        # 最小Profit Factor
        self.min_win_rate = min_win_rate  # 最小胜率
```

### 核心方法

#### optimize

```python
def optimize(
    self,
    pairs: List[Dict],
    timeframe: str = "5m"
) -> List[Dict]
```

**功能**: 对配对列表进行参数优化

**参数**:
- `pairs`: M3输出的配对列表
- `timeframe`: 时间周期

**返回**: 带优化参数的配对列表

**示例**:
```python
from src.optimizer import ParamOptimizer

optimizer = ParamOptimizer()
optimized_pairs = optimizer.optimize(m3_pairs, timeframe="5m")
```

---

## 优化流程详解

```
输入: M3配对列表 (如100个)
       ↓
对于每个配对:
    ┌──────────────────────────────────────────┐
    │ Step 1: 加载数据                          │
    │ 获取90天K线数据                            │
    │ 分割: IS(70天) + OS(20天)                  │
    └──────────────────────────────────────────┘
           ↓
    ┌──────────────────────────────────────────┐
    │ Step 2: Phase 1 粗扫                      │
    │ entry: [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    │ exit: 固定0.5                             │
    │ stop: entry+1.0                           │
    │                                          │
    │ 对每种组合在IS数据上回测                   │
    │ 记录Profit Factor、Sharpe、胜率            │
    └──────────────────────────────────────────┘
           ↓
    ┌──────────────────────────────────────────┐
    │ Step 3: Phase 2 精搜                      │
    │ 取Phase1 Top3                             │
    │ 在其周围精细搜索                           │
    │                                          │
    │ entry: ±0.5范围 (步长0.1)                 │
    │ exit: 0.1~1.0 (步长0.1)                   │
    │ stop: entry+0.5~entry+2.0                 │
    └──────────────────────────────────────────┘
           ↓
    ┌──────────────────────────────────────────┐
    │ Step 4: Walk-Forward验证                  │
    │ 用Step3找到的最优参数                       │
    │ 在OS数据上回测验证                          │
    │                                          │
    │ 要求:                                     │
    │ - OS Profit Factor >= 1.2                 │
    │ - OS Win Rate >= 0.4                      │
    │ - OS Drawdown <= 15%                      │
    └──────────────────────────────────────────┘
           ↓
    如果OS验证通过 → 加入白名单
    如果OS验证失败 → 丢弃
       ↓
输出: 带优化参数的白名单配对
```

---

## 回测指标

| 指标 | 说明 | 阈值 |
|------|------|------|
| Profit Factor | 毛盈利/毛亏损 | IS≥1.5, OS≥1.2 |
| Sharpe Ratio | 风险调整收益 | IS≥1.0, OS≥0.5 |
| Win Rate | 胜率 | IS≥45%, OS≥40% |
| Max Drawdown | 最大回撤 | IS≤20%, OS≤15% |
| Total Trades | 总交易次数 | ≥20 |
| Avg Trade | 平均盈亏 | >0 |

---

## 输出格式

```python
{
    "symbol_a": "BTC/USDT",
    "symbol_b": "ETH/USDT",
    "timeframe": "5m",
    "params": {
        "z_entry": 2.5,
        "z_exit": 0.5,
        "z_stop": 3.5,
        "max_hold": 20
    },
    "is_metrics": {
        "profit_factor": 1.85,
        "sharpe": 1.2,
        "win_rate": 0.52,
        "max_drawdown": 0.12,
        "total_trades": 45,
        "avg_trade": 0.8
    },
    "os_metrics": {
        "profit_factor": 1.45,
        "sharpe": 0.8,
        "win_rate": 0.48,
        "max_drawdown": 0.10,
        "total_trades": 15,
        "avg_trade": 0.6
    }
}
```

---

## 性能优化

### Numba JIT加速

```python
from numba import njit

@njit(cache=True)
def backtest_loop(spread, entry, exit, stop):
    # 编译为机器码，速度提升100x
    ...
```

### 并行处理

```python
from multiprocessing import Pool

def optimize_pair(pair):
    # 单个配对的优化
    ...

with Pool(processes=4) as pool:
    results = pool.map(optimize_pair, pairs)
```

---

## 相关文档

- [M4.2 Walk-Forward算法](M4-02-walk-forward.md)
- [M4.3 参数边界约束](M4-03-param-constraints.md)
- [M5.1 Persistence职责](M5-01-persistence-purpose.md)
- [src/optimizer.py](../../src/optimizer.py)
