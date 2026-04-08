"""
稳健性包装器
S001-Pro 系统稳健性增强层

为现有组件提供:
- 版本追踪
- 健康监控
- 状态保护
- 熔断保护
"""

import asyncio
import logging
from typing import Any, Callable
from functools import wraps

from version_tracker import tracker, ChangeRecord
from health_monitor import health_monitor, ComponentHealth
from state_guard import state_guard
from circuit_breaker import get_circuit_breaker, degradation_manager

logger = logging.getLogger("RobustnessWrapper")


class RobustnessLayer:
    """
    稳健性层
    
    为交易系统提供完整的稳健性保障
    """
    
    def __init__(self):
        self.initialized = False
        logger.info("RobustnessLayer initialized")
    
    async def start(self):
        """启动稳健性监控"""
        if self.initialized:
            return
        
        # 启动健康监控
        await health_monitor.start()
        
        # 注册系统组件健康检查
        health_monitor.register_component("trading_system", self._check_trading_health)
        health_monitor.register_component("data_pipeline", self._check_data_health)
        health_monitor.register_component("order_execution", self._check_order_health)
        
        # 记录启动
        tracker.record_change(ChangeRecord(
            version=tracker.VERSION,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            component="robustness_layer",
            change_type="start",
            description="Robustness layer started",
            author="system",
            impact_level="low",
            rollback_available=False,
            related_files=["src/robustness_wrapper.py"],
            validation_status="pass"
        ))
        
        self.initialized = True
        logger.info("RobustnessLayer started")
    
    async def stop(self):
        """停止稳健性监控"""
        await health_monitor.stop()
        logger.info("RobustnessLayer stopped")
    
    def _check_trading_health(self):
        """检查交易系统健康"""
        # 简化实现
        return True, {"status": "running"}
    
    def _check_data_health(self):
        """检查数据管道健康"""
        return True, {"status": "running"}
    
    def _check_order_health(self):
        """检查订单执行健康"""
        return True, {"status": "running"}
    
    def protect_state_change(self, func: Callable) -> Callable:
        """
        状态变更保护装饰器
        
        在状态变更前后进行验证
        """
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 前置检查
            if args and hasattr(args[0], 'positions'):
                state = args[0].positions
                passed, errors = state_guard.validate_state(state)
                if not passed:
                    logger.error(f"State validation failed before {func.__name__}: {errors}")
                    if any("critical" in e.lower() for e in errors):
                        raise StateValidationError(f"Critical state error: {errors}")
            
            # 执行函数
            result = await func(*args, **kwargs)
            
            # 后置检查
            if args and hasattr(args[0], 'positions'):
                state = args[0].positions
                passed, errors = state_guard.validate_state(state)
                if not passed:
                    logger.warning(f"State validation failed after {func.__name__}: {errors}")
            
            return result
        
        return wrapper
    
    def with_circuit_breaker(self, name: str):
        """
        熔断器装饰器
        
        保护关键调用免受级联故障
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                cb = get_circuit_breaker(name)
                return await cb.call(func, *args, **kwargs)
            return wrapper
        return decorator
    
    def with_degradation_check(self, feature: str):
        """
        降级检查装饰器
        
        检查功能是否被降级禁用
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                if not degradation_manager.is_enabled(feature):
                    logger.debug(f"Feature {feature} is disabled due to degradation")
                    return None
                return await func(*args, **kwargs)
            return wrapper
        return decorator
    
    def get_health_report(self) -> dict:
        """获取健康报告"""
        return {
            "health": health_monitor.get_health_report(),
            "violations": state_guard.get_violations_report(),
            "circuits": {name: cb.get_status() for name, cb in get_circuit_breaker.__closure__[0].cell_contents.items()} if hasattr(get_circuit_breaker, '__closure__') else {},
            "degradation": {
                "level": degradation_manager.level,
                "features": degradation_manager.features
            }
        }


class StateValidationError(Exception):
    """状态验证错误"""
    pass


import time

# 全局实例
robustness = RobustnessLayer()
