# RecoverySystem 重启恢复模块 - 原子级文档

> **职责**: 生产级重启恢复系统，三层恢复策略，防止重启后裸仓  
> **文件**: `src/recovery_system.py` (611行)  
> **状态**: P0-核心  
> **最后更新**: 2025-01-13

---

## 1. 类、函数完整签名

### 1.1 RecoveryLevel (行27-33) - 恢复等级枚举
```python
class RecoveryLevel(Enum):
    FULL = "full"           # 完全恢复: 仓位+订单+状态
    PARTIAL = "partial"     # 部分恢复: 仓位+状态
    MINIMAL = "minimal"     # 最小恢复: 仅仓位
    EMERGENCY = "emergency" # 紧急: 只平仓不新开
```

### 1.2 SystemMode (行35-41) - 系统模式枚举
```python
class SystemMode(Enum):
    NORMAL = "normal"       # 正常运行
    RECOVERY = "recovery"   # 恢复模式
    SAFE = "safe"           # 安全模式(降低仓位)
    HALT = "halt"           # 停止交易
```

### 1.3 PositionSnapshot (行43-76) - 仓位快照
```python
@dataclass
class PositionSnapshot:
    pair: str                      # 配对ID
    symbol_a: str                  # 币种A
    symbol_b: str                  # 币种B
    direction: int                 # 1=多A空B, -1=空A多B
    size_a: float                  # A仓位大小
    size_b: float                  # B仓位大小
    entry_price_a: float           # A入场价
    entry_price_b: float           # B入场价
    entry_z: float                 # 入场Z-Score
    current_z: float               # 当前Z-Score
    unrealized_pnl: float          # 未实现盈亏
    margin_used: float             # 占用保证金
    open_time: str                 # 开仓时间ISO
    scale_in_layer: int            # 建仓层数
    scale_out_layer: int           # 平仓层数
```

### 1.4 OrderIntent (行78-115) - 订单意图
```python
@dataclass
class OrderIntent:
    symbol: str                    # 交易对
    side: str                      # buy/sell
    amount: float                  # 数量
    price: Optional[float]         # 价格(限价单)
    order_type: str                # limit/market
    params: Dict                   # 额外参数
```

### 1.5 OrderRecord (行117-144) - 订单记录
```python
@dataclass
class OrderRecord:
    order_id: str                  # 订单ID
    client_order_id: str           # 客户端订单ID
    pair: str                      # 配对
    symbol: str                    # 币种
    side: str                      # 方向
    amount: float                  # 数量
    filled: float                  # 已成交
    price: float                   # 价格
    status: str                    # 状态
    created_at: str                # 创建时间
```

### 1.6 ClientOrderIdGenerator (行146-143) - 订单ID生成器
```python
class ClientOrderIdGenerator:
    def generate(
        strategy: str,      # 策略名
        symbol: str,        # 币种
        action: str,        # OPEN/CLOSE/STOP
        side: str,          # LONG/SHORT
        timestamp: int      # 毫秒时间戳
    ) -> str               # 返回: S001_ETH_OPEN_LONG_123456789
    # 行106-126
    
    def parse(client_order_id: str) -> Dict
    # 行127-143
    # 解析订单ID获取元数据
```

### 1.7 RecoverySystem (行145-611) - 恢复系统主类
```python
class RecoverySystem:
    def __init__(
        self,
        exchange: ccxt.Exchange,
        config: Dict,
        data_dir: str = "data"
    )  # 行163
    
    # 核心恢复流程
    async def recover(self) -> Tuple[RecoveryLevel, Dict]  # 行215
    
    # 三层恢复策略
    async def _level1_position_recovery(self) -> List[PositionSnapshot]  # 行273
    async def _level2_order_recovery(self, positions: List[PositionSnapshot])  # 行373
    async def _level3_state_recovery(self, positions: List[PositionSnapshot])  # 行473
    
    # 辅助方法
    def _load_last_state(self) -> Optional[Dict]           # 行265
    def _detect_orphan_positions(self, exchange_pos: List, local_pos: List)  # 行296
    def _match_positions(self, orphan: Dict, local: List) -> Optional[str]   # 行323
    def _rebuild_state_from_position(self, position: Dict) -> Optional[Dict]  # 行349
    async def _cancel_all_pending_orders(self)           # 行417
    def _determine_recovery_level(self, results: Dict) -> RecoveryLevel  # 行549
    def save_recovery_report(self, level: RecoveryLevel, results: Dict)   # 行571
```

---

## 2. 常量、阈值、默认值

| 常量 | 值 | 行号 | 说明 |
|------|-----|------|------|
| `SNAPSHOT_INTERVAL` | 60 | 165 | 快照保存间隔(秒) |
| `MAX_ORPHAN_AGE_HOURS` | 24 | 167 | 孤儿持仓最大年龄 |
| `RECOVERY_TIMEOUT` | 300 | 169 | 恢复总超时(秒) |
| `MAX_PENDING_ORDERS` | 10 | 171 | 最大待处理订单数 |
| `MIN_FILL_RATIO` | 0.95 | 173 | 最小成交率(视为完全成交) |
| `POSITION_MATCH_TOLERANCE` | 0.01 | 175 | 仓位匹配容差(1%) |

---

## 3. 三层恢复策略

```
╔═══════════════════════════════════════════════════════════════╗
║                RecoverySystem 三层恢复                         ║
╚═══════════════════════════════════════════════════════════════╝

恢复触发: main.py 检测到重启或异常后调用 recover()

┌─────────────────────────────────────────────────────────────┐
│ Level 1: Position Recovery (仓位恢复) - 必须成功              │
├─────────────────────────────────────────────────────────────┤
│ _level1_position_recovery() (行273)                          │
│ ├─ fetch_positions(): 获取所有交易所持仓 (行283)              │
│ ├─ _detect_orphan_positions(): 检测孤儿持仓 (行296)           │
│ │  └─ 交易所有但本地没有的仓位                                │
│ ├─ _match_positions(): 尝试匹配到配对 (行323)                 │
│ ├─ _rebuild_state_from_position(): 重建状态 (行349)           │
│ └─ 返回: List[PositionSnapshot]                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 2: Order Recovery (订单恢复) - 可选                     │
├─────────────────────────────────────────────────────────────┤
│ _level2_order_recovery() (行373)                             │
│ ├─ fetch_open_orders(): 获取未完成订单 (行383)               │
│ ├─ _cancel_all_pending_orders(): 取消待处理 (行417)          │
│ ├─ 检查已成交但未记录的订单                                  │
│ └─ 更新仓位状态                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 3: State Recovery (状态恢复) - 重建Runtime状态          │
├─────────────────────────────────────────────────────────────┤
│ _level3_state_recovery() (行473)                             │
│ ├─ _load_last_state(): 加载上次状态 (行265)                   │
│ ├─ 核对交易所实际持仓 vs 本地状态                             │
│ ├─ 重建 Scale In/Out 层数                                    │
│ ├─ 计算当前Z-Score                                           │
│ └─ 生成新的state.json                                        │
└─────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════
恢复等级判定 (_determine_recovery_level):
  FULL:    三层都成功
  PARTIAL: L1+L2成功，L3失败
  MINIMAL: 仅L1成功
  EMERGENCY: L1失败，进入只平仓模式
═══════════════════════════════════════════════════════════════
```

---

## 4. 孤儿持仓处理

```
孤儿持仓 = 交易所实际持仓 与 本地state.json记录不一致

检测逻辑 (行296-322):
  ├─ 遍历所有交易所持仓
  ├─ 检查该symbol是否在任何本地配对中
  └─ 如果不存在 = 孤儿持仓

处理流程:
  1. 尝试匹配到最接近的配对 (行323-348)
     └─ 基于仓位大小、币种、方向的相似度
  2. 如果匹配成功 → 重建配对状态
  3. 如果匹配失败 → 标记为孤儿，单独管理
     └─ 可选: 立即平仓或人工处理
```

---

## 5. ClientOrderId 编码规范

```
格式: {Strategy}_{Symbol}_{Action}_{Side}_{Timestamp}

示例: S001_ETH_OPEN_LONG_1640995200000

字段:
  Strategy:  S001 (策略标识)
  Symbol:    ETH (币种，去除/USDT后缀)
  Action:    OPEN / CLOSE / STOP / SCALE_IN / SCALE_OUT
  Side:      LONG / SHORT
  Timestamp: 毫秒时间戳

解析 (parse方法):
  └─ 从订单ID反推交易意图，用于恢复时识别订单
```

---

## 6. 数据流转

```
Input:
  ├─ data/state.json (上次运行状态)
  ├─ data/recovery/ (历史快照)
  ├─ 交易所API (实际持仓、未完成订单)
  └─ config/pairs_v2.json (配对配置)

Process:
  RecoverySystem.recover()
    ├─ Level 1: 获取并匹配所有持仓
    ├─ Level 2: 处理未完成订单
    ├─ Level 3: 重建完整状态
    └─ _determine_recovery_level(): 判定恢复等级

Output:
  ├─ Tuple[RecoveryLevel, Dict] (恢复结果)
  ├─ data/state.json (更新后状态)
  ├─ data/recovery_report_{timestamp}.json
  └─ Telegram通知恢复详情
```

---

## 7. 调用关系

### 谁调用我
```
main.py
├─ 启动时: recovery_system.recover()
└─ 异常时: 自动触发恢复

runtime.py
└─ 状态异常时调用
```

### 我调用谁
```
RecoverySystem
├─ ccxt.Exchange
│  ├─ fetch_positions()
│  ├─ fetch_open_orders()
│  ├─ cancel_order()
│  └─ fetch_balance()
├─ json (读写state.json)
└─ logging
```

---

## 8. 故障排查

| 症状 | 可能原因 | 解决 |
|------|----------|------|
| L1失败 | 孤儿持仓过多 | 检查配对配置，手动平仓 |
| L2卡住 | 订单取消失败 | 检查交易所API状态 |
| L3失败 | state.json损坏 | 从recovery/恢复备份 |
| 恢复超时 | 网络延迟 | 增加RECOVERY_TIMEOUT |
| 仓位不匹配 | 交易所异常 | 人工核对后重置state.json |

---

**维护**: 修改恢复逻辑时同步更新本文档
