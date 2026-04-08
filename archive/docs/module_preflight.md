# PreFlight 启动检查模块 - 原子级文档

> **职责**: 生产级7阶段16步启动前检查，带熔断机制  
> **文件**: `src/preflight_check.py` (691行)  
> **状态**: P0-核心  
> **最后更新**: 2025-01-13

---

## 1. 类、函数完整签名

### 1.1 PreFlightResult (行34-45)
```python
@dataclass
class PreFlightResult:
    phase: str           # 阶段名称
    passed: bool         # 是否通过
    message: str         # 描述信息
    details: Dict = None # 详细数据
    timestamp: str = ""  # ISO时间戳
```

### 1.2 RestartSnapshot (行49-61)
```python
@dataclass  
class RestartSnapshot:
    restart_time: str      # 重启时间
    reason: str            # 重启原因
    initial_equity: float  # 初始权益
    positions_count: int   # 持仓数量
    daily_pnl_pct: float   # 日盈亏%
    margin_ratio: float    # 保证金率
    checks_passed: int     # 通过检查数
    checks_total: int      # 总检查数
```

### 1.3 StartupLock (行64-94)
```python
class StartupLock:
    def __init__(self, lock_file: str = ".startup.lock")
    def acquire(self, timeout: int = 30) -> bool   # 行71
    def release(self)                               # 行85
```

### 1.4 PreFlightCheck (行97-691)
```python
class PreFlightCheck:
    # 初始化
    def __init__(
        self, 
        exchange: ccxt.Exchange, 
        config: Dict, 
        state_file: str = "data/state.json"
    )  # 行109
    
    # 主入口
    def run_all_phases(self) -> Tuple[bool, List[PreFlightResult]]  # 行124
    
    # P1_Connect (行186-214)
    def _phase_connect(self) -> Tuple[bool, str, Dict]
    
    # P2_Config (行219-318)
    def _validate_symbols(self) -> Tuple[bool, str, int]  # 行219
    def _phase_config(self) -> Tuple[bool, str, Dict]      # 行263
    
    # P3_Position (行323-387)
    def _phase_position(self) -> Tuple[bool, str, Dict]    # 行323
    def _load_local_state(self) -> Dict                    # 行388
    
    # P4_Risk (行407-482)
    def _phase_risk(self) -> Tuple[bool, str, Dict]        # 行407
    def _check_drawdown(self) -> Tuple[bool, str]          # 行483
    
    # P5_Channel (行518-555)
    def _phase_channel(self) -> Tuple[bool, str, Dict]     # 行518
    
    # P6_Data (行556-604)
    def _phase_data(self) -> Tuple[bool, str, Dict]        # 行556
    
    # P7_Launch (行605-647)
    def _phase_launch(self) -> Tuple[bool, str, Dict]      # 行605
    def _create_restart_snapshot(self, reason: str)        # 行648
```

---

## 2. 常量、阈值、默认值

| 常量 | 值 | 行号 | 说明 |
|------|-----|------|------|
| `CHECK_TIMEOUT` | 30 | 101 | 单阶段超时(秒) |
| `TOTAL_TIMEOUT` | 300 | 102 | 总超时5分钟 |
| `MAX_MARGIN_RATIO` | 0.80 | 105 | 最大仓位使用率80% |
| `MIN_MARGIN_BUFFER` | 1.5 | 106 | 保证金缓冲倍数 |
| `MAX_DAILY_DRAWDOWN` | -5.0 | 107 | 最大日回撤-5% |
| `MIN_CAPITAL_USDT` | 500.0 | 447 | 最小本金500U |
| `MAX_POSITION_PCT` | 0.50 | 464 | 单对最大仓位50% |
| `MIN_PAIRS_FOR_STOP` | 5 | 568 | 强制停止的最小配对数 |

---

## 3. 7阶段16步检查流程

```
╔═══════════════════════════════════════════════════════════════╗
║                    PreFlight 7阶段检查                         ║
╚═══════════════════════════════════════════════════════════════╝

P1_Connect [步骤2]
├─ 测试API连接 (行190-193)
├─ 验证余额查询权限 (行193)
└─ 验证持仓查询权限 (行196)

P2_Config [步骤4]
├─ _validate_symbols(): 验证symbol存在性 (行219)
│  └─ 移除无效配对，防止Leg Sync Fail
├─ set_position_mode(True): 双向持仓模式 (行276)
└─ set_leverage(5x): 统一5倍杠杆 (行300)
   └─ 处理 -4048, -4164, No need to change

P3_Position [步骤1,3]
├─ _load_local_state(): 读取本地状态 (行388)
├─ fetch_positions(): 拉取交易所持仓 (行331)
└─ 核对本地 vs 交易所 (行343-387)
   ├─ 匹配: 恢复Runtime状态
   └─ 不匹配: 提示手动处理

P4_Risk [步骤5,6,7,13]
├─ _check_drawdown(): 检查回撤 (行483)
│  ├─ 日回撤 < -5%: 停止
│  └─ 总回撤 < -15%: 停止
├─ 检查保证金率 (行427-445)
│  ├─ margin_ratio > 80%: 告警
│  └─ 可用保证金不足: 停止
└─ 检查本金充足性 (行447-465)
   └─ 本金 < 500U: 停止

P5_Channel [步骤10,11]
├─ 交易通道测试 (行518-555)
├─ fetch_orders(): 查询订单 (行534)
└─ 检查响应时间 < 1秒 (行540)

P6_Data [步骤8,9]
├─ 检查配对配置 (行556-604)
│  ├─ pairs_v2.json 存在
│  ├─ 至少1对有效配对
│  └─ FIX P0-2: 无配对时警告继续
├─ 检查state.json可写
└─ 检查日志目录

P7_Launch [步骤14,15,16]
├─ _create_restart_snapshot(): 创建重启快照 (行648)
├─ 发送Telegram通知 (行630)
└─ 返回 (all_passed, results) (行181)

═══════════════════════════════════════════════════════════════
熔断机制: 任何阶段失败立即停止
超时保护: 单阶段30s, 总超时300s
并发保护: StartupLock文件锁
═══════════════════════════════════════════════════════════════
```

---

## 4. 数据流转

```
Input:
  ├─ config/base.yaml (风险参数、杠杆)
  ├─ config/pairs_v2.json (交易对配置)
  ├─ data/state.json (本地持仓状态)
  └─ 交易所API (实时余额、持仓)

Process:
  PreFlightCheck.run_all_phases()
    ├─ P1: 连接检查
    ├─ P2: 配置设置
    ├─ P3: 持仓核对
    ├─ P4: 风控检查
    ├─ P5: 通道测试
    ├─ P6: 数据检查
    └─ P7: 启动完成
      └─ _create_restart_snapshot()

Output:
  ├─ Tuple[bool, List[PreFlightResult]] (启动结果)
  ├─ data/restart_snapshot.json (重启快照)
  └─ Telegram通知
```

---

## 5. 调用关系

### 谁调用我
```
main.py
└─ run_preflight_check() (行647-691)
   └─ PreFlightCheck.run_all_phases()
```

### 我调用谁
```
PreFlightCheck
├─ ccxt.Exchange
│  ├─ load_markets()
│  ├─ fetch_balance()
│  ├─ fetch_positions()
│  ├─ set_position_mode()
│  └─ set_leverage()
├─ json (读写state.json)
├─ fcntl (文件锁)
└─ logging
```

---

## 6. 关键代码片段

### 6.1 启动锁实现 (行64-94)
```python
class StartupLock:
    def acquire(self, timeout: int = 30) -> bool:
        self.fd = open(self.lock_file, 'w')
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # 非阻塞获取，失败返回False
```

### 6.2 Symbol验证 (行219-261)
```python
def _validate_symbols(self) -> Tuple[bool, str, int]:
    """FIX P0-6: 验证symbol存在性，移除无效配对"""
    for pair in pairs:
        a_exists = sym_a in self.exchange.markets
        b_exists = sym_b in self.exchange.markets
        if not (a_exists and b_exists):
            # 从配置中移除
            self.config["pairs"] = valid_pairs
```

### 6.3 无配对处理 (行568-585)
```python
# FIX P0-2: 无配对时警告但不停止
if not pairs:
    logger.warning("⚠️ [P6] 无交易对配置，跳过交易通道测试")
    return True, "无配对，等待扫描添加", {"pairs_count": 0}
```

---

## 7. 故障排查

| 症状 | 可能原因 | 解决 |
|------|----------|------|
| P1失败 | API Key错误 | 检查config/base.yaml |
| P2失败 | 杠杆设置被拒 | 检查账户状态/币种支持 |
| P3失败 | 持仓不一致 | 手动平仓后清理state.json |
| P4失败 | 回撤超限 | 检查daily_stats.json |
| P5失败 | 网络延迟 | 检查服务器网络 |
| P6失败 | pairs_v2.json缺失 | 运行扫描生成 |

---

**维护**: 每次修改启动流程时更新本文档
