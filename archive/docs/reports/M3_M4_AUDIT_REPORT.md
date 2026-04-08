# S001-Pro M3-M4 配对与优化模块审计报告

**审计时间**: 2026-04-08  
**审计范围**: src/pairwise_scorer.py (M3), src/optimizer.py (M4), src/streaming_scanner.py  
**文档对照**: docs/module_3_pairwise_scoring.md, docs/module_4_optimizer.md

---

## 严重等级统计

| 等级 | 数量 | 说明 |
|------|------|------|
| 🔴 CRITICAL | 3 | 代码与文档严重不符，可能导致错误交易信号 |
| 🟠 HIGH | 2 | 参数不一致，影响策略性能 |
| 🟡 MEDIUM | 5 | 实现缺陷或边界条件处理不当 |
| 🟢 LOW | 3 | 代码质量问题 |
| **总计** | **13** | - |

---

## 🔴 CRITICAL 级别

### [CRIT-001] M3 Spread计算与M4不一致 — 核心算法错误

**文件**: `src/pairwise_scorer.py:96`, `src/optimizer.py:81`

**问题描述**:
- M3 配对评分模块计算spread: `spread = log_a[:n] - log_b[:n]` (无beta)
- M4 优化模块计算spread: `spread = log_a[:n] - beta * log_b[:n]` (有beta)
- M3输出的配对在M4中回测时，spread计算方式完全不同，导致信号失真

**风险**: 策略在M3中看起来好的配对，在实盘中表现完全不同

**修复建议**: 统一spread计算方式，M3也应使用beta（可先用简单线性回归估计）

```python
# 建议M3中也计算beta
beta = np.std(log_a) / (np.std(log_b) + 1e-12) * np.sign(np.corrcoef(log_a, log_b)[0,1])
spread = log_a - beta * log_b
```

---

### [CRIT-002] M3实现与文档严重不符 — 核心功能缺失

**文件**: `src/pairwise_scorer.py` (整体实现)

**文档要求** (module_3_pairwise_scoring.md):
- 三阶段筛选: Phase1 → OS Sanity Check → Phase2
- Kalman Filter计算动态beta
- reg_count回归次数统计 (>=30)
- 评分公式: `0.5*kalman_quality + 0.3*reg_count + 0.2*corr`

**实际实现**:
- 只有两阶段筛选 (Phase1 + Phase2)
- 无Kalman Filter实现
- 无reg_count统计
- 评分公式完全不同: `0.4*corr_mean + 0.3*(1-corr_std) + 0.2*(1/(1+half_life/10)) + 0.1*min(recent_z_cross/5, 1)`

**风险**: 文档描述的算法优势（Kalman自适应、回归频率评估）完全未实现

**修复建议**: 按文档实现完整的三阶段筛选和Kalman Filter，或更新文档以反映实际实现

---

### [CRIT-003] Phase1阈值文档与实现相差27倍

**文件**: `src/pairwise_scorer.py:215`

**文档**: `corr_mean >= 0.03` (module_3_pairwise_scoring.md line 268)

**实现**: `corr <= 0.8` (pairwise_scorer.py line 215)

**问题**: 阈值从0.03变成0.8，过滤严格度大幅增加，可能错过大量潜在配对

**风险**: 市场适应性降低，在相关性较低的市场环境下找不到交易机会

**修复建议**: 确认正确阈值，统一文档与代码

---

## 🟠 HIGH 级别

### [HIGH-001] IS/OS切分比例文档与代码不一致

**文件**: `src/optimizer.py:38`, `docs/module_4_optimizer.md`

**文档描述**: 
- 多处注释写 "前67%训练(IS)，后33%验证(OS)"
- 但常量定义 `IS_RATIO = 0.81`

**实际代码**: `IS_RATIO = 0.81` (81% IS, 19% OS)

**问题**: 注释与代码不符，容易造成理解错误

**修复建议**: 统一为81/19，更新所有注释

---

### [HIGH-002] M4 Phase1交易数阈值与文档不符

**文件**: `src/optimizer.py:296`

**文档**: `stats['n_trades'] < 10` 跳过 (module_4_optimizer.md line 152)

**实现**: `stats['n_trades'] < 3` (optimizer.py line 296)

**风险**: 过滤条件过松，可能保留低质量参数

**修复建议**: 统一为文档要求的10笔

---

## 🟡 MEDIUM 级别

### [MED-001] M3单币互斥限制与文档不符

**文件**: `src/pairwise_scorer.py:336,428-439`

**文档**: 单币最多3对，输出Top 100 (module_3_pairwise_scoring.md line 328)

**实现**: 
- 单币最多5对 (`max_per_coin = 5`)
- 输出所有通过筛选的配对，无Top N限制

**修复建议**: 按文档实现Top 100截断，或更新文档

---

### [MED-002] M3输出无Top N限制可能导致内存问题

**文件**: `src/pairwise_scorer.py:423-443`

**问题**: M3输出所有通过Phase2的配对，在极端市场情况下可能产生数千对

**风险**: M4处理大量配对时内存和CPU压力剧增

**修复建议**: 添加硬限制，最多输出200-300对

---

### [MED-003] _count_z_crosses算法效率低下

**文件**: `src/pairwise_scorer.py:108-135`

**问题**: 每次计算z-score都重新计算 expanding window 的均值和标准差，O(n²)复杂度

**风险**: 大数据量时性能瓶颈

**建议优化**: 使用Welford算法增量计算，如M4中的实现

---

### [MED-004] streaming_scanner代码重复

**文件**: `src/streaming_scanner.py:352-419`

**问题**: 重复实现了`_fast_corr`, `_count_z_crosses`, `_rolling_corr_stats`, `_compute_half_life`

**风险**: 维护困难，一处修改需同步多处，容易遗漏导致不一致

**修复建议**: 从pairwise_scorer.py导入共享函数

---

### [MED-005] optimize_pair未实现实际优化

**文件**: `src/streaming_scanner.py:186-201`

**问题**: `optimize_pair`只是返回固定参数，没有实际参数搜索

```python
# 当前实现
best_params = {'entry': 2.0, 'exit': 0.5, 'stop': 3.5}
```

**风险**: streaming_scanner的输出质量远低于正式扫描流程

**修复建议**: 接入与M4相同的参数优化逻辑，或标记为开发中功能

---

## 🟢 LOW 级别

### [LOW-001] 函数名与实际功能不符

**文件**: `src/optimizer.py:406-431`

**问题**: 函数名`_six_dim_score`实际只计算5个维度 (P,R,S,E,St)

**修复建议**: 重命名为`_five_dim_score`

---

### [LOW-002] 魔法数字未集中管理

**文件**: 多处

**问题**: `1e-12`, `1e-8`, `2.0`等epsilon值和阈值散落在代码中

**修复建议**: 集中到constants.py管理

---

### [LOW-003] M3与M4数据需求不一致

**文件**: `src/pairwise_scorer.py:209`, `src/optimizer.py:79`

**问题**:
- M3要求最少120根K线
- M4要求最少300根K线

**风险**: M3通过的配对可能在M4因数据不足被过滤

**修复建议**: 统一为300根，或在M3也要求300根

---

## 参数配置一致性检查

| 参数 | 文档值 | M3实现 | M4实现 | 状态 |
|------|--------|--------|--------|------|
| Phase1 corr阈值 | 0.03 | 0.8 | - | ❌ 不一致 |
| Phase1 spread_std | - | 0.002 | - | ⚠️ 未文档化 |
| Phase2 corr_mean | - | 0.85 | - | ⚠️ 未文档化 |
| Phase2 corr_std | - | 0.1 | - | ⚠️ 未文档化 |
| IS_RATIO | 0.81 | - | 0.81 | ✅ 一致 |
| MIN_TRADES_HARD_GATE | 10 | - | 10 | ✅ 一致 |
| MIN_PF_HARD_GATE | 1.5 | - | 1.5 | ✅ 一致 |
| MAX_DD_HARD_GATE | 20% | - | 20% | ✅ 一致 |
| 单币最大配对数 | 3 | 5 | 5 | ❌ 不一致 |
| Top N输出 | 100 | 无限制 | 30 | ❌ 不一致 |

---

## 修复建议优先级

### 立即修复 (本周)
1. **CRIT-001**: 统一M3和M4的spread计算方式
2. **CRIT-003**: 确认Phase1 corr阈值 (0.03 vs 0.8)

### 短期修复 (本月)
3. **CRIT-002**: 决定是补全Kalman实现还是更新文档
4. **HIGH-001**: 修正IS/OS注释
5. **HIGH-002**: 统一Phase1交易数阈值

### 持续改进
6. **MED-003**: 优化_count_z_crosses性能
7. **MED-004**: 消除streaming_scanner代码重复
8. 所有魔法数字集中管理

---

## 附注: 当前实现vs文档功能对照

| 功能 | 文档 | M3实现 | M4实现 |
|------|------|--------|--------|
| Kalman Filter | ✅ | ❌ 缺失 | N/A |
| reg_count统计 | ✅ | ❌ 缺失 | N/A |
| OS Sanity Check | ✅ | ❌ 缺失 | N/A |
| 三阶段筛选 | ✅ | ⚠️ 两阶段 | N/A |
| 动态beta | ✅ | ❌ 固定1.0 | ✅ 使用传入beta |
| IS/OS验证 | ✅ | N/A | ✅ 已实现 |
| 五维评分 | N/A | ❌ 四维评分 | ✅ 五维评分 |
| Numba加速 | N/A | ✅ 已实现 | ✅ 已实现 |
