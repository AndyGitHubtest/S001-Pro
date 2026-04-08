# M6.1 Runtime 职责

**所属模块**: M6 运行时  
**版本**: 2.1.0-hardened  
**对应代码**: `src/runtime/runtime_core.py`, `src/runtime/order_executor.py`, `src/runtime/state_machine.py`, `src/runtime/position_manager.py`, `src/runtime/risk_guard.py`, `src/runtime/position_state.py`

---

## 一句话描述

实盘监控执行引擎，管理持仓状态机、执行订单、风险控制，确保交易按策略规则执行。

---

## 架构组成

```
┌─────────────────────────────────────────────────────────┐
│                      M6 Runtime                          │
├─────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │
│  │ StateMachine  │  │ OrderExecutor │  │ RiskGuard   │  │
│  │ (状态机)       │  │ (订单执行)     │  │ (风控守卫)   │  │
│  └───────┬───────┘  └───────┬───────┘  └──────┬──────┘  │
│          │                  │                 │         │
│          └──────────────────┼─────────────────┘         │
│                             ↓                           │
│                    ┌─────────────────┐                  │
│                    │  RuntimeCore    │                  │
│                    │  (协调中心)      │                  │
│                    └────────┬────────┘                  │
│                             ↓                           │
│                    ┌─────────────────┐                  │
│                    │ PositionManager │                  │
│                    │ (持仓管理)       │                  │
│                    └─────────────────┘                  │
└─────────────────────────────────────────────────────────┘
```

---

## 核心组件

### 1. RuntimeCore (运行时核心)

**文件**: `src/runtime/runtime_core.py`

```python
class Runtime:
    """
    S001-Pro 实盘运行时 - 模块化重构版
    
    职责:
    1. 初始化各子模块
    2. 协调扫描和交易流程
    3. 处理信号和订单
    4. 管理生命周期
    """
    
    def __init__(
        self,
        config_manager: ConfigManager,
        exchange_api: Optional[ExchangeApi] = None,
        monitor: Optional[Monitor] = None,
    ):
        self.config_manager = config_manager
        self.exchange_api = exchange_api
        self.monitor = monitor
        
        # 初始化子模块
        self.position_manager = PositionManager(exchange_api)
        self.order_executor = OrderExecutor(exchange_api, config_manager)
        self.risk_guard = RiskGuard(config_manager)
        self.state_machine = StateMachine(
            order_executor=self.order_executor,
            position_manager=self.position_manager,
            risk_guard=self.risk_guard,
        )
```

**核心方法**:

| 方法 | 功能 |
|------|------|
| `start()` | 启动运行时，开始主循环 |
| `stop()` | 停止运行时，优雅关闭 |
| `on_signal()` | 处理交易信号 |
| `handle_hot_reload()` | 处理配置热重载 |

---

### 2. StateMachine (状态机)

**文件**: `src/runtime/state_machine.py`

**状态定义**:
```python
class PositionStateEnum(Enum):
    IDLE = "idle"              # 空闲（无持仓）
    SCALING_IN = "scaling_in"  # 建仓中
    IN_POSITION = "in_position" # 持仓中
    COOLDOWN = "cooldown"      # 冷却中
```

**状态转换**:
```
┌─────────┐    进场信号     ┌─────────────┐
│  IDLE   │ ─────────────→ │  SCALING_IN │
│ (空闲)   │                │  (建仓中)    │
└─────────┘                └──────┬──────┘
    ↑                             │ 建仓成功
    │                             ↓
    │     冷却结束           ┌─────────────┐
    └─────────────────────── │ IN_POSITION │
                             │  (持仓中)    │
                             └──────┬──────┘
                                    │ 出场信号
                                    ↓
                             ┌─────────────┐
                             │  COOLDOWN   │
                             │  (冷却中)    │
                             └─────────────┘
```

**核心方法**:
```python
def on_signal(
    self,
    pair: str,
    z_score: float,
    signal_type: str,  # "ENTRY", "EXIT", "STOP"
)
```

---

### 3. OrderExecutor (订单执行)

**文件**: `src/runtime/order_executor.py`

**核心职责**: 双边同步下单，防裸仓

```python
class OrderExecutor:
    """
    订单执行模块 - 生产级实现
    
    核心功能:
    1. 双边同步下单 (防裸仓)
    2. 订单确认轮询
    3. 失败回滚机制
    """
```

**防裸仓策略**:
```
开仓流程:
┌─────────────┐
│ 下单symbol_a │ ──┐
└─────────────┘   │
                  │
┌─────────────┐   │    等待双向成交
│ 下单symbol_b │ ──┤
└─────────────┘   │
                  ↓
           ┌──────────────┐
           │  两边都成交？  │
           └───────┬──────┘
              是 /    \ 否
                /      \
               ↓        ↓
        ┌────────┐   ┌──────────┐
        │ 成功   │   │ 回滚      │
        └────────┘   │ (平掉已成交)│
                     └──────────┘
```

**核心方法**:

| 方法 | 功能 |
|------|------|
| `execute_scale_in()` | 建仓（双向开仓） |
| `execute_scale_out()` | 平仓（双向平仓） |
| `execute_stop_loss()` | 止损平仓 |
| `_rollback_partial_fill()` | 回滚部分成交 |

---

### 4. RiskGuard (风控守卫)

**文件**: `src/runtime/risk_guard.py`

**检查项**:
```python
class RiskGuard:
    """
    风险控制守卫模块
    
    检查项:
    1. Kill Switch 状态
    2. 系统模式（NORMAL/PROTECTION）
    3. 每日回撤限制
    4. 余额充足性
    5. 持仓限制
    6. 价格波动异常
    """
```

**风控检查列表**:

| 检查项 | 说明 | 触发动作 |
|--------|------|----------|
| Kill Switch | 紧急停止开关 | 禁止所有开仓 |
| Daily Drawdown | 单日最大回撤 | 暂停交易 |
| Balance Check | 余额是否充足 | 拒绝订单 |
| Position Limit | 最大持仓对数 | 拒绝新订单 |
| Price Anomaly | 价格异常波动 | 报警+暂停 |
| API Health | API连接状态 | 重试或切换 |

---

### 5. PositionManager (持仓管理)

**文件**: `src/runtime/position_manager.py`

```python
class PositionManager:
    """
    持仓管理模块
    
    职责:
    1. 跟踪当前持仓
    2. 计算仓位大小
    3. 持仓对账
    4. 处理孤儿持仓
    """
```

**核心方法**:

| 方法 | 功能 |
|------|------|
| `reconcile_positions()` | 持仓对账（本地vs交易所） |
| `calculate_position_size()` | 计算下单数量 |
| `get_position()` | 获取指定配对持仓 |
| `update_position()` | 更新持仓状态 |

---

### 6. PositionState (持仓状态)

**文件**: `src/runtime/position_state.py`

```python
class PositionState:
    """
    持仓状态定义
    
    记录单个配对的完整持仓信息
    """
    
    pair: str                    # 配对名称
    state: PositionStateEnum     # 当前状态
    symbol_a: str               # 交易对A
    symbol_b: str               # 交易对B
    
    # 持仓信息
    position_a: float           # A持仓数量
    position_b: float           # B持仓数量
    entry_z: float             # 进场Z值
    current_z: float           # 当前Z值
    
    # 时间戳
    entry_time: Optional[datetime]
    last_update: datetime
    
    # 冷却机制
    cooldown_until: Optional[datetime]
    failure_count: int          # 连续失败次数
```

---

## 完整交易流程

```
┌──────────────────────────────────────────────────────────────┐
│                      信号检测阶段                             │
├──────────────────────────────────────────────────────────────┤
│  M9 SignalEngine 检测到Z-score信号                            │
│  ↓                                                           │
│  RuntimeCore.on_signal(pair, z_score, signal_type)           │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                      风控检查阶段                             │
├──────────────────────────────────────────────────────────────┤
│  RiskGuard.check_all():                                      │
│    ✓ Kill Switch 未触发                                      │
│    ✓ 系统模式 NORMAL                                         │
│    ✓ 回撤未超限                                              │
│    ✓ 余额充足                                                │
│    ✓ 持仓未满                                                │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                      状态机处理阶段                           │
├──────────────────────────────────────────────────────────────┤
│  StateMachine.on_signal():                                   │
│    IF 状态 == IDLE AND 信号 == ENTRY:                        │
│        → 进入 SCALING_IN                                     │
│    IF 状态 == IN_POSITION AND 信号 == EXIT:                  │
│        → 平仓                                                │
│    IF 状态 == IN_POSITION AND 信号 == STOP:                  │
│        → 止损平仓                                            │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                      订单执行阶段                             │
├──────────────────────────────────────────────────────────────┤
│  OrderExecutor.execute_scale_in():                           │
│    1. 计算下单数量                                            │
│    2. 双边同步下单                                            │
│    3. 等待成交确认                                            │
│    4. 防裸仓检查                                              │
│    5. 失败回滚（如需要）                                       │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                      状态更新阶段                             │
├──────────────────────────────────────────────────────────────┤
│  PositionManager.update_position()                           │
│  Monitor.record_trade()                                      │
│  StateMachine.Transition()                                   │
└──────────────────────────────────────────────────────────────┘
```

---

## 相关文档

- [M6.2 状态机定义](M6-02-state-machine.md)
- [M6.3 订单执行流程](M6-03-order-execution.md)
- [M6.4 风控检查点](M6-04-risk-checks.md)
- [M6.5 防裸仓机制](M6-05-naked-position-prevention.md)
- [src/runtime/](../../src/runtime/)
