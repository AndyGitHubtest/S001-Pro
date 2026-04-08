# gstack 架构深度解析

> 来源: github.com/garrytan/gstack (60.3K Stars)
> 目标: 彻底掌握这套代码编写方式，作为以后的第一技能

---

## 一、核心理念

### 1.1 不是"更会写代码"，而是"更会工作"

```
传统AI工具: 代码生成快不快？多文件修改准不准？
gstack:      需求定义对了吗？方案边界清晰吗？架构完整吗？
```

### 1.2 Boil the Lake 原则

> "AI makes completeness near-free. Always recommend the complete option over shortcuts."

| 概念 | 含义 |
|-----|------|
| Lake (湖) | 100%覆盖、所有边界情况 — **可煮沸** |
| Ocean (海) | 完整重写、多季度迁移 — **不可煮沸** |

**实践**: Boil lakes, flag oceans. 用AI的边际成本优势做到完整。

---

## 二、工作流架构 (7阶段)

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   THINK     │ →  │    PLAN     │ →  │    BUILD    │ →  │   REVIEW    │
│  /office-   │    │ /plan-ceo   │    │   编码实现   │    │   /review   │
│   hours     │    │  -review    │    │             │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                            ↓
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   REFLECT   │ ←  │    SHIP     │ ←  │    TEST     │ ←  │   REVIEW    │
│   /retro    │    │    /ship    │    │     /qa     │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### 2.1 各阶段职责

| 阶段 | Skill | 关键问题 | 输出物 |
|-----|-------|---------|--------|
| **定义** | `/office-hours` | 真正要解决什么问题？谁会买单？ | Design Doc |
| **产品** | `/plan-ceo-review` | 值得这样做吗？10星产品是什么？ | Product Review |
| **技术** | `/plan-eng-review` | 架构能落地吗？边界清晰吗？ | Architecture Doc |
| **审查** | `/review` | 有结构问题吗？能通过CI但生产崩溃吗？ | Review Report |
| **测试** | `/qa` | 真实浏览器验证通过吗？ | QA Report |
| **发布** | `/ship` | 测试通过？CHANGELOG更新？PR创建？ | Merged PR |
| **复盘** | `/retro` | 这周学到了什么？如何改进？ | Retro Notes |

---

## 三、Skill 系统设计模式

### 3.1 文件结构标准

```
skill-name/
├── SKILL.md           # 生成的最终文档 (不直接编辑)
├── SKILL.md.tmpl      # 模板源文件 (编辑这个)
└── (其他辅助文件)
```

### 3.2 SKILL.md 标准格式

```yaml
---
name: skill-name
preamble-tier: 3          # 1-4, 控制执行优先级
version: 1.0.0
description: |
  一句话描述这个skill做什么。
  使用场景: 当用户...时
  主动建议时机: 当...时主动建议
benefits-from: [other-skill]  # 依赖的前置skill
allowed-tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
---

<!-- AUTO-GENERATED from SKILL.md.tmpl — do not edit directly -->

## Preamble (run first)

```bash
# 1. 更新检查
# 2. Session管理
# 3. 配置读取 (PROACTIVE, TELEMETRY等)
# 4. 状态标记
```

## AskUserQuestion Format

**ALWAYS follow this structure:**
1. **Re-ground**: 项目、分支、当前任务 (1-2句)
2. **Simplify**: 用16岁能懂的话解释问题
3. **Recommend**: `RECOMMENDATION: Choose [X] because... Completeness: X/10`
4. **Options**: `A) ... B) ...` 显示工作量 `(human: ~X / CC: ~Y)`

## 核心工作流指令
...
```

### 3.3 模板系统 (`bun run gen:skill-docs`)

**为什么用模板？**
- 可维护: 修改模板 → 批量生成
- 可迁移: 换宿主工具时重新生成
- 一致性: 所有skill遵循相同结构

**模板变量:**
```yaml
{{PREAMBLE}}           # 通用前置代码
{{BROWSE_SETUP}}       # 浏览器设置
{{SNAPSHOT_FLAGS}}     # 快照标志
{{COMMAND_REFERENCE}}  # 命令参考
```

---

## 四、关键设计模式

### 4.1 AskUserQuestion 四段式

```
1. Re-ground (重新定位)
   "当前在 [项目] 的 [分支] 分支，正在 [任务]"

2. Simplify (简化解释)
   用类比解释问题本质，不要说技术术语

3. Recommend (推荐方案)
   RECOMMENDATION: Choose [A] because [原因]
   Completeness: 9/10 (完整实现所有边界情况)

4. Options (选项)
   A) 完整方案 (human: 2天 / CC: 10分钟)
   B) 快捷方案 (human: 2小时 / CC: 2分钟) ⚠️ 会遗漏X
```

### 4.2 Preamble 标准化

每个skill执行前必须运行:

```bash
# 1. 更新检查
_UPD=$(~/.claude/skills/gstack/bin/gstack-update-check 2>/dev/null || true)
[ -n "$_UPD" ] && echo "$_UPD" || true

# 2. Session管理
mkdir -p ~/.gstack/sessions
touch ~/.gstack/sessions/"$PPID"
_SESSIONS=$(find ~/.gstack/sessions -mmin -120 -type f 2>/dev/null | wc -l | tr -d ' ')
find ~/.gstack/sessions -mmin +120 -type f -delete 2>/dev/null || true

# 3. 配置读取
_PROACTIVE=$(~/.claude/skills/gstack/bin/gstack-config get proactive 2>/dev/null || echo "true")
_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
echo "BRANCH: $_BRANCH"
echo "PROACTIVE: $_PROACTIVE"

# 4. 遥测 (可选)
# ...记录skill使用情况...
```

### 4.3 Proactive Behavior (主动行为)

```yaml
If PROACTIVE is true:
  - 根据对话上下文主动建议skill
  - "我觉得 /qa 可能有用 — 要我运行吗？"

If PROACTIVE is false:
  - 只运行用户明确输入的 /command
  - 等待确认后再建议
```

---

## 五、安全机制

### 5.1 Safety Skills

| Skill | 功能 |
|-------|------|
| `/careful` | 危险操作前警告 (rm -rf, DROP TABLE, force-push) |
| `/freeze` | 锁定只编辑一个目录 |
| `/guard` | 同时激活 careful + freeze |
| `/unfreeze` | 解除目录锁定 |

### 5.2 破坏性操作检查

```bash
# 自动检测危险命令
careful_mode=$(~/.claude/skills/gstack/bin/gstack-config get careful 2>/dev/null || echo "true")

if [ "$careful_mode" = "true" ]; then
  # 执行前确认
  echo "⚠️  即将执行破坏性操作: [命令]"
  echo "确认? (yes/no)"
fi
```

---

## 六、应用到 S001-Pro

### 6.1 我们为 S001-Pro 设计的 Skill 工作流

```
/office-hours-s001      → 策略想法 brainstorming
/plan-risk-review       → 风控方案评审  
/plan-execution-review  → 执行逻辑评审
/review-s001            → 代码审查
/qa-s001                → 回测验证
/ship-s001              → 部署发布
/retro-s001             → 交易复盘
```

### 6.2 关键Skill设计

#### `/plan-risk-review` (风控方案评审)

```yaml
---
name: plan-risk-review
description: |
  评审量化交易策略的风控方案。
  检查: 仓位管理、止损逻辑、裸仓保护、资金费率、最大回撤。
  Use when: 修改风控参数、新策略上线前、发现异常交易时。
---

## 检查清单

### P0 风控 (必须全部通过)
- [ ] 有明确的单笔最大亏损限制
- [ ] 有日/周/月最大回撤限制
- [ ] 有自动停损机制 (不是人工)
- [ ] 不会在任何情况下产生裸仓
- [ ] 有异常检测和自动告警

### P1 风控 (建议有)
- [ ] 仓位与波动率自适应
- [ ] 多层级止损 (止损线、警告线)
- [ ] 流动性检查 (成交量过滤)
- [ ] 交易所状态监控

### 代码实现检查
```bash
# 1. 检查关键函数存在
grep -n "def calculate_position_size" src/*.py
grep -n "def check_stop_loss" src/*.py
grep -n "def naked_position_check" src/*.py

# 2. 检查硬编码风险值
# 不允许: MAGIC_NUMBER = 10000
# 应该: 从配置读取

grep -rn "=[0-9]\{4,\}" src/*.py | grep -v "config"
```
```

#### `/review-s001` (代码审查)

```yaml
---
name: review-s001
description: |
  Pre-trading code review for S001-Pro.
  检查: 裸仓保护、精度计算、异常处理、日志完整性。
---

## 审查流程

### Step 1: 检查修改范围
git diff --name-only HEAD~1

### Step 2: 关键文件必查
- src/main.py          → 主流程逻辑
- src/runtime.py       → 持仓管理
- src/preflight_check.py → 启动检查
- src/position_recovery.py → 仓位恢复

### Step 3: 风险模式扫描
grep -n "pass  # TODO" src/*.py
grep -n "except.*pass" src/*.py
grep -n "while True" src/*.py

### Step 4: 裸仓保护验证
grep -A5 "def open_position" src/*.py | grep -E "check|verify|assert"
```

---

## 七、实施计划

### 7.1 第一阶段: 建立核心Skill

1. [ ] 创建 `.claude/skills/s001/` 目录
2. [ ] 实现 `/plan-risk-review`
3. [ ] 实现 `/review-s001`
4. [ ] 实现 `/qa-s001` (回测验证)

### 7.2 第二阶段: 集成到工作流

1. [ ] 修改代码前 → 运行 `/plan-risk-review`
2. [ ] 提交代码前 → 运行 `/review-s001`
3. [ ] 部署前 → 运行 `/qa-s001`
4. [ ] 每周 → 运行 `/retro-s001`

### 7.3 第三阶段: 自动化

1. [ ] Git pre-commit hook 自动运行 `/review-s001`
2. [ ] GitHub Actions 集成
3. [ ] Telegram 通知集成

---

## 八、关键学习要点

### 8.1 思维模式转变

| 从前 | 以后 |
|-----|------|
| "帮我写这个函数" | "帮我评审这个方案" |
| 直接开始编码 | 先定义问题，再设计方案 |
| 写完就提交 | 写完review，review完测试 |
| 出了问题再修 | 上线前预防 |
| 个人经验 | 结构化工作流 |

### 8.2 代码编写铁律 (基于 gstack)

```
1. Plan Before Execute
   任何复杂功能先写方案，后写代码

2. Test-Driven
   先写测试，再写实现

3. Review Before Ship
   任何代码必须经过 review 才能提交

4. QA Before Deploy
   任何部署必须经过 QA 验证

5. Document Before Move On
   任何功能必须同步更新文档

6. Retro Before Next Week
   每周复盘，持续改进
```

---

## 九、参考资源

- [Boil the Lake Essay](https://garryslist.org/posts/boil-the-ocean)
- [gstack GitHub](https://github.com/garrytan/gstack)
- [AGENTS.md](./AGENTS.md) - 完整的36个agent说明

---

**下一步**: 要我立即为 S001-Pro 实现第一个 Skill (`/plan-risk-review`) 吗？
