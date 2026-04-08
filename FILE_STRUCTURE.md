# S001-Pro 文件结构手册

> **最后更新**: 2026-04-08  
> **版本**: v1.0  
> **用途**: 全项目文件索引，随时更新

---

## 目录

- [1. 项目概览](#1-项目概览)
- [2. 核心代码 (src/)](#2-核心代码-src)
- [3. 配置文件 (config/)](#3-配置文件-config)
- [4. 文档 (docs/)](#4-文档-docs)
- [5. 监控面板 (monitor/)](#5-监控面板-monitor)
- [6. 测试 (tests/)](#6-测试-tests)
- [7. 工具脚本 (tools/)](#7-工具脚本-tools)
- [8. 运维脚本 (scripts/)](#8-运维脚本-scripts)
- [9. 数据目录 (data/)](#9-数据目录-data)

---

## 1. 项目概览

```
~/S001-Pro/
├── 📄 FILE_STRUCTURE.md      # 本文件（文件结构手册）
├── 📄 README.md              # 项目说明
├── 📄 CHANGELOG.md           # 变更日志
├── 📄 requirements.txt       # Python依赖
├── 📄 deploy.sh              # 部署脚本
└── [其他目录见下方]
```

---

## 2. 核心代码 (src/)

| 文件 | 模块 | 功能描述 | 重要程度 |
|------|------|----------|----------|
| `main.py` | - | 策略主入口，协调M1-M9全流程 | ⭐⭐⭐ |
| `data_engine.py` | M1 | 数据获取、标准化、存储 | ⭐⭐⭐ |
| `filters/initial_filter.py` | M2 | 6重防线初筛配对候选 | ⭐⭐⭐ |
| `m3_base.py` | M3 | 配对评分基类 | ⭐⭐⭐ |
| `m3_1m.py` | M3-1m | 1分钟周期配对评分 | ⭐⭐⭐ |
| `m3_5m.py` | M3-5m | 5分钟周期配对评分 | ⭐⭐⭐ |
| `m3_15m.py` | M3-15m | 15分钟周期配对评分 | ⭐⭐⭐ |
| `m3_selector.py` | M3 | 多周期配对选择器 | ⭐⭐⭐ |
| `pairwise_scorer.py` | M3 | 配对评分（已弃用） | ⭐ |
| `optimizer.py` | M4 | 回测+参数优化，输出Top 30 | ⭐⭐⭐ |
| `persistence.py` | M5 | 分批策略+配置写入 | ⭐⭐⭐ |
| `runtime/` | M6 | 实盘执行模块化 | ⭐⭐⭐ |
| `runtime/__init__.py` | - | Runtime包入口 | ⭐⭐⭐ |
| `runtime/runtime_core.py` | - | 核心运行时 | ⭐⭐⭐ |
| `signal_engine.py` | M6 | Z-score信号计算 | ⭐⭐ |
| `config_manager.py` | M8 | 配置管理 | ⭐⭐ |
| `notifier.py` | M9 | Telegram通知 | ⭐⭐ |
| `position_recovery.py` | M6 | 仓位恢复 | ⭐⭐ |
| `preflight_check.py` | - | 启动前检查 | ⭐⭐ |
| `profit_manager.py` | - | 利润划转管理 | ⭐ |
| `recovery_system.py` | M6 | 重启恢复逻辑 | ⭐ |
| `trade_recorder.py` | M5 | 交易记录 | ⭐ |
| `binance_validator.py` | M2 | 币安合约验证 | ⭐⭐ |
| `monitor_logger.py` | M9 | 监控日志 | ⭐ |
| `streaming_scanner.py` | - | 实时扫描器 | ⭐⭐ |
| `streaming_integration.py` | - | 流式集成 | ⭐⭐ |

**已删除文件**:
- `bug_scanner.py` - 调试脚本（已废弃）
- `types_example.py` - 示例文件（未使用）
- `pairwise_scorer_backup_*.py` - 备份文件

---

## 3. 配置文件 (config/)

| 文件 | 用途 | 修改频率 |
|------|------|----------|
| `base.yaml` | 基础配置：资金、杠杆、成本 | 低 |
| `base.yaml.example` | 配置模板 | 从不 |
| `strategy.yaml` | 策略参数 | 中 |
| `pairs_v2.json` | M4输出的配对白名单 | 高（每次扫描后） |
| `cron.conf` | 定时任务配置 | 低 |

---

## 4. 文档 (docs/)

### 4.1 核心模块文档 (M0-M9)

| 文件 | 模块 | 内容 |
|------|------|------|
| `module_1_data_engine.md` | M1 | 数据引擎架构 |
| `module_2_initial_filter.md` | M2 | 初筛逻辑 |
| `module_3_pairwise_scoring.md` | M3 | 配对评分 |
| `module_4_optimizer.md` | M4 | 回测优化 |
| `module_5_persistence.md` | M5 | 持久化策略 |
| `module_6_runtime.md` | M6 | 实盘执行 |
| `module_7_monitoring.md` | M7 | 监控（未使用） |
| `module_8_config_management.md` | M8 | 配置管理 |
| `module_9_logging_monitoring.md` | M9 | 日志监控 |
| `MODULE_INDEX.md` | - | 模块索引 |

### 4.2 gstack 工作流

| 文件 | 内容 |
|------|------|
| `GSTACK_ARCHITECTURE.md` | gstack架构适配 |
| `GSTACK_CHEATSHEET.md` | 速查表 |
| `GSTACK_TUTORIAL.md` | 使用教程 |

### 4.3 审计报告

| 文件 | 日期 | 内容 |
|------|------|------|
| `audit/gstack-review-report-20260408.md` | 2026-04-08 | gstack Review报告 |
| `audit/gstack-qa-report-20260408.md` | 2026-04-08 | QA测试报告 |

### 4.4 其他重要文档

| 文件 | 内容 |
|------|------|
| `ATOMIC_GUIDE.md` | 原子级精度指南 |
| `AUTO_PAIR_UPDATE.md` | 自动更新配对流程 |
| `BUG_AUDIT_REPORT.md` | Bug审计报告 |
| `ROADMAP.md` | 项目路线图 |
| `TELEGRAM_TEMPLATES.md` | TG消息模板 |

---

## 5. 监控面板 (monitor/)

### 5.1 后端 (backend/)

| 文件 | 功能 |
|------|------|
| `app/main.py` | FastAPI入口 |
| `app/routers/positions.py` | 持仓API |
| `app/routers/orders.py` | 订单API |
| `app/routers/alerts.py` | 告警API |
| `app/routers/charts.py` | 图表数据API |
| `app/routers/logs.py` | 日志API |
| `app/routers/share.py` | 分享链接API |
| `app/routers/summary.py` | 汇总API |
| `app/routers/websocket.py` | WebSocket实时推送 |
| `app/database.py` | 数据库连接 |
| `app/auth.py` | 认证逻辑 |
| `start.sh` | 启动脚本 |
| `requirements.txt` | Python依赖 |

### 5.2 前端 (frontend/)

| 文件 | 功能 |
|------|------|
| `src/App.tsx` | 主应用 |
| `src/pages/Dashboard.tsx` | 监控面板页 |
| `src/pages/Login.tsx` | 登录页 |
| `src/pages/ShareView.tsx` | 分享视图 |
| `src/components/PositionsTable.tsx` | 持仓表格 |
| `src/components/SummaryCard.tsx` | 汇总卡片 |
| `src/components/DailyChart.tsx` | 日收益图 |
| `src/components/ProfitChart.tsx` | 利润图 |
| `src/components/AlertPanel.tsx` | 告警面板 |
| `src/components/LogsPanel.tsx` | 日志面板 |
| `src/components/SharePanel.tsx` | 分享面板 |
| `src/services/api.ts` | API客户端 |
| `src/services/websocket.ts` | WebSocket连接 |
| `package.json` | npm依赖 |
| `vite.config.ts` | Vite配置 |

---

## 6. 测试 (tests/)

| 文件 | 测试内容 |
|------|----------|
| `run_tests.py` | 测试入口 |
| `test_phase1.py` | M1数据引擎测试 |
| `test_phase2.py` | M2初筛测试 |
| `test_phase3.py` | M3配对评分测试 |
| `test_phase4.py` | M4优化器测试 |
| `test_integration.py` | 集成测试 |
| `test_backtest_equivalence.py` | 回测等价性测试 |
| `test_optimization.py` | 优化测试 |

---

## 7. 工具脚本 (tools/)

| 文件 | 功能 | 使用频率 |
|------|------|----------|
| `auto_pair_update.py` | 自动更新配对 | 每次扫描后 |
| `auto_healer.py` | 自动修复异常 | 持续运行 |
| `watchdog.py` | 进程监控 | 持续运行 |
| `binance_futures_sync.py` | 币安数据同步 | 定时运行 |
| `binance_live_scanner.py` | 实时扫描 | 手动/定时 |
| `code_audit.py` | 代码审计 | 不定期 |
| `ghost_order_manager.py` | 幽灵订单处理 | 异常时 |
| `generate_report.py` | 生成报告 | 手动 |
| `reset_and_start.sh` | 重置并启动 | 紧急时 |

---

## 8. 运维脚本 (scripts/)

| 文件 | 功能 |
|------|------|
| `cleanup.sh` | 清理临时文件 |
| `monitor_data_and_launch.sh` | 监控数据并启动 |
| `start_streaming_scan.sh` | 启动实时扫描 |
| `streaming-scan.service` | systemd服务模板 |
| `build_market_stats.py` | 构建市场统计 |

---

## 9. 数据目录 (data/)

| 文件 | 内容 | 重要性 |
|------|------|--------|
| `trades.db` | 交易记录SQLite | ⭐⭐⭐ |
| `daily_stats.json` | 每日统计 | ⭐⭐ |

---

## 10. 快速查找

### 按功能查找

| 功能 | 文件 |
|------|------|
| 修改策略参数 | `config/base.yaml` |
| 查看配对配置 | `config/pairs_v2.json` |
| 修改分批策略 | `src/persistence.py` |
| 修改回测参数 | `src/optimizer.py` |
| 修改信号阈值 | `src/signal_engine.py` |
| 查看文档 | `docs/` |
| 查看日志 | `monitor/backend/data/monitor.db` |
| 查看交易记录 | `data/trades.db` |

---

## 更新记录

| 日期 | 更新内容 | 更新人 |
|------|----------|--------|
| 2026-04-08 | 初始版本 | gstack Review |

---

**使用说明**: 本文件由 `gstack /review` 流程自动生成，每次添加新文件时请更新此表。
