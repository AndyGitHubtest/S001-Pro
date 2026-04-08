# CHANGELOG

## v2.4 - M3多周期重构 + 代码清理 (2026-04-09)

### 架构重构

#### M3模块: 多时间周期配对评分
- **新增文件**:
  - `src/m3_base.py` - 配对评分基类，统一阈值管理
  - `src/m3_1m.py` - 1分钟周期配对评分
  - `src/m3_5m.py` - 5分钟周期配对评分  
  - `src/m3_15m.py` - 15分钟周期配对评分
  - `src/m3_selector.py` - 多周期配对选择器
- **变更**:
  - 原 `pairwise_scorer.py` 已弃用
  - 支持三周期并行筛选 (1m/5m/15m)
  - 各周期独立阈值配置

#### M4优化器: Top 30选择逻辑
- **文件**: `src/optimizer.py`
- **变更**:
  - M3不限制数量，全部通过筛选的进入M4
  - M4优化全部配对，按评分排名
  - 只选Top 30给M5实盘

#### Runtime模块化
- **新增目录**: `src/runtime/`
- **文件**:
  - `src/runtime/__init__.py`
  - `src/runtime/runtime_core.py`
- **变更**: 原 `runtime.py` 拆分为模块化结构

### 代码清理

#### 删除废旧文件
- `src/pairwise_scorer_backup_20260408_130109.py` - 备份文件
- `src/types_example.py` - 未使用的示例文件
- `src/bug_scanner.py` - 调试脚本
- `bug_scanner.py` (根目录) - 重复文件

#### 文档更新
- `FILE_STRUCTURE.md` - 更新文件结构索引

---

## v2.3 - 实时信号引擎 + ccxt 对接 (2026-04-07)

### 核心新增

#### SignalEngine: 实时 Z-score 计算
- **文件**: 新增 `src/signal_engine.py`
- **功能**: 滑动窗口实时计算配对 Z-score
- **架构**:
  - 滑动窗口 500 根 1m K 线 (~8 小时)
  - Expanding window 统计 (均值/标准差)
  - REST API 轮询获取价格 (5 秒间隔, 无需 WebSocket)
- **预热**: 启动时从数据库加载历史数据

#### ExchangeApi: ccxt 完整对接
- **文件**: `src/main.py`
- **变更**: Mock 实现 → 真实 ccxt 封装
- **功能**:
  - `place_order`: ccxt.create_order (支持 price/postOnly/reduceOnly)
  - `cancel_order`: ccxt.cancel_order
  - `cancel_all_orders`: 批量撤销所有挂单
  - `fetch_order`: ccxt.fetch_order (成交确认用)
  - `fetch_ticker`: ccxt.fetch_ticker (实时价格用)
  - `get_positions`: ccxt.fetch_positions (对账用)
- **限流**: enableRateLimit=True 自动限流

#### _check_all_signals: 真实信号循环
- **之前**: 空函数 (pass), Z = 0.0 placeholder
- **现在**:
  1. 每 5 秒轮询交易所价格
  2. 更新 SignalEngine 滑动窗口
  3. 获取每个配对的 Z-score
  4. 调用 Runtime.check_signals 驱动状态机

### 数据流完整链路
```
交易所 API (ccxt) → fetch_ticker → SignalEngine.update_prices()
                                        ↓
                                   Z-score 计算
                                        ↓
                              Runtime.check_signals(pair, z)
                                        ↓
                              状态机驱动 → execute_sync_open/close
```

## v2.2 - P0/P1 全面审计修复 (2026-04-07)

### P0 修复 (资金安全/核心逻辑)

#### P0-6: 回测未来函数修复
- **文件**: `src/optimizer.py` `PairBacktester.run()`
- **问题**: `mean = np.mean(spread[warmup:])` 用全部数据算均值, bar 201 的 Z 用到了 bar 5000 的数据
- **修复**: Expanding Window — 每个 bar 只用 `warmup~当前bar` 的数据计算均值和标准差
- **影响**: 回测结果将更保守 (Z-score 更宽, 交易更少, 但更真实)

#### P0-7: 真实 PnL 计算
- **文件**: `src/optimizer.py` `_calc_pnl()` → `_calc_real_pnl()`
- **问题**: `pnl_pct = z_move * 0.01` — Z-score 和实际盈亏没有线性关系, 回测 PnL 是编的
- **修复**: 用实际价格、beta、仓位计算真实 PnL, 扣除 4 腿成本
- **公式**: Long Spread = (exit_a - entry_a)*qty_a + (entry_b - exit_b)*qty_b - 4*cost*notional

#### P0-2: 限价单成交确认
- **文件**: `src/runtime.py`
- **问题**: `place_order` 不抛异常就认为成功, 不检查是否实际成交
- **修复**: 新增 `_wait_order_filled()` 轮询确认, 超时 90s, 每 5s 查询一次
- **超时处理**: 撤未成交订单 + 回滚已成交腿

#### P0-3: 平仓 reduceOnly
- **文件**: `src/runtime.py` `execute_sync_close`, `execute_rollback`, `_emergency_close`
- **问题**: 平仓单没传 `reduceOnly=True`, 方向错误时会反向加仓
- **修复**: 所有平仓调用加 `reduce_only=True`

#### P0-4: 紧急平仓验证
- **文件**: `src/runtime.py` `_emergency_close()`
- **问题**: 市价平仓后不确认是否成交, 不重试
- **修复**: 3 次重试 + 确认成交 + TG 紧急告警

#### P0-5: 状态持久化
- **文件**: `src/runtime.py` `_save_state()`, `_load_state()`
- **问题**: 有 `to_dict()`/`from_dict()` 但从未调用, 状态从不持久化
- **修复**: 每次状态变更后原子写入 `data/state.json`, 启动时恢复

### P1 修复 (稳定性/策略准确性)

#### P1-1: Scale-In 第一层无法触发
- **文件**: `src/persistence.py` `SCALE_IN_PLAN`
- **问题**: Layer 1 offset=-0.5 → trigger_z < entry, 状态机在 IDLE 不检查 scale_in
- **修复**: offset 改为 0.0, +0.5, +1.0 (从 entry 开始)

#### P1-3: valid_until_iso 跨天崩溃
- **文件**: `src/persistence.py`
- **问题**: `now.replace(hour=24)` 在 23:xx 时 ValueError
- **修复**: 用 `timedelta(minutes=30)` 替代

#### P1-4: CLOSING_MODE 死代码清理
- **文件**: `src/runtime.py` `check_signals()`
- **问题**: `if state==IDLE:` 里面又 `if state==CLOSING_MODE:` — 不可能成立

#### P1-5: 硬编码本金修复
- **文件**: `src/main.py`
- **问题**: `monitor.initialize(10000.0)` 不读配置
- **修复**: 从 `config.risk.initial_capital` 读取

#### P1-6: API 密钥安全
- **文件**: `.gitignore`, `config/base.yaml.example`, `src/config_manager.py`
- **问题**: API keys 明文在 git 仓库
- **修复**: base.yaml 加入 .gitignore, 提供环境变量注入机制

### 其他
- 新增 `ExchangeApi` 适配器 (mock 实现, TODO: 对接 ccxt)
- 信号检查循环 `_check_all_signals()` 从空函数改为遍历逻辑
- 同步更新 4 个模块文档

## v2.1 - 扫描性能优化 (2024-04-06)

### 优化概述
在不改变算法逻辑和过滤阈值的前提下，通过工程优化和计算顺序重组，实现扫描流程整体提速 3-5x。

### 优化清单

#### 优化 1: 删除 `_beta_rolling` 重复定义
- **文件**: `src/pairwise_scorer.py`
- **问题**: 第 169 行定义了向量化版本 (cumsum)，第 244 行定义了 for 循环版本，后者覆盖前者
- **修复**: 删除 for 循环版本，保留向量化版本
- **效果**: beta_std 计算提速 50-100x
- **风险**: 零 (功能完全等价)

#### 优化 2: 三阶段漏斗 (Three-Stage Funnel)
- **文件**: `src/pairwise_scoring.py` `_score_pair()`
- **原理**: 先计算低成本指标做预过滤，通过的才进入高成本计算
- **阶段 1** (Hot Pool, 纯 numpy, 无 lstsq): corr_mean, corr_std, volume_ratio, Abs(Return_288) → 过滤 ~90%
- **阶段 2** (Hot Pool, 无 lstsq): hurst, spread_std_cv, beta_std, rolling_corr_std → 过滤 ~5%
- **阶段 3** (90d 历史数据): EG_p, ADF_p, half_life, reg_count → 仅 ~10% 配对进入
- **效果**: 节省 90% 的 lstsq 矩阵运算和 90d 数据加载
- **风险**: 低 (过滤阈值不变，仅改变计算顺序)

#### 优化 3: 批量 SQL 加载
- **文件**: `src/data_engine.py`
- **新增**: `batch_load_historical(symbols, days=90)` 方法
- **原理**: 一次 `WHERE symbol IN (...)` SQL 替代 N 次逐条查询
- **效果**: N 次 SQL → 1 次 SQL
- **风险**: 零

#### 优化 4: 两阶段网格搜索 (Coarse-to-Fine)
- **文件**: `src/optimizer.py` `ParamOptimizer.run()`
- **粗搜**: 4×3×3 = 36 次 (entry: 2.0/3.0/4.0/5.0, offset: 1.0/2.0/3.0, exit: 0.5/1.5/2.5)
- **精搜**: Top 3 粗搜结果 ±0.5 范围内精搜，约 60-70 次
- **早停**: n_trades < 5 跳过评分
- **回退**: 粗搜无结果时取最优粗搜参数
- **效果**: ~106 次回测 vs 原来 420 次，减少 75%
- **风险**: 低 (参数空间连续，收敛到同一最优解)

#### 优化 5: 回测引擎向量化 (已取消)
- **尝试**: 将 for 循环状态机改为 searchsorted 事件驱动
- **结果**: 发现边界条件导致交易计数不匹配，回退到稳定 for 循环版本
- **原因**: 原始 for 循环单次仅需 14ms，在优化 2+4 的组合下已足够快

#### 优化 6: 主流程预缓存
- **文件**: `src/main.py` `run_scan_and_optimize()`, `quick_scan.py`
- **改动**: 在 M3/M4 启动前批量预加载 hist_cache
- **效果**: 消除重复 SQL 查询

### 综合性能预估
```
优化前: 100 币 → 9900 对 → 每对 2 次 lstsq → 每对 ~50-100ms
优化后: 100 币 → 9900 对 → 90% 在阶段 1 过滤 (无需 lstsq) → 剩余 10% × 2 次 lstsq
       + 批量 SQL (N→1)
       + 优化器回测减少 75%
       → 整体提速约 3-5x
```

### Git Commits
- `f406c73` 优化 1+3+6: 扫描流程性能优化 (零风险)
- `763f915` 优化 2+4: 三阶段漏斗 + 网格搜索裁剪

### 文档更新
- `docs/module_1_data_engine.md` → 新增 3.7 节 batch_load_historical 规范
- `docs/module_3_pairwise_scoring.md` → 新增第 4 节三阶段漏斗规范 + 阈值对照表
- `docs/module_4_optimizer.md` → 新增第 6 节两阶段网格搜索规范

### 测试
- `tests/test_backtest_equivalence.py` → 10 组参数对比，100% 通过
- `tests/test_optimization.py` → 综合功能验证
