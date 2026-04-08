# M1.2 DataEngine API

**所属模块**: M1 数据层  
**版本**: 2.1.0-hardened  
**对应代码**: `src/data_engine.py`

---

## 完整API列表

### DataEngine 类

```python
class DataEngine:
    """
    M1数据引擎主类
    
    提供一站式数据访问接口，封装所有子模块功能。
    """
```

#### 构造函数

```python
def __init__(self, db_path: str = "data/klines.db")
```

**参数**:
- `db_path`: SQLite数据库路径

**示例**:
```python
engine = DataEngine("data/klines.db")
```

---

#### get_all_symbols

```python
def get_all_symbols(
    self, 
    interval: str = "1m"
) -> List[str]
```

**功能**: 获取指定时间周期的所有交易对列表

**参数**:
- `interval`: 时间周期，可选 "1m", "5m", "15m"

**返回**: 
- `List[str]`: 交易对列表，如 ["BTC/USDT", "ETH/USDT", ...]

**示例**:
```python
symbols = engine.get_all_symbols("1m")
# 返回: ["BTC/USDT", "ETH/USDT", "BNB/USDT", ...]
```

---

#### load_market_stats

```python
def load_market_stats(
    self,
    min_vol: float = 2_000_000,
    interval: str = "1m"
) -> Dict[str, Dict]
```

**功能**: 加载市场统计指标，过滤低流动性交易对

**参数**:
- `min_vol`: 最小日成交量阈值（USDT），默认2M
- `interval`: 时间周期

**返回**:
- `Dict[str, Dict]`: {symbol: stats_dict}

**stats_dict结构**:
```python
{
    "daily_volume": 5000000.0,    # 日成交量
    "volatility": 0.025,           # 波动率
    "avg_price": 45000.0,          # 平均价格
    "data_points": 86400,          # 数据点数
    "last_update": 1640995200000   # 最后更新时间戳
}
```

**示例**:
```python
stats = engine.load_market_stats(min_vol=2_000_000)
for symbol, stat in stats.items():
    print(f"{symbol}: 日成交量={stat['daily_volume']:.0f}")
```

---

#### get_aligned_klines

```python
def get_aligned_klines(
    self,
    symbol_a: str,
    symbol_b: str,
    interval: str = "1m",
    lookback: int = 90*24*60
) -> pd.DataFrame
```

**功能**: 获取两个交易对的**时间对齐**K线数据

**参数**:
- `symbol_a`: 第一个交易对
- `symbol_b`: 第二个交易对
- `interval`: 时间周期
- `lookback`: 回溯条数，默认90天(1m)

**返回**:
- `pd.DataFrame`: 对齐后的K线数据

**DataFrame结构**:
```
                    BTC/USDT_open  BTC/USDT_high  ...  ETH/USDT_close
2025-01-01 00:00    45000.0        45100.0       ...   3200.0
2025-01-01 00:01    45100.0        45200.0       ...   3205.0
...
```

**示例**:
```python
df = engine.get_aligned_klines(
    symbol_a="BTC/USDT",
    symbol_b="ETH/USDT",
    interval="1m",
    lookback=7*24*60  # 7天
)
print(df.shape)  # (10080, 10)
```

---

#### get_multi_timeframe_data

```python
def get_multi_timeframe_data(
    self,
    symbol: str,
    timeframes: List[str] = ["1m", "5m", "15m"],
    lookback_days: int = 90
) -> Dict[str, pd.DataFrame]
```

**功能**: 同时获取多个时间周期的K线数据

**参数**:
- `symbol`: 交易对
- `timeframes`: 时间周期列表
- `lookback_days`: 回溯天数

**返回**:
- `Dict[str, pd.DataFrame]`: {timeframe: df}

**示例**:
```python
data = engine.get_multi_timeframe_data("BTC/USDT")
for tf, df in data.items():
    print(f"{tf}: {df.shape}")
# 输出:
# 1m: (129600, 5)
# 5m: (25920, 5)
# 15m: (8640, 5)
```

---

#### close

```python
def close(self) -> None
```

**功能**: 关闭数据库连接，释放资源

**示例**:
```python
engine.close()
```

---

## ConnectionManager API

### 构造函数

```python
def __init__(self, db_path: str)
```

### 核心方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `execute` | `execute(sql: str, params: tuple = ()) -> List[Tuple]` | 执行SQL查询 |
| `executemany` | `executemany(sql: str, params: List[tuple]) -> None` | 批量执行 |
| `commit` | `commit() -> None` | 提交事务 |
| `close` | `close() -> None` | 关闭连接 |

### 使用示例

```python
from src.data_engine import ConnectionManager

conn = ConnectionManager("data/klines.db")

# 查询
results = conn.execute(
    "SELECT * FROM klines_1m WHERE symbol = ? LIMIT 10",
    ("BTC/USDT",)
)

# 批量插入
conn.executemany(
    "INSERT INTO klines_1m VALUES (?, ?, ?, ?, ?, ?, ?)",
    [("BTC/USDT", 1234567890, 45000, 45100, 44900, 45050, 100.5), ...]
)
conn.commit()

conn.close()
```

---

## 数据类型定义

### MarketStats

```python
from typing import TypedDict

class MarketStats(TypedDict):
    daily_volume: float      # 日成交量(USDT)
    volatility: float        # 价格波动率(0-1)
    avg_price: float         # 平均价格
    data_points: int         # 数据点数
    last_update: int         # 最后更新时间戳(毫秒)
```

### KlineData

```python
class KlineData(TypedDict):
    symbol: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
```

---

## 异常处理

### 常见异常

| 异常 | 触发条件 | 处理方式 |
|------|----------|----------|
| `FileNotFoundError` | 数据库文件不存在 | 检查db_path |
| `sqlite3.OperationalError` | SQL语法错误或表不存在 | 检查SQL |
| `ValueError` | 参数无效 | 检查参数类型 |
| `ConnectionError` | 连接断开 | 自动重连 |

### 异常示例

```python
try:
    engine = DataEngine("wrong/path.db")
    symbols = engine.get_all_symbols()
except FileNotFoundError as e:
    print(f"数据库文件不存在: {e}")
except sqlite3.OperationalError as e:
    print(f"数据库操作错误: {e}")
finally:
    engine.close()
```

---

## 性能优化建议

1. **批量查询**: 使用BatchLoader代替多次单条查询
2. **及时关闭**: 使用`with`语句或确保调用`close()`
3. **缓存统计**: market_stats结果可缓存复用
4. **按需加载**: 只加载需要的symbol和timeframe
