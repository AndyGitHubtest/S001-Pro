"""
S001-Pro Monitor 配置管理
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    
    # 安全
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24小时
    
    # 数据库 (服务器路径)
    TRADES_DB_PATH: str = "/home/ubuntu/strategies/S001-Pro/data/trades.db"
    KLINES_DB_PATH: str = "/home/ubuntu/strategies/S001-Pro/data/klines.db"
    MONITOR_DB_PATH: str = "/home/ubuntu/strategies/S001-Pro/monitor/backend/data/monitor.db"
    
    # 管理员
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"
    
    # Binance API (只读)
    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    
    # 服务器
    HOST: str = "0.0.0.0"
    PORT: int = 3000
    DEBUG: bool = True
    
    # 缓存
    CACHE_TTL: int = 5  # 5秒
    
    # 日志
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
