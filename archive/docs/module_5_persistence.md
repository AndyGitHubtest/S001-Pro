# 模块五：持久化与落地 (Persistence) - P0 LOCKED

> **职责**: 将 M4 优化器输出的 Top 30 白名单序列化为 config/pairs_v2.json，包含完整的分批进出场策略与交易所元数据注入。
> **最后更新**: 2026-04-08 - scale_in offsets [-0.3, 0.0, 0.3], M4推荐参数在中间, 止损在L3后生效
> **代码路径**: `src/persistence.py`

---

## 1. 数据流转

| 阶段 | 来源/去向 | 说明 |
|------|-----------|------|
| Input | M4 优化器 | `whitelist: List[Dict]`，含最优参数 (z_entry, z_exit, z_stop, beta 等) |
| Output | `config/pairs_v2.json` | 物理文件，含计算好的绝对 trigger_z 值 |
| Consumer | M6 Runtime | 实时读取此文件执行交易 |

---

## 2. 常量定义

### 2.1 SCALE_IN_PLAN — 分批进场策略 (3-3-4 比例)

围绕最优甜点 (z_entry) 分布的三层进场计划，**M4推荐参数(z_entry)处于中间位置**:

| 层级 | offset_z | ratio | type | post_only | 说明 |
|------|----------|-------|------|-----------|------|
| L1 | -0.3 | 0.3 | limit | True | 提前埋伏 30% (entry前0.3) |
| L2 | 0.0 | 0.3 | limit | True | 最优entry点 30% (M4推荐, 处于中间) |
| L3 | 0.3 | 0.4 | limit | True | 极端兜底 40% (entry后0.3) |

完整定义 (代码行 39-55):

```python
SCALE_IN_PLAN = [
    {"offset_z": -0.3, "ratio": 0.3, "type": "limit", "post_only": True},  # Layer 1: 提前埋伏
    {"offset_z": 0.0, "ratio": 0.3, "type": "limit", "post_only": True},   # Layer 2: 最优entry点(中间)
    {"offset_z": 0.3, "ratio": 0.4, "type": "limit", "post_only": True},   # Layer 3: 极端兜底
]
```

### 2.2 SCALE_OUT_PLAN — 分批出场策略

| 层级 | trigger_z | ratio | type | post_only | 说明 |
|------|-----------|-------|------|-----------|------|
| TP1 | Entry × 0.6 | 0.3 | limit | True | 回撤40%出30% (Z 回落到 entry 的 60%) |
| TP2 | Exit | 0.4 | limit | True | 到达exit出40% (Z 回到目标退出值) |
| TP3 | Mean | 0.3 | market | False | 靠近mean出30% (Z 回到动态滚动均值, 市价全平) |

完整定义 (代码行 63-67):

```python
SCALE_OUT_PLAN = [
    {"trigger_z": "Entry * 0.6", "ratio": 0.3, "type": "limit", "post_only": True},  # 回撤40%出30%
    {"trigger_z": "Exit", "ratio": 0.4, "type": "limit", "post_only": True},         # 到达exit出40%
    {"trigger_z": "Mean", "ratio": 0.3, "type": "market", "post_only": False},       # 靠近mean出30%
]
```

### 2.3 STOP_LOSS_PLAN — 止损策略 (L3完成后生效)

| 属性 | 值 | 说明 |
|------|-----|------|
| trigger_z | L3 + StopOffset | 止损在L3完成后才生效，距离 = L3位置 + (z_stop - z_entry) = z_stop + 0.3 |
| type | market | 市价单确保立即成交 |
| post_only | False | 止损不挂单 |

**计算公式**: `trigger_z = (z_entry + 0.3) + (z_stop - z_entry) = z_stop + 0.3`

完整定义 (代码行 70-74):

```python
STOP_LOSS_PLAN = {
    "trigger_z": "z_stop + 0.3",  # L3在 z_entry+0.3, 止损在 z_stop + 0.3
    "type": "market",
    "post_only": False,
}
```

---

## 3. 核心函数

### 3.1 compute_md5(filepath: str) -> str

计算文件 MD5 校验值，用于持久化写入后的完整性校验。

```python
def compute_md5(filepath: str) -> str:
    """计算文件 MD5"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
```

- 以 8192 字节分块读取，避免大文件内存溢出
- 返回 32 字符十六进制字符串

### 3.2 _compute_scale_in_triggers(z_entry: float) -> List[Dict]

根据 z_entry 计算三层进场的**绝对** trigger_z 值。

**核心公式**: `trigger_z = z_entry + offset_z`

| 层级 | offset_z | 计算公式 | 说明 |
|------|----------|----------|------|
| L1 | -0.3 | trigger_z = z_entry - 0.3 | 提前埋伏 30% |
| L2 | 0.0 | trigger_z = z_entry + 0.0 | 最优entry点 30% (M4推荐, 中间位置) |
| L3 | 0.3 | trigger_z = z_entry + 0.3 | 极端兜底 40% |

```python
def _compute_scale_in_triggers(z_entry: float) -> List[Dict]:
    """
    根据 z_entry 计算实际 scale_in trigger_z 绝对值。

    三层触发:
      Layer 1: trigger_z = z_entry - 0.3 (提前埋伏, entry前0.3)
      Layer 2: trigger_z = z_entry + 0.0 (最优entry点, M4推荐, 中间位置)
      Layer 3: trigger_z = z_entry + 0.3 (极端兜底, entry后0.3)
    """
    triggers = []
    for step in SCALE_IN_PLAN:
        abs_z = z_entry + step["offset_z"]
        triggers.append({
            "trigger_z": round(abs_z, 2),
            "ratio": step["ratio"],
            "type": step["type"],
            "post_only": step["post_only"],
        })
    return triggers
```

### 3.3 _compute_scale_out_triggers(z_entry: float, z_exit: float, mean_z: float = 0.0) -> List[Dict]

根据 z_entry, z_exit, mean_z 计算三层出场的**绝对** trigger_z 值。

| 层级 | trigger_z 计算 | ratio | type | 说明 |
|------|----------------|-------|------|------|
| TP1 | z_entry × 0.6 | 0.3 | limit | 回撤40%出30% (Z 回落到 entry 的 60%) |
| TP2 | z_exit | 0.4 | limit | 到达exit出40% (Z 回到目标退出值) |
| TP3 | mean_z | 0.3 | market | 靠近mean出30% (Z 回到动态滚动均值, 市价全平) |

```python
def _compute_scale_out_triggers(z_entry: float, z_exit: float, mean_z: float = 0.0) -> List[Dict]:
    """
    根据 z_entry, z_exit, mean_z 计算实际 scale_out trigger_z 绝对值。

    规则:
      TP1: Entry * 0.6 (Z 回落到 entry 的 60%)
      TP2: Exit (Z 回到目标退出值)
      TP3: mean_z (Z 回到动态滚动均值, 市价全平)
             注: mean_z 由调用方根据历史 spread 计算, 默认 0.0
    """
    return [
        {"trigger_z": round(z_entry * 0.6, 2), "ratio": 0.3, "type": "limit", "post_only": True},
        {"trigger_z": round(z_exit, 2), "ratio": 0.4, "type": "limit", "post_only": True},
        {"trigger_z": round(mean_z, 2), "ratio": 0.3, "type": "market", "post_only": False},
    ]
```

### 3.4 _compute_stop_loss_trigger(z_entry: float, z_stop: float) -> Dict

计算止损的**绝对** trigger_z 值。

**核心公式**: `trigger_z = L3位置 + (z_stop - z_entry) = (z_entry + 0.3) + (z_stop - z_entry) = z_stop + 0.3`

**L3后生效的原因**: 止损在L3完成后才生效，保持止损距离与M4回测一致。
例如: entry=2.5, stop=4.0 → L3@2.8, 止损@2.8+(4.0-2.5)=4.3

```python
def _compute_stop_loss_trigger(z_entry: float, z_stop: float) -> Dict:
    """
    计算止损 trigger_z 绝对值。

    规则: trigger_z = L3位置 + (z_stop - z_entry) = z_stop + 0.3
    L3在 z_entry + 0.3 (最后一批进场)
    止损必须在L3完成后才生效
    止损距离保持与M4回测一致 = z_stop - z_entry
    例如: entry=2.5, stop=4.0 → L3@2.8, 止损@2.8+(4.0-2.5)=4.3
    """
    return {
        "trigger_z": round(z_stop + 0.3, 2),
        "type": "market",
        "post_only": False,
    }
```

---

## 4. Persistence 类

### 4.1 类定义

```python
class Persistence:
    def __init__(self):
        self._last_save_path: Optional[str] = None
        self._last_md5: Optional[str] = None
```

### 4.2 save() 方法

```python
def save(
    self,
    whitelist: List[Dict],
    path: str = "config/pairs_v2.json",
    git_hash: Optional[str] = None,
    exchange_meta_provider=None,
) -> bool:
```

#### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| whitelist | List[Dict] | 必填 | M4 优化器输出的 Top 30 列表 |
| path | str | "config/pairs_v2.json" | 目标文件路径 |
| git_hash | Optional[str] | None | 当前 git commit hash |
| exchange_meta_provider | Callable | None | 提供 min_qty, step_size, price_precision 的回调函数 |

#### 原子写入流程

```
1. 检查 whitelist 是否为空 → 空则返回 False
2. 遍历每个配对，组装完整配置对象
3. 写入临时文件: config/pairs_v2.json.tmp
4. 计算临时文件 MD5: compute_md5(tmp_path)
5. 原子替换: os.replace(tmp_path, path)
6. 失败时清理: os.unlink(tmp_path)
```

**关键代码流程**:

```python
tmp_path = path + ".tmp"
try:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    
    # 写 tmp
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    # MD5 校验
    md5 = compute_md5(tmp_path)
    
    # 原子替换
    os.replace(tmp_path, path)
    return True
except Exception as e:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
    return False
```

#### save() 组装的每个 pair 对象结构

```python
pair_obj = {
    "signal_id": f"{sym_a}_{sym_b}_{timestamp}",
    "symbol_a": sym_a,                    # 例如 "BTC-USDT-SWAP"
    "symbol_b": sym_b,                    # 例如 "ETH-USDT-SWAP"
    "beta": beta,                         # 价差对冲系数
    "params": {
        "z_entry": z_entry,               # 默认 2.5
        "z_exit": z_exit,                 # 默认 0.8
        "z_stop": z_stop,                 # 默认 4.5
    },
    "exchange_meta": {
        "min_qty": 0.001,                 # 或由 exchange_meta_provider 覆盖
        "step_size": 3,
        "price_precision": 2,
    },
    "funding_info": {
        "current_rate": 0.0001,
        "cost_impact_pct": 0.05,
    },
    "allocation": {
        "max_position_value_usd": 5000.0,
        "risk_score": 0.85,
    },
    "execution": {
        "legs_sync": {
            "simultaneous": True,
            "tolerance_ms": 3000,
            "rollback_on_failure": True,
        },
        "scale_in": [...],                # _compute_scale_in_triggers(z_entry) 结果
        "scale_out": [...],               # _compute_scale_out_triggers(z_entry, z_exit) 结果
        "stop_loss": {...},               # _compute_stop_loss_trigger(z_entry, z_stop) 结果
    },
    "valid_until_iso": valid_until.isoformat(),  # now + 30 分钟
    "ttl_minutes": 30,
}
```

**z_entry / z_exit / z_stop 的取值逻辑** (代码行 164-166):

```python
z_entry = params.get("z_entry", item.get("z_entry", 2.5))
z_exit  = params.get("z_exit",  item.get("z_exit",  0.8))
z_stop  = params.get("z_stop",  item.get("z_stop",  4.5))
```

优先从 `item["params"]` 取，其次从 item 顶层取，最后使用硬编码默认值。

**exchange_meta_provider 注入逻辑** (代码行 218-221):

```python
if exchange_meta_provider:
    meta = exchange_meta_provider(sym_a, sym_b)
    if meta:
        pair_obj["exchange_meta"] = meta
```

**valid_until_iso 跨天安全修复** (FIX P1-3, 代码行 191):

```python
# 修复前: now.replace(hour=now.hour + 1) 在 23:xx 时 hour=24 → ValueError
# 修复后: 用 timedelta 安全计算
valid_until = now + timedelta(minutes=30)
```

#### save() 输出顶层结构

```python
output = {
    "meta": {
        "version": "1.0",
        "generated_at": now.isoformat(),
        "git_hash": git_hash or "unknown",
        "pairs_count": len(pairs),
    },
    "pairs": [...],
}
```

### 4.3 load() 方法

```python
def load(self, path: str = "config/pairs_v2.json") -> Optional[Dict]:
```

#### 校验逻辑 (五步校验)

| 步骤 | 校验项 | 失败行为 |
|------|--------|----------|
| 1 | 文件存在 (`os.path.exists`) | 返回 None |
| 2 | JSON 可解析 (`json.load`) | 捕获 JSONDecodeError，返回 None |
| 3 | 顶层有 `meta` 和 `pairs` 字段 | 返回 None |
| 4 | `pairs` 是列表类型 (`isinstance`) | 返回 None |
| 5 | 每个 pair 包含必需字段 | 返回 None |

**必需字段** (代码行 287):

```python
required = ["symbol_a", "symbol_b", "beta", "params", "execution"]
```

校验失败时记录具体缺失字段: `pair[{i}] missing field '{field}'`

#### load() 完整流程

```python
if not os.path.exists(path):
    return None

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

if "meta" not in data or "pairs" not in data:
    return None

pairs = data.get("pairs", [])
if not isinstance(pairs, list):
    return None

required = ["symbol_a", "symbol_b", "beta", "params", "execution"]
for i, pair in enumerate(pairs):
    for field in required:
        if field not in pair:
            return None

return data
```

---

## 5. JSON 完整 Schema

### 5.1 顶层结构

```json
{
  "meta": {
    "version": "string",           // 固定 "1.0"
    "generated_at": "string",      // ISO 8601 UTC 时间
    "git_hash": "string",          // git commit hash 或 "unknown"
    "pairs_count": "integer"       // pair 对象数量
  },
  "pairs": [PairObject, ...]       // 数组，每个元素见下方
}
```

### 5.2 PairObject 结构

```json
{
  "signal_id": "string",            // 格式: "{sym_a}_{sym_b}_{unix_timestamp}"
  "symbol_a": "string",             // 合约 A, 例如 "BTC-USDT-SWAP"
  "symbol_b": "string",             // 合约 B, 例如 "ETH-USDT-SWAP"
  "beta": "number",                 // 对冲系数, 例如 1.234
  "params": {
    "z_entry": "number",            // 进场 Z 值阈值
    "z_exit": "number",             // 退出 Z 值阈值
    "z_stop": "number"              // 止损 Z 值阈值
  },
  "exchange_meta": {
    "min_qty": "number",            // 最小下单量
    "step_size": "number",          // 数量步长 (精度位数)
    "price_precision": "number"     // 价格精度
  },
  "funding_info": {
    "current_rate": "number",       // 当前资金费率
    "cost_impact_pct": "number"     // 成本影响百分比
  },
  "allocation": {
    "max_position_value_usd": "number",  // 最大持仓价值 (USD)
    "risk_score": "number"               // 风险评分 (0-1)
  },
  "execution": {
    "legs_sync": {
      "simultaneous": "boolean",    // 是否同步执行双腿
      "tolerance_ms": "number",     // 同步容忍时间 (毫秒)
      "rollback_on_failure": "boolean"  // 失败是否回滚
    },
    "scale_in": [ScaleInStep, ...], // 进场触发数组 (见下方)
    "scale_out": [ScaleOutStep, ...],// 出场触发数组 (见下方)
    "stop_loss": StopLossStep       // 止损触发对象 (见下方)
  },
  "valid_until_iso": "string",      // 有效期 ISO 8601 (生成时间 + 30 分钟)
  "ttl_minutes": "number"           // TTL 分钟数, 固定 30
}
```

### 5.3 ScaleInStep (进场触发)

```json
{
  "trigger_z": "number",    // z_entry + offset_z (绝对值, 2位小数): L1@z_entry-0.3, L2@z_entry, L3@z_entry+0.3
  "ratio": "number",        // 仓位比例 (0.3, 0.3, 0.4)
  "type": "string",         // "limit"
  "post_only": "boolean"    // true
}
```

### 5.4 ScaleOutStep (出场触发)

```json
{
  "trigger_z": "number",    // 绝对值: TP1=z_entry*0.6, TP2=z_exit, TP3=mean_z(默认0.0)
  "ratio": "number",        // 仓位比例 (0.3, 0.4, 0.3)
  "type": "string",         // "limit" (TP1,TP2) 或 "market" (TP3)
  "post_only": "boolean"    // true (TP1,TP2) 或 false (TP3)
}
```

### 5.5 StopLossStep (止损触发)

```json
{
  "trigger_z": "number",    // L3 + (z_stop - z_entry) = z_stop + 0.3 (2位小数), L3完成后生效
  "type": "string",         // "market"
  "post_only": "boolean"    // false
}
```

### 5.6 完整 JSON 示例

```json
{
  "meta": {
    "version": "1.0",
    "generated_at": "2026-04-07T06:30:00+00:00",
    "git_hash": "abc123def",
    "pairs_count": 2
  },
  "pairs": [
    {
      "signal_id": "BTC-USDT-SWAP_ETH-USDT-SWAP_1744006200",
      "symbol_a": "BTC-USDT-SWAP",
      "symbol_b": "ETH-USDT-SWAP",
      "beta": 1.234,
      "params": {
        "z_entry": 2.5,
        "z_exit": 0.8,
        "z_stop": 4.5
      },
      "exchange_meta": {
        "min_qty": 0.001,
        "step_size": 3,
        "price_precision": 2
      },
      "funding_info": {
        "current_rate": 0.0001,
        "cost_impact_pct": 0.05
      },
      "allocation": {
        "max_position_value_usd": 5000.0,
        "risk_score": 0.85
      },
      "execution": {
        "legs_sync": {
          "simultaneous": true,
          "tolerance_ms": 3000,
          "rollback_on_failure": true
        },
        "scale_in": [
          {"trigger_z": 2.5, "ratio": 0.3, "type": "limit", "post_only": true},
          {"trigger_z": 2.8, "ratio": 0.3, "type": "limit", "post_only": true},
          {"trigger_z": 3.1, "ratio": 0.4, "type": "limit", "post_only": true}
        ],
        "scale_out": [
          {"trigger_z": 1.5, "ratio": 0.3, "type": "limit", "post_only": true},
          {"trigger_z": 0.8, "ratio": 0.4, "type": "limit", "post_only": true},
          {"trigger_z": 0.0, "ratio": 0.3, "type": "market", "post_only": false}
        ],
        "stop_loss": {
          "trigger_z": 5.0,
          "type": "market",
          "post_only": false
        }
      },
      "valid_until_iso": "2026-04-07T07:00:00+00:00",
      "ttl_minutes": 30
    }
  ]
}
```

---

## 6. 设计要点与修复记录

| 修复 | 问题 | 方案 |
|------|------|------|
| FIX P1-1 | scale_in 统一从 0.0 开始，双侧对称加仓 | Layer1@z_entry, Layer2@z_entry+0.3, Layer3@z_entry+0.6 |
| FIX P1-3 | `now.replace(hour=now.hour + 1)` 在 23:xx 时 hour=24 触发 ValueError | 改用 `timedelta(minutes=30)` |
| 止损L3后生效 | 避免过早被扫，保持与M4回测一致 | `trigger_z = L3 + (z_stop - z_entry) = z_stop + 0.6` |
| 原子写入 | Runtime 可能读到半写文件 | tmp → MD5 → os.replace 三步流程 |
