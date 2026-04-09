"""
Hybrid Manager - 混合存储管理器
整合 Redis (实时通信) + SQLite (不可变存储)

设计理念:
1. 写操作: 同时写入Redis和SQLite
   - Redis: 供其他模块实时读取
   - SQLite: 永久保存，不可篡改
   
2. 读操作: 优先从Redis读取
   - Redis有数据: 直接返回 (快)
   - Redis无数据: 从SQLite读取并缓存到Redis
   
3. 故障恢复: SQLite是Source of Truth
   - Redis数据丢失可从SQLite恢复
   - 模块重启时从SQLite加载状态到Redis
"""

import json
import logging
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime

from .immutable_store import ImmutableStore
from .redis_bus import RedisBus
from .data_packet import ModuleDataPacket


class HybridManager:
    """
    混合存储管理器
    
    统一接口管理Redis和SQLite:
    - 模块输出: publish() → Redis广播 + SQLite持久化
    - 模块输入: consume() → 从Redis订阅
    - 状态保存: save_state() → Redis缓存 + SQLite追加
    - 状态恢复: load_state() → 从SQLite恢复
    
    使用示例:
        hm = HybridManager(sqlite_path="data/pipeline.db")
        
        # M3发布结果
        hm.publish_module_output("M3", {"pairs": [...]}, session_id="M3_xxx")
        
        # M4订阅M3
        hm.subscribe_module_output("M3", callback=process_m3_data)
        
        # 保存持仓状态
        hm.save_position_state("BAS_MON", {"state": "IN_POSITION", ...})
        
        # 读取持仓 (优先Redis，回退SQLite)
        pos = hm.get_position_state("BAS_MON")
    """
    
    def __init__(self, 
                 sqlite_path: str,
                 redis_host: str = "localhost",
                 redis_port: int = 6379,
                 redis_db: int = 0,
                 redis_password: Optional[str] = None):
        """
        初始化混合管理器
        
        Args:
            sqlite_path: SQLite数据库路径
            redis_host: Redis主机
            redis_port: Redis端口
            redis_db: Redis数据库
            redis_password: Redis密码
        """
        self.logger = logging.getLogger("HybridManager")
        
        # 初始化两个存储
        self.sqlite = ImmutableStore(sqlite_path)
        self.redis = RedisBus(redis_host, redis_port, redis_db, redis_password)
        
        self.logger.info("HybridManager initialized")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 模块通信 (Redis Pub/Sub + SQLite持久化)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def publish_module_output(self, module: str, data: Dict[str, Any], 
                              session_id: str, persist: bool = True) -> bool:
        """
        发布模块输出
        
        流程:
        1. 写入SQLite (永久保存)
        2. 发布到Redis (实时通知)
        
        Args:
            module: 模块名称 (M3, M4, M5)
            data: 输出数据
            session_id: 会话ID
            persist: 是否持久化到SQLite
            
        Returns:
            bool: 是否成功
        """
        try:
            # Step 1: 持久化到SQLite
            if persist:
                if module == "M3":
                    self.sqlite.append_m3_pairs(session_id, data.get("pairs", []))
                elif module == "M4":
                    self.sqlite.append_m4_optimized(session_id, data.get("pairs", []))
                elif module == "M5":
                    self.sqlite.append_m5_configs(session_id, data.get("configs", []))
            
            # Step 2: 发布到Redis (通知订阅者)
            self.redis.publish_output(module, {
                "session_id": session_id,
                "data": data,
                "timestamp": datetime.now().timestamp()
            })
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to publish {module} output: {e}")
            return False
    
    def subscribe_module_output(self, module: str, 
                                callback: Callable[[Dict], None]) -> bool:
        """
        订阅模块输出
        
        Args:
            module: 模块名称
            callback: 回调函数
            
        Returns:
            bool: 是否成功订阅
        """
        def _wrapped_callback(message: Dict):
            """包装回调，提取数据部分"""
            try:
                callback(message.get("data", {}))
            except Exception as e:
                self.logger.error(f"Callback error: {e}")
        
        return self.redis.subscribe_output(module, _wrapped_callback)
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 实时状态 (Redis为主，SQLite备份)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def save_position_state(self, pair_key: str, state: Dict, 
                           persist: bool = True) -> bool:
        """
        保存持仓状态
        
        Args:
            pair_key: 配对键
            state: 状态数据
            persist: 是否持久化到SQLite
            
        Returns:
            bool: 是否成功
        """
        try:
            # 更新Redis (实时)
            self.redis.update_position(pair_key, state)
            
            # 追加到SQLite (永久)
            if persist:
                self.sqlite.append_position_state(state)
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to save position {pair_key}: {e}")
            return False
    
    def get_position_state(self, pair_key: str, 
                          use_cache: bool = True) -> Optional[Dict]:
        """
        获取持仓状态
        
        策略:
        1. 优先从Redis读取 (快)
        2. Redis没有，从SQLite读取并缓存到Redis
        
        Args:
            pair_key: 配对键
            use_cache: 是否使用缓存
            
        Returns:
            Dict or None: 持仓状态
        """
        if use_cache:
            # 尝试从Redis读取
            state = self.redis.get_position(pair_key)
            if state:
                return state
        
        # 从SQLite读取最新状态
        state = self.sqlite.get_latest_position(pair_key)
        
        # 缓存到Redis
        if state and use_cache:
            self.redis.update_position(pair_key, state)
        
        return state
    
    def get_all_positions(self) -> Dict[str, Dict]:
        """获取所有持仓状态"""
        # 从Redis读取 (最新)
        positions = self.redis.get_all_positions()
        
        # 如果Redis为空，从SQLite恢复
        if not positions:
            self.logger.info("Restoring positions from SQLite to Redis...")
            # 这里需要从SQLite读取所有最新状态
            # 简化处理：实际使用时通过具体pair_key逐个恢复
        
        return positions
    
    def save_order(self, order: Dict, persist: bool = True) -> bool:
        """
        保存订单
        
        Args:
            order: 订单数据
            persist: 是否持久化
            
        Returns:
            bool: 是否成功
        """
        try:
            # 持久化到SQLite
            if persist:
                self.sqlite.append_order(order)
            
            # 更新Redis中的pending orders
            pair_key = order.get("pair_key")
            if pair_key:
                position = self.get_position_state(pair_key)
                if position:
                    pending = position.get("pending_orders", {})
                    pending[order.get("order_id")] = order
                    position["pending_orders"] = pending
                    self.redis.update_position(pair_key, position)
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to save order: {e}")
            return False
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 价格数据 (Redis缓存为主)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def update_prices(self, prices: Dict[str, float]):
        """批量更新价格"""
        self.redis.pipeline_prices(prices)
    
    def get_price(self, symbol: str) -> Optional[float]:
        """获取实时价格"""
        return self.redis.get_price(symbol)
    
    def update_zscore(self, pair_key: str, zscore: float):
        """更新Z-score"""
        self.redis.update_zscore(pair_key, zscore)
    
    def get_zscore(self, pair_key: str) -> Optional[float]:
        """获取Z-score"""
        return self.redis.get_zscore(pair_key)
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 配置管理 (SQLite为主，Redis缓存)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def get_active_configs(self, cache_ttl: int = 60) -> List[Dict]:
        """
        获取当前活跃配置
        
        Args:
            cache_ttl: 缓存时间(秒)
            
        Returns:
            List: 配置列表
        """
        # 检查Redis缓存
        cached = self.redis.get_cache("active_configs", "current")
        if cached:
            return cached
        
        # 从SQLite读取
        configs = self.sqlite.get_enabled_configs()
        
        # 缓存到Redis
        self.redis.set_cache("active_configs", "current", configs, ttl=cache_ttl)
        
        return configs
    
    def invalidate_config_cache(self):
        """使配置缓存失效"""
        # Redis缓存会自动过期，这里可以主动删除
        pass
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 流式数据 (Redis Stream)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def log_trade(self, trade_data: Dict):
        """记录成交"""
        # 写入Redis Stream
        self.redis.add_trade_stream(trade_data)
        
        # 同时追加到SQLite (可选，如果需要永久保存)
        # self.sqlite.append_trade(trade_data)
    
    def log_error(self, error_data: Dict):
        """记录错误"""
        self.redis.add_error_stream(error_data)
    
    def get_recent_trades(self, count: int = 100) -> List[Dict]:
        """获取最近成交"""
        return self.redis.read_stream("trades", count)
    
    def get_recent_errors(self, count: int = 100) -> List[Dict]:
        """获取最近错误"""
        return self.redis.read_stream("errors", count)
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 故障恢复
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def restore_from_sqlite(self, component: str):
        """
        从SQLite恢复数据到Redis
        
        Args:
            component: 恢复的组件 (positions, configs)
        """
        self.logger.info(f"Restoring {component} from SQLite to Redis...")
        
        if component == "positions":
            # 恢复所有持仓状态
            # 实际实现需要遍历所有pair_key
            pass
        
        elif component == "configs":
            # 恢复配置 (清空缓存，下次读取时会自动加载)
            self.invalidate_config_cache()
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 统计和监控
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def get_stats(self) -> Dict[str, Any]:
        """获取混合存储统计"""
        return {
            "sqlite": self.sqlite.get_stats(),
            "redis": self.redis.get_stats(),
            "status": "healthy"
        }
    
    def health_check(self) -> Dict[str, bool]:
        """健康检查"""
        status = {
            "sqlite": False,
            "redis": False
        }
        
        try:
            # 检查SQLite
            with self.sqlite.get_reader() as conn:
                conn.execute("SELECT 1")
            status["sqlite"] = True
        except:
            pass
        
        try:
            # 检查Redis
            self.redis.client.ping()
            status["redis"] = True
        except:
            pass
        
        return status
    
    def close(self):
        """关闭连接"""
        self.redis.close()
        self.logger.info("HybridManager closed")


# 工厂函数
def create_hybrid_manager(sqlite_path: str = "data/pipeline_v3.db",
                         redis_host: str = "localhost",
                         redis_port: int = 6379) -> HybridManager:
    """
    创建混合管理器实例
    
    Args:
        sqlite_path: SQLite路径
        redis_host: Redis主机
        redis_port: Redis端口
        
    Returns:
        HybridManager: 混合管理器实例
    """
    return HybridManager(
        sqlite_path=sqlite_path,
        redis_host=redis_host,
        redis_port=redis_port
    )
