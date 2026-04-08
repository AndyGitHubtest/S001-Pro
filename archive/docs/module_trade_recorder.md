# TradeRecorder 交易记录模块 - 原子级文档

> **职责**: 交易数据持久化，PnL计算，每日报表生成  
> **文件**: `src/trade_recorder.py` (499行)  
> **状态**: P1-重要  
> **最后更新**: 2025-01-13

---

## 1. 类、函数完整签名

### 1.1 TradeLeg (行53-66) - 交易腿
```python
@dataclass
class TradeLeg:
    symbol: str           # 交易对 BTC/USDT
    side: str             # buy/sell
    amount: float         # 数量
    price: float          # 成交价格
    value: float          # 金额 = amount * price
    fee: float            # 手续费
    order_id: str         # 订单ID
    executed_at: str      # 执行时间ISO
```

### 1.2 TradeRecord (行68-114) - 完整交易记录
```python
@dataclass
class TradeRecord:
    # 基本信息
    trade_id: str               # 唯一ID
    pair: str                   # 配对ID
    signal_id: str              # 信号ID
    
    # 开仓信息
    entry_time: str             # 入场时间
    entry_legs: List[TradeLeg]  # 入场腿列表
    entry_z: float              # 入场Z-Score
    
    # 平仓信息
    exit_time: Optional[str]    # 出场时间
    exit_legs: List[TradeLeg]   # 出场腿列表
    exit_z: Optional[float]     # 出场Z-Score
    
    # 盈亏
    gross_pnl: float            # 毛盈亏
    fees: float                 # 总手续费
    net_pnl: float              # 净盈亏
    pnl_pct: float              # 盈亏百分比
    
    # 状态
    status: str                 # open/closed
    holding_period: int         # 持仓时间(分钟)
```

### 1.3 TradeRecorder (行116-499) - 记录器主类
```python
class TradeRecorder:
    def __init__(
        self,
        db_path: str = "data/trades.db"  # SQLite路径
    )  # 行121
    
    def _init_db(self)  # 行126
    # 初始化数据库表
    
    # CRUD操作
    def record_entry(
        self,
        pair: str,
        signal_id: str,
        legs: List[TradeLeg],
        z_score: float
    ) -> str  # 记录入场，返回trade_id (行156)
    
    def record_exit(
        self,
        trade_id: str,
        legs: List[TradeLeg],
        z_score: float
    ) -> bool  # 记录出场 (行213)
    
    def get_open_trades(self) -> List[TradeRecord]  # 获取未平仓 (行275)
    
    def get_trade_history(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        pair: Optional[str] = None,
        limit: int = 100
    ) -> List[TradeRecord]  # 查询历史 (行307)
    
    # 报表生成
    def get_daily_report(self, days: int = 7) -> List[Dict]  # 行355
    def get_pair_stats(self) -> Dict[str, Dict]  # 行408
    def get_performance_summary(self) -> Dict  # 行445
    
    # 数据导出
    def export_to_csv(self, filepath: str)  # 行478
    def export_to_json(self, filepath: str)  # 行491
```

---

## 2. 常量、阈值

| 常量 | 值 | 行号 | 说明 |
|------|-----|------|------|
| `DB_SCHEMA_VERSION` | 1 | 142 | 数据库版本 |
| `MAX_QUERY_LIMIT` | 1000 | 307 | 最大查询条数 |
| `DEFAULT_REPORT_DAYS` | 7 | 355 | 默认报表天数 |

---

## 3. 数据库Schema

```sql
-- trades表 (行142-154)
CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY,
    pair TEXT NOT NULL,
    signal_id TEXT,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    entry_z REAL,
    exit_z REAL,
    gross_pnl REAL DEFAULT 0,
    fees REAL DEFAULT 0,
    net_pnl REAL DEFAULT 0,
    status TEXT DEFAULT 'open',
    data JSON  -- 完整TradeRecord JSON
);

CREATE INDEX idx_trades_pair ON trades(pair);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_entry_time ON trades(entry_time);
```

---

## 4. 数据流转

```
Runtime下单
    │
    ▼
TradeRecorder.record_entry()
    ├─ 生成trade_id (UUID)
    ├─ 计算leg.value
    ├─ INSERT INTO trades
    └─ 返回trade_id
    │
Runtime平仓
    │
    ▼
TradeRecorder.record_exit()
    ├─ UPDATE trades SET exit_time=...
    ├─ 计算gross_pnl, fees, net_pnl
    ├─ UPDATE trades SET net_pnl=..., status='closed'
    └─ 返回success
```

---

## 5. 调用关系

### 谁调用我
```
Runtime
├─ record_entry() (开仓时)
└─ record_exit() (平仓时)

Main
└─ 生成每日报表
```

### 我调用谁
```
TradeRecorder
├─ sqlite3
├─ json
└─ csv
```

---

**维护**: 修改表结构时更新本文档
