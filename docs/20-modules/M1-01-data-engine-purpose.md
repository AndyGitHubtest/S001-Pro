# M1.1 DataEngine 职责

**所属模块**: M1 数据层  
**版本**: 2.1.0-hardened  
**最后更新**: 2025-04-08  
**对应代码**: `src/data_engine.py`

---

## 一句话描述

从SQLite数据库读取K线数据，计算市场统计指标，为后续筛选提供标准化数据。

---

## 核心职责

### 1. 数据连接管理

**ConnectionManager 类**
- 管理SQLite数据库连接池
- 自动连接和重连
- 线程安全的数据库访问

```python
# 核心方法
_connect()        # 建立连接
execute()         # 执行SQL
close()           # 关闭连接
```

### 2. 交易对管理

**SymbolManager 类**
- 获取数据库中所有交易对列表
- 过滤无效交易对
- 支持按时间区间筛选

```python
# 核心方法
get_all_symbols(interval="1m")    # 获取所有symbol
```

### 3. 市场统计计算

**MarketStatsLoader 类**
- 计算每个交易对的日成交量
- 计算价格波动率
- 计算平均价格
- 输出标准化market_stats字典

**统计指标**:
- `daily_volume` - 日成交量(USDT)
- `volatility` - 价格波动率
- `avg_price` - 平均价格
- `data_points` - 数据点数

### 4. 热池构建

**HotPoolBuilder 类**
- 根据流动性阈值构建候选池
- 默认阈值：2,000,000 USDT日成交量
- 输出符合条件的symbol列表

### 5. 历史数据加载

**HistoricalLoader 类**
- 加载对齐后的K线数据
- 支持多时间框架(1m/5m/15m)
- 数据清洗和缺失值处理

```python
# 核心方法
get_aligned_klines(symbol_a, symbol_b, interval, lookback)
```

### 6. 批量加载

**BatchLoader 类**
- 批量加载多个交易对数据
- 并行处理提高效率
- 内存优化管理

---

## 数据流转

```
Input: data/klines.db (SQLite)
       ├── klines_1m 表
       ├── klines_5m 表
       └── klines_15m 表

Processing:
       ↓
  ConnectionManager (连接数据库)
       ↓
  SymbolManager (获取symbol列表)
       ↓
  MarketStatsLoader (计算统计指标)
       ↓
  HotPoolBuilder (构建候选池)
       ↓
  HistoricalLoader/BatchLoader (加载历史数据)

Output:
       ↓
  Output 1: market_stats 字典 → M2 InitialFilter
  Output 2: Hot Pool (List[str]) → M2 InitialFilter
  Output 3: Aligned Klines → M3 Selector
```

---

## 数据库Schema

### klines_1m / klines_5m / klines_15m 表

| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | TEXT | 交易对，如 "BTC/USDT" |
| timestamp | INTEGER | Unix时间戳(毫秒) |
| open | REAL | 开盘价 |
| high | REAL | 最高价 |
| low | REAL | 最低价 |
| close | REAL | 收盘价 |
| volume | REAL | 成交量 |

### 索引
- PRIMARY KEY: (symbol, timestamp)
- INDEX: symbol
- INDEX: timestamp

---

## 核心类详解

### DataEngine (主类)

```python
class DataEngine:
    def __init__(self, db_path: str = "data/klines.db"):
        self.db_path = db_path
        self.conn_manager = ConnectionManager(db_path)
        self.symbol_manager = SymbolManager(self.conn_manager)
        self.stats_loader = MarketStatsLoader(self.conn_manager)
        self.hot_pool_builder = HotPoolBuilder(self.stats_loader)
        self.historical_loader = HistoricalLoader(self.conn_manager)
        self.batch_loader = BatchLoader(self.conn_manager)
```

**关键方法**:

| 方法 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `get_all_symbols()` | interval | List[str] | 获取所有symbol |
| `load_market_stats(min_vol)` | 最小成交量 | Dict | 加载市场统计 |
| `get_aligned_klines()` | symbol_a, symbol_b, interval, lookback | DataFrame | 获取对齐K线 |
| `close()` | - | - | 关闭连接 |

---

## 使用示例

```python
from src.data_engine import DataEngine

# 初始化
engine = DataEngine("data/klines.db")

# 获取所有1分钟symbol
symbols = engine.get_all_symbols(interval="1m")
print(f"共 {len(symbols)} 个交易对")

# 加载市场统计（最小日成交量2M）
market_stats = engine.load_market_stats(min_vol=2_000_000)
print(f"符合流动性要求: {len(market_stats)} 个")

# 获取对齐后的K线
df = engine.get_aligned_klines(
    symbol_a="BTC/USDT",
    symbol_b="ETH/USDT",
    interval="1m",
    lookback=90*24*60  # 90天
)
print(f"数据形状: {df.shape}")

# 关闭连接
engine.close()
```

---

## 性能指标

- **连接池**: 单连接（SQLite限制）
- **查询延迟**: < 100ms（热点数据缓存）
- **内存占用**: 按需加载，批量释放
- **并发支持**: 单线程访问（SQLite限制）

---

## 错误处理

| 错误类型 | 处理方式 | 日志级别 |
|----------|----------|----------|
| 数据库不存在 | 抛出FileNotFoundError | ERROR |
| 表不存在 | 返回空列表 | WARNING |
| 连接断开 | 自动重连 | WARNING |
| 数据缺失 | 填充NaN | INFO |

---

## 相关文档

- [M1.2 DataEngine API](M1-02-data-engine-api.md)
- [M1.3 数据缓存策略](M1-03-caching-strategy.md)
- [M1.4 K线对齐算法](M1-04-alignment-algorithm.md)
- [src/data_engine.py](../../src/data_engine.py)
