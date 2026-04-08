# 模块八：配置与参数管理 (ConfigManager)

> **职责**: 加载、校验、合并配置，支持环境变量注入与热重载。
> **源文件**: `src/config_manager.py` (P0 LOCKED)
> **最后更新**: 2026-04-07

---

## 1. 数据流转

```
  Input:
    Static Config:  config/base.yaml     (API Key, DB Path, Risk Limits, ...)
    Dynamic Config: config/pairs_v2.json (M5 生成，含交易参数、执行策略)
  Processing:
    启动加载 → Schema 校验 → 合并默认值 → 注入内存对象
    文件监听 (Watcher) → 检测变动 → 热重载 (Hot Reload)
  Output:
    Global Config Object: 供模块 1-9 全局只读调用
    Validation Errors: 若校验失败，阻断启动或回滚配置
```

---

## 2. 常量 DEFAULTS

完整默认值字典，四大部分：`system`、`exchange`、`risk`、`notifications`。

```python
DEFAULTS = {
    "system": {
        "env": "production",
        "log_level": "INFO",
        "timezone": "Asia/Shanghai",
        "data_dir": "./data",
        "log_dir": "./logs",
    },
    "exchange": {
        "name": "binance",
        "testnet": False,
        "rate_limit_rps": 5.0,
    },
    "risk": {
        "initial_capital": 10000.0,
        "max_drawdown_pct": 15.0,
        "max_daily_loss_pct": 5.0,
        "max_open_positions": 6,
        "isolated_margin": True,
    },
    "notifications": {
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "alert_level": "ERROR",
    },
}
```

**优先级**: 环境变量 > base.yaml 文件值 > DEFAULTS 默认值

---

## 3. 辅助函数

### 3.1 `_load_yaml_safe(path: str) -> Dict`

安全加载 YAML 文件。

```
1. try: import yaml → yaml.safe_load(f) → 返回结果 (空 dict 兜底)
2. except ImportError:
     记录 warning "PyYAML not installed, using simple parser"
     降级调用 _simple_yaml_parse(path)
```

### 3.2 `_simple_yaml_parse(path: str) -> Dict`

简易 YAML 解析器，仅支持**两级嵌套**的 `key: value`。

```
逐行读取，跳过空行和注释行 (# 开头):
  - 非缩进行 + 以 ":" 结尾 → 识别为 section 标题
    → current_section = 行内容(去除冒号)
    → result[current_section] = {}
  - 含 ":" 的行 + current_section 非空 → 键值对
    → 分割 key, val，去除引号
    → 类型转换: "true"/"false" → bool, 尝试 int, 尝试 float, 否则保留 string
    → result[current_section][key] = val
返回 result
```

### 3.3 `_deep_merge(base: Dict, override: Dict) -> Dict`

递归深度合并两个字典，`override` 优先。

```
result = base.copy()
for key, val in override.items():
    if key in result 且 两者都是 dict:
        result[key] = _deep_merge(result[key], val)
    else:
        result[key] = val
return result
```

---

## 4. ConfigManager 类

### 4.1 `__init__(self, config_dir: str = "config")`

```
实例属性:
  self.config_dir      = config_dir                      # 配置目录
  self.base_path       = os.path.join(config_dir, "base.yaml")
  self.pairs_path      = os.path.join(config_dir, "pairs_v2.json")
  self._config: Dict   = {}                              # 基础配置
  self._pairs_data: Dict = {}                            # 配对配置
  self._pairs_mtime: float = 0                           # pairs 文件 mtime
  self._callback: Optional[Callable] = None              # 热重载回调
  self._running: bool  = False                           # 监听器运行标志
```

### 4.2 `load_and_validate(self) -> Dict`

启动时加载全部配置，失败抛异常终止进程。

```
步骤:
1. 加载 base.yaml:
   if 文件存在:
     raw = _load_yaml_safe(self.base_path)
     self._config = _deep_merge(DEFAULTS, raw)   # DEFAULTS 为底，文件覆盖
   else:
     self._config = DEFAULTS.copy()
     记录 warning

2. 环境变量注入:
   self._inject_env_vars()                       # 优先级最高

3. 基础配置校验:
   self._validate_base_config()                  # 失败抛 ValueError

4. 加载 pairs_v2.json (如果存在):
   if 文件存在:
     self._load_pairs_config()                   # 内部含校验

5. return self._config
```

### 4.3 `_inject_env_vars(self)`

从环境变量注入敏感配置，覆盖已有值。

**环境变量映射表**:

| 环境变量 | 目标路径 | 类型处理 |
|---|---|---|
| `S001_BINANCE_API_KEY` | `exchange.api_key` | 字符串直写 |
| `S001_BINANCE_API_SECRET` | `exchange.api_secret` | 字符串直写 |
| `S001_TG_BOT_TOKEN` | `notifications.telegram_bot_token` | 字符串直写 |
| `S001_TG_CHAT_ID` | `notifications.telegram_chat_id` | 字符串直写 |
| `S001_TESTNET` | `exchange.testnet` | `lower()` in ("true", "1", "yes") → bool |
| `S001_INITIAL_CAPITAL` | `risk.initial_capital` | `float()` 转换，失败记录 warning |

```
遍历 env_map:
    val = os.environ.get(env_name)
    if val:
        确保 section 存在于 self._config
        if key == "testnet":
            self._config[section][key] = val.lower() in ("true", "1", "yes")
        else:
            self._config[section][key] = val
        记录 info log

特殊处理 S001_INITIAL_CAPITAL:
    val = os.environ.get("S001_INITIAL_CAPITAL")
    if val:
        确保 "risk" 存在于 self._config
        try: float(val) → self._config["risk"]["initial_capital"]
        except ValueError: 记录 warning
```

### 4.4 `_validate_base_config(self)`

严格校验基础配置，失败抛 `ValueError`。

```
1. 非 testnet 时必填项检查:
   if not exchange.get("testnet", False):
       if 缺少 api_key 或 api_secret:
           raise ValueError("api_key and api_secret are required for live trading...")

2. 范围检查:
   max_drawdown_pct > 0        → 否则 ValueError
   max_daily_loss_pct > 0      → 否则 ValueError
   max_open_positions > 0      → 否则 ValueError
```

### 4.5 `_load_pairs_config(self) -> bool`

加载并校验 `pairs_v2.json`。

```
1. try: json.load(self.pairs_path)
   except: 记录 error, return False

2. if not self._validate_pairs_data(data):
       return False

3. self._pairs_data = data
   self._pairs_mtime = os.path.getmtime(self.pairs_path)
   return True
```

### 4.6 `_validate_pairs_data(self, data: Dict) -> bool`

校验 `pairs_v2.json` 的结构和逻辑正确性。

```
1. 类型检查: data 必须是 dict
2. pairs 必须是 list

3. 遍历每个 pair:
   a. 必填字段: symbol_a, symbol_b, beta, params, execution
      缺失任何一个 → return False

   b. 逻辑检查 - z_entry < z_stop:
      z_entry = params.get("z_entry", 0)
      z_stop = params.get("z_stop", 0)
      if z_entry >= z_stop → return False

   c. 逻辑检查 - scale_in ratios 总和 ≈ 1.0:
      scale_in = execution.get("scale_in", [])
      if scale_in:
          total_ratio = sum(s.get("ratio", 0) for s in scale_in)
          if abs(total_ratio - 1.0) > 0.01 → return False

   d. 逻辑检查 - tolerance_ms > 0:
      tolerance = execution.get("legs_sync", {}).get("tolerance_ms", 0)
      if tolerance <= 0 → return False

4. 全部通过 → return True
```

### 4.7 `watch_config(self, callback: Callable)`

启动后台线程监控文件变动。

```
1. import threading
2. self._callback = callback
3. self._running = True
4. 创建 daemon 线程，target=_watcher (闭包)
5. thread.start()
```

### 4.8 `_watcher()` (watch_config 内部闭包)

后台轮询线程逻辑。

```
while self._running:
    time.sleep(2)

    if pairs_v2.json 存在:
        mtime = os.path.getmtime(pairs_path)
        if mtime > self._pairs_mtime:       # 检测到文件变动
            if self._load_pairs_config():   # 尝试热重载
                self._pairs_mtime = mtime   # 更新 mtime
                if self._callback:
                    self._callback("pairs_updated", self._pairs_data)
            else:
                记录 error "hot reload failed, keeping old config"
```

### 4.9 `stop_watching(self)`

```
self._running = False
记录 info "watcher stopped"
```

### 4.10 `get_pair_config(self, symbol_pair: str) -> Optional[Dict]`

获取指定交易对的完整执行参数。

```
symbol_pair 格式: "BTC/USDT_ETH/USDT" 或 "BTC/USDT-ETH/USDT"

key_normalized = symbol_pair.replace("-", "_")
遍历 pairs:
    pair_key = f"{pair['symbol_a']}_{pair['symbol_b']}"
    if pair_key == key_normalized:
        return pair
return None
```

### 4.11 `config` property -> Dict

返回 `self._config` (全局基础配置，只读语义)。

### 4.12 `pairs_data` property -> Dict

返回 `self._pairs_data` (配对配置，只读语义)。

---

## 5. 环境变量注入完整逻辑

```
注入时机: load_and_validate() 步骤 2，在 _deep_merge 之后、_validate_base_config 之前。

映射表 (6 个环境变量):
  S001_BINANCE_API_KEY     → exchange.api_key          (str)
  S001_BINANCE_API_SECRET  → exchange.api_secret       (str)
  S001_TG_BOT_TOKEN        → notifications.telegram_bot_token  (str)
  S001_TG_CHAT_ID          → notifications.telegram_chat_id    (str)
  S001_TESTNET             → exchange.testnet          (bool: lower in "true"/"1"/"yes")
  S001_INITIAL_CAPITAL     → risk.initial_capital      (float)

规则:
  - 仅当环境变量存在且非空时注入
  - 注入值覆盖配置文件中的对应值
  - testnet 字段做布尔转换
  - initial_capital 做 float 转换，失败时仅 warning 不阻断
```

---

## 6. 热重载流程

```
触发: watch_config(callback) 启动后台 daemon 线程
轮询: 每 2 秒检查 pairs_v2.json 的 mtime

检测到变动 (mtime > _pairs_mtime):
  1. 调用 _load_pairs_config()
     a. json.load() 读取新文件
     b. _validate_pairs_data() 校验新数据
     c. 校验通过:
        → self._pairs_data = 新数据
        → self._pairs_mtime = 新 mtime
        → callback("pairs_updated", self._pairs_data)
     d. 校验失败:
        → 记录 error "hot reload failed, keeping old config"
        → _pairs_data 不变 (回滚保护)
        → _pairs_mtime 不变 (下次仍会尝试)

停止: stop_watching() → _running = False → 线程自然退出
```

---

## 7. 完整接口汇总

```python
# 常量
DEFAULTS: Dict                                          # 完整默认值

# 辅助函数
_load_yaml_safe(path: str) -> Dict                      # 安全 YAML 加载
_simple_yaml_parse(path: str) -> Dict                   # 降级解析器
_deep_merge(base: Dict, override: Dict) -> Dict         # 递归深度合并

# ConfigManager 类
class ConfigManager:
    def __init__(self, config_dir: str = "config")
    def load_and_validate(self) -> Dict
    def _inject_env_vars(self)
    def _validate_base_config(self)
    def _load_pairs_config(self) -> bool
    def _validate_pairs_data(self, data: Dict) -> bool
    def watch_config(self, callback: Callable)
    def _watcher(self)              # watch_config 内部闭包
    def stop_watching(self)
    def get_pair_config(self, symbol_pair: str) -> Optional[Dict]
    @property
    def config(self) -> Dict
    @property
    def pairs_data(self) -> Dict
```
