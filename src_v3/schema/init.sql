-- S001-Pro V3 Database Schema
-- 模块化架构数据库设计 - 读写分离
-- Created: 2026-04-09

-- 启用WAL模式支持并发读写
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;  -- 64MB缓存
PRAGMA temp_store=memory;

-- ═══════════════════════════════════════════════════════════════════════════════
-- M1: 原始市场数据 (Data-Core写入, 其他模块只读)
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS m1_raw_klines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,  -- '1m', '5m', '15m', '1h'
    timestamp INTEGER NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    quote_volume REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timeframe, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_m1_lookup 
    ON m1_raw_klines(symbol, timeframe, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_m1_symbol_time 
    ON m1_raw_klines(symbol, timestamp);

-- ═══════════════════════════════════════════════════════════════════════════════
-- M2: 过滤后的币种列表 (M2写入)
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS m2_filtered_symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    filter_passed BOOLEAN DEFAULT 0,
    filter_reason TEXT,  -- 未通过原因
    metrics TEXT,        -- JSON: {vol_24h, atr_14, kurtosis, ...}
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_m2_session 
    ON m2_filtered_symbols(session_id);
CREATE INDEX IF NOT EXISTS idx_m2_passed 
    ON m2_filtered_symbols(session_id, filter_passed);

-- ═══════════════════════════════════════════════════════════════════════════════
-- M3: 配对评分结果 (M3写入)
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS m3_scored_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_id INTEGER NOT NULL DEFAULT 1,  -- 批次序列号
    session_id TEXT NOT NULL,
    symbol_a TEXT NOT NULL,
    symbol_b TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    score REAL,
    -- 结构稳定性指标
    correlation REAL,
    correlation_std REAL,
    coint_pvalue REAL,
    adf_pvalue REAL,
    -- 均值回归能力
    half_life REAL,
    zscore_range REAL,
    zscore_max REAL,
    zscore_min REAL,
    -- 交易性
    spread_volatility REAL,
    daily_volume REAL,
    -- 状态
    status TEXT DEFAULT 'pending',  -- pending, selected, rejected
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_m3_lookup 
    ON m3_scored_pairs(session_id, timeframe, status);
CREATE INDEX IF NOT EXISTS idx_m3_score 
    ON m3_scored_pairs(session_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_m3_pair 
    ON m3_scored_pairs(symbol_a, symbol_b, timeframe);

-- ═══════════════════════════════════════════════════════════════════════════════
-- M4: 参数优化结果 (M4写入)
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS m4_optimized_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_id INTEGER NOT NULL DEFAULT 1,
    session_id TEXT NOT NULL,
    m3_id INTEGER REFERENCES m3_scored_pairs(id),
    symbol_a TEXT,
    symbol_b TEXT,
    timeframe TEXT,
    -- 优化参数
    z_entry REAL,
    z_exit REAL,
    z_stop REAL,
    beta REAL DEFAULT 1.0,
    -- IS样本内回测结果
    is_pf REAL,           -- Profit Factor
    is_dd REAL,           -- Max Drawdown
    is_n INTEGER,         -- Trade Count
    is_wr REAL,           -- Win Rate
    is_sharpe REAL,
    -- OS样本外验证结果
    os_pf REAL,
    os_dd REAL,
    os_n INTEGER,
    os_wr REAL,
    os_sharpe REAL,
    -- 综合评分
    final_score REAL,
    selected BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_m4_session 
    ON m4_optimized_pairs(session_id);
CREATE INDEX IF NOT EXISTS idx_m4_selected 
    ON m4_optimized_pairs(session_id, selected);
CREATE INDEX IF NOT EXISTS idx_m4_score 
    ON m4_optimized_pairs(session_id, final_score DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- M5: 最终交易配置 (M5写入)
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS m5_trade_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_id INTEGER NOT NULL DEFAULT 1,
    session_id TEXT NOT NULL,
    pair_key TEXT UNIQUE NOT NULL,  -- "BAS/USDT_MON/USDT"
    symbol_a TEXT NOT NULL,
    symbol_b TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    -- 交易参数
    config TEXT NOT NULL,  -- JSON完整配置
    -- 风控参数
    z_entry REAL,
    z_exit REAL,
    z_stop REAL,
    max_position_value REAL,
    -- 状态
    enabled BOOLEAN DEFAULT 1,
    activated_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_m5_pair_key 
    ON m5_trade_configs(pair_key);
CREATE INDEX IF NOT EXISTS idx_m5_enabled 
    ON m5_trade_configs(enabled);
CREATE TRIGGER IF NOT EXISTS trg_m5_updated_at 
    AFTER UPDATE ON m5_trade_configs
    BEGIN
        UPDATE m5_trade_configs SET updated_at = datetime('now') WHERE id = NEW.id;
    END;

-- ═══════════════════════════════════════════════════════════════════════════════
-- M6: 运行时状态 (M6读写)
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS runtime_positions (
    id INTEGER PRIMARY KEY,
    pair_key TEXT UNIQUE NOT NULL,
    symbol_a TEXT,
    symbol_b TEXT,
    state TEXT DEFAULT 'IDLE',  -- IDLE, SCALING_IN, IN_POSITION, SCALING_OUT, EXITED
    direction INTEGER DEFAULT 0,  -- 1: 做多价差, -1: 做空价差
    entry_z REAL,
    position_size_pct REAL DEFAULT 0.0,
    scale_in_layer INTEGER DEFAULT 0,
    scale_out_layer INTEGER DEFAULT 0,
    entry_price_a REAL,
    entry_price_b REAL,
    current_price_a REAL,
    current_price_b REAL,
    unrealized_pnl REAL DEFAULT 0.0,
    pending_orders TEXT,  -- JSON
    -- 失败计数
    scale_in_fail_count INTEGER DEFAULT 0,
    scale_out_fail_count INTEGER DEFAULT 0,
    -- 冷却时间
    scale_in_cool_until REAL DEFAULT 0,
    scale_out_cool_until REAL DEFAULT 0,
    -- 时间戳
    entry_time REAL,
    last_update_time REAL DEFAULT 0,
    last_signal_bar INTEGER DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rt_state 
    ON runtime_positions(state);
CREATE INDEX IF NOT EXISTS idx_rt_pair 
    ON runtime_positions(pair_key);

CREATE TABLE IF NOT EXISTS runtime_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT UNIQUE,
    pair_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT,  -- buy, sell
    order_type TEXT,  -- market, limit
    qty REAL,
    price REAL,
    status TEXT DEFAULT 'pending',  -- pending, filled, partial, canceled, failed
    filled_qty REAL DEFAULT 0,
    avg_price REAL,
    error_msg TEXT,
    reduce_only BOOLEAN DEFAULT 0,
    post_only BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rt_order_pair 
    ON runtime_orders(pair_key, status);
CREATE INDEX IF NOT EXISTS idx_rt_order_id 
    ON runtime_orders(order_id);

-- 信号记录表
CREATE TABLE IF NOT EXISTS runtime_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_key TEXT NOT NULL,
    timestamp REAL,
    z_score REAL,
    signal_type TEXT,  -- entry, exit, stop, scale_in, scale_out
    triggered BOOLEAN DEFAULT 0,
    executed BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rt_signal_pair 
    ON runtime_signals(pair_key, timestamp DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 模块状态追踪 (审计日志)
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS module_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_name TEXT NOT NULL,  -- M1, M2, M3, M4, M5, M6
    session_id TEXT,
    status TEXT,  -- idle, running, completed, failed, skipped
    progress_pct INTEGER DEFAULT 0,
    message TEXT,
    duration_ms INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mod_status_lookup 
    ON module_status(module_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mod_session 
    ON module_status(session_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 系统配置表
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR REPLACE INTO system_config (key, value) VALUES 
    ('schema_version', '3.0.0'),
    ('created_at', datetime('now'));

-- ═══════════════════════════════════════════════════════════════════════════════
-- 视图: 方便查询
-- ═══════════════════════════════════════════════════════════════════════════════

-- 当前活跃配置视图
CREATE VIEW IF NOT EXISTS v_active_configs AS
SELECT 
    m5.pair_key,
    m5.symbol_a,
    m5.symbol_b,
    m5.timeframe,
    m5.z_entry,
    m5.z_exit,
    m5.z_stop,
    m4.is_pf,
    m4.os_pf,
    m4.final_score,
    rt.state as runtime_state,
    rt.position_size_pct
FROM m5_trade_configs m5
LEFT JOIN m4_optimized_pairs m4 ON m5.session_id = m4.session_id 
    AND m5.symbol_a = m4.symbol_a AND m5.symbol_b = m4.symbol_b
LEFT JOIN runtime_positions rt ON m5.pair_key = rt.pair_key
WHERE m5.enabled = 1;

-- 最新会话视图
CREATE VIEW IF NOT EXISTS v_latest_session AS
SELECT 
    module_name,
    session_id,
    status,
    progress_pct,
    message,
    created_at
FROM module_status
WHERE (module_name, created_at) IN (
    SELECT module_name, MAX(created_at)
    FROM module_status
    GROUP BY module_name
);
