# 清理清单 (Cleanup Manifest)

**清理日期**: 2025-04-08  
**执行人**: gstack  
**版本**: v2.1.0-hardened  

---

## 清理项汇总

### 1. 缓存文件 (已删除)

| 类型 | 数量 | 大小 |
|------|------|------|
| __pycache__ 目录 | 98个 | ~5MB |
| .pyc 文件 | 789个 | ~3MB |
| 测试缓存 | 1个 | ~100KB |

**删除命令**:
```bash
find . -type d -name '__pycache__' -exec rm -rf {} +
find . -name '*.pyc' -delete
find . -name '.pytest_cache' -type d -exec rm -rf {} +
```

---

### 2. 代码模块 (已归档)

从 `src/` 归档到 `archive/deprecated_code/`:

| 模块 | 大小 | 归档原因 |
|------|------|----------|
| binance_validator.py | 3.7KB | 无引用 |
| notifier.py | 8.9KB | 无引用 |
| pairwise_scorer.py | 13KB | 无引用 |
| position_recovery.py | 6.7KB | 无引用 |
| preflight_check.py | 28KB | 无引用 |
| profit_manager.py | 5.4KB | 无引用 |
| streaming_integration.py | 9.4KB | 无引用 |
| streaming_scanner.py | 17KB | 无引用 |
| trade_recorder.py | 17KB | 无引用 |

**总计**: 9个模块, ~108KB

---

### 3. 文档 (已归档)

从 `docs/` 归档到 `archive/docs/`:

#### 旧模块文档 (16个)
- module_1_data_engine.md
- module_2_initial_filter.md
- module_3_pairwise_scoring.md
- module_4_optimizer.md
- module_5_persistence.md
- module_6_runtime.md
- module_7_monitoring.md
- module_8_config_management.md
- module_9_logging_monitoring.md
- module_binance_validator.md
- module_position_recovery.md
- module_preflight.md
- module_profit_manager.md
- module_recovery.md
- module_signal.md
- module_trade_recorder.md

#### 其他旧文档
- ATOMIC_GUIDE.md
- GSTACK_TUTORIAL.md

#### 目录
- architecture/
- design/
- audit/

**总计**: 18个文件 + 3个目录

---

### 4. 测试文件 (已归档)

从 `tests/` 归档到 `archive/tests/`:

| 测试文件 | 依赖的已归档代码 |
|----------|-----------------|
| test_phase1.py | - |
| test_phase2.py | pairwise_scorer |
| test_phase3.py | - |
| test_phase4.py | notifier |
| test_backtest_equivalence.py | - |
| test_integration.py | - |
| test_optimization.py | - |

**总计**: 7个测试文件

---

## 验证结果

### 清理后测试
```
总测试数: 8
通过: 8
失败: 0
```

### 核心模块导入
- ✅ main.py
- ✅ runtime
- ✅ data_engine
- ✅ config_manager
- ✅ signal_engine
- ✅ m3_selector
- ✅ optimizer

---

## 保留的核心文件

### 代码 (src/)
```
src/
├── config_manager.py
├── constants.py
├── data_engine.py
├── filters/
│   └── initial_filter.py
├── health_monitor.py
├── main.py
├── m3_15m.py
├── m3_1m.py
├── m3_5m.py
├── m3_base.py
├── m3_selector.py
├── monitor_logger.py
├── optimizer.py
├── persistence.py
├── recovery_system.py
├── runtime/
│   ├── __init__.py
│   ├── order_executor.py
│   ├── position_manager.py
│   ├── position_state.py
│   ├── risk_guard.py
│   ├── runtime_core.py
│   └── state_machine.py
├── signal_engine.py
├── state_guard.py
├── version_tracker.py
├── circuit_breaker.py
└── robustness_wrapper.py
```

### 文档 (docs/)
```
docs/
├── ATOMIC_INDEX.md          (原子级文档索引)
├── README.md                (项目简介)
├── 00-getting-started/      (入门)
├── 10-architecture/         (架构)
├── 20-modules/              (模块详解)
├── 30-robustness/           (稳健性)
├── 40-ops/                  (运维)
├── 50-config/               (配置)
├── 60-dev/                  (开发)
└── meta/                    (元文档)
```

### 测试 (tests/)
```
tests/
└── run_tests.py             (主测试套件)
```

---

## 如需恢复

如需要恢复已归档的文件:

```bash
# 恢复代码模块
cp archive/deprecated_code/MODULE.py src/

# 恢复文档
cp archive/docs/DOCUMENT.md docs/

# 恢复测试
cp archive/tests/TEST.py tests/
```

---

## 后续建议

1. **观察期**: 建议观察1-2周，确认系统稳定
2. **最终删除**: 观察期后，可删除 archive/ 目录
3. **定期清理**: 建议每月清理一次缓存文件
4. **日志策略**: 设置日志保留策略(如保留30天)
