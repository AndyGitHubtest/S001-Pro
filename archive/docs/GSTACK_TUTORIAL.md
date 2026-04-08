# gstack 完全上手指册

> **目标**: 第一时间使用，彻底掌握这套技能系统  
> **场景**: 在 S001-Pro 项目中实战应用  
> **时间**: 30分钟上手，1小时掌握

---

## 第一步: 验证安装

```bash
# 检查 gstack 是否已就绪
ls ~/.claude/skills/gstack/

# 应该看到: office-hours/ review/ ship/ qa/ 等目录
```

**你的状态**: ✅ 已安装 (版本 0.12.2.0)

---

## 第二步: 核心概念 (5分钟)

### 2.1 什么是 gstack?

**一句话**: gstack 是一套**AI 软件工程工作流**，把 AI 从"代码生成器"变成"虚拟工程团队"。

### 2.2 7阶段工作流

```
想法 → 定义 → 设计 → 编码 → 审查 → 测试 → 发布 → 复盘
      ↑           ↑          ↑         ↑        ↑
  /office    /plan-eng    /review    /qa     /ship
  -hours     -review                         /retro
```

### 2.3 为什么用 gstack?

| 不用 gstack | 用 gstack |
|-----------|----------|
| "帮我写这个函数" | "帮我评审这个方案" |
| 写完发现方向错了 | 写前先定义问题 |
| 上线后出 bug | 上线前 QA 验证 |
| 个人经验驱动 | 结构化流程驱动 |

---

## 第三步: 第一个技能实战 (10分钟)

### 场景: 你想为 S001-Pro 添加一个新功能

**传统方式**:
- 直接开始写代码 → 写到一半发现逻辑有问题 → 重构 → 发现方案不对 → 重来

**gstack 方式**:

### Step 1: /office-hours (定义问题)

**输入**:
```
/office-hours
```

**你会被问到**:
1. "你真正要解决什么问题？"
2. "谁会为这件事买单？"
3. "什么是当前最应该推进的一步？"

**输出**: 一份 Design Doc，明确:
- 问题定义
- 目标用户
- 成功标准
- 第一阶段边界

### Step 2: /plan-eng-review (技术方案)

**输入**:
```
/plan-eng-review
```

**AI 会做**:
- 检查现有架构
- 设计数据流
- 识别边界情况
- 规划测试矩阵

**输出**: 技术方案文档，包含:
- 架构图
- API 设计
- 失败模式分析
- 测试计划

### Step 3: 编码实现

基于前两个步骤的文档，开始编码。

### Step 4: /review (代码审查)

**输入**:
```
/review
```

**AI 会做**:
- 分析 git diff
- 检查 SQL 注入风险
- 检查边界情况
- 检查测试覆盖

**输出**: Review Report

### Step 5: /ship (发布)

**输入**:
```
/ship
```

**AI 会做**:
- 运行测试
- 更新 CHANGELOG
- 创建 PR
- 合并代码

---

## 第四步: 实战演练 (15分钟)

### 演练 1: 用 /office-hours 定义一个新策略想法

**场景**: 你想为 S001-Pro 添加"动态仓位管理"功能

**操作**:
```
/office-hours
```

**预期对话**:

AI: "我们在 S001-Pro 的 main 分支，你提到要添加动态仓位管理。让我先理解："

AI: "**真正的问题是什么？**
当前固定仓位可能在波动率变化时风险过大，你想让仓位自动适应市场波动？"

你: "是的，波动大时减少仓位"

AI: "**谁会受益？**
这将直接影响实盘的资金安全和回撤控制。"

AI: "**RECOMMENDATION**: Choose [基于ATR的动态仓位] because 它直接关联波动率，且已有成熟实践
Completeness: 9/10"

**输出文件**: `docs/design/dynamic-position-sizing.md`

---

### 演练 2: 用 /review 审查最近修改

**操作**:
```
/review
```

**AI 会执行**:

```bash
# 1. 获取 git diff
git diff main...HEAD

# 2. 扫描风险模式
grep -n "pass  # TODO" src/*.py
grep -n "except.*pass" src/*.py
grep -n "while True" src/*.py

# 3. 检查关键文件
- src/main.py
- src/runtime.py
- src/preflight_check.py
```

**输出示例**:
```
## Review Report

### 发现的问题

⚠️  HIGH: 裸仓风险
文件: src/main.py:234
问题: place_order 失败后没有验证两条腿是否都成交
建议: 添加 verify_both_legs_filled() 检查

⚠️  MEDIUM: 硬编码参数
文件: src/config.py:15
问题: MAX_POSITION = 10000
建议: 从账户权益动态计算

### 通过检查
✅ 无 SQL 注入风险
✅ 有错误处理
✅ 测试覆盖率 > 80%
```

---

### 演练 3: 用 /qa 验证回测结果

**操作**:
```
/qa
```

**AI 会执行**:

```bash
# 1. 运行测试
python tests/run_tests.py

# 2. 检查回测数据完整性
ls data/backtest_results/

# 3. 验证关键指标
python -c "
import json
with open('data/backtest_results/latest.json') as f:
    r = json.load(f)
    assert r['sharpe'] > 1.0, 'Sharpe too low'
    assert r['max_drawdown'] < 0.2, 'Drawdown too high'
"
```

---

## 第五步: 日常开发工作流

### 每日工作流程

```
1. 开始新功能
   └── /office-hours → 定义问题和范围

2. 设计技术方案
   └── /plan-eng-review → 确定架构和边界

3. 编码实现
   └── 写代码 + 测试

4. 提交前
   └── /review → 代码审查

5. 部署前
   └── /qa → 验证测试通过

6. 发布
   └── /ship → 合并推送

7. 周末
   └── /retro → 复盘本周
```

### 常用技能速查

| 技能 | 使用时机 | 一句话说明 |
|-----|---------|-----------|
| `/office-hours` | 有新想法时 | 定义问题，避免做错 |
| `/plan-ceo-review` | 产品方向不确定 | 从CEO视角审视 |
| `/plan-eng-review` | 技术方案设计 | 锁定架构边界 |
| `/review` | 代码写完后 | 预发布代码审查 |
| `/qa` | 准备部署前 | 浏览器/功能测试 |
| `/ship` | 一切就绪后 | 一键发布 |
| `/retro` | 每周结束时 | 复盘改进 |
| `/careful` | 执行危险操作前 | 增加安全检查 |

---

## 第六步: 为 S001-Pro 定制技能

### 6.1 创建 S001-Pro 专用技能

```bash
# 创建技能目录
mkdir -p ~/.claude/skills/s001/plan-risk-review
mkdir -p ~/.claude/skills/s001/review-s001
mkdir -p ~/.claude/skills/s001/qa-s001
```

### 6.2 已为你创建的技能

我已经创建了:

1. **`/plan-risk-review`** - 风控方案评审
   - 检查裸仓保护
   - 检查止损逻辑
   - 检查硬编码风险值

2. **`/review-s001`** - S001-Pro 代码审查
   - 扫描裸仓风险
   - 检查精度计算
   - 验证异常处理

### 6.3 使用 S001-Pro 专用技能

```
# 在 S001-Pro 目录下

cd ~/S001-Pro

# 修改代码前 - 评审风控
/plan-risk-review

# 提交前 - 代码审查
/review-s001

# 部署前 - QA验证
/qa-s001
```

---

## 第七步: 高级技巧

### 7.1 快速启动新功能

```
# 一条命令序列
/office-hours && /plan-eng-review && echo "可以开始编码了"
```

### 7.2 安全模式

```
# 在执行危险操作前
/careful

# 这会添加安全检查:
# - rm -rf 前确认
# - DROP TABLE 前确认
# - git force-push 前确认
```

### 7.3 锁定编辑范围

```
# 只让 AI 编辑特定目录
/freeze src/

# 完成后解除
/unfreeze
```

### 7.4 调试模式

```
# 系统化调试
/investigate

# AI 会:
# 1. 收集日志
# 2. 分析错误模式
# 3. 提出假设
# 4. 验证修复
```

---

## 第八步: 常见问题

### Q: gstack 和直接让 AI 写代码有什么区别?

**A**: 
- 直接写: 容易方向错误、遗漏边界情况、上线后出问题
- gstack: 先定义清楚，再设计方案，然后编码，最后验证 — 降低错误率

### Q: 每个功能都要走完整7步吗?

**A**: 
- 小改动 (改错别字、调参数): 直接做
- 中等改动 (新函数、重构): /review
- 大改动 (新功能、架构调整): 完整流程

### Q: 可以用在 S001-Pro 之外的项目吗?

**A**: 可以！gstack 是通用的，任何项目都可以用。

---

## 第九步: 练习作业

### 作业 1: 用 /office-hours 定义一个新功能

**任务**: 为 S001-Pro 设计"自动资金划转"功能

**提交物**:
- 运行 `/office-hours` 的对话记录
- 生成的 Design Doc

### 作业 2: 用 /review 审查代码

**任务**: 让 `/review` 分析 `src/main.py`

**提交物**:
- Review Report
- 发现的 3 个问题

### 作业 3: 完整工作流

**任务**: 用 gstack 完成一个小功能

**步骤**:
1. `/office-hours` - 定义功能
2. 编码实现
3. `/review` - 审查代码
4. `/ship` - 发布

---

## 第十步: 记忆卡片

### 每天必用

```
/office-hours    → 有新想法时先用这个
/review          → 提交前必用
```

### 每周必用

```
/retro           → 周末复盘
```

### 关键原则

```
1. 先定义问题，再写代码
2. 任何提交前必须经过 /review
3. 任何部署前必须经过 /qa
4. Boil the Lake: 用AI做到完整，不要走捷径
```

---

## 现在开始！

**选择你的第一个练习:**

A) 运行 `/office-hours` 讨论 S001-Pro 的改进想法  
B) 运行 `/review` 审查最近的代码修改  
C) 运行 `/plan-risk-review` 检查当前风控实现

**输入 A/B/C 或告诉我你想做什么，我立即带你实战！**
