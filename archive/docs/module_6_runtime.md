# 模块六：实盘监控 (Runtime) - P0 LOCKED

> **职责**: 状态机驱动实盘交易，双边同步下单，回滚保护，止损紧急平仓。
> **文件**: `src/runtime.py`
> **最后更新**: 2026-04-07

---

## 1. 数据流转

```
Input (来源):
  Config:     config/pairs_v2.json (M5 生成，含 E/X/S/Offset/Ratio/Step_Size)
  Real-time:  实时价格流 (1Hz 轮询交易所 ticker)
  State:      data/state.json (重启恢复用)

Processing:
  解析 JSON -> 构建内存 Execution Plan
  维护 Active Positions (状态机驱动)
  计算实时 Z-Score (由外部 SignalEngine 提供)
  驱动执行逻辑 (挂单、撤单、平仓)

Output (去向):
  Binance API: 下单 (Limit/Market)、撤单、查询
  State:       data/state.json (持久化，用于重启恢复)
  Logs/Alerts: Telegram 报警 (如 Sync Fail, Rollback)
```

---

## 2. 状态常量

| 常量 | 值 | 含义 |
|------|-----|------|
| `STATE_IDLE` | `"IDLE"` | 无持仓，等待信号 |
| `STATE_SCALING_IN` | `"SCALING_IN"` | 分批建仓中 |
| `STATE_IN_POSITION` | `"IN_POSITION"` | 满仓持有，等待止盈 |
| `STATE_SCALING_OUT` | `"SCALING_OUT"` | 分批平仓中 |
| `STATE_STOPPING` | `"STOPPING"` | 止损执行中 (过渡态) |
| `STATE_EXITED` | `"EXITED"` | 已完全退出 (一帧后重置为 IDLE) |
| `STATE_CLOSING_MODE` | `"CLOSING_MODE"` | 热重载关闭模式，只平不开 |

---

## 3. 超时/重试常量

| 常量 | 值 | 用途 |
|------|-----|------|
| `ORDER_CONFIRM_TIMEOUT` | `90` (秒) | 限价单轮询确认成交超时 |
| `ORDER_CONFIRM_INTERVAL` | `5` (秒) | 轮询检查订单状态的间隔 |
| `EMERGENCY_CLOSE_RETRIES` | `3` (次) | 市价紧急平仓最大重试次数 |
| `EMERGENCY_CLOSE_TIMEOUT` | `15` (秒) | 市价紧急平仓单确认超时 |
| `STATE_FILE` | `Path("data/state.json")` | 状态持久化文件路径 |

---

## 4. PositionState 类

单个配对的持仓状态，管理状态机属性。

### 4.1 `__init__(self, pair_config: Dict)`

从配对配置初始化。

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `pair_config` | `Dict` | - | 配对原始配置 (来自 pairs_v2.json) |
| `symbol_a` | `str` | - | 腿 A 的 symbol (从 pair_config 提取) |
| `symbol_b` | `str` | - | 腿 B 的 symbol (从 pair_config 提取) |
| `beta` | `float` | `1.0` | 对冲比率 |
| `state` | `str` | `STATE_IDLE` | 当前状态机状态 |
| `direction` | `int` | `0` | 方向: `1` = Long Spread (买 A 卖 B), `-1` = Short Spread (卖 A 买 B) |
| `entry_z` | `float` | `0.0` | 进场时的 Z-Score |
| `scale_in_layer` | `int` | `0` | 已完成的建仓层数 (0-based, 指向下一待触发层) |
| `scale_out_layer` | `int` | `0` | 已完成的平仓层数 (0-based, 指向下一待触发层) |
| `position_size_pct` | `float` | `0.0` | 当前持仓占总仓位的百分比 (0.0 ~ 1.0) |
| `pending_orders` | `Dict` | `{}` | 挂中的订单字典 (预留字段) |
| `entry_price_a` | `float` | `0.0` | 腿 A 成交均价 |
| `entry_price_b` | `float` | `0.0` | 腿 B 成交均价 |
| `last_signal_bar` | `int` | `0` | 上次信号 K 线索引 |
| `last_check_time` | `float` | `0.0` | 上次 check_signals 调用时间 (1Hz 限频用) |

### 4.2 `to_dict(self) -> Dict`

序列化为可存储字典，仅包含需要持久化的字段：

```python
{
    "state": str,
    "direction": int,
    "entry_z": float,
    "scale_in_layer": int,
    "scale_out_layer": int,
    "position_size_pct": float,
    "entry_price_a": float,
    "entry_price_b": float,
}
```

### 4.3 `from_dict(cls, pair_config: Dict, data: Dict) -> PositionState`

从持久化数据恢复。新建实例后逐个赋值 `state`, `direction`, `entry_z`, `scale_in_layer`, `scale_out_layer`, `position_size_pct`, `entry_price_a`, `entry_price_b`。未提供的字段使用 `.get()` 默认值。

---

## 5. Runtime 类

### 5.1 `__init__`

```python
Runtime(
    config_manager=None,   # ConfigManager 实例
    persistence=None,      # Persistence 实例 (预留)
    exchange_api=None,     # ExchangeAPI 实例
    notifier=None,         # Notifier 实例 (Telegram 告警)
    monitor=None,          # Monitor 实例 (Kill Switch / 交易记录)
)
```

| 属性 | 说明 |
|------|------|
| `positions: Dict[str, PositionState]` | pair_key -> PositionState 映射 |
| `_running: bool` | 运行标志 |
| `_check_interval: float` | check_signals 限频间隔，默认 `1.0` 秒 |
| `_price_cache: Dict[str, float]` | symbol -> price 缓存 |

---

### 5.2 方法清单

#### `async start(self)`

启动 Runtime 引擎。

1. `self._load_pair_configs()` — 加载配对配置
2. `await self._reconcile_positions()` — 与交易所持仓对账 (Ghost/Orphan 检测)
3. `await self._load_state()` — 从 state.json 恢复持久化状态
4. 设置 `_running = True`

#### `_load_pair_configs(self)`

从 `config_manager.pairs_data["pairs"]` 遍历，为每个新配对创建 `PositionState` 并加入 `self.positions`。pair_key 格式: `"{symbol_a}_{symbol_b}"`。仅添加 `pair_key` 不在 `self.positions` 中的新配对。

#### `async _reconcile_positions(self)`

启动时与交易所实际持仓对账。

1. 调用 `exchange_api.get_positions()` 获取交易所持仓
2. 构建交易所持仓映射 `ex_map[symbol] = {"side": "long"|"short", "contracts": float}`
3. 构建本地有仓位的 symbol 集合 (state != STATE_IDLE)
4. **Ghost 检测**: `ex_keys - local_syms` — 交易所有持仓但本地无记录 → 自动接管，标记 `STATE_IN_POSITION`, `position_size_pct = 1.0`, 补充 `entry_z` (从 pair_config params), `entry_price_a/b` (从 _price_cache) [FIX P1-1]
5. **Orphan 检测**: `local_syms - ex_keys` — 本地有记录但交易所无持仓 → 调用 `_reset_position()` 清理

#### `async _load_state(self)`

从 `STATE_FILE` (`data/state.json`) 恢复状态。遍历文件中每个 pair_key，若存在于 `self.positions` 中且 `saved_ps.state != STATE_IDLE`，则恢复所有字段 (`state`, `direction`, `entry_z`, `scale_in_layer`, `scale_out_layer`, `position_size_pct`, `entry_price_a`, `entry_price_b`)。文件不存在则跳过。

#### `async _save_state(self)`

原子写入状态到磁盘。

1. 过滤出 `state != STATE_IDLE` 的 PositionState，调用 `to_dict()`
2. `os.makedirs(STATE_FILE.parent, exist_ok=True)`
3. 写入临时文件 `data/state.json.tmp`
4. `os.replace(tmp_path, STATE_FILE)` — 原子替换

#### `async _validate_json_md5(self, path: str) -> bool`

读取文件二进制内容，计算 MD5 hexdigest 并记录日志。文件不存在返回 `False`。异常时返回 `False`。

#### `async _fetch_prices(self, symbols: List[str])`

批量获取价格更新缓存。遍历 symbols，调用 `exchange_api.fetch_ticker(sym)`，提取 `last` 或 `close` 字段存入 `self._price_cache[sym]`。

#### `async _get_price(self, symbol: str) -> float`

获取最新价格。优先使用 `_price_cache`；无缓存时调用 `fetch_ticker` 实时查询并更新缓存。[FIX P0-3] `_calculate_quantity` 中 fallback 从 `1.0` 改为 `0.0`，价格为 0 时拒绝下单并返回 `qty=0.0`，防止 BTC 等高价币下单量爆炸 10 万倍。

#### `async check_signals(self, pair_key: str, z: float, current_bar: int = 0)`

1Hz 主循环调用，状态机驱动核心方法。

**原子级流程**:

1. **1Hz 限频**: `now - ps.last_check_time < _check_interval` → 直接返回
2. **止损检查** (最高优先级，所有非空仓状态): `abs(z) >= stop_trigger` 且 `ps.state not in (STATE_IDLE, STATE_EXITED)` → 调用 `_execute_stop_loss(ps)` 并返回
3. **按状态分支**:

   | 状态 | 行为 |
   |------|------|
   | `STATE_IDLE` | 检查 Kill Switch (`monitor.is_trading_paused()`) → 若暂停则返回；检查 `z >= z_entry` → Short Spread (`direction=-1`)；检查 `z <= -z_entry` → Long Spread (`direction=1`)；触发后设 `state=SCALING_IN`, `scale_in_layer=0`，调用 `_execute_scale_in(ps, scale_in, z)` |
   | `STATE_SCALING_IN` | 检查下一层 `scale_in[next_layer]` 的 `trigger_z` 是否达到 (direction=-1 则 `z >= trigger_z`, direction=1 则 `z <= -trigger_z`) → 调用 `_execute_scale_in_layer(ps, scale_in, next_layer)`；若 `position_size_pct >= 0.99` → 转 `STATE_IN_POSITION` |
   | `STATE_IN_POSITION` | 检查下一层 `scale_out[next_out]` 的 `trigger_z` 是否达到 (direction=-1 则 `z <= trigger_z`, direction=1 则 `z >= -trigger_z`) → 调用 `_execute_scale_out_layer(ps, scale_out, next_out)`；若 `position_size_pct <= 0.01` 且 `scale_out_layer > 0` → 转 `STATE_EXITED` |
   | `STATE_SCALING_OUT` | 同 IN_POSITION 止盈逻辑；若 `position_size_pct <= 0.01` → 转 `STATE_EXITED` |
   | `STATE_EXITED` | 调用 `_reset_position(ps)` + `_save_state()`，重置为 IDLE |
   | `STATE_CLOSING_MODE` | 只检查止盈/止损 (止损已在顶部统一检查)；执行 scale_out 层；若 `position_size_pct <= 0.01` → 转 `STATE_EXITED`；不开新仓 |

#### `async _execute_scale_in(self, ps, scale_in, z)`

执行第一层建仓。调用 `_execute_scale_in_layer(ps, scale_in, 0)`。

#### `async _execute_scale_in_layer(self, ps, scale_in, layer)`

执行指定层建仓。

1. 从 `scale_in[layer]` 提取 `ratio`, `order_type` (默认 `"limit"`), `post_only` (默认 `True`)
2. 调用 `execute_sync_open(ps, ps.direction, ratio, order_type, post_only)`
3. 若成功: `scale_in_layer = layer + 1`, `position_size_pct += ratio`，调用 `_save_state()`

#### `async _execute_scale_out_layer(self, ps, scale_out, layer, z=0.0)`

执行指定层平仓。[FIX P0-4] 签名新增 `z` 参数，所有 6 处调用传入实时 `z`，`TradeRecord.z_out` 不再为 0。

1. 从 `scale_out[layer]` 提取 `ratio`, `order_type` (默认 `"market"`), `post_only` (默认 `False`)
2. 调用 `execute_sync_close(ps, ps.direction, ratio, order_type, post_only)`
3. 若成功: `scale_out_layer = layer + 1`, `position_size_pct = max(0, position_size_pct - ratio)`，调用 `_save_state()`
4. 若 `position_size_pct <= 0.01`，调用 `monitor.record_trade(TradeRecord(...))` 记录交易

#### `async _execute_stop_loss(self, ps)`

执行止损: Cancel All + Market Close Both Legs。

1. `ps.state = STATE_STOPPING`
2. 调用 `_cancel_all_orders(ps)`
3. 调用 `execute_sync_close(ps, ps.direction, ps.position_size_pct, order_type="market")`
4. 若失败 → 调用 `_emergency_close_both(ps)`
5. 异常时发 TG 告警 + 调用 `_emergency_close_both(ps)`
6. 调用 `_reset_position(ps)`，设 `state = STATE_EXITED`，调用 `_save_state()`

#### `async execute_sync_open(self, ps, direction, ratio, order_type="limit", post_only=True) -> bool`

双边同步开仓。

1. 无 exchange_api → 返回 `True` (dry-run)
2. 确定方向: `direction=1` → leg_a=`buy`, leg_b=`sell`；`direction=-1` → leg_a=`sell`, leg_b=`buy`
3. 调用 `_fetch_prices([symbol_a, symbol_b])` 获取真实价格
4. 调用 `_calculate_quantity` 计算 `qty_a`, `qty_b`
5. `asyncio.gather` 并发下单双腿
6. **双腿都成功**:
   - 调用 `_wait_order_filled` 轮询确认双腿成交 (超时 `ORDER_CONFIRM_TIMEOUT`)
   - 都成交 → 返回 `True`
   - 超时 → 调用 `_cancel_and_check` 撤单后二次确认真实状态
     - 若撤单后发现双腿都已成交 → 接受开仓，返回 `True`
     - 否则 → 用真实状态调用 `execute_rollback`，返回 `False`
7. **任一腿失败**: 调用 `execute_rollback(ps, success_a, success_b, leg_a_side, leg_b_side)`，返回 `False`

#### `async _wait_order_filled(self, symbol, order_id, timeout) -> bool`

轮询确认订单成交。

1. 每隔 `ORDER_CONFIRM_INTERVAL` (5s) 调用 `fetch_order(order_id, symbol)`
2. `status == "closed"` → 返回 `True`
3. `status in ("canceled", "rejected", "expired")` → 返回 `False`
4. 超时 → 返回 `False`

#### `async _cancel_and_check(self, order_id, symbol) -> str`

撤单后二次确认，防止幽灵成交。

1. 调用 `cancel_order(order_id, symbol)` (异常忽略，可能已成交)
2. 轮询 3 次 `fetch_order`:
   - `status == "closed"` 且 `filled >= amount * 0.9` → 返回 `"filled"`，否则 `"partial"`
   - `status in ("canceled", "expired", "rejected")` → 返回 `"canceled"`
3. 3 次都失败 → 返回 `"unknown"`

#### `async execute_sync_close(self, ps, direction, ratio, order_type="market", post_only=False) -> bool`

双边同步平仓。**所有平仓单 `reduce_only=True`**。

1. 无 exchange_api → 返回 `True`
2. 平仓方向与开仓相反: `direction=1` → leg_a=`sell`, leg_b=`buy`；`direction=-1` → leg_a=`buy`, leg_b=`sell`
3. 计算 `qty_a`, `qty_b` (不重新 fetch 价格，使用缓存)
4. `asyncio.gather` 并发下单双腿，`reduce_only=True`
5. 双腿都成功 → 返回 `True`
6. 任一腿失败 → 调用 `execute_rollback`，返回 `False`

#### `async execute_rollback(self, ps, success_a, success_b, side_a, side_b)`

回滚: 对已成交的腿发送市价平仓单。

1. 发 TG 告警 (Leg Sync Fail)
2. 对 `success_a=True` 的腿: 反向下单 `qty = _calculate_quantity(symbol_a, 1.0)`，调用 `_emergency_close`
3. 对 `success_b=True` 的腿: 同理
4. 异常时发 TG 紧急告警

#### `async _emergency_close(self, symbol, qty, side, leg_name) -> bool`

紧急市价平仓，带重试和确认。

1. 最多重试 `EMERGENCY_CLOSE_RETRIES` (3) 次
2. 每次: 下单 `market`, `reduce_only=True` → 调用 `_wait_order_filled(symbol, order_id, EMERGENCY_CLOSE_TIMEOUT)`
3. 成交 → 发 TG 成功通知，返回 `True`
4. 全部失败 → 发 TG 紧急告警 ("请立即手动处理")，返回 `False`
5. 重试间隔: `asyncio.sleep(2)`

#### `async _emergency_close_both(self, ps)`

止损失败时的紧急双平。

1. 按 `ps.direction` 计算双腿平仓方向和数量
2. 依次调用 `_emergency_close` 平腿 A 和腿 B

#### `async _cancel_all_orders(self, ps)`

撤销指定配对的所有未成交挂单。调用 `exchange_api.cancel_all_orders(symbol_a)` 和 `cancel_all_orders(symbol_b)`。

#### `async _reset_position(self, ps)`

重置配对状态为 IDLE。清零所有字段: `state=STATE_IDLE`, `direction=0`, `entry_z=0.0`, `scale_in_layer=0`, `scale_out_layer=0`, `position_size_pct=0.0`, `entry_price_a=0.0`, `entry_price_b=0.0`。

#### `_calculate_quantity(self, symbol, ratio) -> float`

计算下单数量。[FIX P0-3] `_price_cache.get(symbol, 0.0)` 替代 `1.0` fallback，价格为 0 时返回 `0.0` 并记录警告，拒绝下单。公式 `qty = (max_position_value * ratio) / price`。

1. 从 `config_manager` 获取 `allocation.max_position_value_usd` (默认 5000.0)
2. 从 `_price_cache` 获取当前价格 (默认 0.0，<=0 时拒绝下单返回 0.0) [FIX P0-3]
3. `notional = max_position_value * ratio`
4. `qty = notional / current_price`
5. 从 `config_manager` 获取 `exchange_meta.step_size` (默认 0.001)，向下取整对齐: `qty = int(qty / step_size) * step_size`
6. 返回 `max(qty, 0.001)` 确保最小下单量

#### `handle_hot_reload(self, new_pairs_data: Dict)`

热重载: 合并新配置。

1. 遍历新配置中的 pairs，pair_key 不在 `self.positions` 中的 → 新建 `PositionState` 加入
2. 遍历 `self.positions`，不在新配置中的:
   - `state == STATE_IDLE` → 从 `self.positions` 删除
   - `state != STATE_IDLE` (有持仓) → `state = STATE_CLOSING_MODE` (只平不开)

#### `stop(self)`

设置 `_running = False`。

---

## 6. 状态机完整转换图

```
                    ┌──────────────────────────────────────────────────────────────┐
                    │                                                              │
                    ▼                                                              │
┌─────────┐    z >= z_entry / z <= -z_entry    ┌──────────────┐                   │
│  IDLE   │ ──────────────────────────────────►│ SCALING_IN   │                   │
│         │ ◄───────────────────────────────── │              │                   │
│ (初始态) │   _reset_position (EXITED 后)      │ 分批建仓中     │                   │
└────┬────┘                                    └──────┬───────┘                   │
     │                                               │                           │
     │                              position_size_pct >= 0.99                     │
     │                                               │                           │
     │                                               ▼                           │
     │                                        ┌──────────────┐                    │
     │                                        │ IN_POSITION  │                    │
     │                                        │              │                    │
     │                                        │ 满仓持有      │                    │
     │                                        └──────┬───────┘                    │
     │                                               │                           │
     │                     z 达到 scale_out trigger    │                           │
     │                                               ▼                           │
     │               ┌──────────────┐          ┌──────────────┐                  │
     │               │   EXITED     │◄─────────│ SCALING_OUT  │                  │
     │               │              │ 完全平仓  │              │                  │
     │               └──────┬───────┘          └──────────────┘                  │
     │                      │                                                    │
     │     _reset_position  │                                                    │
     │                      │                                                    │
     │                      ▼                                                    │
     │                (回到 IDLE)                                                │
     │                                                                           │
     │  ┌─ 任何非 IDLE/EXITED 状态 ──────────────────────────────────────────┐   │
     │  │                                                                  │   │
     │  │  abs(z) >= stop_loss.trigger_z                                   │   │
     │  │                                                                  │   │
     │  │  ▼                                                               │   │
     │  │  ┌──────────┐                                                    │   │
     │  └─►│ STOPPING │ ── _reset_position + state=EXITED ─────────────────┘   │
     │     │          │                                                        │
     │     │ 止损执行  │                                                        │
     │     └──────────┘                                                        │
     │                                                                         │
     │  ┌─ Hot Reload 移除有持仓的 Pair ──────────────────────────────────┐    │
     │  │                                                                 │    │
     │  │  ▼                                                              │    │
     │  │  ┌────────────────┐                                            │    │
     └────┤ CLOSING_MODE   │ ── 只执行止盈/止损，position_size_pct<=0.01 ─┘    │
          │                │     → EXITED → IDLE                               │
          │ 只平不开新仓    │                                                   │
          └────────────────┘
```

### 状态转换表

| 起始状态 | 触发条件 | 目标状态 | 触发来源 |
|----------|----------|----------|----------|
| `IDLE` | `z >= z_entry` 或 `z <= -z_entry` | `SCALING_IN` | `check_signals` |
| `SCALING_IN` | `position_size_pct >= 0.99` | `IN_POSITION` | `check_signals` |
| `SCALING_IN` | `abs(z) >= stop_loss.trigger_z` | `STOPPING` → `EXITED` → `IDLE` | `check_signals` |
| `IN_POSITION` | `z` 达到 scale_out trigger 且完全平仓 | `EXITED` → `IDLE` | `check_signals` |
| `IN_POSITION` | `abs(z) >= stop_loss.trigger_z` | `STOPPING` → `EXITED` → `IDLE` | `check_signals` |
| `SCALING_OUT` | `position_size_pct <= 0.01` | `EXITED` → `IDLE` | `check_signals` |
| `SCALING_OUT` | `abs(z) >= stop_loss.trigger_z` | `STOPPING` → `EXITED` → `IDLE` | `check_signals` |
| `CLOSING_MODE` | `position_size_pct <= 0.01` | `EXITED` → `IDLE` | `check_signals` |
| `CLOSING_MODE` | `abs(z) >= stop_loss.trigger_z` | `STOPPING` → `EXITED` → `IDLE` | `check_signals` |
| `任何非IDLE/EXITED` | `abs(z) >= stop_loss.trigger_z` | `STOPPING` → `EXITED` → `IDLE` | `check_signals` |
| `非IDLE (热重载移除)` | Hot Reload | `CLOSING_MODE` | `handle_hot_reload` |
| `IDLE (热重载移除)` | Hot Reload | 从 positions 删除 | `handle_hot_reload` |
| `EXITED` | `_reset_position` | `IDLE` | `check_signals` / `_execute_stop_loss` |

---

## 7. 双边同步下单流程

### 7.1 开仓流程 (execute_sync_open)

```
execute_sync_open(ps, direction, ratio, order_type="limit", post_only=True)
    │
    ├── 确定方向: direction=1 → A买B卖; direction=-1 → A卖B买
    │
    ├── _fetch_prices([symbol_a, symbol_b])    // 获取真实价格
    │
    ├── _calculate_quantity(symbol_a, ratio)   // 精度对齐计算 qty_a
    ├── _calculate_quantity(symbol_b, ratio)   // 精度对齐计算 qty_b
    │
    ├── asyncio.gather(                        // 并发下单双腿
    │       place_order(symbol_a, ...),
    │       place_order(symbol_b, ...)
    │   )
    │
    ├── 双腿都成功? ──否──► execute_rollback(ps, success_a, success_b, ...)
    │                       │
    │                       └── 对已成交腿市价平仓
    │
    └── 是
        │
        ├── _wait_order_filled(order_id_a, 90s)    // 轮询确认腿A
        ├── _wait_order_filled(order_id_b, 90s)    // 轮询确认腿B
        │
        ├── 都成交? ──是──► 返回 True (开仓成功)
        │
        └── 否 (超时)
            │
            ├── _cancel_and_check(order_id_a, symbol_a)    // 撤单+二次确认
            ├── _cancel_and_check(order_id_b, symbol_b)    // 撤单+二次确认
            │
            ├── 撤单后发现双腿都已成交? ──是──► 返回 True (接受开仓)
            │
            └── 否
                │
                └── execute_rollback(ps, real_filled_a, real_filled_b, ...)
                    │
                    └── 用真实成交状态决定回滚哪条腿
```

### 7.2 平仓流程 (execute_sync_close)

```
execute_sync_close(ps, direction, ratio, order_type="market", post_only=False)
    │
    ├── 反向确定: direction=1 → A卖B买; direction=-1 → A买B卖
    │
    ├── _calculate_quantity(symbol_a, ratio)    // 使用缓存价格
    ├── _calculate_quantity(symbol_b, ratio)
    │
    ├── asyncio.gather(                          // 并发下单双腿
    │       place_order(symbol_a, ..., reduce_only=True),   // ← P0: reduceOnly
    │       place_order(symbol_b, ..., reduce_only=True)    // ← P0: reduceOnly
    │   )
    │
    ├── 双腿都成功? ──是──► 返回 True
    │
    └── 否
        │
        └── execute_rollback(ps, success_a, success_b, ...)
```

---

## 8. 回滚保护逻辑

### 8.1 触发场景

| 场景 | 触发点 | 回滚动作 |
|------|--------|----------|
| 开仓时一腿下单失败 | `execute_sync_open` gather 后检查 | 对成功腿市价平仓 |
| 开仓时一腿确认超时且未成交 | `_wait_order_filled` 超时 | 撤单 + 二次确认 + 对真实成交腿平仓 |
| 开仓时撤单后发现一腿成交另一腿未成交 | `_cancel_and_check` 后 | 对真实成交腿市价平仓 |
| 平仓时一腿下单失败 | `execute_sync_close` gather 后检查 | 对成功腿市价平仓 |

### 8.2 execute_rollback 执行流程

```
execute_rollback(ps, success_a, success_b, side_a, side_b)
    │
    ├── 发 TG 告警: "Leg Sync Fail on {pair}. Rolled back..."
    │
    ├── success_a? ──是──► close_side_a = 反向(side_a)
    │                      qty_a = _calculate_quantity(symbol_a, 1.0)
    │                      _emergency_close(symbol_a, qty_a, close_side_a, "腿A")
    │                      │
    │                      ├── 最多重试 3 次 (EMERGENCY_CLOSE_RETRIES)
    │                      ├── 每次: place_order(market, reduce_only=True)
    │                      ├── 每次: _wait_order_filled(timeout=15s)
    │                      └── 全部失败 → TG 紧急告警 "请立即手动处理"
    │
    └── success_b? ──是──► 同上，针对腿B
```

### 8.3 _emergency_close 重试机制

```
for attempt in range(EMERGENCY_CLOSE_RETRIES):    // 3 次
    │
    ├── place_order(symbol, "market", side, qty, reduce_only=True)
    │
    ├── _wait_order_filled(order_id, EMERGENCY_CLOSE_TIMEOUT)   // 15s 轮询
    │
    ├── 成交? ──是──► TG 通知 "紧急平仓成功" → 返回 True
    │
    └── 否 ──► asyncio.sleep(2) → 下一次重试

// 全部失败
TG 紧急告警: "市价平仓失败 3 次，请立即手动处理!" → 返回 False
```

---

## 9. 裸仓防护铁律 (P0)

| # | 规则 | 代码位置 |
|---|------|----------|
| 1 | 所有平仓单必须 `reduceOnly=True` | `execute_sync_close`, `_emergency_close` |
| 2 | 限价单下单后必须轮询确认成交 | `_wait_order_filled` (90s timeout, 5s interval) |
| 3 | 回滚必须验证市价平仓成功 | `_emergency_close` (3 retries, 15s timeout each) |
| 4 | 每次状态变更后持久化到 state.json | `_save_state` (原子写入 .tmp + os.replace) |
| 5 | 开仓前检查余额充足性 | `check_signals` 中 Kill Switch 检查 (`monitor.is_trading_paused()`) |
| 6 | Ghost 持仓自动接管 | `_reconcile_positions` (启动时扫描交易所持仓) |
| 7 | 撤单后二次确认防止幽灵成交 | `_cancel_and_check` (3 次轮询 fetch_order) |
| 8 | 止损触发后 Cancel All + 市价全平 | `_execute_stop_loss` |
| 9 | 紧急平仓失败后 TG 告警人工介入 | `_emergency_close` 全部失败路径 |
| 10 | 真实价格下单 (非硬编码) | `_calculate_quantity` 使用 `_price_cache` |
