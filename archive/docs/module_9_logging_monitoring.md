# 模块九：日志管理 (Logging) - ✅ LOCKED

> **最后更新**: 2026-04-07 — 以代码为唯一基准 (monitor_logger.py)
>
> **职责边界**: M9 仅关注日志格式化 / 轮转 / 路由。M7 Monitor 的 PnL 统计、Kill Switch、Telegram 推送见 [module_7_monitoring.md](./module_7_monitoring.md)。

---

## 1. JSONFormatter

继承 `logging.Formatter`，将 `LogRecord` 序列化为单行 JSON 字符串。

### 输出字段

| 字段 | 类型 | 来源 | 必填 |
|------|------|------|------|
| `ts` | string | `datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()` | ✅ |
| `level` | string | `record.levelname` (DEBUG/INFO/WARNING/ERROR/CRITICAL) | ✅ |
| `module` | string | `record.name` (即 `get_logger()` 传入的 module_name) | ✅ |
| `event` | string | `record.getMessage()` (格式化后的日志消息) | ✅ |
| `pair` | string | `record.pair` (若存在) | 可选 |
| `trace_id` | string | `record.trace_id` (若存在) | 可选 |
| `data` | object | `record.extra_data` (若存在，任意可序列化对象) | 可选 |

### format() 方法逻辑

```python
def format(self, record: logging.LogRecord) -> str:
    log_entry = {
        "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
        "level": record.levelname,
        "module": record.name,
        "event": record.getMessage(),
    }
    if hasattr(record, "pair"):
        log_entry["pair"] = record.pair
    if hasattr(record, "trace_id"):
        log_entry["trace_id"] = record.trace_id
    if hasattr(record, "extra_data"):
        log_entry["data"] = record.extra_data
    return json.dumps(log_entry, ensure_ascii=False)
```

### 使用方式

通过给 LogRecord 添加自定义属性来附带结构化数据：

```python
logger = logger_manager.get_logger("PairEngine")
record = logger.makeRecord(
    "PairEngine", logging.INFO, "", 0,
    "LEG_SYNC_FAILURE", (), None
)
record.pair = "BTC/ETH"
record.trace_id = "a1b2c3d4"
record.extra_data = {"leg_a": "filled", "leg_b": "timeout_3s"}
logger.handle(record)
```

### JSON 输出完整示例

```json
{
  "ts": "2026-04-07T10:00:00.123456+00:00",
  "level": "ERROR",
  "module": "Runtime",
  "event": "LEG_SYNC_FAILURE",
  "pair": "BTC/ETH",
  "trace_id": "a1b2c3d4",
  "data": {"leg_a": "filled", "leg_b": "timeout_3s"}
}
```

不含可选字段时的精简输出：

```json
{"ts": "2026-04-07T10:00:01.000000+00:00", "level": "INFO", "module": "Runtime", "event": "System started successfully"}
```

---

## 2. LoggerManager

日志管理器：提供结构化 JSON 输出 + 日志轮转 + 分级路由。

### 2.1 `__init__(log_dir: str = "logs")`

```python
def __init__(self, log_dir: str = "logs"):
    self.log_dir = log_dir
    os.makedirs(log_dir, exist_ok=True)
    self._loggers: Dict[str, logging.Logger] = {}
    # 启动自检: 清理过期日志
    self.cleanup_old_logs(max_age_days=30)
```

- 创建日志目录（若不存在）
- 初始化内部 logger 缓存字典 `_loggers`
- **启动自检**: 立即调用 `cleanup_old_logs(max_age_days=30)` 清理 30 天前的过期日志

### 2.2 `get_logger(module_name: str) -> logging.Logger`

返回已配置好 JSON 格式与轮转策略的 `logging.Logger` 实例。支持缓存复用。

```python
def get_logger(self, module_name: str) -> logging.Logger:
    if module_name in self._loggers:
        return self._loggers[module_name]

    logger = logging.getLogger(module_name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    # 三个 handler 配置 ...
    self._loggers[module_name] = logger
    return logger
```

**Handler 配置详情**:

| Handler | 类型 | 目标文件/流 | 级别 | 格式化器 | 轮转 |
|---------|------|-------------|------|----------|------|
| `system_handler` | `RotatingFileHandler` | `{log_dir}/system.log` | **INFO+** | `JSONFormatter()` | 50MB, 30 备份 |
| `error_handler` | `RotatingFileHandler` | `{log_dir}/error.log` | **ERROR+** | `JSONFormatter()` | 50MB, 30 备份 |
| `console_handler` | `StreamHandler` | stdout/stderr | **INFO+** | `%(asctime)s [%(levelname)s] %(name)s: %(message)s` | 无 |

- Logger 自身级别设为 `DEBUG`（允许所有级别通过，由各 handler 的级别过滤）
- 通过 `if logger.handlers` 防止重复添加 handler
- 所有文件 handler 均使用 `encoding="utf-8"`

### 2.3 日志分级路由

```
                    ┌───────────────┐
                    │  LogRecord    │
                    │  (any level)  │
                    └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ system.log │ │ error.log  │ │  console   │
     │  JSON      │ │  JSON      │ │  text      │
     │  INFO+     │ │  ERROR+    │ │  INFO+     │
     │ 50MB×30    │ │ 50MB×30    │ │            │
     └────────────┘ └────────────┘ └────────────┘
```

- **DEBUG 级别**: 仅被 logger 接受，不被任何 handler 输出（所有 handler 最低 INFO）
- **INFO / WARNING**: 写入 `system.log` (JSON) + 打印到控制台 (文本)
- **ERROR / CRITICAL**: 写入 `system.log` (JSON) + 写入 `error.log` (JSON) + 打印到控制台 (文本)

### 2.4 `cleanup_old_logs(max_age_days: int = 30)`

启动自检方法，清理超过指定天数的过期日志文件。

```python
def cleanup_old_logs(self, max_age_days: int = 30):
    now = time.time()
    cleaned = 0
    for pattern in ["system.log*", "error.log*", "trade.log*", "debug.log*"]:
        for f in glob.glob(os.path.join(self.log_dir, pattern)):
            if now - os.path.getmtime(f) > max_age_days * 86400:
                try:
                    os.unlink(f)
                    cleaned += 1
                except OSError as e:
                    logging.getLogger("LoggerManager").debug(f"Failed to cleanup old log {f}: {e}")
    if cleaned > 0:
        logging.getLogger("LoggerManager").info(f"cleanup_old_logs: removed {cleaned} expired log files")
```

- **扫描模式**: `system.log*`, `error.log*`, `trade.log*`, `debug.log*` (包含轮转备份如 `system.log.1`)
- **判断条件**: `当前时间 - 文件修改时间 > max_age_days × 86400 秒`
- **操作**: 直接 `os.unlink()` 删除，不压缩
- **统计**: 清理完毕后输出 INFO 日志记录删除数量

---

## 3. 日志轮转配置

两个文件 handler 使用完全相同的轮转参数：

| 参数 | 值 | 说明 |
|------|-----|------|
| Handler 类型 | `RotatingFileHandler` | Python 标准库 |
| `maxBytes` | `50 * 1024 * 1024` | 单文件上限 50MB |
| `backupCount` | `30` | 保留 30 个备份文件 (`.1` ~ `.30`) |
| `encoding` | `"utf-8"` | 文件编码 |

轮转行为：当 `system.log` 达到 50MB 时，自动重命名为 `system.log.1`（旧的 `.1` → `.2`，以此类推），超过 30 个备份的最旧文件被删除。

---

## 4. 与 M7 Monitor 的关系

`monitor_logger.py` 同时包含 M9 (`LoggerManager`, `JSONFormatter`) 和 M7 (`Monitor`, `TradeRecord`, `TelegramNotifier`, `MockNotifier`)。

### 职责分离

| 模块 | 关注点 | 核心能力 |
|------|--------|----------|
| **M9 LoggerManager** | 日志基础设施 | JSON 格式化、分级路由、轮转、过期清理 |
| **M7 Monitor** | 交易监控 | PnL 统计、回撤计算、Kill Switch、Telegram 通知、日报 |

### 日志集成方式

- `LoggerManager.get_logger(module_name)` 为指定模块名配置 handler 并缓存
- `Monitor` 类内部通过 `logging.getLogger("Monitor")` 获取 logger
- 当 `LoggerManager.get_logger("Monitor")` 被调用后，`logging.getLogger("Monitor")` 返回的是同一个已配置好 JSON 格式和轮转策略的 logger 对象（Python logging 模块的全局 registry 机制）
- M7 Monitor 的 PnL 记录、Kill Switch 触发、日报发送等业务事件，通过此 logger 输出到 `system.log` / `error.log` / 控制台

### 关键区别

- **M9 产出**: 结构化日志文件（`logs/system.log`, `logs/error.log`），供运维审计、问题排查
- **M7 产出**: 实时 Telegram 消息（成交通知、Kill Switch 报警、日报），供人工监控
- **M7 的 `_notify_sync`**: 处理 async notifier 在 sync 上下文的调用，与 M9 的日志系统独立

---

## 5. 完整使用示例

```python
from src.monitor_logger import LoggerManager

# 1. 创建 LoggerManager (自动创建 logs/ 目录 + 清理 30 天前过期日志)
logger_mgr = LoggerManager(log_dir="logs")

# 2. 获取已配置的 logger
logger = logger_mgr.get_logger("Runtime")

# 3. 常规日志 (输出到 system.log + console)
logger.info("System started successfully")
logger.warning("API rate limit approaching")

# 4. 错误日志 (输出到 system.log + error.log + console)
logger.error("LEG_SYNC_FAILURE for BTC/ETH")

# 5. 带结构化数据的日志 (通过 LogRecord 自定义属性)
record = logger.makeRecord(
    "PairEngine", logging.ERROR, "", 0,
    "Leg sync timeout", (), None
)
record.pair = "BTC/ETH"
record.trace_id = "a1b2c3d4"
record.extra_data = {"leg_a": "filled", "leg_b": "timeout_3s"}
logger.handle(record)
# → {"ts":"2026-04-07T10:00:00.123456+00:00","level":"ERROR",
#    "module":"PairEngine","event":"Leg sync timeout",
#    "pair":"BTC/ETH","trace_id":"a1b2c3d4",
#    "data":{"leg_a":"filled","leg_b":"timeout_3s"}}

# 6. 手动清理过期日志
logger_mgr.cleanup_old_logs(max_age_days=7)
```
