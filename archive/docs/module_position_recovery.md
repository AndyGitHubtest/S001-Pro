# PositionRecovery 仓位恢复模块 - 原子级文档

> **职责**: 简单状态持久化，state.json读写  
> **文件**: `src/position_recovery.py` (210行)  
> **状态**: P1-重要  
> **最后更新**: 2025-01-13

---

## 1. 类、函数完整签名

### 1.1 PositionState (行22-36) - 仓位状态
```python
@dataclass
class PositionState:
    pair: str                   # 配对ID
    symbol_a: str               # 币种A
    symbol_b: str               # 币种B
    direction: int              # 1=多A空B, -1=空A多B
    state: str                  # IDLE/SCALING_IN/IN_POSITION/SCALING_OUT
    entry_z: float              # 入场Z-Score
    scale_in_layer: int         # 建仓层数 0-3
    scale_out_layer: int        # 平仓层数 0-3
    position_size_pct: float    # 仓位百分比
    entry_price_a: float        # A入场价
    entry_price_b: float        # B入场价
    updated_at: str             # 更新时间ISO
```

### 1.2 PositionRecoveryManager (行38-210) - 恢复管理器
```python
class PositionRecoveryManager:
    def __init__(
        self,
        state_path: str = "data/state.json"
    )  # 行48
    
    # 状态管理
    def update_position(self, position: PositionState)  # 行54
    def remove_position(self, pair: str)              # 行59
    def get_position(self, pair: str) -> Optional[PositionState]  # 行64
    def get_all_positions(self) -> Dict[str, PositionState]  # 行74
    
    # 持久化
    def save_state(self)                              # 行79
    def load_state(self) -> Dict[str, PositionState]  # 行94
    def clear_state(self)                             # 行109
    
    # 辅助
    def _save_if_needed(self)                         # 行114
    def get_positions_by_state(self, state: str) -> List[PositionState]  # 行124
    def export_to_dict(self) -> Dict                  # 行134
    def import_from_dict(self, data: Dict)            # 行144
    
    # 统计
    def get_summary(self) -> Dict                     # 行154
    def validate_state(self) -> Tuple[bool, str]      # 行174
```

---

## 2. 常量

| 常量 | 值 | 行号 | 说明 |
|------|-----|------|------|
| `SAVE_INTERVAL` | 5 | 44 | 自动保存间隔(秒) |
| `STATE_VERSION` | "1.0" | 46 | 状态文件版本 |

---

## 3. state.json 格式

```json
{
  "version": "1.0",
  "last_updated": "2025-01-13T08:30:00",
  "positions": {
    "BTC_ETH": {
      "pair": "BTC_ETH",
      "symbol_a": "BTC/USDT",
      "symbol_b": "ETH/USDT",
      "direction": 1,
      "state": "IN_POSITION",
      "entry_z": 2.8,
      "scale_in_layer": 3,
      "scale_out_layer": 0,
      "position_size_pct": 1.0,
      "entry_price_a": 50000.0,
      "entry_price_b": 3000.0,
      "updated_at": "2025-01-13T08:30:00"
    }
  }
}
```

---

## 4. 调用关系

### 谁调用我
```
Runtime
├─ update_position() (状态变更)
└─ get_all_positions() (恢复时)

PreFlight
└─ load_state() (启动核对)
```

---

**维护**: 修改状态结构时更新本文档
