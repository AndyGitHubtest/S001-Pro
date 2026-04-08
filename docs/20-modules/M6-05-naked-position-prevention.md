# M6.5 防裸仓机制

**所属模块**: M6 运行时  
**版本**: 2.1.0-hardened  
**对应代码**: `src/runtime/order_executor.py`

---

## 什么是裸仓(Naked Position)？

在配对交易中，裸仓指**只持有配对的一边**，而非同时持有多空双边。

**示例**:
```
正常配对持仓:
  Long BTC/USDT: +0.1 BTC
  Short ETH/USDT: -1.0 ETH

裸仓（危险状态）:
  Long BTC/USDT: +0.1 BTC
  Short ETH/USDT: 0 ETH  ← 空单未成交！
```

**风险**:
- 失去对冲保护
- 单边暴露于市场风险
- 可能产生巨额亏损

---

## 防裸仓核心策略

### 策略1: 双边同步下单

```python
def execute_scale_in(self, pair_config: Dict) -> SyncOpenResult:
    """
    同步建仓 - 防裸仓核心
    
    流程:
    1. 同时提交两个订单
    2. 等待双向成交
    3. 超时或失败则回滚
    """
    symbol_a = pair_config['symbol_a']
    symbol_b = pair_config['symbol_b']
    
    # Step 1: 计算下单数量
    qty_a = self._calculate_quantity(symbol_a, pair_config)
    qty_b = self._calculate_quantity(symbol_b, pair_config)
    
    # Step 2: 同时提交订单
    order_a = self._place_order(symbol_a, 'BUY', qty_a)
    order_b = self._place_order(symbol_b, 'SELL', qty_b)
    
    # Step 3: 等待双向成交（带超时）
    filled_a = self._wait_for_fill(order_a['id'], timeout=30)
    filled_b = self._wait_for_fill(order_b['id'], timeout=30)
    
    # Step 4: 检查成交状态
    if filled_a and filled_b:
        # 两边都成交 → 成功
        return SyncOpenResult(success=True, ...)
    else:
        # 有任一边未成交 → 回滚
        self._rollback_partial_fill(order_a, order_b, filled_a, filled_b)
        return SyncOpenResult(success=False, ...)
```

### 策略2: 成交确认轮询

```python
def _wait_for_fill(
    self, 
    order_id: str, 
    timeout: float = 30.0,
    poll_interval: float = 0.5
) -> bool:
    """
    等待订单成交，带超时保护
    
    Args:
        order_id: 订单ID
        timeout: 最大等待时间(秒)
        poll_interval: 轮询间隔(秒)
    
    Returns:
        bool: 是否成交
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        # 查询订单状态
        status = self.exchange.fetch_order_status(order_id)
        
        if status == 'closed':
            # 完全成交
            return True
        elif status == 'canceled':
            # 订单被取消
            return False
        
        # 等待下次轮询
        time.sleep(poll_interval)
    
    # 超时
    return False
```

### 策略3: 失败自动回滚

```python
def _rollback_partial_fill(
    self,
    order_a: Dict,
    order_b: Dict,
    filled_a: bool,
    filled_b: bool
) -> None:
    """
    回滚部分成交 - 防止裸仓
    
    逻辑:
    - 如果A成交但B未成交 → 平掉A
    - 如果B成交但A未成交 → 平掉B
    - 使用reduce_only=True防止反向开仓
    """
    if filled_a and not filled_b:
        # A成交了，B没成交 → 必须平掉A
        self.logger.error("Partial fill detected! Rolling back symbol_a...")
        
        # 平仓A（reduce_only=True确保不会反向开仓）
        self.exchange.create_order(
            symbol=order_a['symbol'],
            type='market',
            side='sell',  # 反向
            amount=order_a['filled_amount'],
            params={'reduce_only': True}  # 关键参数！
        )
        
    elif filled_b and not filled_a:
        # B成交了，A没成交 → 必须平掉B
        self.logger.error("Partial fill detected! Rolling back symbol_b...")
        
        self.exchange.create_order(
            symbol=order_b['symbol'],
            type='market',
            side='buy',  # 反向
            amount=order_b['filled_amount'],
            params={'reduce_only': True}
        )
    
    # 记录失败，触发冷却
    self._record_failure(pair)
```

### 策略4: 冷却机制

```python
class PositionState:
    """持仓状态 - 包含冷却机制"""
    
    def record_failure(self):
        """记录失败，增加冷却时间"""
        self.failure_count += 1
        
        # 指数退避冷却
        cooldown_minutes = min(2 ** self.failure_count, 60)  # 最大60分钟
        self.cooldown_until = datetime.now() + timedelta(minutes=cooldown_minutes)
        
        self.logger.warning(
            f"Failure recorded for {self.pair}. "
            f"Cooldown until {self.cooldown_until}"
        )
    
    def is_in_cooldown(self) -> bool:
        """检查是否在冷却期"""
        if self.cooldown_until is None:
            return False
        return datetime.now() < self.cooldown_until
```

---

## 完整防裸仓流程图

```
                    ┌─────────────────┐
                    │  收到进场信号    │
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │  检查冷却状态    │
                    │  (是否在cooldown)│
                    └────────┬────────┘
                         是 /    \ 否
                           /      \
                          ↓        ↓
                ┌──────────┐    ┌─────────────────┐
                │ 跳过信号 │    │  风控检查通过？  │
                └──────────┘    └────────┬────────┘
                                     否 /    \ 是
                                       /      \
                                      ↓        ↓
                            ┌──────────┐    ┌─────────────────┐
                            │ 拒绝订单 │    │  计算下单数量    │
                            └──────────┘    └────────┬────────┘
                                                      ↓
                                         ┌─────────────────────┐
                                         │  同时提交双边订单    │
                                         │  symbol_a: BUY      │
                                         │  symbol_b: SELL     │
                                         └──────────┬──────────┘
                                                    ↓
                                         ┌─────────────────────┐
                                         │  等待成交（30秒超时） │
                                         └──────────┬──────────┘
                                                    ↓
                                         ┌─────────────────────┐
                                         │  双向都成交？        │
                                         └──────────┬──────────┘
                                              是 /    \ 否
                                                /      \
                                               ↓        ↓
                                    ┌──────────┐    ┌──────────────────┐
                                    │ 成功更新 │    │  执行回滚         │
                                    │ 持仓状态 │    │  平掉已成交边      │
                                    └──────────┘    │  reduce_only=True │
                                                    └──────────┬───────┘
                                                               ↓
                                                    ┌──────────────────┐
                                                    │  记录失败次数     │
                                                    │  进入冷却期       │
                                                    └──────────────────┘
```

---

## 代码实现

### OrderStatus 枚举

```python
from enum import Enum

class OrderStatus(Enum):
    PENDING = "pending"      # 等待成交
    PARTIAL = "partial"      # 部分成交
    FILLED = "filled"        # 完全成交
    CANCELED = "canceled"    # 已取消
    REJECTED = "rejected"    # 被拒绝
    TIMEOUT = "timeout"      # 超时
```

### SyncOpenResult 结果

```python
from dataclasses import dataclass

@dataclass
class SyncOpenResult:
    """同步建仓结果"""
    success: bool                    # 是否成功
    pair: str                       # 配对名称
    symbol_a: str                   # A交易对
    symbol_b: str                   # B交易对
    filled_a: float                 # A成交数量
    filled_b: float                 # B成交数量
    error: Optional[str] = None     # 错误信息
    
    @property
    def is_naked(self) -> bool:
        """检查是否产生裸仓"""
        return self.filled_a > 0 and self.filled_b == 0 or \
               self.filled_b > 0 and self.filled_a == 0
```

---

## 回滚策略详解

### 情况1: A成交，B未成交

```
持仓状态:
  Before: 空仓
  After:  Long A, 空仓 B  ← 裸仓！

回滚操作:
  1. 立即市价平掉A
  2. reduce_only=True 防止意外反向开仓
  3. 记录失败，进入冷却

最终结果: 空仓（安全）
```

### 情况2: A未成交，B成交

```
持仓状态:
  Before: 空仓
  After:  空仓 A, Short B  ← 裸仓！

回滚操作:
  1. 立即市价平掉B
  2. reduce_only=True 防止意外反向开仓
  3. 记录失败，进入冷却

最终结果: 空仓（安全）
```

### 情况3: 两边都未成交

```
持仓状态:
  Before: 空仓
  After:  空仓

操作:
  无需回滚
  记录失败（网络或流动性问题）
```

---

## 冷却策略

### 指数退避算法

```python
def calculate_cooldown(failure_count: int) -> int:
    """
    计算冷却时间（指数退避）
    
    failure_count: 连续失败次数
    returns: 冷却分钟数
    """
    # 2^n 分钟，最大60分钟
    return min(2 ** failure_count, 60)

# 示例:
# failure_count=1 → 2分钟
# failure_count=2 → 4分钟
# failure_count=3 → 8分钟
# failure_count=4 → 16分钟
# failure_count=5 → 32分钟
# failure_count>=6 → 60分钟
```

### 冷却状态持久化

```python
def save_state(self):
    """保存持仓状态（含冷却信息）"""
    state_dict = {
        'pair': self.pair,
        'state': self.state.value,
        'cooldown_until': self.cooldown_until.isoformat() if self.cooldown_until else None,
        'failure_count': self.failure_count,
        # ... 其他字段
    }
    
    with open(f"data/position_{self.pair}.json", 'w') as f:
        json.dump(state_dict, f)
```

---

## 监控与告警

### 关键日志

```python
# 下单
logger.info(f"[ORDER] Placing synchronized orders for {pair}: {symbol_a} BUY {qty_a}, {symbol_b} SELL {qty_b}")

# 成交
logger.info(f"[FILL] Both legs filled: {symbol_a}={filled_a}, {symbol_b}={filled_b}")

# 回滚
logger.error(f"[ROLLBACK] Partial fill detected! Rolling back {symbol_to_close}")

# 冷却
logger.warning(f"[COOLDOWN] {pair} entering cooldown until {cooldown_until}")
```

### Telegram告警

```python
# 裸仓风险告警
if result.is_naked:
    notifier.send_message(
        f"🚨 NAKED POSITION RISK\n"
        f"Pair: {pair}\n"
        f"Status: {symbol_a}={filled_a}, {symbol_b}={filled_b}\n"
        f"Action: Rolling back..."
    )
```

---

## 相关文档

- [M6.1 Runtime 职责](M6-01-runtime-purpose.md)
- [M6.3 订单执行流程](M6-03-order-execution.md)
- [M6.4 风控检查点](M6-04-risk-checks.md)
- [src/runtime/order_executor.py](../../src/runtime/order_executor.py)
