#!/usr/bin/env python3
"""
交易记录器 (Trade Recorder)

功能:
  1. SQLite 数据库存储每笔交易详情
  2. 支持开仓、平仓、加仓、减仓全记录
  3. 盈亏计算和统计分析
  4. 导出 CSV/Excel 用于人工分析

表结构:
  - trades: 主交易表
  - trade_legs: 交易腿详情
  - daily_summary: 每日汇总

用法:
  from src.trade_recorder import TradeRecorder
  
  recorder = TradeRecorder()
  
  # 记录开仓
  await recorder.record_open(
      pair="BTC/USDT_ETH/USDT",
      direction=1,
      leg_a={"symbol": "BTC/USDT", "side": "buy", "amount": 0.5, "price": 50000},
      leg_b={"symbol": "ETH/USDT", "side": "sell", "amount": 8, "price": 3000},
      z_score=2.5,
      layer=0
  )
  
  # 记录平仓
  await recorder.record_close(
      trade_id="xxx",
      exit_z=0.5,
      leg_a_exit={...},
      leg_b_exit={...}
  )
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger("TradeRecorder")


@dataclass
class TradeLeg:
    """交易腿数据"""
    symbol: str
    side: str  # buy/sell
    amount: float
    price: float
    order_type: str = "market"
    filled_amount: float = 0.0
    avg_price: float = 0.0
    fee: float = 0.0
    order_id: str = ""
    status: str = "pending"  # pending/filled/partial/failed


@dataclass
class TradeRecord:
    """完整交易记录"""
    # 基础信息
    trade_id: str
    pair: str
    symbol_a: str
    symbol_b: str
    direction: int  # 1=做多价差, -1=做空价差
    
    # 入场信息
    entry_time: str
    entry_z: float
    layer: int
    
    # 腿A (所有非默认参数在前)
    leg_a_side: str
    leg_a_amount: float
    leg_a_price: float
    leg_b_side: str
    leg_b_amount: float
    leg_b_price: float
    
    # 腿A 可选字段 (默认参数在后)
    leg_a_filled: float = 0.0
    leg_a_avg_price: float = 0.0
    leg_a_fee: float = 0.0
    
    # 腿B 可选字段
    leg_b_filled: float = 0.0
    leg_b_avg_price: float = 0.0
    leg_b_fee: float = 0.0
    
    # 出场信息 (平仓时填充)
    exit_time: Optional[str] = None
    exit_z: Optional[float] = None
    exit_reason: str = ""  # exit/stop_loss/cooldown/manual
    
    # 盈亏计算
    realized_pnl: float = 0.0
    pnl_pct: float = 0.0
    holding_minutes: float = 0.0
    
    # 状态
    status: str = "open"  # open/closed/partial
    
    # 元数据
    created_at: str = ""
    updated_at: str = ""


class TradeRecorder:
    """
    交易记录器: SQLite 存储 + 统计分析
    """
    
    def __init__(self, db_path: str = "data/trades.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        
    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- 主交易表
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    pair TEXT NOT NULL,
                    symbol_a TEXT NOT NULL,
                    symbol_b TEXT NOT NULL,
                    direction INTEGER NOT NULL,
                    
                    entry_time TEXT NOT NULL,
                    entry_z REAL NOT NULL,
                    layer INTEGER NOT NULL,
                    
                    leg_a_side TEXT NOT NULL,
                    leg_a_amount REAL NOT NULL,
                    leg_a_price REAL NOT NULL,
                    leg_a_filled REAL DEFAULT 0,
                    leg_a_avg_price REAL DEFAULT 0,
                    leg_a_fee REAL DEFAULT 0,
                    
                    leg_b_side TEXT NOT NULL,
                    leg_b_amount REAL NOT NULL,
                    leg_b_price REAL NOT NULL,
                    leg_b_filled REAL DEFAULT 0,
                    leg_b_avg_price REAL DEFAULT 0,
                    leg_b_fee REAL DEFAULT 0,
                    
                    exit_time TEXT,
                    exit_z REAL,
                    exit_reason TEXT DEFAULT '',
                    
                    realized_pnl REAL DEFAULT 0,
                    pnl_pct REAL DEFAULT 0,
                    holding_minutes REAL DEFAULT 0,
                    
                    status TEXT DEFAULT 'open',
                    
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                -- 索引
                CREATE INDEX IF NOT EXISTS idx_trades_pair ON trades(pair);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
                
                -- 每日汇总表
                CREATE TABLE IF NOT EXISTS daily_summary (
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
                
                -- 操作日志表
                CREATE TABLE IF NOT EXISTS trade_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT,
                    action TEXT NOT NULL,  -- open/add/reduce/close
                    details TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        logger.info(f"TradeRecorder: database initialized at {self.db_path}")
    
    async def record_open(
        self,
        pair: str,
        direction: int,
        leg_a: Dict[str, Any],
        leg_b: Dict[str, Any],
        z_score: float,
        layer: int = 0,
    ) -> str:
        """
        记录开仓
        
        Returns:
            trade_id: 交易ID
        """
        import uuid
        
        trade_id = str(uuid.uuid4())[:16]
        now = datetime.now().isoformat()
        
        symbol_a = leg_a["symbol"]
        symbol_b = leg_b["symbol"]
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO trades (
                        trade_id, pair, symbol_a, symbol_b, direction,
                        entry_time, entry_z, layer,
                        leg_a_side, leg_a_amount, leg_a_price,
                        leg_b_side, leg_b_amount, leg_b_price,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                """, (
                    trade_id, pair, symbol_a, symbol_b, direction,
                    now, z_score, layer,
                    leg_a["side"], leg_a["amount"], leg_a.get("price", 0),
                    leg_b["side"], leg_b["amount"], leg_b.get("price", 0),
                    now, now
                ))
                
                # 记录操作日志
                conn.execute("""
                    INSERT INTO trade_logs (trade_id, action, details)
                    VALUES (?, 'open', ?)
                """, (trade_id, json.dumps({
                    "z_score": z_score,
                    "layer": layer,
                    "leg_a": leg_a,
                    "leg_b": leg_b
                })))
                
                conn.commit()
            
            logger.info(f"TradeRecorder: recorded OPEN {pair} (ID: {trade_id})")
            return trade_id
            
        except Exception as e:
            logger.error(f"TradeRecorder: failed to record open: {e}")
            raise
    
    async def record_close(
        self,
        trade_id: str,
        exit_z: float,
        exit_reason: str = "exit",
        leg_a_exit: Optional[Dict] = None,
        leg_b_exit: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        记录平仓并计算盈亏
        
        Returns:
            盈亏统计
        """
        now = datetime.now().isoformat()
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 获取原交易
                cursor = conn.execute(
                    "SELECT * FROM trades WHERE trade_id = ?", (trade_id,)
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError(f"Trade {trade_id} not found")
                
                # 计算持仓时间
                entry_time = datetime.fromisoformat(row[5])
                exit_time = datetime.now()
                holding_minutes = (exit_time - entry_time).total_seconds() / 60
                
                # 计算盈亏
                direction = row[4]
                
                # 腿A盈亏
                leg_a_amount = row[10]
                leg_a_entry = row[11]
                leg_a_exit_price = leg_a_exit.get("price", leg_a_entry) if leg_a_exit else leg_a_entry
                leg_a_pnl = (leg_a_exit_price - leg_a_entry) * leg_a_amount * direction
                
                # 腿B盈亏 (方向相反)
                leg_b_amount = row[15]
                leg_b_entry = row[16]
                leg_b_exit_price = leg_b_exit.get("price", leg_b_entry) if leg_b_exit else leg_b_entry
                leg_b_pnl = (leg_b_entry - leg_b_exit_price) * leg_b_amount * direction
                
                total_pnl = leg_a_pnl + leg_b_pnl
                
                # 更新交易记录
                conn.execute("""
                    UPDATE trades SET
                        exit_time = ?,
                        exit_z = ?,
                        exit_reason = ?,
                        realized_pnl = ?,
                        holding_minutes = ?,
                        status = 'closed',
                        updated_at = ?
                    WHERE trade_id = ?
                """, (now, exit_z, exit_reason, total_pnl, holding_minutes, now, trade_id))
                
                # 记录操作日志
                conn.execute("""
                    INSERT INTO trade_logs (trade_id, action, details)
                    VALUES (?, 'close', ?)
                """, (trade_id, json.dumps({
                    "exit_z": exit_z,
                    "exit_reason": exit_reason,
                    "realized_pnl": total_pnl,
                    "holding_minutes": holding_minutes
                })))
                
                conn.commit()
            
            logger.info(f"TradeRecorder: recorded CLOSE {trade_id}, PnL={total_pnl:.2f}")
            
            return {
                "trade_id": trade_id,
                "realized_pnl": total_pnl,
                "holding_minutes": holding_minutes,
                "exit_reason": exit_reason
            }
            
        except Exception as e:
            logger.error(f"TradeRecorder: failed to record close: {e}")
            raise
    
    async def update_daily_summary(self, date: Optional[str] = None):
        """
        更新每日汇总
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 统计当日交易
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losses,
                        SUM(realized_pnl) as total_pnl,
                        AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl END) as avg_profit,
                        AVG(CASE WHEN realized_pnl < 0 THEN realized_pnl END) as avg_loss
                    FROM trades
                    WHERE date(exit_time) = ? AND status = 'closed'
                """, (date,))
                
                row = cursor.fetchone()
                total, wins, losses, total_pnl, avg_profit, avg_loss = row
                
                if total and total > 0:
                    win_rate = wins / total * 100
                    profit_factor = abs(avg_profit / avg_loss) if avg_loss and avg_loss != 0 else 0
                else:
                    win_rate = 0
                    profit_factor = 0
                
                # 插入或更新
                conn.execute("""
                    INSERT OR REPLACE INTO daily_summary (
                        date, total_trades, winning_trades, losing_trades,
                        total_pnl, win_rate, avg_profit, avg_loss, profit_factor,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date, total or 0, wins or 0, losses or 0,
                    total_pnl or 0, win_rate, avg_profit or 0, avg_loss or 0, profit_factor,
                    datetime.now().isoformat()
                ))
                
                conn.commit()
                
                logger.info(f"TradeRecorder: daily summary updated for {date}")
                
        except Exception as e:
            logger.error(f"TradeRecorder: failed to update daily summary: {e}")
    
    def get_open_trades(self) -> List[Dict]:
        """获取所有未平仓交易"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC"
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_trade_history(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        pair: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """获取交易历史"""
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND date(entry_time) >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date(entry_time) <= ?"
            params.append(end_date)
        if pair:
            query += " AND pair = ?"
            params.append(pair)
        
        query += " ORDER BY entry_time DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_daily_report(self, days: int = 7) -> List[Dict]:
        """获取最近N天日报"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM daily_summary
                WHERE date >= date('now', '-{} days')
                ORDER BY date DESC
            """.format(days))
            return [dict(row) for row in cursor.fetchall()]
    
    def export_to_csv(self, filepath: str, start_date: Optional[str] = None):
        """导出交易记录到 CSV"""
        import csv
        
        trades = self.get_trade_history(start_date=start_date, limit=10000)
        
        if not trades:
            logger.warning("TradeRecorder: no trades to export")
            return
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        
        logger.info(f"TradeRecorder: exported {len(trades)} trades to {filepath}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取整体统计"""
        with sqlite3.connect(self.db_path) as conn:
            # 总体统计
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_trades,
                    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(realized_pnl) as total_pnl,
                    AVG(realized_pnl) as avg_pnl,
                    MAX(realized_pnl) as max_profit,
                    MIN(realized_pnl) as max_loss
                FROM trades
            """)
            
            row = cursor.fetchone()
            
            return {
                "total_trades": row[0] or 0,
                "open_trades": row[1] or 0,
                "winning_trades": row[2] or 0,
                "total_pnl": row[3] or 0,
                "avg_pnl": row[4] or 0,
                "max_profit": row[5] or 0,
                "max_loss": row[6] or 0,
            }


# 全局实例
trade_recorder = TradeRecorder()
