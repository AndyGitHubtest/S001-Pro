# ProfitManager 利润管理模块 - 原子级文档

> **职责**: 利润自动划转，资金费率监控，成本追踪  
> **文件**: `src/profit_manager.py` (162行)  
> **状态**: P2-辅助  
> **最后更新**: 2025-01-13

---

## 1. 类、函数完整签名

### 1.1 ProfitManager (行20-162)
```python
class ProfitManager:
    def __init__(
        self,
        exchange: ccxt.Exchange,
        config: Dict
    )  # 行23
    
    # 利润划转
    async def transfer_profits(
        self,
        amount: Optional[float] = None  # 默认全部可划转
    ) -> bool  # 行38
    
    # 资金费率
    async def check_funding_rates(self) -> List[Dict]  # 行67
    # 检查持仓币种的资金费率
    # 返回高风险列表(funding > 0.1%)
    
    # 成本计算
    def calculate_total_cost(
        self,
        trades: List[Dict]
    ) -> Dict  # 行87
    # 计算总手续费、滑点成本
    
    # 利润统计
    def get_daily_pnl(self) -> Dict  # 行112
    def get_cumulative_pnl(self) -> Dict  # 行127
    
    # 停止
    def stop(self)  # 行147
```

---

## 2. 常量

| 常量 | 值 | 行号 | 说明 |
|------|-----|------|------|
| `FUNDING_THRESHOLD` | 0.001 | 28 | 资金费率告警阈值(0.1%) |
| `MIN_TRANSFER_AMOUNT` | 10.0 | 29 | 最小划转金额(USDT) |
| `TRANSFER_FEE` | 0.0 | 30 | 划转手续费(币安内部划转免费) |

---

## 3. 数据流转

```
Runtime (定时任务)
    │
    ▼
ProfitManager
    ├─ check_funding_rates()
    │  ├─ fetch_positions()
    │  ├─ fetch_funding_rate() (每个持仓币种)
    │  └─ 返回高风险列表 → Telegram通知
    │
    └─ transfer_profits() (每日/达到阈值)
       ├─ fetch_balance()
       ├─ 计算可划转金额
       └─ transfer() (到现货账户)
```

---

**维护**: 修改利润逻辑时更新本文档
