# S001-Pro 统计套利交易系统

全自动跨品种统计套利策略，基于Kalman Filter和Z-Score信号。

## 系统架构

```
Phase A (扫描优化):
  M1 DataEngine → M2 InitialFilter → M3 M3Selector → M4 Optimizer → M5 Persistence
  
Phase B (实盘交易):
  M6 Runtime ← M8 ConfigManager ← M7 Monitor ← M9 SignalEngine
```

### 模块清单

| 模块 | 文件 | 功能 |
|------|------|------|
| M1 | `data_engine.py` | K线数据读取、市场统计 |
| M2 | `filters/initial_filter.py` | 6层流动性初筛 |
| M3 | `m3_selector.py` | 三周期配对精选(Kalman+ADF) |
| M4 | `optimizer.py` | Walk-Forward参数优化 |
| M5 | `persistence.py` | 结果保存到JSON |
| M6 | `runtime/` | 订单执行、状态机、风控 |
| M7 | `monitor_logger.py` | PnL监控、Telegram通知 |
| M8 | `config_manager.py` | 配置管理、热重载 |
| M9 | `signal_engine.py` | 实时Z-score计算 |

### 稳健性模块

| 模块 | 文件 | 功能 |
|------|------|------|
| R1 | `version_tracker.py` | 变更追踪 |
| R2 | `health_monitor.py` | 健康检查 |
| R3 | `state_guard.py` | 状态保护 |
| R4 | `circuit_breaker.py` | 熔断机制 |
| R5 | `robustness_wrapper.py` | 统一接口 |

## 快速开始

```bash
# 安装
pip install -r requirements.txt

# 配置API
cp config/base.yaml.example config/base.yaml
# 编辑 config/base.yaml 填写你的API Key

# 运行测试
python3 tests/run_tests.py

# 启动系统
python3 -m src.main --mode full
```

## 运行模式

- `full` - 扫描+实盘 (默认)
- `scan` - 仅扫描
- `trade` - 仅实盘
- `--dry-run` - 模拟模式

## 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - 系统架构
- [docs/USAGE.md](docs/USAGE.md) - 使用指南
- [docs/API.md](docs/API.md) - 模块API

## 风险提示

⚠️ 本系统仅供技术研究，不构成投资建议。加密货币交易有风险。
