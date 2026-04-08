# S001-Pro 原子级操作指南

> 版本: 2.0-CleanSlate  
> 最后更新: 2025-01-13  
> 状态: 生产就绪  

---

## 📋 目录

1. [系统概览](#1-系统概览)
2. [原子级架构](#2-原子级架构)
3. [文件系统布局](#3-文件系统布局)
4. [配置原子手册](#4-配置原子手册)
5. [启动流程（16步）](#5-启动流程16步)
6. [模块原子说明](#6-模块原子说明)
7. [数据流原子图](#7-数据流原子图)
8. [故障排查原子指南](#8-故障排查原子指南)
9. [API原子参考](#9-api原子参考)
10. [维护命令](#10-维护命令)

---

## 1. 系统概览

### 1.1 系统身份卡

```yaml
系统名称: S001-Pro Statistical Arbitrage
版本: 2.0-CleanSlate
策略类型: 跨品种统计套利
交易所: 币安 USDT永续合约
时间周期: 1分钟K线
持仓周期: 15-60分钟
资金规模: $1,082.89 (实际)
交易对数量: 0-30对 (动态)
```

### 1.2 核心指标

| 指标 | 数值 | 说明 |
|------|------|------|
| 预期年化 | 20-40% | 基于回测 |
| 最大回撤 | <15% | 硬限制 |
| 日最大亏损 | <5% | 硬限制 |
| 胜率 | 55-65% | 目标区间 |
| 盈亏比 | 1.5:1 | 最小要求 |
| 手续费+滑点 | 0.23% | 每腿双边 |

---

## 2. 原子级架构

### 2.1 7阶段启动流程

```
┌─────────────────────────────────────────────────────────────┐
│                    S001-Pro 启动架构                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  P1_Connect  ──▶ API连接 + 权限验证                          │
│       │                                                     │
│       ▼                                                     │
│  P2_Config   ──▶ 杠杆设置(5x) + 持仓模式                      │
│       │                                                     │
│       ▼                                                     │
│  P3_Position ──▶ 本地状态 vs 交易所持仓 核对                   │
│       │                                                     │
│       ▼                                                     │
│  P4_Risk     ──▶ 本金检查 + 仓位使用率 + 回撤                  │
│       │                                                     │
│       ▼                                                     │
│  P5_Channel  ──▶ 交易通道测试(只读)                          │
│       │                                                     │
│       ▼                                                     │
│  P6_Data     ──▶ 配对配置检查(无配对=警告)                    │
│       │                                                     │
│       ▼                                                     │
│  P7_Launch   ──▶ 重启快照 + 通知 + 进入交易循环                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 9模块架构

```
┌────────────────────────────────────────────────────────────┐
│                      S001-Pro 模块架构                        │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  Phase A: 扫描优化 (周期性)                                  │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌────────┐ │
│  │ M1      │───▶│ M2      │───▶│ M3      │───▶│ M4     │ │
│  │Data     │    │Initial  │    │Pairwise │    │Optimizer│ │
│  │Engine   │    │Filter   │    │Scorer   │    │        │ │
│  └─────────┘    └─────────┘    └─────────┘    └────────┘ │
│       │                                              │     │
│       │         ┌─────────┐                         │     │
│       └────────▶│ M5      │◀────────────────────────┘     │
│                 │Persist  │                               │
│                 │ence     │                               │
│                 └─────────┘                               │
│                                                            │
│  Phase B: 实盘监控 (持续循环)                                │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐                │
│  │ M8      │───▶│ M6      │───▶│ M7      │                │
│  │Config   │    │Runtime  │    │Monitor  │                │
│  │Manager  │    │(状态机)  │    │Logger   │                │
│  └─────────┘    └────┬────┘    └─────────┘                │
│                      │                                     │
│              ┌───────┴───────┐                            │
│              ▼               ▼                            │
│         ┌─────────┐    ┌─────────┐                        │
│         │Signal   │    │ M9      │                        │
│         │Engine   │    │Logger   │                        │
│         │(Z-Score)│    │Manager  │                        │
│         └─────────┘    └─────────┘                        │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## 3. 文件系统布局

### 3.1 目录结构（原子级）

```
S001-Pro/
├── 📁 config/                    # 配置文件
│   ├── base.yaml                 # 主配置（风险参数、API）
│   ├── pairs_v2.json             # 交易对配置（扫描生成）
│   ├── strategy.yaml             # 策略特定配置
│   └── cron.conf                 # 定时任务配置
│
├── 📁 src/                       # 源代码
│   ├── main.py                   # 主入口（910行）
│   ├── runtime.py                # 状态机核心（1074行）
│   ├── preflight_check.py        # 启动检查（634行）
│   ├── recovery_system.py        # 重启恢复（610行）
│   ├── signal_engine.py          # Z-Score计算（344行）
│   ├── data_engine.py            # 数据引擎（354行）
│   ├── pairwise_scorer.py        # 配对评分（731行）
│   ├── optimizer.py              # 参数优化（636行）
│   ├── exchange_api.py           # 交易所API（500行）
│   ├── config_manager.py         # 配置管理（347行）
│   ├── monitor_logger.py         # 监控日志（480行）
│   ├── notifier.py               # 通知系统（266行）
│   ├── persistence.py            # 持久化（306行）
│   ├── position_recovery.py      # 仓位恢复（209行）
│   ├── profit_manager.py         # 利润管理（161行）
│   ├── trade_recorder.py         # 交易记录（498行）
│   ├── binance_validator.py      # 币安验证器（132行）
│   └── filters/                  # 过滤器模块
│       ├── __init__.py
│       └── initial_filter.py     # 初筛（150行）
│
├── 📁 data/                      # 数据文件
│   ├── klines.db -> /home/ubuntu/projects/data-core/data/klines.db
│   ├── state.json                # 持仓状态（实时）
│   ├── daily_stats.json          # 每日统计
│   ├── watchdog.db               # 监控数据库
│   └── recovery/                 # 恢复数据
│
├── 📁 logs/                      # 日志文件
│   ├── live_trading.log          # 交易日志
│   ├── watchdog.log              # 监控日志
│   └── scan_*.log                # 扫描日志
│
├── 📁 docs/                      # 文档
│   ├── ATOMIC_GUIDE.md           # 本文件
│   ├── BUG_AUDIT_REPORT.md       # BUG审计报告
│   ├── ROADMAP.md                # 开发路线图
│   ├── README.md                 # 项目简介
│   └── module_*.md               # 模块文档（9个）
│
├── 📁 systemd/                   # 系统服务
│   └── trading-s001.service      # systemd服务文件
│
├── 📁 tests/                     # 测试套件
│   └── run_tests.py              # 强制测试框架
│
├── 📁 scripts/                   # 工具脚本
│   └── deploy.sh                 # 部署脚本
│
├── 📁 tools/                     # 开发工具
│
├── .git/                         # Git仓库
├── .gitignore                    # Git忽略规则
├── requirements.txt              # Python依赖
├── test_preflight.py             # 测试文件
└── run_*.py                      # 运行脚本（4个）
```

### 3.2 关键文件大小

| 文件 | 大小 | 说明 |
|------|------|------|
| src/main.py | 36KB | 主程序 |
| src/runtime.py | 46KB | 状态机核心 |
| src/preflight_check.py | 28KB | 启动检查 |
| data/klines.db | 427MB | K线数据（软链接） |
| venv/ | ~500MB | Python环境 |

---

## 4. 配置原子手册

### 4.1 base.yaml（主配置）

```yaml
# 系统配置
system:
  name: "S001-Pro"
  version: "2.0-CleanSlate"
  mode: "live"                    # live | dry-run
  log_level: "INFO"

# 交易所配置
exchange:
  name: "binance"
  api_key: "xxx"                  # 从环境变量读取
  api_secret: "xxx"               # 从环境变量读取
  testnet: false

# 风险参数
risk:
  initial_capital: 1082.89        # 实际账户余额
  max_drawdown_pct: 15.0          # 最大回撤15%
  max_daily_loss_pct: 5.0         # 日最大亏损5%
  max_open_positions: 6           # 最大持仓对数
  position_size_usdt: 50.0        # 每对仓位大小
  leverage: 5                     # 杠杆倍数
  isolated_margin: true           # 逐仓模式

# 数据配置
data:
  db_path: "data/klines.db"       # K线数据库路径

# 通知配置
notifications:
  enabled: true
  telegram_bot_token: "xxx"
  telegram_chat_id: "xxx"
  alert_level: "ERROR"
```

### 4.2 pairs_v2.json（交易对配置）

```json
{
  "meta": {
    "version": "1.0",
    "generated_at": "2025-01-13T08:36:49",
    "pairs_count": 30
  },
  "pairs": [
    {
      "signal_id": "BTC_USDT_ETH_USDT_xxx",
      "symbol_a": "BTC/USDT",
      "symbol_b": "ETH/USDT",
      "beta": 0.85,
      "params": {
        "z_entry": 2.7,
        "z_exit": 1.3,
        "z_stop": 4.2
      },
      "exchange_meta": {
        "min_qty": 0.001,
        "step_size": 0.001,
        "price_precision": 2
      },
      "allocation": {
        "max_position_value_usd": 5000.0
      },
      "execution": {
        "scale_in": [...],
        "scale_out": [...],
        "stop_loss": {...}
      },
      "ttl_minutes": 30
    }
  ]
}
```

### 4.3 state.json（运行状态）

```json
{
  "BTC/USDT_ETH/USDT": {
    "state": "IDLE",
    "direction": 0,
    "entry_z": 0.0,
    "scale_in_layer": 0,
    "scale_out_layer": 0,
    "position_size_pct": 0.0,
    "entry_price_a": 0.0,
    "entry_price_b": 0.0,
    "scale_in_fail_count": 0,
    "scale_in_cool_until": 0
  }
}
```

---

## 5. 启动流程（16步）

### 5.1 启动检查清单

```bash
# Step 1: 检查数据同步状态
ssh ubuntu@43.160.192.48 "du -h ~/projects/data-core/data/klines.db"
# 期望: ≥400MB

# Step 2: 检查配置
cat ~/strategies/S001-Pro/config/base.yaml | grep initial_capital
# 期望: 1082.89

# Step 3: 检查交易对
cat ~/strategies/S001-Pro/config/pairs_v2.json | grep pairs_count
# 期望: >0

# Step 4: 测试启动（dry-run）
cd ~/strategies/S001-Pro && source venv/bin/activate
python -m src.main --dry-run 2>&1 | head -50
```

### 5.2 7阶段检查详解

| 阶段 | 检查项 | 通过标准 | 失败处理 |
|------|--------|----------|----------|
| P1 | API连接 | fetch_balance成功 | 停止启动 |
| P2 | 杠杆设置 | 统一5x | 停止启动 |
| P3 | 持仓核对 | 本地=交易所 | 自动清理残留 |
| P4 | 风控检查 | 回撤<5%, 仓位<80% | 停止启动 |
| P5 | 通道测试 | fetch_orders正常 | 跳过(无配对) |
| P6 | 数据检查 | 配对数≥0 | 警告但继续 |
| P7 | 启动完成 | 快照+通知 | 进入交易 |

---

## 6. 模块原子说明

### 6.1 Runtime（状态机）

```python
# 状态定义
STATE_IDLE = "IDLE"                    # 空闲
STATE_SCALING_IN = "SCALING_IN"        # 开仓中
STATE_IN_POSITION = "IN_POSITION"      # 持仓中
STATE_SCALING_OUT = "SCALING_OUT"      # 平仓中
STATE_EXITED = "EXITED"                # 已退出
STATE_CLOSING_MODE = "CLOSING_MODE"    # 关闭模式

# 状态转换
IDLE ──[Z>Entry]──▶ SCALING_IN ──[完成]──▶ IN_POSITION
                      │                         │
                      │                         ▼
                      │◀──────────────  SCALING_OUT
                      │                    [Z<Exit]
                      └───────────────────────┘
                      [Z>Stop/强制平仓]
```

### 6.2 PreFlight（启动检查）

```python
class PreFlightCheck:
    """
    启动前检查系统
    
    职责:
      1. 验证交易所连接
      2. 配置自动设置（杠杆、持仓模式）
      3. 持仓核对（三层对账）
      4. 风控检查（回撤、仓位）
      5. 数据准备检查
    
    超时设置:
      - 单阶段: 30秒
      - 总超时: 300秒
    """
```

### 6.3 SignalEngine（信号引擎）

```python
# Z-Score计算
z_score = (spread - mean) / std

# 信号生成
if z_score > z_entry:
    signal = -1  # 做空价差
elif z_score < -z_entry:
    signal = 1   # 做多价差
elif abs(z_score) < z_exit:
    signal = 0   # 平仓
```

---

## 7. 数据流原子图

### 7.1 启动时数据流

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  config/     │     │  data/       │     │  交易所      │
│  base.yaml   │────▶│  state.json  │◀────│  持仓查询    │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  Preflight   │
                     │  Check       │
                     └──────┬───────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  Runtime     │
                     │  状态机      │
                     └──────────────┘
```

### 7.2 运行时数据流

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Exchange    │────▶│  Signal      │────▶│  Runtime     │
│  Ticker      │     │  Engine      │     │  状态机       │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                       ┌──────────────────────────┘
                       ▼
                ┌──────────────┐
                │  Order       │
                │  Execution   │
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐     ┌──────────────┐
                │  state.json  │────▶│  Telegram    │
                │  持久化      │     │  通知        │
                └──────────────┘     └──────────────┘
```

---

## 8. 故障排查原子指南

### 8.1 启动失败排查树

```
启动失败
│
├─▶ P1_Connect失败
│   ├─ API Key错误 → 检查config/base.yaml
│   ├─ 网络问题 → 检查服务器网络
│   └─ 币安维护 → 查看币安公告
│
├─▶ P3_Position失败
│   ├─ 状态残留 → 自动清理
│   └─ 持仓不一致 → 手动平仓后重启
│
├─▶ P4_Risk失败
│   ├─ 回撤超限 → 检查daily_stats.json
│   ├─ 仓位过高 → 手动减仓
│   └─ 本金不符 → 更新initial_capital
│
└─▶ P6_Data失败
    └─ 无配对 → 运行扫描
```

### 8.2 常用排查命令

```bash
# 1. 检查服务状态
ssh ubuntu@43.160.192.48 "ps aux | grep -i s001 | grep -v grep"

# 2. 检查日志
ssh ubuntu@43.160.192.48 "tail -50 ~/strategies/S001-Pro/logs/watchdog.log"

# 3. 检查数据
ssh ubuntu@43.160.192.48 "du -h ~/projects/data-core/data/klines.db"

# 4. 检查配置
ssh ubuntu@43.160.192.48 "cat ~/strategies/S001-Pro/config/pairs_v2.json | grep pairs_count"

# 5. 检查余额
ssh ubuntu@43.160.192.48 "cd ~/strategies/S001-Pro && source venv/bin/activate && python -c 'import ccxt; e=ccxt.binance({\"options\":{\"defaultType\":\"future\"}}); print(e.fetch_balance()[\"USDT\"])'"
```

### 8.3 紧急情况处理

```bash
# 紧急停止
ssh ubuntu@43.160.192.48 "killall -9 python"

# 清理状态
ssh ubuntu@43.160.192.48 "echo '{}' > ~/strategies/S001-Pro/data/state.json"

# 查看持仓
ssh ubuntu@43.160.192.48 "cd ~/strategies/S001-Pro && source venv/bin/activate && python -c 'import ccxt; e=ccxt.binance({\"options\":{\"defaultType\":\"future\"}}); [print(p[\"symbol\"], p[\"contracts\"]) for p in e.fetch_positions() if p[\"contracts\"]!=0]'"
```

---

## 9. API原子参考

### 9.1 Runtime API

```python
# 启动Runtime
runtime = Runtime(config_manager, persistence, exchange_api, notifier, monitor)
await runtime.start(recovery_system=recovery_system)

# 检查信号
await runtime.check_signals(pair_key, z_score)

# 热重载
runtime.handle_hot_reload(new_pairs_data)

# 停止
runtime.stop()
```

### 9.2 Exchange API

```python
# 下单
order = await exchange_api.place_order(
    symbol="BTC/USDT",
    order_type="limit",
    side="long",
    qty=0.1,
    price=50000,
    post_only=True,
    reduce_only=False
)

# 查询持仓
positions = await exchange_api.get_positions()

# 查询订单
orders = await exchange_api.get_orders(symbol="BTC/USDT")
```

---

## 10. 维护命令

### 10.1 日常检查

```bash
# 每日检查脚本
check_s001() {
    echo "=== S001-Pro 日常检查 ==="
    
    # 1. 检查进程
    ssh ubuntu@43.160.192.48 "pgrep -f 'src.main' && echo '进程正常' || echo '进程未运行'"
    
    # 2. 检查日志
    ssh ubuntu@43.160.192.48 "tail -5 ~/strategies/S001-Pro/logs/watchdog.log"
    
    # 3. 检查数据
    ssh ubuntu@43.160.192.48 "du -h ~/projects/data-core/data/klines.db"
    
    # 4. 检查权益
    ssh ubuntu@43.160.192.48 "cat ~/strategies/S001-Pro/data/daily_stats.json | grep current_equity"
}
```

### 10.2 定时任务

```bash
# crontab -e

# 每小时检查
0 * * * * cd ~/strategies/S001-Pro && source venv/bin/activate && python -c "from src.main import health_check; health_check()" >> logs/health.log 2>&1

# 每日扫描（凌晨2点）
0 2 * * * cd ~/strategies/S001-Pro && source venv/bin/activate && python run_scan.py >> logs/scan_cron.log 2>&1
```

---

## 附录A: 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 2.0-CleanSlate | 2025-01-13 | 重构启动检查，7阶段16步 |
| 1.9 | 2025-01-10 | 添加RecoverySystem |
| 1.0 | 2024-12-01 | 初始版本 |

## 附录B: 术语表

| 术语 | 说明 |
|------|------|
| Z-Score | 标准化价差分数 |
| Leg Sync | 双腿同步下单 |
| Scale In | 分批建仓 |
| Scale Out | 分批平仓 |
| Kalman Filter | 卡尔曼滤波器 |
| Half-Life | 均值回归半衰期 |

---

**文档维护**: 每次代码变更后更新  
**验证方式**: `python tests/run_tests.py`
