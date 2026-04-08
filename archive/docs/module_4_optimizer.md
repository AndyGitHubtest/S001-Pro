# 模块四：回测优化 (Optimizer) - P0 LOCKED

> **职责**: 对 M3 给的 Top 100 配对做参数搜索，输出 Top 30 最优参数。
> **最后更新**: 2026-04-08 - 原子级对齐代码（IS_RATIO=0.81, MIN_PF_OS_GATE=1.5）

---

## 1. 数据流转

| 方向 | 说明 |
|------|------|
| **Input** | Top 100 候选配对列表（来自 M3）+ 90 天全量 K 线历史数据（来自 M1） |
| **Output** | Whitelist (List[Dict])，Top 30，传递给模块五 (Persistence) |

---

## 2. 常量定义

```python
Z_WARMUP = 200                  # Z-score 扩窗预热根数
IS_RATIO = 0.81                 # IS/OS 切分比例（前 81% 训练(IS), 后 19% 验证(OS)）
MIN_TRADES_HARD_GATE = 10       # 硬门槛: 90 天最少交易数
MAX_DD_HARD_GATE = 0.20         # 硬门槛: 最大回撤上限
MIN_PF_HARD_GATE = 1.5          # 硬门槛: 最小盈利因子（亏 1 必赚 1.5）
MIN_PF_OS_GATE = 1.5            # OS 验证门槛: PF >= 1.5 才放行
COST_PER_LEG = 0.0005           # 单腿成本（手续费 0.05% + 滑点 0.05%）
COST_ROUND_TRIP = COST_PER_LEG * 4  # 4 腿总成本 = 0.002
```

---

## 3. Numba JIT 加速

### HAS_NUMBA 检测与 Fallback

```python
try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*args, **kwargs):
        def decorator(f):
            return f
        return decorator
```

### _backtest_core — JIT 回测核心

```python
@njit(cache=True)
def _backtest_core(
    log_a: np.ndarray,
    log_b: np.ndarray,
    beta: float,
    z_entry: float,
    z_exit: float,
    z_stop: float,
    init_capital: float,
    cost_pct: float,
    early_abort_check: int = 0,
) -> tuple:
```

**返回值**: `(n_trades, wins, losses, gross_profit, gross_loss, max_dd, final_equity, early_abort)`

**核心逻辑**:
1. 数据量校验: `n < 300` 或 `n < Z_WARMUP + 100` 直接返回空结果
2. 计算 spread: `spread = log_a[:n] - beta * log_b[:n]`
3. Welford 增量算法计算 Z-score 序列（预热 Z_WARMUP=200 根）
4. 状态机回测: position 0→1（开仓）→ 出场条件检查 → 记录 PnL
5. 每笔交易扣除 4 腿成本: `total_cost = cost_pct * 4 * notional`
6. Early abort: 到达 `warmup + early_abort_check` 时 `trade_count < 2` 则提前终止

**出场条件**:
```python
abs_z >= z_stop
or (direction == -1 and z <= z_exit)
or (direction == 1 and z >= -z_exit)
```

---

## 4. PairBacktester 类

```python
class PairBacktester:
    @staticmethod
    def run(
        log_close_a: np.ndarray,
        log_close_b: np.ndarray,
        beta: float,
        z_entry: float,
        z_exit: float,
        z_stop: float,
        init_capital: float = 10000.0,
        cost_pct: float = COST_PER_LEG,     # 0.0005
        early_abort: bool = True,
    ) -> Dict:
```

**前置校验**: `n < 300` 或 `n < Z_WARMUP + 100` 返回 `None`

**early_abort 计算**: `early_check = int(n * 0.5)` 当 `early_abort=True`，否则为 `0`

**返回字段**:
```python
{
    'net_profit': final_equity - init_capital,
    'max_drawdown': max_dd,
    'n_trades': n_trades,
    'wins': wins,
    'losses': losses,
    'win_rate': wins / n_trades,
    'profit_factor': gross_profit / (gross_loss + 1e-8),
    'sharpe': avg_pnl / (std_pnl + 1e-8) * sqrt(n_trades),  # n_trades>1
    'final_equity': final_equity,
    'aborted': aborted,  # 0/1
}
```

---

## 5. _optimize_single_pair 函数

```python
def _optimize_single_pair(args) -> Dict:
```

**输入**: `args = (idx, total, sym_a, sym_b, beta, log_a, log_b)`

### IS/OS 切分

```python
n = min(len(log_a), len(log_b))
is_end = int(n * IS_RATIO)   # IS_RATIO = 0.81
log_a_is = log_a[:is_end]    # 前 81% 训练集(IS)
log_b_is = log_b[:is_end]
log_a_os = log_a[is_end:]    # 后 19% 验证集(OS)
log_b_os = log_b[is_end:]
# 任一部分 < 300 根直接返回 None
```

### Phase 1: 粗扫（IS 数据）

| 参数 | 取值 |
|------|------|
| entry | [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0] — **9 个** |
| exit | 固定 0.5 |
| stop | 固定 entry + 1.0 |

**过滤**: `stats['n_trades'] < 10` 或 `_score_result(stats) <= -1.0` 的跳过。按分数降序取 **Top 3 entry**。

### Phase 2: 精细搜索（IS 数据）

围绕每个 Top 3 entry 做网格搜索:

| 参数 | 范围 | 说明 |
|------|------|------|
| entry | `[best_e - 0.3, best_e + 0.3]`, 步长 0.1, 截断 [2.0, 7.0] | 约 7 个 |
| exit | [0.3, 0.8, 1.3] | 3 档止盈 |
| stop_offset | [0.5, 1.0, 1.5] | 3 档止损偏移 |
| z_stop | `round(entry + stop_offset, 1)` | — |

**合法性**: `x >= e` 或 `s <= e` 跳过。每组合调用 `PairBacktester.run`（IS 数据），要求 `n_trades >= 10`。

**搜索量**: 每个 Top entry 约 63 次，3 个共 **~189 次**。

### OS 验证

用最优参数跑后 33% 数据:

```python
os_stats = PairBacktester.run(
    log_a_os, log_b_os, beta,
    best_params['z_entry'], best_params['z_exit'], best_params['z_stop'],
    early_abort=False
)
if os_stats is None: return None
if os_stats['profit_factor'] < MIN_PF_OS_GATE: return None  # PF < 1.5 淘汰
```

### 返回结构

```python
{
    'symbol_a': sym_a,
    'symbol_b': sym_b,
    'beta': beta,
    'params': {'z_entry': e, 'z_exit': x, 'z_stop': s},
    'z_entry': e, 'z_exit': x, 'z_stop': s,
    'score': round(best_score, 4),
    'is_stats': { profit_factor, max_drawdown, n_trades, win_rate, sharpe, net_profit },
    'os_stats': { profit_factor, max_drawdown, n_trades, win_rate, sharpe, net_profit },
}
```

---

## 6. _score_result 硬门槛逻辑

```python
def _score_result(stats: Dict) -> float:
    if stats['profit_factor'] < MIN_PF_HARD_GATE:    # PF < 1.5 → 淘汰
        return -1.0
    if stats['max_drawdown'] > MAX_DD_HARD_GATE:     # MaxDD > 0.20 → 淘汰
        return -1.0
    if stats['n_trades'] < MIN_TRADES_HARD_GATE:     # Trades < 10 → 淘汰
        return -1.0
    return _six_dim_score(stats)
```

---

## 7. _six_dim_score 五维评分完整公式

所有维度归一化到 [0, 1]，加权求和:

| 维度 | 权重 | 归一化公式 | 说明 |
|------|------|------------|------|
| **P** (Profit) | 30% | `p = clamp(net_profit / 10000 / 0.5, 0, 1)` | 净值收益百分比 / 50% 封顶 |
| **R** (Risk) | 20% | `r = max(0, 1 - max_dd / 0.20)` | 最大回撤反向归一化 |
| **S** (Sharpe) | 15% | `s = clamp(sharpe / 2.0, 0, 1)` | Sharpe / 2.0 封顶 |
| **E** (Exposure) | 15% | `e = min(log(n_trades + 1) / log(101), 1.0)` | 对数归一化，100 笔满 |
| **St** (Stability) | 10% | `st = clamp((win_rate - 0.4) / 0.2, 0, 1)` | 胜率 40% 起算，60% 满 |

```python
score = 0.30 * p + 0.20 * r + 0.15 * s + 0.15 * e + 0.10 * st
```

其中 `clamp(x, 0, 1) = min(max(x, 0), 1.0)`。

---

## 8. ParamOptimizer 类

```python
class ParamOptimizer:
    def __init__(self, is_ratio: float = IS_RATIO, n_workers: int = None):
        self.is_ratio = is_ratio
        if n_workers is None:
            n_workers = min(cpu_count(), 4)
        self.n_workers = n_workers
```

### run() 方法

```python
def run(
    self,
    candidates: List[Dict],
    get_historical_data_fn: Callable,
) -> List[Dict]:
```

**流程**:
1. 遍历 candidates，通过 `get_historical_data_fn(sym, days=90)` 获取历史数据
2. 校验: 历史数据为 None 或 `n < 300` 的跳过
3. 构建任务列表: `tasks.append((i, len(candidates), sym_a, sym_b, beta, log_a[:n], log_b[:n]))`
4. **多进程并行**: 当 `n_workers > 1` 且 `len(tasks) > 1`:
   ```python
   with Pool(processes=self.n_workers) as pool:
       results = pool.map(_optimize_single_pair, tasks)
   ```
   否则串行: `results = [_optimize_single_pair(t) for t in tasks]`
5. 过滤 None，按 `score` 降序排序
6. 调用 `_filter_top_30(results, max_per_coin=5)` 返回 Top 30

### _filter_top_30() 方法

```python
def _filter_top_30(self, results: List[Dict], max_per_coin: int = 5) -> List[Dict]:
```

**逻辑**: 遍历已排序结果，统计每个币种出现次数。仅当 `symbol_a` 和 `symbol_b` 的计数均 `< max_per_coin` 时才加入最终列表，同时更新双方计数。满 30 对截断。

---

## 9. Telegram 推送

### _send_telegram_message

```python
def _send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """同步发送 Telegram 消息 (urllib，无外部依赖)"""
    url = "https://api.telegram.org/bot{}/sendMessage".format(bot_token)
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status == 200
```

### format_scan_notification

```python
def format_scan_notification(whitelist, total_candidates=0,
                              elapsed_sec=0, scan_id="") -> str:
    """格式化扫描结果为 Telegram HTML 消息 (<=4096 字符)"""
```

**格式**: 标题 + 统计（配对数/耗时）+ Top 30 明细 + 免责声明。
每行格式:
```
#{:2d} SYMA/SYMB  Score={:.3f}  E={:.1f} X={:.1f} S={:.1f}  PF={:.2f} DD={:.0%} N={} WR={:.0%} PnL=${:.0f}
```
超长截断: `>4000 字符` 时缩减为 Top 20 精简行。

### notify_scan_results

```python
def notify_scan_results(whitelist, bot_token, chat_id,
                        total_candidates=0, elapsed_sec=0,
                        scan_id="") -> bool:
    """扫描完成后推送 Top 30 到 Telegram"""
```

**逻辑**: 无 token/chat_id 则跳过并返回 False；whitelist 为空发送失败消息；否则调用 `format_scan_notification` + `_send_telegram_message`。

---

## 10. 多进程并行

```python
from multiprocessing import Pool, cpu_count
```

- **Worker 数**: `min(cpu_count(), 4)`，可通过 `ParamOptimizer(n_workers=N)` 覆盖
- **并行方式**: `Pool(processes=self.n_workers).map(_optimize_single_pair, tasks)`
- **Fallback**: `n_workers <= 1` 或 `len(tasks) <= 1` 时串行执行
- **任务函数**: `_optimize_single_pair` 为顶层函数（非方法），确保 pickle 兼容

---

## 11. 搜索策略总结

| 阶段 | 数据 | 参数组合数 | 说明 |
|------|------|-----------|------|
| Phase 1 粗扫 | IS (81%) | 9 | entry [2.0~6.0] 0.5步长, exit=0.5, stop=entry+1.0 |
| Phase 2 精扫 | IS (81%) | ~189 | Top3 entry ±0.3(0.1步长) × 3 exit × 3 stop_offset |
| OS 验证 | OS (19%) | 1 | 最优参数验证，PF < 1.5 淘汰 |
| **总计** | | **~200次/对** | Numba 加速后 100 对约 2-5 分钟 |
