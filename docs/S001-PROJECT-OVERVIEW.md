# S001-Pro 项目总览

**全称**: S001-Pro Statistical Arbitrage Trading System  
**版本**: 2.1.0-hardened  
**类型**: 加密货币跨品种统计套利交易系统  
**交易所**: Binance USDT永续合约  
**最后更新**: 2025-04-08

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [核心流程](#3-核心流程)
4. [模块详解](#4-模块详解)
5. [配置说明](#5-配置说明)
6. [部署运行](#6-部署运行)
7. [监控运维](#7-监控运维)
8. [风险管控](#8-风险管控)

---

## 1. 项目概述

### 1.1 什么是S001-Pro？

S001-Pro是一个**全自动化的统计套利交易系统**，通过识别历史价格相关性高的加密货币交易对，利用价格偏离均值的特性进行多空对冲交易，赚取均值回归的利润。

### 1.2 核心原理

```
统计套利原理:

假设 BTC 和 ETH 历史上价格高度相关
当 BTC 涨10%, ETH 只涨5% 时 → 价差异常扩大
策略: 做空BTC, 做多ETH (对冲市场风险)
等待: 价差回归正常
平仓: 赚取价差收敛的利润
```

### 1.3 系统特性

| 特性 | 说明 |
|------|------|
| **多时间框架** | 同时运行1m/5m/15m三个周期 |
| **动态回归** | Kalman Filter实时计算hedge ratio |
| **参数优化** | Walk-Forward自动优化交易参数 |
| **防裸仓** | 双边同步下单，失败自动回滚 |
| **稳健性** | v2.1.0新增5个稳健性模块 |

### 1.4 项目里程碑

```
v1.0.0 (2024 Q4) - 基础架构
  └── M1-M9模块完成
  └── Binance USDT永续合约对接

v2.0.0 (2025 Q1) - 模块化重构
  └── runtime目录结构优化
  └── 子模块拆分

v2.1.0-hardened (2025 Q2) - 稳健性增强 ← 当前
  └── R1-R5稳健性模块
  └── 健康监控与自愈
  └── 生产级 hardened
```

---

## 2. 系统架构

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           S001-Pro 系统架构                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Phase A: 扫描优化                            │   │
│  │                    (周期性执行，如每小时1次)                          │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    │   │
│  │   │   M1     │───→│   M2     │───→│   M3     │───→│   M4     │    │   │
│  │   │DataEngine│    │Initial   │    │ M3Selector│    │Optimizer│    │   │
│  │   │          │    │Filter    │    │          │    │          │    │   │
│  │   └──────────┘    └──────────┘    └──────────┘    └────┬─────┘    │   │
│  │                                                        │          │   │
│  │                                                   ┌────┴────┐     │   │
│  │                                                   │   M5    │     │   │
│  │                                                   │Persist  │     │   │
│  │                                                   └────┬────┘     │   │
│  └──────────────────────────────────────────────────────┼───────────┘   │
│                                                         │                │
│                              config/pairs_v2.json      │                │
│                                                         ▼                │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                      Phase B: 实盘交易                               │ │
│  │                    (持续运行，实时监控)                              │ │
│  ├─────────────────────────────────────────────────────────────────────┤ │
│  │   ┌──────────┐    ┌──────────────────────────────────────────┐    │ │
│  │   │   M8     │    │              M6 Runtime                   │    │ │
│  │   │ Config   │───→│  ┌────────┐  ┌────────┐  ┌────────┐      │    │ │
│  │   │ Manager  │    │  │ State  │  │ Order  │  │  Risk  │      │    │ │
│  │   └──────────┘    │  │Machine │  │Executor│  │ Guard  │      │    │ │
│  │                   │  └────────┘  └────────┘  └────────┘      │    │ │
│  │        ┌──────────┘                                         │    │ │
│  │        │                                                    │    │ │
│  │   ┌────▼─────┐                                              │    │ │
│  │   │   M9     │                                              │    │ │
│  │   │Signal    │──────────────────────────────────────────────┘    │ │
│  │   │Engine    │                                                   │ │
│  │   └──────────┘                                                   │ │
│  │        │                                                         │ │
│  │        └──────────────────┐                                      │ │
│  │                           ▼                                      │ │
│  │                    ┌─────────────┐                               │ │
│  │                    │ M7 Monitor  │                               │ │
│  │                    │ Logger      │                               │ │
│  │                    └─────────────┘                               │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流向

```
外部数据 → M1 DataEngine → M2 InitialFilter → M3 M3Selector
                                              ↓
                                         M4 Optimizer
                                              ↓
                                    config/pairs_v2.json
                                              ↓
M8 ConfigManager → M6 Runtime ←── M9 SignalEngine
       ↓                               ↓
   配置热重载                    Z-score信号
       ↓                               ↓
  风控检查 ←────────────────── 订单执行 → Binance API
       ↓                               ↓
  M7 Monitor ←────────────────── 持仓状态
```

---

## 3. 核心流程

### 3.1 Phase A: 扫描优化流程

```
Step 1: M1 DataEngine
  输入: data/klines.db (SQLite数据库)
  处理: 读取1m/5m/15m K线数据，计算市场统计
  输出: market_stats字典 + symbol列表

Step 2: M2 InitialFilter
  输入: 全量symbols (200+个)
  处理: 6层过滤（流动性、价格、波动率、数据质量、黑名单、上市时间）
  输出: Qualified Pool (50-80个)

Step 3: M3 M3Selector
  输入: Qualified symbols
  处理: 
    - 三周期独立筛选（1m/5m/15m）
    - Kalman Filter动态回归
    - ADF协整性检验
    - 多指标评分（hurst、半衰期等）
  输出: 候选配对列表（按评分排序）

Step 4: M4 Optimizer
  输入: 候选配对
  处理:
    - Phase1: 粗扫参数空间
    - Phase2: 精搜最优参数
    - Walk-Forward IS/OS验证
  输出: 带最优参数的白名单

Step 5: M5 Persistence
  输入: 优化后的配对列表
  处理: 保存为JSON格式
  输出: config/pairs_v2.json
```

### 3.2 Phase B: 实盘交易流程

```
初始化:
  1. M8 ConfigManager加载配置
  2. M6 Runtime初始化各子模块
  3. M9 SignalEngine启动价格监控

主循环:
  ┌─────────────────────────────────────┐
  │  1. 更新价格 (每秒)                  │
  │     M9 SignalEngine获取最新价格      │
  │     计算实时Z-score                  │
  └──────────────┬──────────────────────┘
                 ↓
  ┌─────────────────────────────────────┐
  │  2. 信号检测                         │
  │     IF |Z-score| > z_entry: 进场信号 │
  │     IF |Z-score| < z_exit: 出场信号  │
  │     IF |Z-score| > z_stop: 止损信号  │
  └──────────────┬──────────────────────┘
                 ↓
  ┌─────────────────────────────────────┐
  │  3. 风控检查                         │
  │     ✓ Kill Switch未触发             │
  │     ✓ 回撤未超限                     │
  │     ✓ 余额充足                       │
  │     ✓ 持仓未满                       │
  └──────────────┬──────────────────────┘
                 ↓
  ┌─────────────────────────────────────┐
  │  4. 状态机处理                       │
  │     IDLE → SCALING_IN → IN_POSITION │
  │     IN_POSITION → COOLDOWN → IDLE   │
  └──────────────┬──────────────────────┘
                 ↓
  ┌─────────────────────────────────────┐
  │  5. 订单执行                         │
  │     双边同步下单                     │
  │     成交确认轮询                     │
  │     失败自动回滚                     │
  └──────────────┬──────────────────────┘
                 ↓
  ┌─────────────────────────────────────┐
  │  6. 监控记录                         │
  │     M7 Monitor记录PnL               │
  │     Telegram通知                    │
  │     日志记录                         │
  └─────────────────────────────────────┘
```

---

## 4. 模块详解

### 4.1 M1 - DataEngine (数据引擎)

**文件**: `src/data_engine.py`

**职责**: 从SQLite读取K线数据，提供标准化数据访问

**核心类**:
```python
class DataEngine:
    def get_all_symbols(interval) -> List[str]
    def load_market_stats(min_vol) -> Dict
    def get_aligned_klines(symbol_a, symbol_b, interval, lookback) -> DataFrame
```

**数据库Schema**:
```sql
CREATE TABLE klines_1m (
    symbol TEXT,
    timestamp INTEGER,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    PRIMARY KEY (symbol, timestamp)
);
```

---

### 4.2 M2 - InitialFilter (初筛模块)

**文件**: `src/filters/initial_filter.py`

**职责**: 6层快速过滤，剔除不合格标的

**6层过滤**:
1. 流动性过滤: 日成交量 ≥ 2M USDT
2. 价格过滤: 0.01 ≤ 价格 ≤ 100000
3. 波动率过滤: 0.1% ≤ 波动率 ≤ 50%
4. 数据质量: 缺失率 ≤ 5%
5. 黑名单: 剔除杠杆代币
6. 上市时间: ≥ 90天

---

### 4.3 M3 - M3Selector (精选模块)

**文件**: `src/m3_selector.py`, `src/m3_base.py`, `src/m3_1m.py`, `src/m3_5m.py`, `src/m3_15m.py`

**职责**: 三周期独立筛选，输出高质量配对

**三周期架构**:
```
M3Selector (统一入口)
    ├── M3Selector1m (1分钟，直接使用)
    ├── M3Selector5m (5分钟，1m聚合)
    └── M3Selector15m (15分钟，1m聚合)
```

**核心算法**:
- **Kalman Filter**: 动态回归计算hedge ratio
- **ADF检验**: 验证协整性 (p < 0.05)
- **半衰期**: 均值回归速度
- **Hurst指数**: 均值回归特性 (< 0.5)

**评分指标**:
- Pearson相关系数 (20%)
- ADF p值 (25%)
- 半衰期 (20%)
- Hurst指数 (15%)
- 回归次数 (10%)
- 当前Z-score (10%)

---

### 4.4 M4 - Optimizer (优化器)

**文件**: `src/optimizer.py`

**职责**: Walk-Forward参数优化

**优化参数**:
```python
{
    "z_entry": 2.0~6.0,    # 进场阈值
    "z_exit": 0.1~1.0,     # 出场阈值
    "z_stop": entry+0.5~entry+2.0,  # 止损阈值
    "max_hold": 10~100     # 最大持仓时间
}
```

**搜索策略**:
```
Phase 1 (粗扫):
  entry: 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0
  → 9种组合，快速筛选

Phase 2 (精搜):
  取Phase1 Top3，在其周围精细搜索
  entry步长: 0.1
  → ~300次回测
```

**Walk-Forward验证**:
```
数据分割:
┌──────────────────┬──────────────┐
│ IS (样本内) 70天  │ OS (样本外) 20天│
│ 用于参数优化      │ 用于验证      │
└──────────────────┴──────────────┘
```

---

### 4.5 M5 - Persistence (持久化)

**文件**: `src/persistence.py`

**职责**: 保存优化结果到JSON

**输出文件**: `config/pairs_v2.json`

**格式**:
```json
{
  "meta": {
    "version": "1.0",
    "generated_at": "2025-04-08T20:00:36",
    "git_hash": "abc1234",
    "pairs_count": 6
  },
  "pairs": [
    {
      "symbol_a": "BTC/USDT",
      "symbol_b": "ETH/USDT",
      "beta": 0.15,
      "params": {
        "z_entry": 2.5,
        "z_exit": 0.5,
        "z_stop": 3.5,
        "max_hold": 20
      }
    }
  ]
}
```

---

### 4.6 M6 - Runtime (运行时)

**目录**: `src/runtime/`

**职责**: 实盘监控执行引擎

**子模块**:

| 子模块 | 文件 | 职责 |
|--------|------|------|
| RuntimeCore | `runtime_core.py` | 主控制器，协调各模块 |
| StateMachine | `state_machine.py` | 状态机管理 |
| OrderExecutor | `order_executor.py` | 订单执行，防裸仓 |
| PositionManager | `position_manager.py` | 持仓管理 |
| RiskGuard | `risk_guard.py` | 风控检查 |
| PositionState | `position_state.py` | 持仓状态定义 |

**状态机**:
```
IDLE ──(进场信号)──→ SCALING_IN ──(成交)──→ IN_POSITION
                        ↑                      │
                        └──(冷却结束)──────────┘
                                          (出场/止损)
                                               ↓
                                          COOLDOWN
```

**防裸仓机制**:
```python
def execute_scale_in(pair):
    # 1. 同时提交双边订单
    order_a = place_order(symbol_a, side_a, qty_a)
    order_b = place_order(symbol_b, side_b, qty_b)
    
    # 2. 等待双向成交
    filled_a = wait_for_fill(order_a, timeout=30)
    filled_b = wait_for_fill(order_b, timeout=30)
    
    # 3. 检查状态
    if filled_a and filled_b:
        return Success
    else:
        # 4. 回滚部分成交
        rollback(filled_a, filled_b)
        return Failed
```

---

### 4.7 M7 - Monitor (监控)

**文件**: `src/monitor_logger.py`

**职责**: PnL追踪、通知、日志

**核心类**:
- `Monitor`: PnL计算、统计报表
- `TelegramNotifier`: Telegram通知
- `LoggerManager`: 日志管理

**通知内容**:
- 扫描完成通知
- 交易信号通知
- 风控告警
- 每日PnL报告

---

### 4.8 M8 - ConfigManager (配置管理)

**文件**: `src/config_manager.py`

**职责**: 配置加载、验证、热重载

**配置文件**:
- `config/base.yaml`: 主配置
- `config/pairs_v2.json`: 配对配置

**热重载**: 修改pairs_v2.json后自动重载，无需重启

---

### 4.9 M9 - SignalEngine (信号引擎)

**文件**: `src/signal_engine.py`

**职责**: 实时Z-score计算

**核心方法**:
```python
class SignalEngine:
    def update_prices(self, symbol, price)  # 更新价格
    def get_z(self, pair) -> float          # 获取Z-score
    def check_signals(self) -> List[Signal] # 检查信号
```

**Z-score计算**:
```
Z = (spread - mean) / std

其中:
  spread = price_a - beta * price_b
  mean = 滑动窗口均值
  std = 滑动窗口标准差
```

---

### 4.10 R1-R5 稳健性模块 (v2.1.0)

| 模块 | 文件 | 职责 |
|------|------|------|
| R1 VersionTracker | `version_tracker.py` | 变更追踪、审计日志 |
| R2 HealthMonitor | `health_monitor.py` | 健康检查、自愈 |
| R3 StateGuard | `state_guard.py` | 状态一致性保护 |
| R4 CircuitBreaker | `circuit_breaker.py` | 熔断保护、优雅降级 |
| R5 RobustnessWrapper | `robustness_wrapper.py` | 统一接口 |

---

## 5. 配置说明

### 5.1 base.yaml

```yaml
exchange:
  name: "binance"
  api_key: "YOUR_API_KEY"
  api_secret: "YOUR_SECRET"
  testnet: false  # true=测试网, false=实盘

risk:
  initial_capital: 10000    # 本金(USDT)
  max_position_pairs: 6     # 最大持仓对数
  leverage: 3               # 杠杆倍数
  margin_mode: "cross"      # 全仓/逐仓
  max_daily_drawdown: 0.05  # 日最大回撤5%

notifications:
  enabled: true
  telegram_bot_token: ""
  telegram_chat_id: ""

scanning:
  min_daily_volume_usd: 2000000  # 最小日成交量2M
  top_n_scan: 100                # 扫描Top 100
  top_n_final: 30                # 最终保留30对
  scan_interval_hours: 1         # 每小时扫描
```

### 5.2 pairs_v2.json

由M5自动生成，包含交易对和优化后的参数。

---

## 6. 部署运行

### 6.1 快速启动

```bash
# 1. 克隆代码
git clone https://github.com/AndyGitHubtest/S001-Pro.git
cd S001-Pro

# 2. 安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 配置
cp config/base.yaml.example config/base.yaml
# 编辑 config/base.yaml 填写API Key

# 4. 运行测试
python3 tests/run_tests.py

# 5. 启动系统
python3 -m src.main --mode full
```

### 6.2 运行模式

| 模式 | 命令 | 说明 |
|------|------|------|
| 完整模式 | `--mode full` | 扫描+实盘 |
| 仅扫描 | `--mode scan` | 只进行配对筛选 |
| 仅实盘 | `--mode trade` | 使用已有配置交易 |
| 模拟模式 | `--dry-run` | 完整流程但不下单 |

### 6.3 生产部署

```bash
# 使用systemd
sudo systemctl enable s001-pro
sudo systemctl start s001-pro
sudo systemctl status s001-pro
```

---

## 7. 监控运维

### 7.1 日志查看

```bash
# 实时日志
tail -f logs/live_*.log

# 搜索交易信号
grep "SIGNAL" logs/live_*.log

# 查看错误
grep "ERROR" logs/live_*.log
```

### 7.2 关键指标

| 指标 | 正常范围 | 检查命令 |
|------|----------|----------|
| CPU使用率 | < 50% | `top` |
| 内存使用 | < 1GB | `free -h` |
| 磁盘空间 | > 5GB | `df -h` |
| 进程状态 | Running | `ps aux \| grep src.main` |

### 7.3 Telegram通知

启用后自动发送：
- ✅ 扫描完成
- 📊 交易信号
- 🚨 风控告警
- 📈 每日PnL

---

## 8. 风险管控

### 8.1 防裸仓机制

**问题**: 配对中一边成交另一边失败，导致单边持仓

**解决方案**:
1. 双边同步下单
2. 成交确认轮询（30秒超时）
3. 失败自动回滚
4. 进入冷却期

### 8.2 风险控制

| 风控项 | 触发条件 | 动作 |
|--------|----------|------|
| Kill Switch | 手动触发 | 停止所有开仓 |
| 日回撤限制 | 回撤 > 5% | 暂停交易24h |
| 持仓限制 | 持仓 ≥ 6对 | 拒绝新订单 |
| 价格异常 | 价格偏离 > 10% | 报警+暂停 |

### 8.3 熔断机制

连续失败3次 → 进入冷却期（指数退避）
```
失败1次: 冷却2分钟
失败2次: 冷却4分钟
失败3次: 冷却8分钟
...
最大: 冷却60分钟
```

---

## 9. 故障排查

### 9.1 无交易信号

检查清单:
- [ ] pairs_v2.json存在且有效
- [ ] Z-score达到阈值
- [ ] 风控未触发
- [ ] 状态机为IDLE

### 9.2 订单失败

常见错误:
- `Order would immediately match` → 调整价格
- `PERCENT_PRICE_BY_SIDE` → 价格偏离过大
- `Position side does not match` → 检查持仓模式

### 9.3 紧急停止

```bash
# 方式1
pkill -f src.main

# 方式2
sudo systemctl stop s001-pro
```

---

## 10. 相关资源

- **GitHub**: https://github.com/AndyGitHubtest/S001-Pro
- **文档目录**: `docs/`
- **配置文件**: `config/`
- **日志目录**: `logs/`
- **数据目录**: `data/`

---

**最后更新**: 2025-04-08  
**版本**: 2.1.0-hardened  
**作者**: Andy
