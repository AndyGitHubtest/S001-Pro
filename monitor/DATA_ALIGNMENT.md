# 数据对齐记录

## ✅ 已完成对齐

## 数据库结构确认

### 1. 数据库文件位置
| 数据库 | 路径 | 用途 |
|--------|------|------|
| klines.db | `data/klines.db` | K线历史数据（币安下载）|
| trades.db | `data/trades.db` | 交易记录（S001-Pro生成）|

### 2. trades.db 表结构 ✅

#### `trades` 表 - 交易记录
```sql
CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY,
    pair TEXT NOT NULL,              -- 如: BTC/USDT_ETH/USDT
    symbol_a TEXT NOT NULL,          -- 如: BTC/USDT
    symbol_b TEXT NOT NULL,          -- 如: ETH/USDT
    direction INTEGER NOT NULL,      -- 1=做多价差, -1=做空价差
    
    entry_time TEXT NOT NULL,        -- ISO格式时间
    entry_z REAL NOT NULL,           -- 入场Z-score
    layer INTEGER NOT NULL,          -- 加仓层级
    
    -- 腿A
    leg_a_side TEXT NOT NULL,        -- buy/sell
    leg_a_amount REAL NOT NULL,
    leg_a_price REAL NOT NULL,
    leg_a_filled REAL DEFAULT 0,
    leg_a_avg_price REAL DEFAULT 0,
    leg_a_fee REAL DEFAULT 0,
    
    -- 腿B
    leg_b_side TEXT NOT NULL,
    leg_b_amount REAL NOT NULL,
    leg_b_price REAL NOT NULL,
    leg_b_filled REAL DEFAULT 0,
    leg_b_avg_price REAL DEFAULT 0,
    leg_b_fee REAL DEFAULT 0,
    
    -- 出场信息
    exit_time TEXT,                  -- 平仓时间
    exit_z REAL,                     -- 出场Z-score
    exit_reason TEXT DEFAULT '',     -- exit/stop_loss/cooldown/manual
    
    -- 盈亏
    realized_pnl REAL DEFAULT 0,     -- 已实现盈亏
    pnl_pct REAL DEFAULT 0,          -- 盈亏百分比
    holding_minutes REAL DEFAULT 0,  -- 持仓时间(分钟)
    
    -- 状态
    status TEXT DEFAULT 'open',      -- open/closed/partial
    
    -- 时间戳
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_trades_pair ON trades(pair);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_entry_time ON trades(entry_time);
```

#### `daily_summary` 表 - 每日汇总
```sql
CREATE TABLE daily_summary (
    date TEXT PRIMARY KEY,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0,
    win_rate REAL DEFAULT 0,
    avg_profit REAL DEFAULT 0,
    avg_loss REAL DEFAULT 0,
    profit_factor REAL DEFAULT 0,
    max_drawdown REAL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### `trade_logs` 表 - 操作日志
```sql
CREATE TABLE trade_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT,
    action TEXT NOT NULL,  -- open/add/reduce/close
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

## 需要修改的SQL

### 1. summary.py - 使用 daily_summary 表
```python
# 原查询: orders 表
# 改为: daily_summary 表 或 trades 表聚合

# 今日盈亏
SELECT total_pnl FROM daily_summary WHERE date = DATE('now')

# 或从 trades 表计算
SELECT COALESCE(SUM(realized_pnl), 0) 
FROM trades 
WHERE DATE(entry_time) = DATE('now') 
  AND status = 'closed'
```

### 2. positions.py - 使用 trades 表
```python
# 当前持仓
SELECT * FROM trades WHERE status = 'open'

# direction 字段说明:
# 1 = 做多价差 (买A卖B)
# -1 = 做空价差 (卖A买B)
```

### 3. orders.py - 使用 trades 表
```python
# 历史订单
SELECT * FROM trades 
WHERE status = 'closed' 
ORDER BY exit_time DESC
```

### 4. logs.py - 使用 trade_logs 表
```python
# 操作日志
SELECT * FROM trade_logs 
ORDER BY created_at DESC 
LIMIT 50
```

### 5. charts.py - 使用 daily_summary 或 trades 表
```python
# 收益曲线 - 使用 daily_summary
SELECT date, total_pnl 
FROM daily_summary 
ORDER BY date ASC

# 或从 trades 表计算累计收益
```

## 文件位置映射

| 监控面板查询 | S001-Pro 实际表 | 数据库文件 |
|-------------|----------------|-----------|
| 汇总数据 | daily_summary / trades | trades.db |
| 持仓列表 | trades (status='open') | trades.db |
| 历史订单 | trades (status='closed') | trades.db |
| 日志 | trade_logs | trades.db |
| K线数据 | klines | klines.db |

## 更新计划

- [x] 确认表结构
- [x] 修改 backend/app/routers/summary.py
- [x] 修改 backend/app/routers/positions.py
- [x] 修改 backend/app/routers/orders.py
- [x] 修改 backend/app/routers/logs.py
- [x] 修改 backend/app/routers/charts.py
- [x] 更新数据库连接配置（指向 trades.db）
- [ ] 测试验证

## 对齐完成 ✅

**所有后端代码已更新为使用 S001-Pro 实际表结构**

### 主要变更
1. **数据库连接**: 从 `klines.db` 改为 `trades.db`
2. **表名变更**:
   - `orders` → `trades`
   - `positions` → `trades` (status='open')
   - `logs` → `trade_logs`
3. **字段名变更**:
   - `created_at` → `entry_time` / `exit_time`
   - `pnl` → `realized_pnl`
   - `side` → `direction` (1=long, -1=short)
4. **状态值变更**:
   - `OPEN` / `CLOSED` → `open` / `closed`

### 容错处理
- 所有查询都添加了 try-except 保护
- 数据库不存在时返回示例数据
- 表不存在时不报错，返回空数据
