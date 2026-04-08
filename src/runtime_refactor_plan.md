# Runtime 模块重构计划

## 现状问题

`runtime.py` 当前 1082 行，包含多个职责：
- 状态机管理
- 订单执行
- 持仓对账
- 风险管理
- 信号处理

## 重构目标

拆分为 4 个独立模块，每个 < 300 行

## 新模块结构

```
src/
├── runtime/
│   ├── __init__.py          # 导出 Runtime 主类
│   ├── position_state.py    # PositionState 类定义
│   ├── state_machine.py     # 状态机转换逻辑
│   ├── order_executor.py    # 下单执行逻辑
│   ├── position_manager.py  # 持仓对账管理
│   └── risk_guard.py        # 风险控制检查
└── runtime.py               # 主入口 (简化版)
```

## 详细拆分

### 1. position_state.py (约 100 行)
```python
@dataclass
class PositionState:
    """单个配对的持仓状态"""
    pair_config: Dict[str, Any]
    symbol_a: str
    symbol_b: str
    beta: float
    state: str = STATE_IDLE
    direction: int = 0
    entry_z: float = 0.0
    scale_in_layer: int = 0
    scale_out_layer: int = 0
    position_size_pct: float = 0.0
    # ... 其他字段
```

### 2. state_machine.py (约 250 行)
```python
class StateMachine:
    """处理所有状态转换逻辑"""
    
    async def on_idle(self, ps: PositionState, z: float) -> None:
        """IDLE 状态处理"""
        
    async def on_scaling_in(self, ps: PositionState, z: float) -> None:
        """SCALING_IN 状态处理"""
        
    async def on_in_position(self, ps: PositionState, z: float) -> None:
        """IN_POSITION 状态处理"""
```

### 3. order_executor.py (约 280 行)
```python
class OrderExecutor:
    """处理所有订单相关操作"""
    
    async def execute_scale_in(
        self, 
        ps: PositionState, 
        scale_in_plan: List[Dict],
        current_z: float
    ) -> bool:
        """执行分层进场"""
        
    async def execute_rollback(
        self, 
        ps: PositionState,
        filled_a: bool,
        filled_b: bool,
        side_a: str,
        side_b: str
    ) -> bool:
        """执行回滚"""
```

### 4. position_manager.py (约 200 行)
```python
class PositionManager:
    """持仓对账和恢复管理"""
    
    async def reconcile_positions(self) -> None:
        """交易所持仓对账"""
        
    async def handle_ghost_position(
        self, 
        symbol: str, 
        position_data: Dict
    ) -> None:
        """处理 Ghost 持仓接管"""
        
    async def handle_orphan_position(self, symbol: str) -> None:
        """处理 Orphan 持仓清理"""
```

### 5. risk_guard.py (约 150 行)
```python
class RiskGuard:
    """风险控制检查"""
    
    def check_kill_switch(self) -> bool:
        """检查是否触发 Kill Switch"""
        
    def check_daily_drawdown(self, current_pnl: float) -> bool:
        """检查日回撤限制"""
        
    def validate_order_risk(
        self, 
        symbol: str, 
        qty: float, 
        side: str
    ) -> Tuple[bool, str]:
        """验证订单风险"""
```

## 重构后的 runtime.py (约 200 行)

```python
class Runtime:
    """主运行时，协调各子模块"""
    
    def __init__(self, config_manager, exchange_api=None):
        self.config = config_manager
        self.exchange = exchange_api
        
        # 子模块初始化
        self.state_machine = StateMachine(self)
        self.order_executor = OrderExecutor(self)
        self.position_manager = PositionManager(self)
        self.risk_guard = RiskGuard(self)
        
    async def on_signal(self, pair_key: str, z: float) -> None:
        """主信号处理入口"""
        # 简化为调用子模块
        pass
```

## 实施步骤

1. **阶段1**: 创建常量文件 ✅
2. **阶段2**: 提取 PositionState 到独立文件
3. **阶段3**: 提取 OrderExecutor
4. **阶段4**: 提取 StateMachine
5. **阶段5**: 提取 PositionManager 和 RiskGuard
6. **阶段6**: 简化主 Runtime 类
7. **阶段7**: 全量测试验证

## 注意事项

- 保持现有接口不变（向后兼容）
- 每次重构后运行测试
- 保留详细注释和文档
- 错误处理逻辑完整迁移
