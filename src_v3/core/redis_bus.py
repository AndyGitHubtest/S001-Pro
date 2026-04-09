"""
Redis Bus - 实时通信总线
提供Pub/Sub、状态缓存、流式日志功能
"""

import json
import logging
import threading
import time
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime

try:
    import redis
except ImportError:
    raise ImportError("Redis not installed. Run: pip install redis")


class RedisBus:
    """
    Redis实时通信总线
    
    职责:
    1. 模块间Pub/Sub通信
    2. 实时状态缓存 (价格、Z-score、持仓)
    3. 流式数据记录 (成交、错误)
    4. 临时数据存储 (有过期时间)
    
    Key命名规范:
    - s001:channel:{module}:output  - 模块输出通道
    - s001:state:{type}             - 实时状态Hash
    - s001:cache:{type}:{id}        - 临时缓存 (有TTL)
    - s001:stream:{type}            - 流式数据
    
    Example:
        bus = RedisBus()
        
        # 发布模块输出
        bus.publish_output("M3", {"pairs": [...]})
        
        # 订阅模块输出
        bus.subscribe_output("M3", callback=lambda data: print(data))
        
        # 更新实时价格
        bus.update_price("BTC/USDT", 50000.0)
        
        # 读取实时价格
        price = bus.get_price("BTC/USDT")
    """
    
    # Key前缀
    PREFIX = "s001"
    
    def __init__(self, host: str = "localhost", port: int = 6379, 
                 db: int = 0, password: Optional[str] = None,
                 decode_responses: bool = True):
        """
        初始化Redis连接
        
        Args:
            host: Redis主机
            port: Redis端口
            db: 数据库编号
            password: 密码
            decode_responses: 自动解码响应
        """
        self.logger = logging.getLogger("RedisBus")
        
        try:
            self.client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=decode_responses,
                socket_connect_timeout=5,
                socket_timeout=5,
                health_check_interval=30
            )
            self.client.ping()
            self.logger.info(f"Redis connected: {host}:{port}/{db}")
        except redis.ConnectionError as e:
            self.logger.error(f"Redis connection failed: {e}")
            raise
        
        # 订阅管理
        self._pubsub = None
        self._subscribers: Dict[str, List[Callable]] = {}
        self._sub_thread = None
        self._sub_lock = threading.Lock()
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 模块通信 (Pub/Sub)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def publish_output(self, module: str, data: Dict[str, Any]) -> int:
        """
        发布模块输出到Redis
        
        Args:
            module: 模块名称 (M1, M2, ...)
            data: 输出数据
            
        Returns:
            int: 接收者数量
        """
        channel = f"{self.PREFIX}:channel:{module}:output"
        message = {
            "module": module,
            "timestamp": datetime.now().timestamp(),
            "data": data
        }
        
        try:
            count = self.client.publish(channel, json.dumps(message))
            self.logger.debug(f"Published to {channel}, receivers: {count}")
            return count
        except Exception as e:
            self.logger.error(f"Publish failed: {e}")
            return 0
    
    def subscribe_output(self, module: str, callback: Callable[[Dict], None]) -> bool:
        """
        订阅模块输出
        
        Args:
            module: 模块名称
            callback: 回调函数，接收Dict参数
            
        Returns:
            bool: 订阅是否成功
        """
        channel = f"{self.PREFIX}:channel:{module}:output"
        
        with self._sub_lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = []
            self._subscribers[channel].append(callback)
        
        # 启动订阅线程 (如果未启动)
        self._ensure_sub_thread()
        
        self.logger.debug(f"Subscribed to {channel}")
        return True
    
    def _ensure_sub_thread(self):
        """确保订阅线程运行"""
        if self._sub_thread is None or not self._sub_thread.is_alive():
            self._pubsub = self.client.pubsub()
            self._sub_thread = threading.Thread(target=self._listen_subscriptions, daemon=True)
            self._sub_thread.start()
    
    def _listen_subscriptions(self):
        """监听订阅消息"""
        while True:
            try:
                # 动态订阅所有频道
                with self._sub_lock:
                    channels = list(self._subscribers.keys())
                
                if channels:
                    for channel in channels:
                        self._pubsub.subscribe(channel)
                    
                    for message in self._pubsub.listen():
                        if message["type"] == "message":
                            channel = message["channel"]
                            data = json.loads(message["data"])
                            
                            # 调用该频道的所有回调
                            with self._sub_lock:
                                callbacks = self._subscribers.get(channel, []).copy()
                            
                            for callback in callbacks:
                                try:
                                    callback(data)
                                except Exception as e:
                                    self.logger.error(f"Callback error: {e}")
                else:
                    time.sleep(0.1)
                    
            except Exception as e:
                self.logger.error(f"Subscription error: {e}")
                time.sleep(1)
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 实时状态 (Hash)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def update_price(self, symbol: str, price: float, ttl: int = 60):
        """
        更新实时价格
        
        Args:
            symbol: 交易对
            price: 价格
            ttl: 过期时间(秒)
        """
        key = f"{self.PREFIX}:state:prices"
        self.client.hset(key, symbol, str(price))
        self.client.expire(key, ttl)
    
    def get_price(self, symbol: str) -> Optional[float]:
        """
        获取实时价格
        
        Args:
            symbol: 交易对
            
        Returns:
            float or None: 价格
        """
        key = f"{self.PREFIX}:state:prices"
        value = self.client.hget(key, symbol)
        return float(value) if value else None
    
    def get_all_prices(self) -> Dict[str, float]:
        """
        获取所有实时价格
        
        Returns:
            Dict: {symbol: price}
        """
        key = f"{self.PREFIX}:state:prices"
        data = self.client.hgetall(key)
        return {k: float(v) for k, v in data.items()}
    
    def update_zscore(self, pair_key: str, zscore: float, ttl: int = 300):
        """
        更新实时Z-score
        
        Args:
            pair_key: 配对键
            zscore: Z-score值
            ttl: 过期时间
        """
        key = f"{self.PREFIX}:state:zscores"
        self.client.hset(key, pair_key, str(zscore))
        self.client.expire(key, ttl)
    
    def get_zscore(self, pair_key: str) -> Optional[float]:
        """获取实时Z-score"""
        key = f"{self.PREFIX}:state:zscores"
        value = self.client.hget(key, pair_key)
        return float(value) if value else None
    
    def update_position(self, pair_key: str, position: Dict, ttl: int = 3600):
        """
        更新持仓状态
        
        Args:
            pair_key: 配对键
            position: 持仓数据
            ttl: 过期时间
        """
        key = f"{self.PREFIX}:state:positions"
        self.client.hset(key, pair_key, json.dumps(position))
        self.client.expire(key, ttl)
    
    def get_position(self, pair_key: str) -> Optional[Dict]:
        """获取持仓状态"""
        key = f"{self.PREFIX}:state:positions"
        value = self.client.hget(key, pair_key)
        return json.loads(value) if value else None
    
    def get_all_positions(self) -> Dict[str, Dict]:
        """获取所有持仓"""
        key = f"{self.PREFIX}:state:positions"
        data = self.client.hgetall(key)
        return {k: json.loads(v) for k, v in data.items()}
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 缓存 (String with TTL)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def set_cache(self, cache_type: str, cache_id: str, data: Any, ttl: int = 300):
        """
        设置缓存
        
        Args:
            cache_type: 缓存类型 (klines, stats, module_status)
            cache_id: 缓存ID
            data: 数据
            ttl: 过期时间(秒)
        """
        key = f"{self.PREFIX}:cache:{cache_type}:{cache_id}"
        self.client.setex(key, ttl, json.dumps(data))
    
    def get_cache(self, cache_type: str, cache_id: str) -> Optional[Any]:
        """获取缓存"""
        key = f"{self.PREFIX}:cache:{cache_type}:{cache_id}"
        value = self.client.get(key)
        return json.loads(value) if value else None
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 流式数据 (Stream)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def add_trade_stream(self, trade_data: Dict) -> str:
        """
        添加成交记录到流
        
        Args:
            trade_data: 成交数据
            
        Returns:
            str: 消息ID
        """
        key = f"{self.PREFIX}:stream:trades"
        return self.client.xadd(key, {"data": json.dumps(trade_data)})
    
    def add_error_stream(self, error_data: Dict) -> str:
        """添加错误记录到流"""
        key = f"{self.PREFIX}:stream:errors"
        return self.client.xadd(key, {"data": json.dumps(error_data)})
    
    def read_stream(self, stream_type: str, count: int = 100) -> List[Dict]:
        """
        读取流数据
        
        Args:
            stream_type: trades/errors
            count: 数量
            
        Returns:
            List: 流数据
        """
        key = f"{self.PREFIX}:stream:{stream_type}"
        messages = self.client.xrevrange(key, count=count)
        
        result = []
        for msg_id, fields in messages:
            if "data" in fields:
                data = json.loads(fields["data"])
                data["_msg_id"] = msg_id
                result.append(data)
        
        return result
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 批量操作和工具
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def pipeline_prices(self, prices: Dict[str, float], ttl: int = 60):
        """
        批量更新价格
        
        Args:
            prices: {symbol: price}
            ttl: 过期时间
        """
        key = f"{self.PREFIX}:state:prices"
        pipe = self.client.pipeline()
        
        for symbol, price in prices.items():
            pipe.hset(key, symbol, str(price))
        
        pipe.expire(key, ttl)
        pipe.execute()
    
    def clear_all(self, confirm: bool = False):
        """
        清空所有s001数据 (危险操作!)
        
        Args:
            confirm: 必须设为True才能执行
        """
        if not confirm:
            self.logger.warning("Set confirm=True to clear all data")
            return
        
        pattern = f"{self.PREFIX}:*"
        keys = self.client.keys(pattern)
        
        if keys:
            self.client.delete(*keys)
            self.logger.info(f"Cleared {len(keys)} keys")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取Redis统计信息"""
        info = self.client.info()
        
        # 统计s001相关的key
        pattern = f"{self.PREFIX}:*"
        keys = self.client.keys(pattern)
        
        by_type = {}
        for key in keys:
            key_type = key.split(":")[1] if ":" in key else "other"
            by_type[key_type] = by_type.get(key_type, 0) + 1
        
        return {
            "connected": True,
            "used_memory_mb": round(info.get("used_memory", 0) / (1024 * 1024), 2),
            "total_keys": len(keys),
            "keys_by_type": by_type,
            "uptime_seconds": info.get("uptime_in_seconds", 0)
        }
    
    def close(self):
        """关闭连接"""
        if self._pubsub:
            self._pubsub.close()
        self.client.close()
        self.logger.info("Redis connection closed")


# 全局实例
_global_redis_bus: Optional[RedisBus] = None
_global_lock = threading.Lock()


def get_redis_bus(host: str = "localhost", port: int = 6379, 
                  **kwargs) -> RedisBus:
    """获取全局RedisBus实例"""
    global _global_redis_bus
    if _global_redis_bus is None:
        with _global_lock:
            if _global_redis_bus is None:
                _global_redis_bus = RedisBus(host=host, port=port, **kwargs)
    return _global_redis_bus
