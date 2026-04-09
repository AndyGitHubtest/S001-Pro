"""
数据总线 - 模块间松耦合通信机制
提供事件订阅/发布功能，实现模块解耦
"""

import logging
import threading
from typing import Dict, List, Callable, Any, Optional
from datetime import datetime


class DataBus:
    """
    数据总线
    
    职责:
    1. 模块状态变更广播
    2. 数据就绪通知
    3. 错误/告警广播
    4. 系统事件分发
    
    设计原则:
    - 发布-订阅模式，发布者不需要知道订阅者
    - 异步处理，不阻塞发布者
    - 异常隔离，单个订阅者失败不影响其他订阅者
    
    事件类型:
    - {module}_completed: 模块完成 (M3_completed)
    - {module}_failed: 模块失败 (M3_failed)
    - pipeline_started: 管道开始
    - pipeline_completed: 管道完成
    - config_updated: 配置更新
    - error: 错误广播
    
    Example:
        bus = DataBus()
        
        # 订阅事件
        def on_m3_complete(data):
            print(f"M3 done: {data['session_id']}")
            m4.run()  # 触发M4
        
        bus.subscribe("M3_completed", on_m3_complete)
        
        # 发布事件
        bus.publish("M3_completed", {
            "module": "M3",
            "session_id": "M3_20260101_120000_abc123",
            "timestamp": 1234567890
        })
    """
    
    def __init__(self):
        """初始化数据总线"""
        self._subscribers: Dict[str, List[Callable]] = {}
        self._lock = threading.RLock()
        self.logger = logging.getLogger("DataBus")
        
        # 统计信息
        self._stats = {
            "events_published": 0,
            "events_delivered": 0,
            "errors": 0
        }
    
    def subscribe(self, event_type: str, callback: Callable[[Any], None]) -> bool:
        """
        订阅事件
        
        Args:
            event_type: 事件类型 (如 "M3_completed")
            callback: 回调函数，接收事件数据
            
        Returns:
            bool: 订阅是否成功
        """
        if not callable(callback):
            self.logger.error(f"Callback for {event_type} is not callable")
            return False
        
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)
        
        self.logger.debug(f"Subscribed to {event_type}")
        return True
    
    def unsubscribe(self, event_type: str, callback: Callable[[Any], None]) -> bool:
        """
        取消订阅
        
        Args:
            event_type: 事件类型
            callback: 回调函数
            
        Returns:
            bool: 取消是否成功
        """
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(callback)
                    self.logger.debug(f"Unsubscribed from {event_type}")
                    return True
                except ValueError:
                    pass
        return False
    
    def publish(self, event_type: str, data: Any) -> int:
        """
        发布事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
            
        Returns:
            int: 成功投递的订阅者数量
        """
        with self._lock:
            callbacks = self._subscribers.get(event_type, []).copy()
        
        delivered = 0
        errors = []
        
        for callback in callbacks:
            try:
                callback(data)
                delivered += 1
            except Exception as e:
                errors.append(str(e))
                self.logger.error(f"Event handler error for {event_type}: {e}")
        
        # 更新统计
        self._stats["events_published"] += 1
        self._stats["events_delivered"] += delivered
        if errors:
            self._stats["errors"] += len(errors)
        
        self.logger.debug(f"Published {event_type} to {delivered}/{len(callbacks)} subscribers")
        return delivered
    
    def publish_async(self, event_type: str, data: Any) -> threading.Thread:
        """
        异步发布事件 (在新线程中执行)
        
        Args:
            event_type: 事件类型
            data: 事件数据
            
        Returns:
            Thread: 执行线程
        """
        def _publish():
            self.publish(event_type, data)
        
        thread = threading.Thread(target=_publish, name=f"DataBus-{event_type}")
        thread.daemon = True
        thread.start()
        return thread
    
    def get_subscribers(self, event_type: Optional[str] = None) -> Dict[str, int]:
        """
        获取订阅者统计
        
        Args:
            event_type: 事件类型，None则返回所有
            
        Returns:
            Dict: {event_type: subscriber_count}
        """
        with self._lock:
            if event_type:
                return {event_type: len(self._subscribers.get(event_type, []))}
            else:
                return {k: len(v) for k, v in self._subscribers.items()}
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()
    
    def clear(self):
        """清空所有订阅者"""
        with self._lock:
            self._subscribers.clear()
        self.logger.info("All subscribers cleared")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # 便捷方法 - 模块事件
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def notify_module_complete(self, module_name: str, session_id: str, 
                               metadata: Optional[Dict] = None):
        """
        通知模块完成
        
        Args:
            module_name: 模块名称
            session_id: 会话ID
            metadata: 额外元数据
        """
        data = {
            "event": "module_completed",
            "module": module_name,
            "session_id": session_id,
            "timestamp": datetime.now().timestamp(),
            "metadata": metadata or {}
        }
        self.publish(f"{module_name}_completed", data)
        self.publish("module_completed", data)  # 通用事件
    
    def notify_module_failed(self, module_name: str, session_id: str, 
                            error: str, metadata: Optional[Dict] = None):
        """
        通知模块失败
        
        Args:
            module_name: 模块名称
            session_id: 会话ID
            error: 错误信息
            metadata: 额外元数据
        """
        data = {
            "event": "module_failed",
            "module": module_name,
            "session_id": session_id,
            "error": error,
            "timestamp": datetime.now().timestamp(),
            "metadata": metadata or {}
        }
        self.publish(f"{module_name}_failed", data)
        self.publish("module_failed", data)
    
    def notify_pipeline_started(self, pipeline_id: str, modules: List[str]):
        """通知管道开始"""
        self.publish("pipeline_started", {
            "event": "pipeline_started",
            "pipeline_id": pipeline_id,
            "modules": modules,
            "timestamp": datetime.now().timestamp()
        })
    
    def notify_pipeline_completed(self, pipeline_id: str, success: bool, 
                                   duration_ms: int):
        """通知管道完成"""
        self.publish("pipeline_completed", {
            "event": "pipeline_completed",
            "pipeline_id": pipeline_id,
            "success": success,
            "duration_ms": duration_ms,
            "timestamp": datetime.now().timestamp()
        })
    
    def notify_config_updated(self, pair_key: str, config: Dict):
        """通知配置更新"""
        self.publish("config_updated", {
            "event": "config_updated",
            "pair_key": pair_key,
            "config": config,
            "timestamp": datetime.now().timestamp()
        })
    
    def notify_error(self, source: str, error: str, severity: str = "error"):
        """
        广播错误
        
        Args:
            source: 错误来源
            error: 错误信息
            severity: 严重程度 (info, warning, error, critical)
        """
        self.publish("error", {
            "event": "error",
            "source": source,
            "error": error,
            "severity": severity,
            "timestamp": datetime.now().timestamp()
        })


# 全局数据总线实例 (单例模式)
_global_bus: Optional[DataBus] = None
_global_bus_lock = threading.Lock()


def get_data_bus() -> DataBus:
    """
    获取全局数据总线实例
    
    Returns:
        DataBus: 数据总线实例
    """
    global _global_bus
    if _global_bus is None:
        with _global_bus_lock:
            if _global_bus is None:
                _global_bus = DataBus()
    return _global_bus


def reset_data_bus():
    """重置全局数据总线 (测试用)"""
    global _global_bus
    with _global_bus_lock:
        _global_bus = None
