# SignalEngine 信号计算模块 - 原子级文档

> **职责**: Z-Score实时计算，Kalman滤波，协整检验  
> **文件**: `src/signal_engine.py` (345行)  
> **状态**: P0-核心  
> **最后更新**: 2025-01-13

---

## 1. 类、函数完整签名

### 1.1 PairSignal (行33-170) - 配对信号结构
```python
@dataclass
class PairSignal:
    pair: str                      # 配对ID (如 "BTC_ETH")
    symbol_a: str                  # 币种A
    symbol_b: str                  # 币种B
    
    # 价格数据
    price_a: float                 # A当前价格
    price_b: float                 # B当前价格
    
    # Z-Score
    z_score: float                 # 当前Z-Score
    z_entry: float                 # 入场阈值 (默认2.7)
    z_exit: float                  # 出场阈值 (默认1.3)
    z_stop: float                  # 止损阈值 (默认4.2)
    
    # 协整参数
    beta: float                    # 对冲比率
    half_life: float               # 半衰期(小时)
    reg_count: int                 # 回归样本数
    
    # Kalman滤波
    kf_mean: float                 # Kalman均值
    kf_std: float                  # Kalman标准差
    
    # 信号
    signal: int                    # 1=做多价差, -1=做空价差, 0=无信号
    confidence: float              # 置信度 0-1
    
    # 时间戳
    timestamp: int                 # 毫秒时间戳
```

### 1.2 SignalEngine (行173-345) - 信号引擎主类
```python
class SignalEngine:
    def __init__(
        self,
        pair_config: Dict,              # 配对配置
        historical_data: Dict           # 历史数据 {symbol: {close: [], ...}}
    )  # 行173
    
    #  warmup与初始化
    def _warmup(self, hist_data: Dict)  # 行195
    # Kalman滤波器预热
    # 计算初始beta、均值、标准差
    
    def _recalculate_stats(self)        # 行217
    # 重新计算统计量
    # 使用滚动窗口更新均值和标准差
    
    # 核心信号计算
    def update_prices(
        self,
        price_a: float,                 # A最新价格
        price_b: float                  # B最新价格
    ) -> PairSignal                     # 行239
    # 更新价格并返回信号
    
    def get_z(self) -> float            # 行312
    # 获取当前Z-Score
    
    # 辅助方法
    def _calculate_spread(self) -> float  # 行321
    # 计算价差: spread = log(A) - beta * log(B)
    
    def _kalman_update(self, observation: float)  # 行332
    # Kalman滤波更新
```

---

## 2. 常量、阈值、默认值

| 常量 | 值 | 行号 | 说明 |
|------|-----|------|------|
| `MAX_FETCH_ERRORS` | 10 | 30 | 连续失败阈值 |
| `DEFAULT_Z_ENTRY` | 2.7 | 185 | 默认入场Z值 |
| `DEFAULT_Z_EXIT` | 1.3 | 186 | 默认出场Z值 |
| `DEFAULT_Z_STOP` | 4.2 | 187 | 默认止损Z值 |
| `KALMAN_Q` | 0.001 | 189 | 过程噪声协方差 |
| `KALMAN_R` | 0.1 | 190 | 观测噪声协方差 |
| `WARMUP_MIN_POINTS` | 100 | 197 | 预热最小数据点 |
| `ROLLING_WINDOW` | 500 | 219 | 滚动窗口大小 |
| `MIN_HALF_LIFE` | 0.5 | 227 | 最小半衰期(小时) |
| `MAX_HALF_LIFE` | 48.0 | 228 | 最大半衰期(小时) |

---

## 3. Z-Score计算流程

```
╔═══════════════════════════════════════════════════════════════╗
║                   SignalEngine Z-Score计算                     ║
╚═══════════════════════════════════════════════════════════════╝

初始化 (_warmup):
  ├─ 输入: 历史数据 hist_data = {symbol: {close: [...], ...}}
  ├─ 计算对冲比率 beta (OLS回归)
  │   log(A) = alpha + beta * log(B) + epsilon
  ├─ 初始化Kalman滤波器
  │   state = [mean, trend]
  │   Q = 0.001 (过程噪声)
  │   R = 0.1 (观测噪声)
  └─ 计算初始均值、标准差

实时计算 (update_prices):
  输入: price_a, price_b
         │
         ▼
  1. 计算对数价格
     log_a = ln(price_a)
     log_b = ln(price_b)
         │
         ▼
  2. 计算价差 (spread)
     spread = log_a - beta * log_b
         │
         ▼
  3. Kalman滤波更新
     kf_mean, kf_std = kalman_update(spread)
         │
         ▼
  4. 计算Z-Score
     z = (spread - kf_mean) / kf_std
         │
         ▼
  5. 生成信号
     ├─ z > z_entry:  signal = -1 (做空价差)
     ├─ z < -z_entry: signal = 1  (做多价差)
     ├─ |z| < z_exit: signal = 0  (平仓)
     └─ |z| > z_stop: signal = -2 (止损)
         │
         ▼
  输出: PairSignal对象

═══════════════════════════════════════════════════════════════
信号规则:
  做多价差 (signal=1):  Z < -entry  → 预期Z回归0
  做空价差 (signal=-1): Z > entry   → 预期Z回归0
  平仓 (signal=0):      |Z| < exit  → 利润锁定
  止损 (signal=-2):     |Z| > stop  → 切割损失
═══════════════════════════════════════════════════════════════
```

---

## 4. Kalman滤波实现

```
Kalman滤波器用于动态估计价差的均值和标准差

状态向量: x = [mean, trend]^T
观测值: z = spread

预测步骤:
  x_pred = F * x_prev
  P_pred = F * P * F^T + Q

更新步骤:
  y = z - H * x_pred      (观测残差)
  S = H * P_pred * H^T + R
  K = P_pred * H^T * S^-1 (Kalman增益)
  x_new = x_pred + K * y
  P_new = (I - K * H) * P_pred

参数:
  F = [[1, 1],    (状态转移矩阵)
       [0, 1]]
  H = [1, 0]      (观测矩阵)
  Q = 0.001 * I   (过程噪声)
  R = 0.1         (观测噪声)
```

---

## 5. 数据流转

```
Input:
  ├─ pair_config: {symbol_a, symbol_b, beta, z_entry, z_exit, z_stop}
  └─ historical_data: {symbol: {open[], high[], low[], close[], volume[]}}

Process:
  SignalEngine.__init__()
    └─ _warmup() 初始化统计量
  
  循环调用:
    update_prices(price_a, price_b)
      ├─ _calculate_spread()
      ├─ _kalman_update()
      └─ 生成信号

Output:
  └─ PairSignal对象 (含z_score, signal, confidence)
```

---

## 6. 调用关系

### 谁调用我
```
Runtime
└─ 每轮循环调用 signal_engine.update_prices()

Main (扫描模式)
└─ 批量计算历史信号
```

### 我调用谁
```
SignalEngine
├─ numpy (数组计算)
├─ statistics (均值/标准差)
└─ dataclasses (PairSignal)
```

---

## 7. 故障排查

| 症状 | 可能原因 | 解决 |
|------|----------|------|
| Z值异常波动 | Kalman参数不当 | 调整Q/R |
| 信号延迟 | 半衰期过长 | 检查配对质量 |
| beta漂移 | 协整关系破裂 | 重新计算beta |
| warmup失败 | 历史数据不足 | 确保>100点 |

---

**维护**: 修改信号逻辑时同步更新本文档
