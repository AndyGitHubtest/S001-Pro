# 模块二：初筛模块 (Initial Filter) - LOCKED

> **职责**: 从全量币种中剔除低质量/高风险币种，输出合格币池 (Qualified Pool)，预计 100-150 个币种。
> **最后更新**: 2026-04-07 - 对齐代码: v1.0 (src/filters/initial_filter.py)
> **状态**: P0 LOCKED — 任一过滤命中立即剔除 (Break on Fail)

## 1. 常量定义

### 1.1 STABLECOINS (稳定币集合)

共 **8** 个。base (symbol `/` 前部分) 精确匹配以下集合则剔除：

```python
STABLECOINS = {'USDC', 'FDUSD', 'TUSD', 'DAI', 'BUSD', 'EUR', 'GBP', 'USTC'}
```

### 1.2 MEME_BLACKLIST (黑名单集合)

共 **72** 个币种，分 4 类：

**Meme 币 (36 个):**
`DOGE`, `SHIB`, `PEPE`, `1000PEPE`, `1000SHIB`, `1000BONK`, `1000RATS`, `FLOKI`, `BONK`, `WIF`, `MEME`, `MYRO`, `BOME`, `SLERF`, `POPCAT`, `GIGA`, `MOG`, `TURBO`, `NEIRO`, `GOAT`, `PNUT`, `ACT`, `TRUMP`, `MELANIA`, `USELESS`, `FARTCOIN`, `PONKE`, `NPC`, `MEW`, `GRIFFAIN`, `ANIME`, `MICHI`, `MOODENG`, `BRETT`, `GIGACHAD`, `DADDY`

**单字母币 (26 个):**
`A`, `B`, `C`, `D`, `E`, `F`, `G`, `H`, `I`, `J`, `K`, `L`, `M`, `N`, `O`, `P`, `Q`, `R`, `S`, `T`, `U`, `V`, `W`, `X`, `Y`, `Z`

**股票代币 (5 个):**
`COIN`, `TSLA`, `NVDA`, `MSTR`, `SOLV`

**已退市/异常币 (5 个):**
`LUNA`, `LUNC`, `FTT`, `SPELL`, `LIME`

匹配逻辑: `base.upper() in MEME_BLACKLIST` (不区分大小写匹配)。

## 2. 类和方法签名

```python
class InitialFilter:
    """初筛模块 — 七重过滤防线 (7-filter pipeline)"""

    def __init__(self) -> None:
        """初始化统计计数器"""
        self.stats_passed: int = 0    # 预留，当前未在 run 中使用
        self.stats_filtered: int = 0  # 预留，当前未在 run 中使用

    def run(self, symbols: List[str], stats_db: Dict) -> List[str]:
        """
        主入口：遍历 symbols，对每个币种调用 _check 进行过滤。

        参数:
            symbols:  全量交易对符号列表，如 ['BTC/USDT', 'ETH/USDT', ...]
            stats_db: Module 1 产出的 market_stats 字典，key 为 symbol

        返回:
            qualified: 通过全部 7 道过滤的 symbol 列表
        """

    def _check(self, symbol: str, stats: Dict) -> bool:
        """
        串行执行 7 道过滤防线 (过滤器 1-7)，任一命中立即返回 False。

        参数:
            symbol: 交易对符号，如 'BTC/USDT'
            stats:  该 symbol 对应的 market_stats 字典

        返回:
            True  = 通过全部过滤 (保留)
            False = 命中某道过滤 (剔除)
        """
```

## 3. 数据流转

```
┌─────────────────────────────────────────────────────────────┐
│  Module 1 (Market Stats Collector)                          │
│  输出: symbols: List[str]                                   │
│        stats_db: Dict[str, Dict] (key=symbol)               │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  InitialFilter.run(symbols, stats_db)                       │
│  for each sym in symbols:                                   │
│    ├─ _check(sym, stats_db.get(sym, {}))                    │
│    │   ├─ base = sym.split('/')[0]                          │
│    │   └─ 过滤器 1→7 串行执行，任一 False 立即剔除           │
│    └─ True → 加入 qualified 列表                             │
│  日志: "{len(symbols)} -> {len(qualified)} assets passed"    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  输出: qualified (List[str]) — 约 100-150 个币种             │
│  去向: → Module 3 (Pairwise Scoring)                        │
└─────────────────────────────────────────────────────────────┘
```

### stats 字典字段依赖

| 字段 | 类型 | 默认值 | 使用过滤器 |
|------|------|--------|------------|
| `vol_24h_usdt` | float | 0 | 过滤器 3 |
| `kline_count` | int | 0 | 过滤器 4 |
| `close` | float | 1 | 过滤器 5, 6 |
| `high_24h` | float | close | 过滤器 5 |
| `low_24h` | float | close | 过滤器 5 |
| `atr_14` | float | 0 | 过滤器 6B |
| `kurtosis` | float | 0 | 过滤器 6C |

## 4. 过滤顺序 (1→7)

### 过滤器 1: 稳定币剔除
- **逻辑**: `base = symbol.split('/')[0]`，若 `base in STABLECOINS` 则剔除
- **阈值**: 精确匹配 (8 个稳定币)
- **示例**: `BTC/USDT` → base=`BTC` → 通过；`USDC/USDT` → base=`USDC` → 剔除

### 过滤器 2: Meme 币 / 单字母 / 股票 / 退市币黑名单
- **逻辑**: `base.upper() in MEME_BLACKLIST` 则剔除
- **阈值**: 精确匹配 (72 个币种)
- **日志**: `logger.debug("Filter-MEME: {base} blacklisted, skipping")`

### 过滤器 3: 流动性门槛
- **逻辑**: `vol_24h_usdt < 2_000_000` 则剔除
- **阈值**: 24h 成交量 ≥ 2,000,000 USDT
- **默认**: 若 stats 中无此字段，默认值为 0 → 剔除

### 过滤器 4: 数据完整度
- **逻辑**: `kline_count < 120_000` 则剔除
- **阈值**: K线数量 ≥ 120,000 根
- **默认**: 若 stats 中无此字段，默认值为 0 → 剔除

### 过滤器 5: 僵尸/刷量盘检测
- **逻辑**: 计算 24h 波动率 `range_pct = (high_24h - low_24h) / close`
- **阈值**: `range_pct < 0.0015` (即 0.15%) 则剔除
- **防护**: 仅当 `close > 0` 时计算，避免除零
- **默认**: `high_24h` 和 `low_24h` 缺失时取 `close` 值 → range_pct=0 → 剔除

### 过滤器 6: 异常波动拦截 (3 个子条件，任一命中剔除)

#### 6A: 价格过低
- **逻辑**: `close < 0.0005` 则剔除
- **阈值**: 价格 ≥ 0.0005

#### 6B: ATR 比率过高
- **逻辑**: `close > 0` 且 `(atr_14 / close) > 0.12` 则剔除
- **阈值**: ATR/Close ≤ 12%
- **防护**: `close > 0` 前置检查，避免除零

#### 6C: 峰度过高
- **逻辑**: `kurtosis > 10` 则剔除
- **阈值**: Kurtosis ≤ 10
- **含义**: 过滤极端尖峰分布 (极端波动/操纵风险)

## 5. 执行逻辑伪代码

```python
for sym in symbols:
    base = sym.split('/')[0]

    # 过滤器 1: 稳定币
    if base in STABLECOINS: continue

    # 过滤器 2: 黑名单
    if base.upper() in MEME_BLACKLIST: continue

    # 过滤器 3: 流动性
    if stats.get('vol_24h_usdt', 0) < 2_000_000: continue

    # 过滤器 4: 数据完整度
    if stats.get('kline_count', 0) < 120_000: continue

    # 过滤器 5: 僵尸盘
    close = stats.get('close', 1)
    if close > 0:
        range_pct = (stats.get('high_24h', close) - stats.get('low_24h', close)) / close
        if range_pct < 0.0015: continue

    # 过滤器 6A: 价格过低
    if close < 0.0005: continue

    # 过滤器 6B: ATR 比率
    atr = stats.get('atr_14', 0)
    if close > 0 and (atr / close) > 0.12: continue

    # 过滤器 6C: 峰度
    if stats.get('kurtosis', 0) > 10: continue

    # 全部通过
    qualified.append(sym)
```

## 6. 边界情况与防护

| 场景 | 防护机制 |
|------|----------|
| symbol 中无 `/` 分隔符 | `split('/')[0]` 返回原字符串 |
| stats 中缺少某字段 | 使用 `.get(key, default)` 提供安全默认值 |
| close = 0 (除零风险) | 过滤器 5 和 6B 均有 `close > 0` 前置检查 |
| stats 完全为空字典 | 过滤器 3 (vol=0<2M)、4 (count=0<120K) 会剔除 |
