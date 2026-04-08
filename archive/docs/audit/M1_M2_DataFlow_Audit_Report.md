# S001-Pro 数据流模块 (M1-M2) 审计报告

**审计时间**: 2025-04-08  
**审计范围**: src/data_engine.py, src/filters/initial_filter.py, src/binance_validator.py  
**文档对比**: docs/module_1_data_engine.md, docs/module_2_initial_filter.md, docs/module_binance_validator.md  

---

## 🔴 CRITICAL 级别问题

### 1. DataEngine 完全没有错误处理
**文件**: `src/data_engine.py`  
**位置**: 全文件 (424行无任何 try-except)  
**问题描述**:
- 数据库连接失败没有捕获 (行38: `sqlite3.connect(db_path)`)
- SQL执行错误没有处理 (行48-55, 75-78 等)
- 文件不存在/权限问题未处理
- 数据库损坏时会导致整个系统崩溃

**风险**: 生产环境数据库文件损坏或权限问题将导致整个交易系统无法启动

**建议修复**:
```python
class ConnectionManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        try:
            self.conn = sqlite3.connect(db_path)
            self._init_connection()
        except sqlite3.Error as e:
            logger.error(f"数据库连接失败: {e}")
            raise RuntimeError(f"无法连接数据库 {db_path}: {e}")
```

---

### 2. 符号链接失效风险
**文件**: `data/klines.db`  
**位置**: 符号链接指向 `/home/ubuntu/projects/data-core/data/klines.db`  
**问题描述**:
- klines.db 是一个指向绝对路径的符号链接
- 如果目标路径不存在或权限不足，系统启动时会直接崩溃
- 目标路径是绝对路径 `/home/ubuntu/...`，在不同环境下会失效

**风险**: 跨环境部署时 100% 失效

**建议修复**:
1. 使用相对路径或配置化路径
2. 启动时检查符号链接有效性
3. 提供降级方案（如使用内存模式或自动创建空数据库）

---

### 3. 文档与代码严重不一致 - min_vol 阈值
**文件**: `src/filters/initial_filter.py` (行57) vs `docs/module_2_initial_filter.md`  
**问题描述**:
| 来源 | min_vol 阈值 |
|------|-------------|
| 文档 module_2_initial_filter.md (行124) | 2,000,000 |
| 代码 initial_filter.py (行57) | 5,000,000 |
| 文档 module_1_data_engine.md (行44) | 2,000,000 |
| 代码 data_engine.py (行92) | 5,000,000 |

**风险**: 文档描述的流动性门槛与实际代码执行不一致，导致筛选结果与预期不符

---

## 🟡 MEDIUM 级别问题

### 4. 黑名单过滤器被移除但文档未更新
**文件**: `src/filters/initial_filter.py` vs `docs/module_2_initial_filter.md`  
**问题描述**:
- 代码中注释"过滤器 2: [已取消] 黑名单限制" (行53)
- 但文档仍详细描述了72个币种的黑名单 (行21-33)
- 文档声称"七重过滤防线"，但代码只有6道过滤

**风险**: 运营团队可能误以为Meme币被过滤，实际代码允许所有币种通过

---

### 5. BinanceValidator 没有缓存刷新机制
**文件**: `src/binance_validator.py`  
**问题描述**:
- 文档 module_binance_validator.md 声称有 `CACHE_TTL = 3600` 和 `refresh_markets()` 方法
- 实际代码中没有这些功能
- 市场列表仅在初始化时加载一次，长期运行时会过期

**风险**: 币种上下线时验证器使用过期的市场数据，可能拒绝有效交易或接受无效交易

---

### 6. HotPool 构建时单线程顺序处理
**文件**: `src/data_engine.py` HotPoolBuilder.build() (行152-249)  
**问题描述**:
- 对每个symbol串行执行SQL查询
- 如果有100个币种，需要100次数据库往返
- 没有使用批量查询或并发

**风险**: 大量币种场景下性能严重下降

**建议优化**:
使用 `IN` 子句批量查询或增加并发线程池

---

### 7. NaN 处理逻辑不一致
**文件**: `src/data_engine.py`  
**问题描述**:
- `_fill_nan` 方法 (行229-249) 仅处理头部 NaN 的"前向填充"
- 但方法名暗示完整的前向填充，实际上只处理头部
- 中间 NaN 的 ffill 逻辑不存在于该函数中

**风险**: 代码可读性下降，维护困难

---

## 🟢 LOW 级别问题

### 8. 日志信息不一致
**文件**: `src/filters/initial_filter.py` (行40)  
**问题描述**:
```python
logger.info(f"InitialFilter: {len(symbols)} -> {len(qualified)} assets passed 7-filter pipeline.")
```
- 声称"7-filter"，实际只有6道过滤
- 日志固定字符串，无法反映实际过滤数量变化

---

### 9. 测试文件硬编码路径
**文件**: `test_dataflow.py` (行21)  
**问题描述**:
```python
db = DataEngine('data/klines.db')  # 硬编码路径
```
- 测试文件硬编码数据库路径
- 没有环境变量或配置覆盖机制

---

### 10. 缺少数据完整性检查
**文件**: `src/data_engine.py` MarketStatsLoader.load() (行92-139)  
**问题描述**:
- 加载market_stats后没有验证数据时间戳是否最新
- 可能使用过期的统计数据做决策
- 没有检查first_ts与当前时间的差距

---

## ✅ 良好实践确认

1. **API Rate Limit 处理正确**: `tools/binance_futures_sync.py` (行152) 使用 `RATE_LIMIT_DELAY = 0.5` 限速保护
2. **ccxt enableRateLimit**: `src/streaming_scanner.py` (行43) 正确启用内置限流
3. **网络错误重试**: `tools/binance_futures_sync.py` (行155-165) 对 `ccxt.NetworkError` 有3次重试机制
4. **数据库PRAGMA优化**: WAL模式、NORMAL同步级别配置正确
5. **Numba加速**: `src/pairwise_scorer.py` 正确使用Numba JIT加速计算

---

## 建议修复优先级

| 优先级 | 问题 | 预计修复时间 |
|--------|------|-------------|
| P0 | DataEngine 错误处理 | 2小时 |
| P0 | 符号链接路径问题 | 30分钟 |
| P0 | min_vol 文档与代码对齐 | 30分钟 |
| P1 | BinanceValidator 缓存刷新 | 1小时 |
| P1 | 黑名单文档更新 | 30分钟 |
| P2 | HotPool 批量查询优化 | 3小时 |
| P2 | 数据时效性检查 | 1小时 |

---

## 审计结论

**M1-M2模块整体风险等级: MEDIUM-HIGH**

主要风险集中在:
1. 生产环境稳定性（缺少错误处理）
2. 文档与代码不一致（可能导致运营决策失误）

建议在生产部署前优先修复 CRITICAL 级别问题。
