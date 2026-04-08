# S001-Pro 原子级文档索引

**版本**: 2.1.0-hardened  
**最后更新**: 2025-04-08  
**文档原则**: [原子级文档规范](meta/PRINCIPLES.md)

---

## 快速导航

### 🚀 入门 (Getting Started)
- [快速开始](00-getting-started/QUICKSTART.md) - 5分钟上手
- [系统概览](00-getting-started/OVERVIEW.md) - 架构鸟瞰
- [术语表](00-getting-started/GLOSSARY.md) - 专业术语解释

### 📐 架构 (Architecture)
- [系统架构图](10-architecture/SYSTEM_DIAGRAM.md)
- [数据流图](10-architecture/DATA_FLOW.md)
- [模块依赖图](10-architecture/DEPENDENCY_GRAPH.md)
- [部署架构](10-architecture/DEPLOYMENT.md)

### 🔧 模块详解 (Modules)

#### M1 - 数据层
- [M1.1 DataEngine 职责](20-modules/M1-01-data-engine-purpose.md)
- [M1.2 DataEngine API](20-modules/M1-02-data-engine-api.md)
- [M1.3 数据缓存策略](20-modules/M1-03-caching-strategy.md)
- [M1.4 K线对齐算法](20-modules/M1-04-alignment-algorithm.md)

#### M2 - 初筛层
- [M2.1 InitialFilter 职责](20-modules/M2-01-filter-purpose.md)
- [M2.2 流动性过滤规则](20-modules/M2-02-liquidity-rules.md)
- [M2.3 价格过滤规则](20-modules/M2-03-price-rules.md)

#### M3 - 精选层
- [M3.1 M3Selector 架构](20-modules/M3-01-selector-arch.md)
- [M3.2 1分钟周期筛选](20-modules/M3-02-1m-selection.md)
- [M3.3 5分钟周期筛选](20-modules/M3-03-5m-selection.md)
- [M3.4 15分钟周期筛选](20-modules/M3-04-15m-selection.md)
- [M3.5 Kalman Filter 实现](20-modules/M3-05-kalman-impl.md)
- [M3.6 配对评分算法](20-modules/M3-06-scoring-algo.md)

#### M4 - 优化层
- [M4.1 Optimizer 职责](20-modules/M4-01-optimizer-purpose.md)
- [M4.2 Walk-Forward 算法](20-modules/M4-02-walk-forward.md)
- [M4.3 参数边界约束](20-modules/M4-03-param-constraints.md)

#### M5 - 持久层
- [M5.1 Persistence 职责](20-modules/M5-01-persistence-purpose.md)
- [M5.2 状态文件格式](20-modules/M5-02-state-format.md)
- [M5.3 自动保存策略](20-modules/M5-03-auto-save.md)

#### M6 - 运行时
- [M6.1 Runtime 职责](20-modules/M6-01-runtime-purpose.md)
- [M6.2 状态机定义](20-modules/M6-02-state-machine.md)
- [M6.3 订单执行流程](20-modules/M6-03-order-execution.md)
- [M6.4 风控检查点](20-modules/M6-04-risk-checks.md)
- [M6.5 防裸仓机制](20-modules/M6-05-naked-position-prevention.md)

#### M7 - 监控层
- [M7.1 Monitor 职责](20-modules/M7-01-monitor-purpose.md)
- [M7.2 日志格式规范](20-modules/M7-02-log-format.md)
- [M7.3 Telegram通知](20-modules/M7-03-telegram-notify.md)

#### M8 - 配置层
- [M8.1 ConfigManager 职责](20-modules/M8-01-config-purpose.md)
- [M8.2 配置热重载](20-modules/M8-02-hot-reload.md)
- [M8.3 pairs_v2.json 格式](20-modules/M8-03-pairs-format.md)

#### M9 - 信号层
- [M9.1 SignalEngine 职责](20-modules/M9-01-signal-purpose.md)
- [M9.2 Z-score计算](20-modules/M9-02-zscore-calc.md)
- [M9.3 实时价格更新](20-modules/M9-03-price-update.md)

### 🛡️ 稳健性模块 (Robustness) - v2.1.0新增
- [R1 VersionTracker 版本追踪](30-robustness/R01-version-tracker.md)
- [R2 HealthMonitor 健康监控](30-robustness/R02-health-monitor.md)
- [R3 StateGuard 状态保护](30-robustness/R03-state-guard.md)
- [R4 CircuitBreaker 熔断保护](30-robustness/R04-circuit-breaker.md)
- [R5 RobustnessWrapper 统一接口](30-robustness/R05-robustness-wrapper.md)

### 🔧 运维 (Operations)
- [部署检查清单](40-ops/DEPLOYMENT_CHECKLIST.md)
- [启动流程](40-ops/STARTUP_PROCEDURE.md)
- [关闭流程](40-ops/SHUTDOWN_PROCEDURE.md)
- [日志查看指南](40-ops/LOG_VIEWING.md)
- [常见问题排查](40-ops/TROUBLESHOOTING.md)
- [紧急停止流程](40-ops/EMERGENCY_STOP.md)

### 📊 配置参考 (Configuration)
- [base.yaml 完整参考](50-config/BASE_YAML_REFERENCE.md)
- [环境变量列表](50-config/ENVIRONMENT_VARIABLES.md)
- [pairs_v2.json 示例](50-config/PAIRS_V2_EXAMPLE.md)
- [配置变更历史](50-config/CONFIG_CHANGELOG.md)

### 🧪 开发 (Development)
- [本地开发环境](60-dev/LOCAL_DEV_SETUP.md)
- [测试套件说明](60-dev/TEST_SUITE.md)
- [代码提交规范](60-dev/COMMIT_CONVENTION.md)
- [调试技巧](60-dev/DEBUGGING_TIPS.md)

---

## 文档状态图

```
[Getting Started] ──┬──→ [Architecture] ──┬──→ [Modules M1-M9]
                    │                      │
                    ├──→ [Robustness] ─────┤
                    │                      │
                    ├──→ [Operations] ─────┤
                    │                      │
                    └──→ [Config Ref] ─────┘
```

## 核心数据流

```
┌─────────────────────────────────────────────────────────────┐
│                        Phase A (扫描)                        │
├─────────────────────────────────────────────────────────────┤
│  M1 DataEngine ──→ M2 InitialFilter ──→ M3 M3Selector       │
│  (读取K线)          (6层过滤)            (Kalman+评分)        │
│                                       ↓                     │
│                              M4 Optimizer                    │
│                              (Walk-Forward优化)              │
│                                       ↓                     │
│                              M5 Persistence                  │
│                              (保存pairs_v2.json)             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                        Phase B (实盘)                        │
├─────────────────────────────────────────────────────────────┤
│  M8 ConfigManager ←── pairs_v2.json                          │
│       ↓                                                      │
│  M6 Runtime ←───────→ M9 SignalEngine                        │
│  (状态机+下单)         (实时Z-score)                          │
│       ↓                                                      │
│  M7 Monitor                                                  │
│  (PnL+通知)                                                  │
└─────────────────────────────────────────────────────────────┘
```

## 关键术语速查

| 术语 | 含义 | 相关模块 |
|------|------|----------|
| Pair | 交易对组合 | M3, M6 |
| Z-score | 标准化价差 | M9 |
| Kalman Filter | 动态回归滤波 | M3 |
| ADF | 协整性检验 | M3 |
| IS/OS | 样本内/样本外 | M4 |
| Walk-Forward | 前向优化 | M4 |
| Naked Position | 裸仓风险 | M6 |
| Cooldown | 冷却期 | M6 |
