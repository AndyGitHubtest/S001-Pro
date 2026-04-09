"""
Immutable Store - 不可变数据仓库
SQLite封装，保证数据只追加、不修改、可追溯
"""

import json
import sqlite3
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime


class ImmutableStore:
    """
    不可变数据存储
    
    核心原则:
    1. 只INSERT，不UPDATE/DELETE
    2. 每条记录有唯一ID和创建时间
    3. 使用sequence_id标记批次
    4. 通过视图获取最新状态
    
    使用场景:
    - M1-M5所有模块输出 (永久保存)
    - 成交记录 (不可篡改)
    - 审计日志 (全链路追溯)
    - 最终配置 (M5输出)
    
    表结构:
    - m1_raw_klines: 原始K线数据
    - m2_filtered_symbols: 过滤后的币种
    - m3_scored_pairs: 配对评分结果
    - m4_optimized_pairs: 参数优化结果
    - m5_trade_configs: 最终交易配置
    - runtime_positions: 运行时持仓 (INSERT新状态，不UPDATE)
    - runtime_orders: 订单记录
    - module_status: 模块执行状态
    """
    
    def __init__(self, db_path: str, init_schema: bool = True):
        """
        初始化不可变存储
        
        Args:
            db_path: 数据库文件路径
            init_schema: 是否初始化Schema
        """
        self.db_path = Path(db_path)
        self.logger = logging.getLogger("ImmutableStore")
        
        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化锁
        self._init_lock = threading.Lock()
        
        # 序列号计数器 (每个session独立)
        self._sequence_counters: Dict[str, int] = {}
        self._seq_lock = threading.Lock()
        
        if init_schema:
            self._init_database()
        
        self.logger.info(f"ImmutableStore initialized: {db_path}")
    
    def _init_database(self):
        """初始化数据库Schema"""
        with self._init_lock:
            schema_path = Path(__file__).parent.parent / "schema" / "init.sql"
            
            if not schema_path.exists():
                self.logger.warning(f"Schema file not found: {schema_path}")
                return
            
            # 检查是否已初始化
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='system_config'"
            )
            if cursor.fetchone():
                conn.close()
                return
            conn.close()
            
            # 执行初始化脚本
            with open(schema_path, 'r') as f:
                schema = f.read()
            
            conn = sqlite3.connect(str(self.db_path))
            conn.executescript(schema)
            conn.close()
            self.logger.info("Database schema initialized (immutable mode)")
    
    def _get_next_sequence(self, session_id: str) -> int:
        """获取下一个序列号"""
        with self._seq_lock:
            self._sequence_counters[session_id] = self._sequence_counters.get(session_id, 0) + 1
            return self._sequence_counters[session_id]
    
    @contextmanager
    def get_reader(self):
        """获取只读连接"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    @contextmanager
    def get_writer(self):
        """获取写入连接 (WAL模式)"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f"Write error: {e}")
            raise
        finally:
            conn.close()
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 不可变写入接口 (只INSERT)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def append_m3_pairs(self, session_id: str, pairs: List[Dict]) -> int:
        """
        追加M3配对评分结果 (不可变)
        
        Args:
            session_id: 会话ID
            pairs: 配对列表
            
        Returns:
            int: 写入数量
        """
        sequence_id = self._get_next_sequence(session_id)
        
        with self.get_writer() as conn:
            for pair in pairs:
                conn.execute("""
                    INSERT INTO m3_scored_pairs 
                    (sequence_id, session_id, symbol_a, symbol_b, timeframe,
                     score, correlation, coint_pvalue, half_life, zscore_range,
                     status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (
                    sequence_id,
                    session_id,
                    pair.get('symbol_a'),
                    pair.get('symbol_b'),
                    pair.get('timeframe', '5m'),
                    pair.get('score'),
                    pair.get('correlation'),
                    pair.get('coint_pvalue'),
                    pair.get('half_life'),
                    pair.get('zscore_range'),
                    pair.get('status', 'pending')
                ))
        
        self.logger.debug(f"Appended {len(pairs)} M3 pairs (session={session_id}, seq={sequence_id})")
        return len(pairs)
    
    def append_m4_optimized(self, session_id: str, pairs: List[Dict]) -> int:
        """追加M4优化结果"""
        sequence_id = self._get_next_sequence(session_id)
        
        with self.get_writer() as conn:
            for pair in pairs:
                conn.execute("""
                    INSERT INTO m4_optimized_pairs
                    (sequence_id, session_id, symbol_a, symbol_b, timeframe,
                     z_entry, z_exit, z_stop, beta,
                     is_pf, is_dd, is_n, os_pf, os_dd, os_n,
                     final_score, selected, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (
                    sequence_id, session_id,
                    pair.get('symbol_a'), pair.get('symbol_b'), pair.get('timeframe'),
                    pair.get('z_entry'), pair.get('z_exit'), pair.get('z_stop'),
                    pair.get('beta', 1.0),
                    pair.get('is_pf'), pair.get('is_dd'), pair.get('is_n'),
                    pair.get('os_pf'), pair.get('os_dd'), pair.get('os_n'),
                    pair.get('final_score'), pair.get('selected', 0)
                ))
        
        return len(pairs)
    
    def append_m5_configs(self, session_id: str, configs: List[Dict]) -> int:
        """追加M5配置 (带激活时间戳)"""
        sequence_id = self._get_next_sequence(session_id)
        
        with self.get_writer() as conn:
            for config in configs:
                pair_key = config.get('pair_key') or f"{config['symbol_a']}_{config['symbol_b']}"
                
                # 禁用旧的配置 (通过插入新记录标记旧记录为disabled)
                # 实际上我们保留所有历史，用视图筛选enabled=1的最新配置
                conn.execute("""
                    INSERT INTO m5_trade_configs
                    (session_id, pair_key, symbol_a, symbol_b, timeframe,
                     config, z_entry, z_exit, z_stop, max_position_value,
                     enabled, activated_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """, (
                    session_id, pair_key,
                    config.get('symbol_a'), config.get('symbol_b'), config.get('timeframe'),
                    json.dumps(config),
                    config.get('z_entry'), config.get('z_exit'), config.get('z_stop'),
                    config.get('max_position_value', 0),
                    config.get('enabled', 1)
                ))
        
        return len(configs)
    
    def append_position_state(self, position: Dict) -> int:
        """
        追加持仓状态 (不UPDATE，每次状态变化INSERT新记录)
        
        Args:
            position: 持仓数据
            
        Returns:
            int: 新记录ID
        """
        with self.get_writer() as conn:
            cursor = conn.execute("""
                INSERT INTO runtime_positions
                (pair_key, symbol_a, symbol_b, state, direction, entry_z,
                 position_size_pct, scale_in_layer, scale_out_layer,
                 entry_price_a, entry_price_b, current_price_a, current_price_b,
                 unrealized_pnl, pending_orders,
                 scale_in_fail_count, scale_out_fail_count,
                 scale_in_cool_until, scale_out_cool_until,
                 entry_time, last_update_time, last_signal_bar, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                position.get('pair_key'),
                position.get('symbol_a'), position.get('symbol_b'),
                position.get('state', 'IDLE'),
                position.get('direction', 0),
                position.get('entry_z', 0),
                position.get('position_size_pct', 0),
                position.get('scale_in_layer', 0),
                position.get('scale_out_layer', 0),
                position.get('entry_price_a'), position.get('entry_price_b'),
                position.get('current_price_a'), position.get('current_price_b'),
                position.get('unrealized_pnl', 0),
                json.dumps(position.get('pending_orders', {})),
                position.get('scale_in_fail_count', 0),
                position.get('scale_out_fail_count', 0),
                position.get('scale_in_cool_until', 0),
                position.get('scale_out_cool_until', 0),
                position.get('entry_time'),
                position.get('last_update_time', 0),
                position.get('last_signal_bar', 0)
            ))
            
            return cursor.lastrowid
    
    def append_order(self, order: Dict) -> int:
        """追加订单记录"""
        with self.get_writer() as conn:
            cursor = conn.execute("""
                INSERT INTO runtime_orders
                (order_id, pair_key, symbol, side, order_type, qty, price,
                 status, filled_qty, avg_price, error_msg, reduce_only, post_only, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                order.get('order_id'),
                order.get('pair_key'),
                order.get('symbol'),
                order.get('side'),
                order.get('order_type'),
                order.get('qty'),
                order.get('price'),
                order.get('status', 'pending'),
                order.get('filled_qty', 0),
                order.get('avg_price'),
                order.get('error_msg'),
                order.get('reduce_only', 0),
                order.get('post_only', 0)
            ))
            return cursor.lastrowid
    
    def append_module_status(self, module_name: str, session_id: str, 
                            status: str, message: str = "", progress: int = 0):
        """追加模块状态"""
        with self.get_writer() as conn:
            conn.execute("""
                INSERT INTO module_status
                (module_name, session_id, status, progress_pct, message, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            """, (module_name, session_id, status, progress, message))
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 查询接口 (只读，通过视图获取最新状态)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def get_latest_m3_pairs(self, session_id: str, timeframe: str = None) -> List[Dict]:
        """获取M3最新配对 (使用视图)"""
        with self.get_reader() as conn:
            if timeframe:
                cursor = conn.execute("""
                    SELECT * FROM m3_scored_pairs
                    WHERE session_id = ? AND timeframe = ?
                    ORDER BY sequence_id DESC, score DESC
                """, (session_id, timeframe))
            else:
                cursor = conn.execute("""
                    SELECT * FROM m3_scored_pairs
                    WHERE session_id = ?
                    ORDER BY sequence_id DESC, score DESC
                """, (session_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_latest_m4_optimized(self, session_id: str, selected_only: bool = True) -> List[Dict]:
        """获取M4最新优化结果"""
        with self.get_reader() as conn:
            if selected_only:
                cursor = conn.execute("""
                    SELECT * FROM m4_optimized_pairs
                    WHERE session_id = ? AND selected = 1
                    ORDER BY sequence_id DESC, final_score DESC
                """, (session_id,))
            else:
                cursor = conn.execute("""
                    SELECT * FROM m4_optimized_pairs
                    WHERE session_id = ?
                    ORDER BY sequence_id DESC, final_score DESC
                """, (session_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_enabled_configs(self) -> List[Dict]:
        """获取当前启用的配置 (最新批次)"""
        with self.get_reader() as conn:
            cursor = conn.execute("""
                SELECT * FROM m5_trade_configs
                WHERE enabled = 1
                AND session_id = (
                    SELECT MAX(session_id) FROM m5_trade_configs
                )
                ORDER BY created_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_position_history(self, pair_key: str, limit: int = 100) -> List[Dict]:
        """获取持仓历史 (不可变存储的优势)"""
        with self.get_reader() as conn:
            cursor = conn.execute("""
                SELECT * FROM runtime_positions
                WHERE pair_key = ?
                ORDER BY updated_at DESC
                LIMIT ?
            """, (pair_key, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_latest_position(self, pair_key: str) -> Optional[Dict]:
        """获取最新持仓状态"""
        with self.get_reader() as conn:
            cursor = conn.execute("""
                SELECT * FROM runtime_positions
                WHERE pair_key = ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (pair_key,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 统计和工具
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def get_stats(self) -> Dict[str, Any]:
        """获取存储统计"""
        stats = {}
        
        with self.get_reader() as conn:
            tables = ['m3_scored_pairs', 'm4_optimized_pairs', 'm5_trade_configs',
                     'runtime_positions', 'runtime_orders', 'module_status']
            
            for table in tables:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[table] = cursor.fetchone()[0]
                except:
                    stats[table] = 0
            
            # 数据库大小
            cursor = conn.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor = conn.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            stats["size_mb"] = round(page_count * page_size / (1024 * 1024), 2)
        
        return stats
    
    def vacuum(self):
        """执行VACUUM优化 (归档后执行)"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("VACUUM")
        self.logger.info("Database vacuum completed")
