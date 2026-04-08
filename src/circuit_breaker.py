"""
熔断器与优雅降级模块
S001-Pro 系统稳定性保障

提供:
- 熔断保护
- 限流控制
- 优雅降级
- 自动恢复
"""

import time
import logging
from typing import Dict, Optional, Callable, Any
from enum import Enum
from dataclasses import dataclass
import asyncio

logger = logging.getLogger("CircuitBreaker")


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常
    OPEN = "open"          # 熔断
    HALF_OPEN = "half_open"  # 半开


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 3
    success_threshold: int = 2


class CircuitBreaker:
    """
    熔断器
    
    防止级联故障，保护系统稳定性
    """
    
    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        self.half_open_calls = 0
        
        logger.info(f"CircuitBreaker '{name}' initialized (threshold: {self.config.failure_threshold})")
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        执行被保护的调用
        
        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数
            
        Returns:
            函数返回值
            
        Raises:
            CircuitOpenError: 熔断器打开时
        """
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.config.recovery_timeout:
                logger.info(f"Circuit '{self.name}' entering half-open state")
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                self.success_count = 0
            else:
                raise CircuitOpenError(f"Circuit '{self.name}' is OPEN")
        
        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls >= self.config.half_open_max_calls:
                raise CircuitOpenError(f"Circuit '{self.name}' half-open limit reached")
            self.half_open_calls += 1
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            self._on_success()
            return result
            
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        """成功处理"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                logger.info(f"Circuit '{self.name}' closed (recovered)")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
        else:
            self.failure_count = 0
    
    def _on_failure(self):
        """失败处理"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN:
            logger.warning(f"Circuit '{self.name}' open again (failure in half-open)")
            self.state = CircuitState.OPEN
        elif self.failure_count >= self.config.failure_threshold:
            logger.error(f"Circuit '{self.name}' opened ({self.failure_count} failures)")
            self.state = CircuitState.OPEN
    
    def get_status(self) -> Dict:
        """获取熔断器状态"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure": self.last_failure_time
        }


class CircuitOpenError(Exception):
    """熔断器打开异常"""
    pass


class DegradationManager:
    """
    降级管理器
    
    系统负载过高时，自动降级非核心功能
    """
    
    def __init__(self):
        self.level = 0  # 0=正常, 1=轻度降级, 2=中度降级, 3=严重降级
        self.features: Dict[str, bool] = {
            "telegram_notifications": True,
            "detailed_logging": True,
            "real_time_monitoring": True,
            "auto_optimization": True,
            "full_scan": True
        }
        logger.info("DegradationManager initialized")
    
    def set_level(self, level: int):
        """设置降级级别"""
        old_level = self.level
        self.level = max(0, min(3, level))
        
        if self.level != old_level:
            logger.warning(f"Degradation level changed: {old_level} -> {self.level}")
            self._apply_degradation()
    
    def _apply_degradation(self):
        """应用降级策略"""
        if self.level == 0:
            # 正常模式
            self.features["telegram_notifications"] = True
            self.features["detailed_logging"] = True
            self.features["real_time_monitoring"] = True
            self.features["auto_optimization"] = True
            self.features["full_scan"] = True
            
        elif self.level == 1:
            # 轻度降级 - 减少通知
            self.features["telegram_notifications"] = False
            logger.info("Degradation L1: Telegram notifications disabled")
            
        elif self.level == 2:
            # 中度降级 - 减少监控和日志
            self.features["telegram_notifications"] = False
            self.features["detailed_logging"] = False
            self.features["real_time_monitoring"] = False
            logger.info("Degradation L2: Detailed logging and monitoring disabled")
            
        elif self.level == 3:
            # 严重降级 - 仅保留核心交易功能
            self.features["telegram_notifications"] = False
            self.features["detailed_logging"] = False
            self.features["real_time_monitoring"] = False
            self.features["auto_optimization"] = False
            self.features["full_scan"] = False
            logger.critical("Degradation L3: Only core trading functions enabled")
    
    def is_enabled(self, feature: str) -> bool:
        """检查功能是否启用"""
        return self.features.get(feature, True)


# 全局实例
circuit_breakers: Dict[str, CircuitBreaker] = {}
degradation_manager = DegradationManager()


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """获取或创建熔断器"""
    if name not in circuit_breakers:
        circuit_breakers[name] = CircuitBreaker(name)
    return circuit_breakers[name]
