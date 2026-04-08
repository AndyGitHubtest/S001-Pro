"""
S001-Pro Runtime 模块
实盘监控执行引擎 - 模块化重构版

模块结构:
- position_state: PositionState 数据类定义
- state_machine: 状态机转换逻辑
- order_executor: 订单执行逻辑
- position_manager: 持仓对账管理
- risk_guard: 风险控制检查
"""

from src.runtime.position_state import (
    PositionState,
    STATE_IDLE,
    STATE_SCALING_IN,
    STATE_IN_POSITION,
    STATE_SCALING_OUT,
    STATE_EXITED,
    STATE_CLOSING_MODE,
)
from src.runtime.state_machine import StateMachine
from src.runtime.order_executor import OrderExecutor
from src.runtime.position_manager import PositionManager
from src.runtime.risk_guard import RiskGuard
from src.runtime.runtime_core import Runtime

__all__ = [
    'PositionState',
    'STATE_IDLE',
    'STATE_SCALING_IN',
    'STATE_IN_POSITION',
    'STATE_SCALING_OUT',
    'STATE_EXITED',
    'STATE_CLOSING_MODE',
    'StateMachine',
    'OrderExecutor',
    'PositionManager',
    'RiskGuard',
    'Runtime',
]
