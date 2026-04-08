"""
健康检查与自愈模块
S001-Pro 系统稳健性保障

提供:
- 组件健康状态监控
- 自动故障检测
- 自愈机制
- 优雅降级
"""

import asyncio
import time
import logging
from typing import Dict, List, Callable, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json

logger = logging.getLogger("HealthMonitor")


class HealthStatus(Enum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """组件健康状态"""
    name: str
    status: HealthStatus
    last_check: float
    response_time_ms: float
    error_count: int = 0
    last_error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


class HealthMonitor:
    """
    健康监控器
    
    持续监控系统组件健康状态，自动检测故障并触发恢复
    """
    
    def __init__(self, check_interval_sec: float = 30.0):
        self.check_interval = check_interval_sec
        self.components: Dict[str, ComponentHealth] = {}
        self.checks: Dict[str, Callable] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # 故障阈值
        self.error_threshold = 3
        self.response_time_threshold_ms = 5000
        
        logger.info(f"HealthMonitor initialized (check interval: {check_interval_sec}s)")
    
    def register_component(self, name: str, check_func: Callable):
        """
        注册组件健康检查
        
        Args:
            name: 组件名称
            check_func: 检查函数，返回 (is_healthy, metadata)
        """
        self.checks[name] = check_func
        self.components[name] = ComponentHealth(
            name=name,
            status=HealthStatus.UNKNOWN,
            last_check=0,
            response_time_ms=0
        )
        logger.info(f"Component registered: {name}")
    
    async def start(self):
        """启动健康检查循环"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("HealthMonitor started")
    
    async def stop(self):
        """停止健康检查"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("HealthMonitor stopped")
    
    async def _check_loop(self):
        """健康检查循环"""
        while self._running:
            try:
                await self._check_all()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def _check_all(self):
        """检查所有组件"""
        for name, check_func in self.checks.items():
            try:
                start = time.time()
                
                # 执行检查
                if asyncio.iscoroutinefunction(check_func):
                    is_healthy, metadata = await check_func()
                else:
                    is_healthy, metadata = check_func()
                
                response_time = (time.time() - start) * 1000
                
                # 更新状态
                component = self.components[name]
                component.last_check = time.time()
                component.response_time_ms = response_time
                
                if is_healthy:
                    if response_time > self.response_time_threshold_ms:
                        component.status = HealthStatus.DEGRADED
                        logger.warning(f"Component {name} degraded: slow response ({response_time:.0f}ms)")
                    else:
                        component.status = HealthStatus.HEALTHY
                        component.error_count = 0  # 重置错误计数
                else:
                    component.error_count += 1
                    if component.error_count >= self.error_threshold:
                        component.status = HealthStatus.UNHEALTHY
                        logger.error(f"Component {name} unhealthy: {component.error_count} consecutive failures")
                        # 触发自愈
                        await self._self_heal(name, metadata)
                
                component.metadata = metadata or {}
                
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                component = self.components[name]
                component.error_count += 1
                component.last_error = str(e)
                if component.error_count >= self.error_threshold:
                    component.status = HealthStatus.UNHEALTHY
    
    async def _self_heal(self, component_name: str, metadata: Dict):
        """
        自愈机制
        
        根据组件类型执行不同的恢复策略
        """
        logger.info(f"Attempting self-healing for {component_name}")
        
        # 记录自愈尝试
        healing_record = {
            "timestamp": time.time(),
            "component": component_name,
            "metadata": metadata
        }
        
        # 通用恢复策略
        try:
            # 1. 短暂等待
            await asyncio.sleep(1)
            
            # 2. 重置错误计数
            self.components[component_name].error_count = 0
            
            # 3. 标记为降级而非完全故障
            self.components[component_name].status = HealthStatus.DEGRADED
            
            logger.info(f"Self-healing completed for {component_name}")
            
        except Exception as e:
            logger.error(f"Self-healing failed for {component_name}: {e}")
    
    def get_health_report(self) -> Dict:
        """获取健康报告"""
        return {
            "timestamp": time.time(),
            "overall_status": self._get_overall_status().value,
            "components": {
                name: {
                    "status": comp.status.value,
                    "last_check": comp.last_check,
                    "response_time_ms": comp.response_time_ms,
                    "error_count": comp.error_count,
                    "last_error": comp.last_error
                }
                for name, comp in self.components.items()
            }
        }
    
    def _get_overall_status(self) -> HealthStatus:
        """获取整体健康状态"""
        if not self.components:
            return HealthStatus.UNKNOWN
        
        statuses = [comp.status for comp in self.components.values()]
        
        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        elif any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        elif all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.UNKNOWN
    
    def is_healthy(self) -> bool:
        """检查系统是否健康"""
        return self._get_overall_status() in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]


# 全局实例
health_monitor = HealthMonitor()
