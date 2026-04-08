"""
模块一：数据源与清洗模块 (Data Engine) - P0 LOCKED

数据流转:
  Input:  data/klines.db (SQLite)
  Output 1: market_stats 字典 -> 供模块二 (Initial Filter) 筛选
  Output 2: Hot Pool 内存字典 -> 供模块三/四计算

子模块划分:
  - ConnectionManager: 数据库连接管理
  - SymbolManager: 币种列表管理  
  - MarketStatsLoader: 市场统计加载
  - HotPoolBuilder: Hot Pool构建
  - HistoricalLoader: 历史数据加载
  - BatchLoader: 批量数据加载

文档规范: docs/module_1_data_engine.md
"""

import sqlite3
import numpy as np
import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger("DataEngine")


# ═══════════════════════════════════════════════════
# 子模块 1: 数据库连接管理
# ═══════════════════════════════════════════════════

class ConnectionManager:
    """数据库连接管理器 (修复CRIT-006: 添加错误处理)"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        self._connect()
    
    def _connect(self):
        """建立数据库连接 (带错误处理)"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self._init_connection()
            logger.info(f"DataEngine: connected to {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"DataEngine: failed to connect to {self.db_path}: {e}")
            self.conn = None
            raise
    
    def _init_connection(self):
        """初始化连接参数 (WAL模式)"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA cache_size=-128000;")  # 500MB cache
        except sqlite3.Error as e:
            logger.warning(f"DataEngine: failed to set PRAGMA: {e}")
    
    def execute(self, sql: str, params=None):
        """执行SQL (带错误处理)"""
        if not self.conn:
            raise sqlite3.Error("Database not connected")
        try:
            cursor = self.conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            return cursor
        except sqlite3.Error as e:
            logger.error(f"DataEngine: SQL execution failed: {sql[:50]}... Error: {e}")
            raise
    
    def close(self):
        """关闭连接"""
        if self.conn:
            try:
                self.conn.close()
                logger.info("DataEngine: connection closed")
            except sqlite3.Error as e:
                logger.warning(f"DataEngine: error closing connection: {e}")
            finally:
                self.conn = None


# ═══════════════════════════════════════════════════
# 子模块 2: 币种列表管理
# ═══════════════════════════════════════════════════

class SymbolManager:
    """币种列表管理器 (修复CRIT-006: 添加错误处理)"""
    
    def __init__(self, conn: ConnectionManager):
        self.conn = conn
    
    def get_all(self, interval: str = "1m") -> List[str]:
        """获取全部币种 (带错误处理)"""
        try:
            cursor = self.conn.execute(
                "SELECT DISTINCT symbol FROM klines WHERE interval = ? ORDER BY symbol",
                (interval,)
            )
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"DataEngine.SymbolManager: failed to get symbols: {e}")
            return []


# ═══════════════════════════════════════════════════
# 子模块 3: 市场统计加载
# ═══════════════════════════════════════════════════

class MarketStatsLoader:
    """市场统计加载器 (修复CRIT-006: 添加错误处理)"""
    
    def __init__(self, conn: ConnectionManager):
        self.conn = conn
    
    def load(self, min_vol: float = 2_000_000) -> Dict[str, Dict]:
        """
        加载市场统计数据 (带错误处理)
        
        Args:
            min_vol: 最小24h成交量门槛 (默认200万USDT，修复MEDIUM-5: 文档对齐)
        
        Returns:
            {symbol: {vol_24h_usdt, high_24h, low_24h, close, kline_count, atr_14, kurtosis}}
        """
        try:
            # 检查表是否存在
            cursor = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='market_stats'"
            )
            if not cursor.fetchone():
                logger.warning("DataEngine.MarketStats: table not found")
                return {}
            
            sql = (
                "SELECT symbol, vol_24h_usdt, high_24h, low_24h, close, "
                "kline_count, COALESCE(atr_14, 0) as atr_14, "
                "COALESCE(kurtosis, 0) as kurtosis, COALESCE(first_ts, 0) as first_ts "
                "FROM market_stats"
            )
            cursor = self.conn.execute(sql)
            rows = cursor.fetchall()
            
            stats: Dict[str, Dict] = {}
            for row in rows:
                try:
                    sym = row[0]
                    vol = row[1] or 0
                    
                    if vol < min_vol:
                        continue
                    
                    stats[sym] = {
                        "vol_24h_usdt": float(vol),
                        "high_24h": float(row[2] or 0),
                        "low_24h": float(row[3] or 0),
                        "close": float(row[4] or 0),
                        "kline_count": int(row[5] or 0),
                        "atr_14": float(row[6] or 0),
                        "kurtosis": float(row[7] or 0),
                        "first_ts": int(row[8] or 0),
                    }
                except (ValueError, TypeError) as e:
                    logger.warning(f"DataEngine.MarketStats: error parsing row for {row[0]}: {e}")
                    continue
            
            logger.info(f"DataEngine.MarketStats: loaded {len(stats)} symbols")
            return stats
        except sqlite3.Error as e:
            logger.error(f"DataEngine.MarketStats: failed to load stats: {e}")
            return {}


# ═══════════════════════════════════════════════════
# 子模块 4: Hot Pool 构建
# ═══════════════════════════════════════════════════

class HotPoolBuilder:
    """Hot Pool 构建器"""
    
    def __init__(self, conn: ConnectionManager):
        self.conn = conn
    
    def build(self, symbols: List[str], limit: int = 5000) -> Dict[str, Dict]:
        """
        构建内存热池
        
        Args:
            symbols: 币种列表
            limit: 每个币种加载K线数 (默认5000根)
        
        Returns:
            {symbol: {ts, close, log_close, volume, high, low, zero_vol_mask}}
        """
        if not symbols:
            return {}
        
        sql = (
            "SELECT ts, close, volume, high, low "
            "FROM klines "
            "WHERE symbol = ? AND interval = '1m' "
            "ORDER BY ts DESC LIMIT ?"
        )
        
        hot_pool: Dict[str, Dict] = {}
        
        for sym in symbols:
            cursor = self.conn.execute(sql, (sym, limit))
            rows = cursor.fetchall()
            
            if len(rows) < 10:
                continue
            
            rows.reverse()  # 时间正序
            
            # 数据清洗
            ts_list, close_list, vol_list, high_list, low_list = [], [], [], [], []
            
            for dr in rows:
                if dr[1] is not None and dr[1] <= 0:
                    continue
                if dr[2] is not None and dr[2] < 0:
                    continue
                
                ts_list.append(dr[0])
                close_list.append(dr[1])
                vol_list.append(dr[2] if dr[2] is not None else 0)
                high_list.append(dr[3] if dr[3] is not None else dr[1])
                low_list.append(dr[4] if dr[4] is not None else dr[1])
            
            if len(close_list) < 10:
                continue
            
            # 转numpy
            close = np.array(close_list, dtype=np.float32)
            volume = np.array(vol_list, dtype=np.float32)
            high = np.array(high_list, dtype=np.float32)
            low = np.array(low_list, dtype=np.float32)
            ts = np.array(ts_list, dtype=np.int64)
            
            # Mask & NaN处理
            zero_vol_mask = (volume == 0)
            close = self._fill_nan(close)
            high = self._fill_nan(high)
            low = self._fill_nan(low)
            volume = self._fill_nan(volume, fill_value=0.0)
            
            hot_pool[sym] = {
                "ts": ts,
                "close": close,
                "log_close": np.log(close),
                "volume": volume,
                "high": high,
                "low": low,
                "zero_vol_mask": zero_vol_mask,
            }
        
        logger.info(f"DataEngine.HotPool: built for {len(hot_pool)} symbols")
        return hot_pool
    
    def _fill_nan(self, arr: np.ndarray, fill_value=None) -> np.ndarray:
        """前向填充NaN"""
        first_valid = 0
        for i in range(len(arr)):
            if not np.isnan(arr[i]):
                first_valid = i
                break
        
        if first_valid > 0:
            arr = arr[first_valid:]
        
        for i in range(1, len(arr)):
            if np.isnan(arr[i]):
                arr[i] = arr[i-1]
        
        if fill_value is not None:
            arr = np.nan_to_num(arr, nan=fill_value)
        else:
            arr = np.nan_to_num(arr, nan=arr[0] if len(arr) > 0 else 0)
        
        return arr


# ═══════════════════════════════════════════════════
# 子模块 5: 历史数据加载
# ═══════════════════════════════════════════════════

class HistoricalLoader:
    """历史数据加载器"""
    
    def __init__(self, conn: ConnectionManager):
        self.conn = conn
    
    def load(self, symbol: str, days: int = 90, interval: str = "1m") -> Optional[Dict]:
        """加载指定币种历史数据"""
        cutoff_ts = int((time.time() - days * 86400) * 1000)
        
        sql = (
            "SELECT ts, close, volume, high, low "
            "FROM klines "
            "WHERE symbol = ? AND interval = ? AND ts >= ? "
            "ORDER BY ts ASC"
        )
        
        cursor = self.conn.execute(sql, (symbol, interval, cutoff_ts))
        rows = cursor.fetchall()
        
        if not rows or len(rows) < 100:
            logger.warning(f"DataEngine.Historical: insufficient data for {symbol}")
            return None
        
        return self._process_rows(rows)
    
    def _process_rows(self, rows) -> Optional[Dict]:
        """处理查询结果"""
        close_list, ts_list, vol_list, high_list, low_list = [], [], [], [], []
        
        for row in rows:
            if row[1] is not None and row[1] > 0:
                ts_list.append(row[0])
                close_list.append(row[1])
                vol_list.append(row[2] if row[2] is not None else 0)
                high_list.append(row[3] if row[3] is not None else row[1])
                low_list.append(row[4] if row[4] is not None else row[1])
        
        if len(close_list) < 100:
            return None
        
        close = np.array(close_list, dtype=np.float32)
        close = np.nan_to_num(close, nan=close[0])
        
        return {
            "ts": np.array(ts_list, dtype=np.int64),
            "close": close,
            "log_close": np.log(close),
            "volume": np.array(vol_list, dtype=np.float32),
            "high": np.array(high_list, dtype=np.float32),
            "low": np.array(low_list, dtype=np.float32),
        }


# ═══════════════════════════════════════════════════
# 子模块 6: 批量数据加载
# ═══════════════════════════════════════════════════

class BatchLoader:
    """批量数据加载器"""
    
    def __init__(self, conn: ConnectionManager):
        self.conn = conn
    
    def load(self, symbols: List[str], days: int = 90, interval: str = "1m") -> Dict[str, Dict]:
        """批量加载多个币种历史数据"""
        if not symbols:
            return {}
        
        limit_per_sym = days * 24 * 60 + 5000
        
        sql = (
            "SELECT ts, close "
            "FROM klines "
            "WHERE symbol = ? AND interval = ? "
            "ORDER BY ts DESC LIMIT ?"
        )
        
        result: Dict[str, Dict] = {}
        loaded = 0
        
        for sym in symbols:
            cursor = self.conn.execute(sql, (sym, interval, limit_per_sym))
            rows = cursor.fetchall()
            
            if len(rows) < 100:
                continue
            
            rows.reverse()
            
            ts_list, close_list = [], []
            for r in rows:
                if r[1] is not None and r[1] > 0:
                    ts_list.append(r[0])
                    close_list.append(r[1])
            
            if len(close_list) < 100:
                continue
            
            close = np.array(close_list, dtype=np.float32)
            close = np.nan_to_num(close, nan=close[0])
            
            result[sym] = {
                "ts": np.array(ts_list, dtype=np.int64),
                "close": close,
                "log_close": np.log(close),
            }
            loaded += 1
        
        logger.info(f"DataEngine.BatchLoader: loaded {loaded}/{len(symbols)} symbols")
        return result


# ═══════════════════════════════════════════════════
# 主类: DataEngine (统一接口)
# ═══════════════════════════════════════════════════

class DataEngine:
    """
    数据引擎主类
    整合所有子模块，提供统一接口
    修复CRIT-007: 支持配置化数据库路径，移除硬编码符号链接
    """
    
    DEFAULT_DB_PATH = "data/klines.db"
    
    def __init__(self, db_path: str = None):
        """
        初始化数据引擎
        
        Args:
            db_path: SQLite数据库路径 (默认从配置读取或使用DEFAULT_DB_PATH)
        """
        # 修复CRIT-007: 路径解析逻辑
        if db_path is None:
            db_path = self._resolve_db_path()
        
        # 验证路径不是符号链接指向不存在的位置
        import os
        if os.path.islink(db_path):
            real_path = os.path.realpath(db_path)
            if not os.path.exists(real_path):
                logger.error(f"DataEngine: database symlink broken: {db_path} -> {real_path}")
                # 删除无效的符号链接
                try:
                    os.remove(db_path)
                    logger.info(f"DataEngine: removed broken symlink {db_path}")
                except OSError:
                    pass
                # 使用默认路径
                db_path = self.DEFAULT_DB_PATH
        
        # 初始化连接
        self._conn = ConnectionManager(db_path)
        
        # 初始化各子模块
        self._symbols = SymbolManager(self._conn)
        self._market_stats = MarketStatsLoader(self._conn)
        self._hot_pool = HotPoolBuilder(self._conn)
        self._historical = HistoricalLoader(self._conn)
        self._batch = BatchLoader(self._conn)
    
    def _resolve_db_path(self) -> str:
        """
        解析数据库路径 (修复CRIT-007)
        优先级: 1) 环境变量 2) 配置文件 3) 默认路径
        """
        import os
        
        # 1. 检查环境变量
        env_path = os.environ.get('S001_DB_PATH')
        if env_path:
            logger.info(f"DataEngine: using db path from environment: {env_path}")
            return env_path
        
        # 2. 检查配置文件
        config_paths = ['data/db.conf', 'config/db.conf']
        for config_path in config_paths:
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#') and '=' in line:
                                key, value = line.split('=', 1)
                                if key.strip() == 'db_path':
                                    path = value.strip()
                                    logger.info(f"DataEngine: using db path from config: {path}")
                                    return path
                except Exception as e:
                    logger.warning(f"DataEngine: error reading config {config_path}: {e}")
        
        # 3. 使用默认路径
        logger.info(f"DataEngine: using default db path: {self.DEFAULT_DB_PATH}")
        return self.DEFAULT_DB_PATH
    
    # ═══════════════════════════════════════════════
    # 公开接口
    # ═══════════════════════════════════════════════
    
    def get_all_symbols(self, interval: str = "1m") -> List[str]:
        """获取全部币种列表"""
        return self._symbols.get_all(interval)
    
    def load_market_stats(self, min_vol: float = 5_000_000) -> Dict[str, Dict]:
        """加载市场统计数据"""
        return self._market_stats.load(min_vol)
    
    def build_hot_pool(self, symbols: List[str], limit: int = 5000) -> Dict[str, Dict]:
        """构建Hot Pool"""
        return self._hot_pool.build(symbols, limit)
    
    def get_historical_data(self, symbol: str, days: int = 90, interval: str = "1m") -> Optional[Dict]:
        """获取单个币种历史数据"""
        return self._historical.load(symbol, days, interval)
    
    def batch_load_historical(self, symbols: List[str], days: int = 90, interval: str = "1m") -> Dict[str, Dict]:
        """批量加载历史数据"""
        return self._batch.load(symbols, days, interval)
    
    def close(self):
        """关闭数据库连接"""
        self._conn.close()
        logger.info("DataEngine: closed")
