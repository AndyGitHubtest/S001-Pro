"""
数据库连接管理
只读访问S001-Pro数据
"""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
from pathlib import Path
import logging

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 数据库文件路径 (从环境变量读取，默认本地开发路径)
# trades.db - 交易记录 (S001-Pro生成)
# klines.db - K线数据 (币安下载)
S001_BASE_PATH = Path(os.getenv("S001_BASE_PATH", "/Users/andy/S001-Pro/data"))
TRADES_DB_PATH = Path(os.getenv("TRADES_DB_PATH", S001_BASE_PATH / "trades.db"))
KLINES_DB_PATH = Path(os.getenv("KLINES_DB_PATH", S001_BASE_PATH / "klines.db"))

# 确保目录存在 (只创建监控数据库目录)
MONITOR_DATA_PATH = Path(os.getenv("MONITOR_DATA_PATH", "/home/ubuntu/S001-Pro/monitor/backend/data"))
MONITOR_DATA_PATH.mkdir(parents=True, exist_ok=True)

# S001-Pro Trades数据库 (只读) - 主要数据源
engine_trades = create_engine(
    f"sqlite:///{TRADES_DB_PATH}",
    connect_args={
        "check_same_thread": False,
    },
    poolclass=StaticPool,
    echo=settings.DEBUG
)

# S001-Pro Klines数据库 (只读)
engine_klines = create_engine(
    f"sqlite:///{KLINES_DB_PATH}",
    connect_args={
        "check_same_thread": False,
    },
    poolclass=StaticPool,
    echo=False
)

# 监控面板数据库 (读写) - 存储用户、心跳等
MONITOR_DB_PATH = Path(os.getenv("MONITOR_DB_PATH", settings.MONITOR_DB_PATH))
MONITOR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine_monitor = create_engine(
    f"sqlite:///{MONITOR_DB_PATH}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

SessionLocalTrades = sessionmaker(autocommit=False, autoflush=False, bind=engine_trades)
SessionLocalKlines = sessionmaker(autocommit=False, autoflush=False, bind=engine_klines)
SessionLocalMonitor = sessionmaker(autocommit=False, autoflush=False, bind=engine_monitor)


@contextmanager
def get_trades_db():
    """获取Trades数据库会话 (只读) - 交易记录、持仓、日志"""
    db = SessionLocalTrades()
    try:
        db.execute(text("PRAGMA query_only = ON"))
        yield db
    finally:
        db.close()


@contextmanager
def get_klines_db():
    """获取Klines数据库会话 (只读) - K线数据"""
    db = SessionLocalKlines()
    try:
        db.execute(text("PRAGMA query_only = ON"))
        yield db
    finally:
        db.close()


@contextmanager
def get_monitor_db():
    """获取监控数据库会话 (读写)"""
    db = SessionLocalMonitor()
    try:
        yield db
    finally:
        db.close()


def init_monitor_db():
    """初始化监控数据库表"""
    from sqlalchemy import Column, Integer, String, DateTime, Float, inspect
    from sqlalchemy.ext.declarative import declarative_base
    
    Base = declarative_base()
    
    class User(Base):
        __tablename__ = "users"
        
        id = Column(Integer, primary_key=True, index=True)
        username = Column(String(50), unique=True, index=True)
        password_hash = Column(String(100))
        role = Column(String(20), default="viewer")  # admin, viewer
        created_at = Column(DateTime)
    
    class Heartbeat(Base):
        __tablename__ = "heartbeats"
        
        id = Column(Integer, primary_key=True, index=True)
        service = Column(String(50))
        last_seen = Column(DateTime)
        status = Column(String(20))
    
    class ShareLink(Base):
        """分享链接表 - 用于分享面板给好友查看"""
        __tablename__ = "share_links"
        
        id = Column(Integer, primary_key=True, index=True)
        token = Column(String(50), unique=True, index=True)  # 分享令牌
        name = Column(String(100))  # 分享名称（方便管理）
        created_by = Column(String(50))  # 创建者用户名
        created_at = Column(DateTime)  # 创建时间
        expires_at = Column(DateTime)  # 过期时间（NULL表示永久）
        password_hash = Column(String(100), nullable=True)  # 可选密码
        is_active = Column(Integer, default=1)  # 0=禁用, 1=启用
        view_count = Column(Integer, default=0)  # 访问次数
        last_viewed_at = Column(DateTime, nullable=True)  # 最后访问时间
        permissions = Column(String(20), default="readonly")  # 权限级别
    
    # 检查表是否已存在，避免多进程冲突
    inspector = inspect(engine_monitor)
    existing_tables = inspector.get_table_names()
    
    try:
        # 只创建不存在的表
        Base.metadata.create_all(bind=engine_monitor, checkfirst=True)
        logger.info("Monitor database initialized")
    except Exception as e:
        # 表已存在时会抛出异常，忽略
        if "already exists" in str(e):
            logger.info("Monitor tables already exist")
        else:
            logger.warning(f"Database init warning: {e}")


# 兼容性别名 (旧代码使用get_s001_db)
get_s001_db = get_trades_db
