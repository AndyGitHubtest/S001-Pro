# BinanceValidator 币安验证器模块 - 原子级文档

> **职责**: 币安合约有效性验证，防止交易无效币种  
> **文件**: `src/binance_validator.py` (133行)  
> **状态**: P1-重要  
> **最后更新**: 2025-01-13

---

## 1. 类、函数完整签名

### 1.1 BinanceFuturesValidator (行12-133)
```python
class BinanceFuturesValidator:
    def __init__(self)  # 行17
    # 初始化ccxt客户端
    
    def _init_client(self)  # 行22
    # 创建币安合约客户端
    
    # 验证方法
    def is_valid_symbol(self, symbol: str) -> bool  # 行50
    # 检查symbol是否在币安合约市场
    
    def filter_valid_pairs(
        self,
        pairs: List[Dict]        # 配对列表
    ) -> Tuple[List[Dict], List[str]]  # 行63
    # 返回: (有效配对列表, 无效symbol列表)
    
    def get_valid_symbols(self) -> Set[str]  # 行103
    # 获取所有有效币种集合
    
    def refresh_markets(self)  # 行113
    # 刷新市场数据(币种上下线)

# 全局单例
def get_validator() -> BinanceFuturesValidator  # 行127
```

---

## 2. 常量

| 常量 | 值 | 行号 | 说明 |
|------|-----|------|------|
| `CACHE_TTL` | 3600 | 19 | 市场数据缓存时间(秒) |
| `TESTNET` | False | 24 | 是否使用测试网 |

---

## 3. 使用场景

```python
# 场景1: 扫描前验证
validator = get_validator()
valid_pairs, invalid = validator.filter_valid_pairs(pairs)
if invalid:
    logger.warning(f"移除无效币种: {invalid}")

# 场景2: 下单前验证
if not validator.is_valid_symbol("BTC/USDT"):
    raise ValueError("无效币种")
```

---

## 4. 调用关系

### 谁调用我
```
PreFlight._validate_symbols()
└─ filter_valid_pairs()

DataEngine (扫描时)
└─ 过滤无效币种
```

---

**维护**: 币安API变更时更新本文档
