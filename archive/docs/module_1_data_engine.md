# 模块一：数据源与清洗模块 (Data Engine) - ✅ LOCKED

> **职责**: 从 SQLite 数据库加载市场统计和 K 线数据，执行清洗管道，构建内存热池。
> **最后更新**: 2025-01-13 - 原子级对齐 `src/data_engine.py` (354 行)

---

## 1. 类、方法、函数签名

### 类: `DataEngine`

**导入依赖**:
```python
import sqlite3
import numpy as np
import logging
from typing import Dict, List, Optional
```

**全局变量**:
```python
logger = logging.getLogger("DataEngine")
```

### 完整签名列表

| # | 签名 | 返回类型 |
|---|------|----------|
| 1 | `__init__(self, db_path: str)` | `None` |
| 2 | `_init_connection(self)` | `None` |
| 3 | `get_all_symbols(self, interval: str = "1m") -> List[str]` | `List[str]` |
| 4 | `load_market_stats(self, min_vol: float = 2_000_000) -> Dict[str, Dict]` | `Dict[str, Dict]` |
| 5 | `build_hot_pool(self, symbols: List[str], limit: int = 5000) -> Dict[str, Dict]` | `Dict[str, Dict]` |
| 6 | `get_historical_data(self, symbol: str, days: int = 90, interval: str = "1m") -> Optional[Dict]` | `Optional[Dict]` |
| 7 | `batch_load_historical(self, symbols: List[str], days: int = 90, interval: str = "1m") -> Dict[str, Dict]` | `Dict[str, Dict]` |
| 8 | `close(self)` | `None` |

---

## 2. 常量、阈值、默认值

| 常量/参数 | 值 | 位置 | 说明 |
|-----------|-----|------|------|
| `min_vol` | `2_000_000` | `load_market_stats` 默认参数 | 24h 成交量过滤阈值 (USDT) |
| `interval` | `"1m"` | 多处默认参数 | K 线周期 |
| `limit` | `5000` | `build_hot_pool` 默认参数 | 每 symbol 最大加载 K 线根数 |
| `days` | `90` | `get_historical_data`, `batch_load_historical` 默认参数 | 历史数据回溯天数 |
| `HOT_POOL_MIN_ROWS` | `10` | `build_hot_pool` (行 133, 159, 204) | 热池最低有效 K 线根数 (三重检查) |
| `HISTORICAL_MIN_ROWS` | `100` | `get_historical_data` (行 247, 265), `batch_load_historical` (行 312, 325) | 历史数据最低有效 K 线根数 |
| `PRAGMA cache_size` | `-128000` | `build_hot_pool` (行 118), `batch_load_historical` (行 292) | SQLite 缓存页大小，≈500MB (128000 × 4KB) |
| `PRAGMA journal_mode` | `WAL` | `_init_connection` (行 34) | Write-Ahead Logging 模式 |
| `PRAGMA synchronous` | `NORMAL` | `_init_connection` (行 35) | 同步模式 (折中性能与安全) |
| `limit_per_sym` 计算 | `days * 24 * 60 + 5000` | `batch_load_historical` (行 295) | 90 天时 = 135000 根 K 线 |
| `cutoff_ts` 计算 | `int((time.time() - days * 86400) * 1000)` | `get_historical_data` (行 235) | 毫秒级时间戳截断 |
| `np.dtype` for OHLCV | `np.float32` | 多处 | K 线数据精度 |
| `np.dtype` for timestamps | `np.int64` | 多处 | 时间戳精度 |
| `np.dtype` for mask | `np.bool` (隐式) | `build_hot_pool` (行 170) | Zero Volume 掩码 |

---

## 3. 数据流转图

### 总体架构

```
data/klines.db (SQLite)
    │
    ├──[PRAGMA: WAL, synchronous=NORMAL]
    │
    ├─► get_all_symbols(interval)
    │       │
    │       └─► List[str] → 所有可用交易对
    │
    ├─► load_market_stats(min_vol)
    │       │
    │       ├─► SQL: SELECT FROM market_stats
    │       ├─► 过滤: vol >= min_vol
    │       ├─► None → 0 替换 (COALESCE)
    │       └─► Dict[str, Dict] → M2 初筛
    │
    ├─► build_hot_pool(symbols, limit)
    │       │
    │       ├─► PRAGMA cache_size=-128000 (500MB)
    │       ├─► SQL: SELECT FROM klines (逐币 LIMIT, 逆序)
    │       ├─► 清洗管道 (详见 §5)
    │       │     ├─ 剔除非法值 (close<=0, vol<0)
    │       │     ├─ None 填充 (vol→0, high/low→close)
    │       │     ├─ Zero Volume Mask
    │       │     ├─ 头部 NaN 丢弃
    │       │     ├─ 中间 NaN ffill
    │       │     └─ np.nan_to_num 兜底
    │       ├─► 转换: float32 + np.int64
    │       ├─► 预计算: log_close = np.log(close)
    │       └─► Dict[str, Dict[np.ndarray]] → M3/M4 计算
    │
    ├─► get_historical_data(symbol, days, interval)
    │       │
    │       ├─► 计算 cutoff_ts
    │       ├─► SQL: SELECT FROM klines WHERE ts >= cutoff
    │       ├─► 清洗: close>0 过滤, None 填充
    │       ├─► 校验: len >= 100
    │       ├─► 转换: float32 + nan_to_num
    │       └─► Optional[Dict] → M3/M4 长周期计算
    │
    ├─► batch_load_historical(symbols, days, interval)
    │       │
    │       ├─► PRAGMA cache_size=-128000
    │       ├─► SQL: SELECT ts,close FROM klines (逐币 LIMIT DESC)
    │       ├─► 清洗: close>0 过滤
    │       ├─► 校验: len >= 100
    │       └─► Dict[str, Dict] → 批量回测
    │
    └─► close()
            └─► sqlite3.Connection.close()
```

### 接口级流转

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ klines.db   │────►│ get_all_symbols  │────►│ List[str]        │
│ market_stats│     │ (DISTINCT query) │     │ ["BTC/USDT",...] │
└─────────────┘     └──────────────────┘     └──────────────────┘

┌─────────────┐     ┌───────────────────────┐     ┌─────────────────────────┐
│ klines.db   │────►│ build_hot_pool        │────►│ Hot Pool Dict           │
│ (逐币 LIMIT)│     │ (清洗+float32+log)    │     │ {sym: {ts,close,...}}   │
└─────────────┘     └───────────────────────┘     └─────────────────────────┘

┌─────────────┐     ┌───────────────────────┐     ┌─────────────────────────┐
│ klines.db   │────►│ get_historical_data   │────►│ Optional[Dict]          │
│ (ts范围查询)│     │ (ts>=cutoff)          │     │ {ts,close,log_close,...}│
└─────────────┘     └───────────────────────┘     └─────────────────────────┘
```

---

## 4. 数据库配置

### 连接初始化 (`_init_connection`)

| 配置项 | SQL 语句 | 值 | 说明 |
|--------|----------|-----|------|
| 日志模式 | `PRAGMA journal_mode=WAL;` | `WAL` | 写前日志，支持并发读写 |
| 同步模式 | `PRAGMA synchronous=NORMAL;` | `NORMAL` | 仅在 WAL 切换时 sync，性能优于 FULL |

### 运行时调优 (临时 PRAGMA)

| 方法 | 配置项 | SQL 语句 | 值 | 说明 |
|------|--------|----------|-----|------|
| `build_hot_pool` | `cache_size` | `PRAGMA cache_size=-128000;` | `-128000 pages` | 负值表示 KB，128000KB ≈ 500MB |
| `batch_load_historical` | `cache_size` | `PRAGMA cache_size=-128000;` | `-128000 pages` | 同上 |

> **注意**: `cache_size` 是连接级临时 PRAGMA，每次调用 `build_hot_pool` 和 `batch_load_historical` 时重新设置。`journal_mode` 和 `synchronous` 在 `__init__` 时设置一次。

---

## 5. 数据清洗步骤 (build_hot_pool 管道)

### 步骤 1: 非法值剔除
```python
# 剔除 close <= 0 的行
if dr[1] is not None and dr[1] <= 0:
    continue
# 剔除 volume < 0 的行
if dr[2] is not None and dr[2] < 0:
    continue
```
- **行为**: 跳过 `close <= 0` 或 `volume < 0` 的 K 线
- **注意**: `close is None` 的行**不会**被此步骤剔除 (会进入后续步骤)

### 步骤 2: None 值填充 (Python 层)
```python
volume_list.append(dr[2] if dr[2] is not None else 0)
high_list.append(dr[3] if dr[3] is not None else dr[1])
low_list.append(dr[4] if dr[4] is not None else dr[1])
```
| 字段 | None 时填充为 | 说明 |
|------|--------------|------|
| `volume` | `0` | 零成交量 |
| `high` | `dr[1]` (即 close 值) | 用收盘价代替最高价 |
| `low` | `dr[1]` (即 close 值) | 用收盘价代替最低价 |
| `ts` | 不填充 (直接从 `dr[0]` 读取) | 假设不为 None |
| `close` | 不填充 (保留原始值) | 可能为 NaN |

### 步骤 3: 数据量校验 (三重门控)
| 检查点 | 行号 | 阈值 | 说明 |
|--------|------|------|------|
| 原始行数 | 133 | `len(rows) >= 10` | SQL 返回行数不足则跳过该 symbol |
| 清洗后行数 | 159 | `len(close_list) >= 10` | 剔除非法值后不足则跳过 |
| NaN 处理后行数 | 204 | `len(close) >= 10` | 头部 NaN 丢弃后不足则跳过 |

### 步骤 4: Numpy 类型转换
```python
close = np.array(close_list, dtype=np.float32)
volume = np.array(volume_list, dtype=np.float32)
high = np.array(high_list, dtype=np.float32)
low = np.array(low_list, dtype=np.float32)
ts = np.array(ts_list, dtype=np.int64)
```

### 步骤 5: Zero Volume Mask
```python
zero_vol_mask = (volume == 0)  # np.bool 数组
```
- **行为**: 标记 `volume == 0` 的位置，**不移除**数据
- **用途**: 供下游识别无交易时段

### 步骤 6: 头部 NaN 丢弃
```python
first_valid = 0
for i in range(len(close)):
    if not np.isnan(close[i]):
        first_valid = i
        break
# 截取从第一个有效值开始的所有数组
if first_valid > 0:
    close = close[first_valid:]
    volume = volume[first_valid:]
    high = high[first_valid:]
    low = low[first_valid:]
    ts = ts[first_valid:]
    zero_vol_mask = zero_vol_mask[first_valid:]
```
- **行为**: 找到第一个非 NaN 的 close 值，丢弃该位置之前的所有数据
- **影响**: 所有字段 (ts, close, volume, high, low, zero_vol_mask) 同步截取

### 步骤 7: 中间 NaN 前值填充 (ffill)
```python
for i in range(1, len(close)):
    if np.isnan(close[i]):
        close[i] = close[i - 1]
    if np.isnan(high[i]):
        high[i] = high[i - 1]
    if np.isnan(low[i]):
        low[i] = low[i - 1]
    if np.isnan(volume[i]):
        volume[i] = volume[i - 1]
```
- **行为**: 从索引 1 开始遍历，NaN 用前一个有效值填充
- **字段**: close, high, low, volume 四个字段独立 ffill

### 步骤 8: np.nan_to_num 兜底
```python
close = np.nan_to_num(close, nan=close[0])
high = np.nan_to_num(high, nan=high[0])
low = np.nan_to_num(low, nan=low[0])
volume = np.nan_to_num(volume, nan=0.0)
```
| 字段 | NaN 替换为 | 说明 |
|------|-----------|------|
| `close` | `close[0]` (第一个元素) | 兜底首个元素 |
| `high` | `high[0]` | 兜底首个元素 |
| `low` | `low[0]` | 兜底首个元素 |
| `volume` | `0.0` | 固定替换为零 |

### 步骤 9: 预计算 log_close
```python
log_close = np.log(close)
```
- **行为**: 对清洗后的 close 数组逐元素取自然对数
- **前提**: 经过上述清洗，close 不应含有 <= 0 的值

---

## 6. 每个方法的详细行为说明

### `__init__(self, db_path: str)`
- **参数**: `db_path` (str) — SQLite 数据库文件路径
- **行为**:
  1. 保存 `db_path` 到 `self.db_path`
  2. 调用 `sqlite3.connect(db_path)` 建立连接
  3. 调用 `self._init_connection()` 初始化 PRAGMA
- **副作用**: 建立数据库连接，设置 WAL 和 synchronous 模式

### `_init_connection(self)`
- **行为**:
  1. 创建游标 `self.conn.cursor()`
  2. 执行 `PRAGMA journal_mode=WAL;`
  3. 执行 `PRAGMA synchronous=NORMAL;`
- **无返回值**

### `get_all_symbols(self, interval: str = "1m") -> List[str]`
- **参数**: `interval` (str, 默认 `"1m"`) — K 线周期
- **行为**:
  1. 创建游标
  2. 执行 `SELECT DISTINCT symbol FROM klines WHERE interval = ? ORDER BY symbol`
  3. 提取每行第一个元素，返回列表
- **返回**: 按字母序排列的 symbol 字符串列表
- **SQL**: 见 §7

### `load_market_stats(self, min_vol: float = 2_000_000) -> Dict[str, Dict]`
- **参数**: `min_vol` (float, 默认 `2_000_000`) — 最小 24h 成交量过滤阈值
- **行为**:
  1. 执行 `SELECT symbol, vol_24h_usdt, high_24h, low_24h, close, kline_count, COALESCE(atr_14, 0), COALESCE(kurtosis, 0), COALESCE(first_ts, 0) FROM market_stats`
  2. 遍历结果行，对每行：
     - 如果 `vol < min_vol`，跳过该 symbol
     - 将 `None` 值替换为 `0` (vol, high_24h, low_24h, close, kline_count)
     - 构建字典: `{"vol_24h_usdt": float, "high_24h": float, "low_24h": float, "close": float, "kline_count": int, "atr_14": float, "kurtosis": float, "first_ts": int}`
  3. 记录日志: `DataEngine: loaded market_stats for {N} symbols (min_vol={min_vol})`
- **返回**: `Dict[str, Dict]` — 以 symbol 为 key 的统计字典
- **注意**: SQL 中 `COALESCE` 只处理 `atr_14`, `kurtosis`, `first_ts`；其他字段的 None 处理在 Python 层完成

### `build_hot_pool(self, symbols: List[str], limit: int = 5000) -> Dict[str, Dict]`
- **参数**:
  - `symbols` (List[str]) — 要加载的交易对列表
  - `limit` (int, 默认 `5000`) — 每个 symbol 最大加载行数
- **行为**:
  1. 如果 `symbols` 为空，立即返回 `{}`
  2. 设置 `PRAGMA cache_size=-128000` (500MB)
  3. 对每个 symbol 执行 `SELECT ts, close, volume, high, low FROM klines WHERE symbol = ? AND interval = '1m' ORDER BY ts DESC LIMIT ?`
  4. 如果原始行数 < 10，跳过
  5. `rows.reverse()` 将结果反转为时间正序
  6. 遍历行，执行清洗管道 (详见 §5)
  7. 清洗后如果行数 < 10，跳过
  8. 转换为 numpy float32/int64
  9. 计算 zero_vol_mask
  10. 执行 NaN ffill 和 nan_to_num 兜底
  11. 如果处理后行数 < 10，跳过
  12. 预计算 `log_close = np.log(close)`
  13. 存入 `hot_pool[sym]` 字典
  14. 记录日志: `DataEngine: built Hot Pool for {N} symbols`
- **返回**: `Dict[str, Dict]` — Hot Pool 内存字典 (详见 §8)
- **SQL**: 见 §7
- **硬编码**: `interval = '1m'` 写在 SQL 中，不受参数控制

### `get_historical_data(self, symbol: str, days: int = 90, interval: str = "1m") -> Optional[Dict]`
- **参数**:
  - `symbol` (str) — 交易对名称
  - `days` (int, 默认 `90`) — 回溯天数
  - `interval` (str, 默认 `"1m"`) — K 线周期
- **行为**:
  1. `import time` (局部导入)
  2. 计算 `cutoff_ts = int((time.time() - days * 86400) * 1000)` (毫秒级)
  3. 执行 SQL 查询 `ts >= cutoff_ts` 的数据
  4. 如果无数据或行数 < 100，记录警告日志并返回 `None`
  5. 遍历行，过滤 `close > 0`，None 填充 (同 build_hot_pool 步骤 2)
  6. 如果过滤后 close_list < 100，返回 `None`
  7. 转换为 `np.float32`，`np.nan_to_num(close, nan=close[0])`
  8. 返回字典 (不含 zero_vol_mask, 含 log_close)
- **返回**: `Optional[Dict]` — 历史数据字典或 `None` (详见 §8)
- **SQL**: 见 §7

### `batch_load_historical(self, symbols: List[str], days: int = 90, interval: str = "1m") -> Dict[str, Dict]`
- **参数**:
  - `symbols` (List[str]) — 交易对列表
  - `days` (int, 默认 `90`) — 回溯天数
  - `interval` (str, 默认 `"1m"`) — K 线周期
- **行为**:
  1. 如果 `symbols` 为空，返回 `{}`
  2. 设置 `PRAGMA cache_size=-128000` (500MB)
  3. 计算 `limit_per_sym = days * 24 * 60 + 5000` (90 天 = 135000)
  4. **仅查询 `ts, close` 两列** (与 get_historical_data 不同)
  5. 对每个 symbol 执行 `SELECT ts, close FROM klines WHERE symbol = ? AND interval = ? ORDER BY ts DESC LIMIT ?`
  6. 如果原始行数 < 100，跳过
  7. `rows.reverse()` 反转为时间正序
  8. 遍历行，过滤 `close > 0`
  9. 如果过滤后 close_list < 100，跳过
  10. 转换为 `np.float32`，`np.nan_to_num(close, nan=close[0])`
  11. 预计算 `log_close = np.log(close)`
  12. 记录日志: `DataEngine: batch_loaded historical data for {loaded}/{len(symbols)} symbols`
- **返回**: `Dict[str, Dict]` — 仅含 ts, close, log_close 的字典 (详见 §8)
- **SQL**: 见 §7

### `close(self)`
- **行为**:
  1. 检查 `self.conn` 是否为真值
  2. 调用 `self.conn.close()`
  3. 记录日志: `DataEngine: connection closed`
- **无返回值**

---

## 7. SQL 语句完整列表

### SQL-1: `get_all_symbols`
```sql
SELECT DISTINCT symbol
FROM klines
WHERE interval = ?
ORDER BY symbol
```
- **参数**: `(interval,)`
- **来源表**: `klines`
- **利用索引**: `idx_klines_sym_int_ts` (推测)

### SQL-2: `load_market_stats`
```sql
SELECT symbol,
       vol_24h_usdt,
       high_24h,
       low_24h,
       close,
       kline_count,
       COALESCE(atr_14, 0) as atr_14,
       COALESCE(kurtosis, 0) as kurtosis,
       COALESCE(first_ts, 0) as first_ts
FROM market_stats
```
- **参数**: 无
- **来源表**: `market_stats`
- **注意**: 无 WHERE 子句，全表扫描；min_vol 过滤在 Python 层执行

### SQL-3: `build_hot_pool`
```sql
SELECT ts, close, volume, high, low
FROM klines
WHERE symbol = ? AND interval = '1m'
ORDER BY ts DESC
LIMIT ?
```
- **参数**: `(sym, limit)`
- **来源表**: `klines`
- **硬编码**: `interval = '1m'`
- **利用索引**: `idx_klines_sym_int_ts` (注释中提及)
- **策略**: 逆序 LIMIT，返回最新 N 根 K 线

### SQL-4: `get_historical_data`
```sql
SELECT ts, close, volume, high, low
FROM klines
WHERE symbol = ? AND interval = ? AND ts >= ?
ORDER BY ts ASC
```
- **参数**: `(symbol, interval, cutoff_ts)`
- **来源表**: `klines`
- **cutoff_ts**: `int((time.time() - days * 86400) * 1000)`

### SQL-5: `batch_load_historical`
```sql
SELECT ts, close
FROM klines
WHERE symbol = ? AND interval = ?
ORDER BY ts DESC
LIMIT ?
```
- **参数**: `(sym, interval, limit_per_sym)`
- **来源表**: `klines`
- **仅两列**: ts, close (减少 60% 数据传输)
- **limit_per_sym**: `days * 24 * 60 + 5000` (默认 135000)

### PRAGMA 语句
```sql
-- 连接初始化
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- 运行时调优
PRAGMA cache_size=-128000;  -- ≈500MB
```

---

## 8. 输出数据结构完整定义

### 8.1 `load_market_stats` 返回值

```python
Dict[str, Dict]
  │
  ├─ Key: str — symbol 名称 (e.g. "BTC/USDT")
  └─ Value: Dict
       ├─ "vol_24h_usdt"   → float   # 24h 成交量 (USDT)
       ├─ "high_24h"        → float   # 24h 最高价
       ├─ "low_24h"         → float   # 24h 最低价
       ├─ "close"           → float   # 最新收盘价
       ├─ "kline_count"     → int     # K 线数量
       ├─ "atr_14"          → float   # 14 周期 ATR (SQL COALESCE 默认 0)
       ├─ "kurtosis"        → float   # 峰度 (SQL COALESCE 默认 0)
       └─ "first_ts"        → int     # 最早时间戳 (SQL COALESCE 默认 0)
```

### 8.2 `build_hot_pool` 返回值 (Hot Pool)

```python
Dict[str, Dict]
  │
  ├─ Key: str — symbol 名称
  └─ Value: Dict
       ├─ "ts"              → np.ndarray  # dtype=np.int64,   形状 (N,)
       ├─ "close"           → np.ndarray  # dtype=np.float32, 形状 (N,)
       ├─ "log_close"       → np.ndarray  # dtype=np.float64, 形状 (N,) (np.log 默认 float64)
       ├─ "volume"          → np.ndarray  # dtype=np.float32, 形状 (N,)
       ├─ "high"            → np.ndarray  # dtype=np.float32, 形状 (N,)
       ├─ "low"             → np.ndarray  # dtype=np.float32, 形状 (N,)
       └─ "zero_vol_mask"   → np.ndarray  # dtype=np.bool_,   形状 (N,)
```

> **注意**: `log_close` 由 `np.log(close)` 计算，numpy 默认返回 float64 (非 float32)。
> **约束**: N >= 10 (三重门控后)。时间顺序为 **升序** (ts 从小到大)。

### 8.3 `get_historical_data` 返回值

```python
Optional[Dict]
  │
  ├─ None — 数据不足 (行数 < 100) 或查询为空
  └─ Dict
       ├─ "ts"              → np.ndarray  # dtype=np.int64,   形状 (N,)
       ├─ "close"           → np.ndarray  # dtype=np.float32, 形状 (N,)
       ├─ "log_close"       → np.ndarray  # dtype=np.float64, 形状 (N,)
       ├─ "volume"          → np.ndarray  # dtype=np.float32, 形状 (N,)
       ├─ "high"            → np.ndarray  # dtype=np.float32, 形状 (N,)
       └─ "low"             → np.ndarray  # dtype=np.float32, 形状 (N,)
```

> **注意**: 与 Hot Pool 不同，**不含** `zero_vol_mask`。
> **约束**: N >= 100。时间顺序为 **升序** (ORDER BY ts ASC)。

### 8.4 `batch_load_historical` 返回值

```python
Dict[str, Dict]
  │
  ├─ Key: str — symbol 名称
  └─ Value: Dict
       ├─ "ts"              → np.ndarray  # dtype=np.int64,   形状 (N,)
       ├─ "close"           → np.ndarray  # dtype=np.float32, 形状 (N,)
       └─ "log_close"       → np.ndarray  # dtype=np.float64, 形状 (N,)
```

> **注意**: 仅含 3 个字段 (ts, close, log_close)，**不含** volume/high/low。
> **约束**: N >= 100。时间顺序为 **升序** (reverse 后)。

---

## 9. 关键差异对比: 三个数据加载方法

| 维度 | `build_hot_pool` | `get_historical_data` | `batch_load_historical` |
|------|------------------|----------------------|------------------------|
| 查询方式 | 逐币 `ORDER BY ts DESC LIMIT` | 单币 `ts >= cutoff` | 逐币 `ORDER BY ts DESC LIMIT` |
| 查询列 | ts, close, volume, high, low (5 列) | ts, close, volume, high, low (5 列) | ts, close (2 列) |
| interval | 硬编码 `'1m'` | 参数控制 | 参数控制 |
| 最低行数 | 10 | 100 | 100 |
| cache_size | 500MB | 无 (使用默认) | 500MB |
| None 填充 | vol→0, high/low→close | vol→0, high/low→close | 无 (仅查 ts+close) |
| NaN 处理 | 头部丢弃 + ffill + nan_to_num | 仅 nan_to_num | 仅 nan_to_num |
| zero_vol_mask | 有 | 无 | 无 |
| 返回类型 | `Dict[str, Dict]` | `Optional[Dict]` | `Dict[str, Dict]` |
