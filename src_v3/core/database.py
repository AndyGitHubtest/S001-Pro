"""
数据库管理器 - 读写分离实现
支持SQLite WAL模式，提供并发安全的读写操作
"""

import sqlite3
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


class DatabaseManager:
    """
    数据库管理器
    
    职责:
    1. 管理数据库连接池
    2. 提供读写分离接口
    3. 维护WAL模式配置
    4. 连接生命周期管理
    
    使用示例:
        db = DatabaseManager("/path/to/pipeline.db")
        
        # 只读查询
        with db.get_reader() as conn:
            cursor = conn.execute("SELECT * FROM m3_scored_pairs")
            rows = cursor.fetchall()
        
        # 写入操作
        with db.get_writer() as conn:
            conn.execute("INSERT INTO m3_scored_pairs ...")
    """
    
    def __init__(self, db_path: str, init_schema: bool = True):
        """
        初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径
            init_schema: 是否自动初始化Schema
        """
        self.db_path = Path(db_path)
        self.logger = logging.getLogger("DatabaseManager")
        
        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 连接锁 (防止并发初始化问题)
        self._init_lock = threading.Lock()
        
        # 线程本地存储
        self._local = threading.local()
        
        # 初始化数据库
        if init_schema:
            self._init_database()
        
        self.logger.info(f"DatabaseManager initialized: {db_path}")
    
    def _init_database(self):
        """初始化数据库Schema"""
        with self._init_lock:
            # 检查是否需要初始化
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='system_config'"
            )
            if cursor.fetchone():
                conn.close()
                return
            conn.close()
            
            # 执行初始化脚本
            schema_path = Path(__file__).parent.parent / "schema" / "init.sql"
            if schema_path.exists():
                with open(schema_path, 'r') as f:
                    schema = f.read()
                
                conn = sqlite3.connect(str(self.db_path))
                conn.executescript(schema)
                conn.close()
                self.logger.info("Database schema initialized")
    
    @contextmanager
    def get_reader(self):
        """
        获取只读数据库连接
        
        特性:
        - 支持并发读取 (WAL模式)
        - 自动关闭连接
        - 返回Row对象 (支持列名访问)
        
        Yields:
            sqlite3.Connection: 数据库连接
        """
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        
        try:
            yield conn
        finally:
            conn.close()
    
    @contextmanager
    def get_writer(self):
        """
        获取写入数据库连接
        
        特性:
        - WAL模式支持并发写
        - 自动事务管理 (成功COMMIT/失败ROLLBACK)
        - 超时30秒防止死锁
        
        Yields:
            sqlite3.Connection: 数据库连接
        """
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        
        # 启用WAL模式
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f"Database write error: {e}")
            raise
        finally:
            conn.close()
    
    def execute_read(self, query: str, params: tuple = ()) -> list:
        """
        便捷方法: 执行只读查询
        
        Args:
            query: SQL查询语句
            params: 查询参数
            
        Returns:
            list: 查询结果列表
        """
        with self.get_reader() as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchall()
    
    def execute_write(self, query: str, params: tuple = ()) -> int:
        """
        便捷方法: 执行写入操作
        
        Args:
            query: SQL语句 (INSERT/UPDATE/DELETE)
            params: 语句参数
            
        Returns:
            int: 受影响的行数
        """
        with self.get_writer() as conn:
            cursor = conn.execute(query, params)
            return cursor.rowcount
    
    def get_latest_session(self, module_name: str) -> Optional[str]:
        """
        获取模块最新的session_id
        
        Args:
            module_name: 模块名称 (M1, M2, ...)
            
        Returns:
            str or None: session_id
        """
        with self.get_reader() as conn:
            cursor = conn.execute(
                "SELECT session_id FROM module_status "
                "WHERE module_name = ? ORDER BY created_at DESC LIMIT 1",
                (module_name,)
            )
            row = cursor.fetchone()
            return row["session_id"] if row else None
    
    def get_module_status(self, module_name: str) -> Optional[dict]:
        """
        获取模块最新状态
        
        Args:
            module_name: 模块名称
            
        Returns:
            dict: 状态信息
        """
        with self.get_reader() as conn:
            cursor = conn.execute(
                "SELECT * FROM module_status "
                "WHERE module_name = ? ORDER BY created_at DESC LIMIT 1",
                (module_name,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def vacuum(self):
        """执行数据库VACUUM优化"""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("VACUUM")
        self.logger.info("Database vacuum completed")
    
    def get_stats(self) -> dict:
        """获取数据库统计信息"""
        stats = {}
        
        with self.get_reader() as conn:
            # 表行数统计
            tables = ['m1_raw_klines', 'm2_filtered_symbols', 'm3_scored_pairs',
                     'm4_optimized_pairs', 'm5_trade_configs', 'runtime_positions',
                     'module_status']
            
            for table in tables:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[table] = cursor.fetchone()[0]
                except:
                    stats[table] = 0
            
            # 数据库文件大小
            cursor = conn.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor = conn.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            stats["db_size_mb"] = round(page_count * page_size / (1024 * 1024), 2)
        
        return stats
