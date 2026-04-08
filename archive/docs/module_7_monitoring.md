# 模块七 + 模块九：监控、统计与日志 (Monitor + LoggerManager) - ✅ LOCKED

> **最后更新**: 2026-04-07 — 以 `src/monitor_logger.py` 代码为唯一基准
> **文件路径**: `src/monitor_logger.py`

---

## 1. TradeRecord 类

单笔交易记录数据类。

### 构造函数

```python
TradeRecord(pair: str, realized_pnl: float, hold_time_min: float = 0, z_in: float = 0, z_out: float = 0)
```

### 属性

| 属性 | 类型 | 说明 |
|---|---|---|
| `pair` | `str` | 交易对名称 (如 "BTCUSDT") |
| `realized_pnl` | `float` | 已实现盈亏 (正数=盈利, 负数=亏损) |
| `hold_time_min` | `float` | 持仓时长 (分钟), 默认 `0` |
| `z_in` | `float` | 入场 Z-Score, 默认 `0` |
| `z_out` | `float` | 出场 Z-Score, 默认 `0` |
| `timestamp` | `str` | ISO 8601 格式时间戳 (UTC), 构造时自动生成 |
| `trade_date` | `str` | 归属日期 (格式 `YYYY-MM-DD`), 构造时自动生成 |

---

## 2. Monitor 类

实时监控：账户权益、PnL、回撤、胜率、盈亏比、Kill Switch、Telegram 推送。

### 构造函数

```python
Monitor(notifier=None, stats_path: str = "data/daily_stats.json")
```

**参数:**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `notifier` | `Notifier \| None` | `None` | 通知器实例 (TelegramNotifier / MockNotifier) |
| `stats_path` | `str` | `"data/daily_stats.json"` | 每日统计数据持久化路径 |

**内部状态变量:**

| 变量 | 类型 | 初始值 | 说明 |
|---|---|---|---|
| `notifier` | `Notifier \| None` | 传入值 | 通知器引用 |
| `stats_path` | `str` | 传入值 | 统计文件路径 |
| `start_equity` | `float` | `0.0` | 起始权益 (每日重置时用) |
| `peak_equity` | `float` | `0.0` | 历史最高权益 |
| `current_equity` | `float` | `0.0` | 当前权益 |
| `daily_pnl` | `float` | `0.0` | 当日累计盈亏 |
| `gross_profit` | `float` | `0.0` | 当日累计盈利总额 |
| `gross_loss` | `float` | `0.0` | 当日累计亏损总额 |
| `wins` | `int` | `0` | 盈利交易笔数 |
| `losses` | `int` | `0` | 亏损交易笔数 |
| `max_drawdown` | `float` | `0.0` | 最大回撤比例 (0~1) |
| `trades` | `List[TradeRecord]` | `[]` | 当日交易记录列表 |
| `_daily_stats` | `Dict` | `{}` | 加载的历史每日统计 |
| `_alert_flags` | `Dict` | `{"risk_high": False}` | 报警标记 |
| `trading_paused` | `bool` | `False` | Kill Switch 暂停标志 (供 Runtime 检查) |
| `pause_reason` | `str` | `""` | 暂停原因描述 |
| `pause_time` | `float` | `0.0` | 暂停时间戳 (`time.time()`) |

---

### 方法详表

#### 2.1 `is_trading_paused() -> bool`

供 Runtime 检查是否应该暂停开仓。Kill Switch 触发时返回 `True`。

```python
def is_trading_paused(self) -> bool:
    return self.trading_paused
```

#### 2.2 `get_pause_reason() -> str`

返回当前暂停原因字符串。未暂停时返回空字符串。

```python
def get_pause_reason(self) -> str:
    return self.pause_reason
```

#### 2.3 `resume_trading()`

手动恢复交易。需人工确认后调用，清除暂停状态和原因。

```python
def resume_trading(self):
    self.trading_paused = False
    self.pause_reason = ""
```

#### 2.4 `initialize(equity: float)`

初始化监控状态，在系统启动时调用。

```python
def initialize(self, equity: float):
    self.start_equity = equity
    self.current_equity = equity
    self.peak_equity = equity
    self._load_daily_stats()
```

**行为:**
- 设置 `start_equity`、`current_equity`、`peak_equity` 为传入值
- 调用 `_load_daily_stats()` 加载历史统计

#### 2.5 `record_trade(trade: TradeRecord)`

记录单笔交易结果，更新胜率、PF、权益，推送成交通知。由 Runtime 在成交确认后调用。

```python
def record_trade(self, trade: TradeRecord):
```

**执行流程:**

1. 将 `trade` 追加到 `self.trades` 列表
2. `daily_pnl += trade.realized_pnl`
3. `current_equity = start_equity + daily_pnl`
4. 分类统计:
   - `realized_pnl > 0` → `gross_profit += realized_pnl`, `wins += 1`
   - `realized_pnl <= 0` → `gross_loss += abs(realized_pnl)`, `losses += 1`
5. 更新 `peak_equity` 和 `max_drawdown`:
   - 若 `current_equity > peak_equity` → 更新峰值
   - 计算 `dd = (peak_equity - current_equity) / peak_equity`
   - 若 `dd > max_drawdown` → 更新最大回撤
6. 若 `notifier` 存在，推送成交通知 (含 pair/PnL%/Hold/Z_In/Z_Out)
7. 调用 `_save_daily_stats()` 持久化统计

#### 2.6 `_notify_sync(level: str, message: str)`

同步通知包装器，处理 async notifier 在 sync 上下文中的调用。

```python
def _notify_sync(self, level: str, message: str):
```

**Level 到方法映射:**

| level | 调用的 notifier 方法 |
|---|---|
| `"INFO"` | `send_info(message)` |
| `"WARNING"` | `send_warning(message)` |
| `"CRITICAL"` | `send_critical(message)` |
| 其他 | 默认 `send_info(message)` |

**执行逻辑:**

1. 通过 `inspect.iscoroutinefunction` 判断方法是否为协程
2. **异步路径:**
   - 通过 `asyncio.get_running_loop()` 获取事件循环
   - `loop.create_task(method(message))` 创建任务
   - 保存 task 引用到 `self._pending_tasks` (防止 GC 回收)
   - 注册 `task.add_done_callback(self._cleanup_task)` 自动清理
3. **无事件循环时:** 缓存消息到 `self._message_queue` (待后续处理)
4. **同步路径:** 直接调用 `method(message)`

#### 2.7 `_cleanup_task(task)`

清理已完成的任务引用。

```python
def _cleanup_task(self, task):
    if hasattr(self, "_pending_tasks"):
        self._pending_tasks.remove(task)  # 忽略 ValueError
```

#### 2.8 `update_account(equity: float)`

更新账户权益，计算回撤，检查报警阈值。由外部定时调用 (建议每 5 分钟)。

```python
def update_account(self, equity: float):
    self.current_equity = equity
    if equity > self.peak_equity:
        self.peak_equity = equity
    if self.peak_equity > 0:
        dd = (self.peak_equity - equity) / self.peak_equity
        if dd > self.max_drawdown:
            self.max_drawdown = dd
    self._check_alerts(equity)
```

#### 2.9 `_check_alerts(equity: float)`

检查报警阈值，触发 Kill Switch 或风险警告。

```python
def _check_alerts(self, equity: float):
```

**报警阈值完整定义:**

| 条件 | 阈值 | 级别 | 动作 |
|---|---|---|---|
| 最大回撤 `max_drawdown > 0.15` | **15%** | CRITICAL | **Kill Switch**: 设置 `trading_paused=True`, 记录 `pause_reason`, 记录 `pause_time`, 推送 CRITICAL 通知, 写入 CRITICAL 日志 |
| 日亏损 `-daily_pnl / start_equity > 0.03` | **3%** | WARNING | 推送 WARNING 通知, 设置 `_alert_flags["risk_high"]=True` (仅触发一次) |

**Kill Switch 详细行为:**
```python
self.trading_paused = True
self.pause_reason = f"Max Drawdown {max_drawdown:.2%} exceeds 15% limit"
self.pause_time = time.time()
self._notify_sync("CRITICAL", "🚨 KILL SWITCH ACTIVATED: ...")
```

**日亏损警告详细行为:**
- 仅在 `risk_high` 标记为 `False` 时触发 (一次性报警)
- 发送后可通过 `send_daily_report()` 重置标记

#### 2.10 `get_stats() -> Dict`

获取当前统计数据，返回完整字典。

```python
def get_stats(self) -> Dict:
```

**返回值完整结构 (13 个字段):**

| 字段 | 类型 | 计算方式 |
|---|---|---|
| `date` | `str` | 当前 UTC 日期 (`YYYY-MM-DD`) |
| `start_equity` | `float` | 当日起始权益 |
| `current_equity` | `float` | 当前权益 |
| `daily_pnl` | `float` | 当日盈亏 (四舍五入至 2 位小数) |
| `daily_pnl_pct` | `float` | 当日盈亏百分比: `daily_pnl / (start_equity + 1e-8) * 100` (四舍五入至 2 位小数) |
| `trades_count` | `int` | 总交易笔数: `wins + losses` |
| `wins` | `int` | 盈利笔数 |
| `losses` | `int` | 亏损笔数 |
| `win_rate` | `float` | 胜率: `wins / trades_count` (0~1, 四舍五入至 4 位小数) |
| `profit_factor` | `float` | 盈亏比: `gross_profit / (gross_loss + 1e-8)` (四舍五入至 2 位小数) |
| `max_drawdown_pct` | `float` | 最大回撤百分比: `max_drawdown * 100` (四舍五入至 2 位小数) |
| `peak_equity` | `float` | 历史最高权益 (四舍五入至 2 位小数) |
| `trading_paused` | `bool` | Kill Switch 暂停状态 |
| `pause_reason` | `str` | 暂停原因 (未暂停时为空字符串) |

#### 2.11 `send_daily_report()`

生成并发送 Telegram 日报。先保存统计再发送，发送失败不清零。

```python
def send_daily_report(self):
```

**执行流程:**

1. 调用 `get_stats()` 获取当前统计
2. 调用 `_save_daily_stats()` 持久化当前统计
3. 若 `notifier` 存在，格式化并发送日报消息 (含净值/盈亏/交易笔数/胜率/PF/回撤/系统状态)
4. **重置当日计数器:**
   ```python
   self.daily_pnl = 0.0
   self.wins = 0
   self.losses = 0
   self.gross_profit = 0.0
   self.gross_loss = 0.0
   self.start_equity = self.current_equity
   self._alert_flags = {"risk_high": False}
   ```

**日报消息格式:**
```
📊 [日报] YYYY-MM-DD
💰 净值: XXXXXX (+XXXX (+X.X%))
📈 交易: N 笔 (胜率 X% | PF X.X)
📉 最大回撤: X.X%
✅ 系统状态: Normal / ⚠️ 系统状态: PAUSED / ⚠️ 系统状态: RISK_HIGH
```

#### 2.12 `_load_daily_stats()`

加载历史每日统计 JSON 文件。

```python
def _load_daily_stats(self):
    if os.path.exists(self.stats_path):
        try:
            with open(self.stats_path, "r") as f:
                self._daily_stats = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._daily_stats = {}
```

**行为:** 文件不存在或解析失败时静默降级为空字典。

#### 2.13 `_save_daily_stats()`

保存当前统计到 JSON 文件。

```python
def _save_daily_stats(self):
    stats = self.get_stats()
    stats_dir = os.path.dirname(os.path.abspath(self.stats_path))
    os.makedirs(stats_dir, exist_ok=True)
    try:
        with open(self.stats_path, "w") as f:
            json.dump(stats, f, indent=2)
    except OSError as e:
        logging.getLogger("Monitor").error(f"Failed to save daily stats: {e}")
```

**行为:** 自动创建父目录，写入失败时记录 ERROR 日志。

---

## 3. TelegramNotifier 类

Telegram Bot 异步通知器。

### 构造函数

```python
TelegramNotifier(bot_token: str, chat_id: str)
```

**参数:**

| 参数 | 类型 | 说明 |
|---|---|---|
| `bot_token` | `str` | Telegram Bot Token |
| `chat_id` | `str` | 目标聊天 ID |

**内部属性:**

| 属性 | 类型 | 说明 |
|---|---|---|
| `bot_token` | `str` | 存储的 Bot Token |
| `chat_id` | `str` | 存储的 Chat ID |
| `_base_url` | `str` | `"https://api.telegram.org/bot{bot_token}"` |

### 方法

#### 3.1 `async send_info(message: str)`

发送 INFO 级别消息。直接调用 `_send(message)`。

#### 3.2 `async send_warning(message: str)`

发送 WARNING 级别消息。前缀 `⚠️ ` 后调用 `_send(f"⚠️ {message}")`。

#### 3.3 `async send_critical(message: str)`

发送 CRITICAL 级别消息。前缀 `🚨🚨 ` 后调用 `_send(f"🚨🚨 {message}")`。

#### 3.4 `async _send(message: str)`

实际发送实现 (HTTP POST to Telegram API)。

**发送策略 (自动降级):**

1. **优先路径: aiohttp**
   - 若 `aiohttp` 可导入，使用异步 HTTP POST
   - URL: `{_base_url}/sendMessage`
   - Payload: `{"chat_id": chat_id, "text": message, "parse_mode": "HTML"}`
   - 超时: 10 秒
   - 失败时记录 ERROR 日志 (含状态码和响应文本)

2. **降级路径: urllib (同步)**
   - 若 `aiohttp` 不可用，回退到 `urllib.request` 同步发送
   - 使用 `application/x-www-form-urlencoded` 编码
   - 超时: 10 秒
   - 失败时记录 ERROR 日志

---

## 4. MockNotifier 类

测试用 Mock 通知器，收集所有发送的消息供断言验证。

### 构造函数

```python
MockNotifier()
```

**内部属性:**

| 属性 | 类型 | 说明 |
|---|---|---|
| `messages` | `List[str]` | 消息列表，每个元素为 `(level, message)` 元组 |

### 方法

| 方法 | 签名 | 行为 |
|---|---|---|
| `send_info` | `async def send_info(self, message: str)` | `self.messages.append(("INFO", message))` |
| `send_warning` | `async def send_warning(self, message: str)` | `self.messages.append(("WARNING", message))` |
| `send_critical` | `async def send_critical(self, message: str)` | `self.messages.append(("CRITICAL", message))` |

---

## 5. 报警阈值完整定义

| 报警名称 | 检查条件 | 阈值 | 级别 | 触发行为 | 重复触发 |
|---|---|---|---|---|---|
| **Kill Switch** | `max_drawdown > 0.15` | **15%** | CRITICAL | 设置 `trading_paused=True`, 设置 `pause_reason`, 记录 `pause_time`, 推送 CRITICAL 通知, 写入 CRITICAL 日志 | 仅首次触发 (检查 `not self.trading_paused`) |
| **RISK_HIGH** | `-daily_pnl / start_equity > 0.03` | **3%** | WARNING | 推送 WARNING 通知, 设置 `_alert_flags["risk_high"]=True` | 仅首次触发 (检查 `not _alert_flags["risk_high"]`) |

**重置时机:**
- `risk_high` 标记在 `send_daily_report()` 中重置
- `trading_paused` 标记在 `resume_trading()` 中手动重置

---

## 6. 数据统计完整字段

`_save_daily_stats()` 写入 `data/daily_stats.json` 的内容，即 `get_stats()` 返回的完整字典：

```json
{
  "date": "YYYY-MM-DD",
  "start_equity": 0.0,
  "current_equity": 0.0,
  "daily_pnl": 0.0,
  "daily_pnl_pct": 0.0,
  "trades_count": 0,
  "wins": 0,
  "losses": 0,
  "win_rate": 0.0,
  "profit_factor": 0.0,
  "max_drawdown_pct": 0.0,
  "peak_equity": 0.0,
  "trading_paused": false,
  "pause_reason": ""
}
```

共 **14 个字段**。JSON 以 `indent=2` 格式化写入。

---

## 7. 类关系与数据流

```
Runtime ──(成交确认)──→ Monitor.record_trade(TradeRecord)
                          │
                          ├── 更新 daily_pnl / wins / losses / gross_profit / gross_loss
                          ├── 更新 peak_equity / max_drawdown
                          ├── Monitor._notify_sync() → TelegramNotifier.send_info()
                          └── Monitor._save_daily_stats() → data/daily_stats.json

外部定时器 ──(每5分钟)──→ Monitor.update_account(equity)
                            │
                            ├── 更新 current_equity / peak_equity / max_drawdown
                            └── Monitor._check_alerts()
                                 ├── DD>15% → Kill Switch → trading_paused=True
                                 └── 日亏>3% → RISK_HIGH 警告

外部定时/手动 ──→ Monitor.send_daily_report()
                    ├── 先 _save_daily_stats()
                    ├── 再 _notify_sync() 发送格式化日报
                    └── 重置当日计数器 (daily_pnl/wins/losses/gross_profit/gross_loss/
                                        start_equity/_alert_flags)
```

---

## 8. Notifier 接口契约

所有 Notifier 实现必须提供以下三个 async 方法：

| 方法 | 签名 |
|---|---|
| `send_info` | `async def send_info(self, message: str)` |
| `send_warning` | `async def send_warning(self, message: str)` |
| `send_critical` | `async def send_critical(self, message: str)` |

当前实现:
- `TelegramNotifier` — 通过 Telegram Bot API 发送消息
- `MockNotifier` — 收集消息到列表，用于测试
