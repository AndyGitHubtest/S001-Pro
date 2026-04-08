# S001-Pro 监控面板 - 技术架构文档

> 生成时间: 2026-04-07  
> 通过: `/plan-eng-review` 流程

---

## 1. 技术栈

| 层级 | 技术 | 版本 | 说明 |
|-----|------|------|------|
| 前端 | React | 18.x | 用户界面 |
| 前端 | TypeScript | 5.x | 类型安全 |
| 前端 | Tailwind CSS | 3.x | 样式框架 |
| 前端 | Recharts | 2.x | 图表库 |
| 后端 | FastAPI | 0.100+ | API框架 |
| 后端 | Python | 3.9+ | 和你策略一致 |
| 数据库 | SQLite | 3.x | 只读访问S001数据 |
| 部署 | Nginx | - | 反向代理 |
| 服务器 | Ubuntu | 22.04 | 现有服务器 |

---

## 2. 系统架构

```
┌───────────────────────────────────────────────────────────────┐
│                        用户浏览器                              │
│                   (电脑/手机/平板)                             │
└───────────────────────┬───────────────────────────────────────┘
                        │ HTTPS/HTTP
                        │ 每5秒刷新
                        ▼
┌───────────────────────────────────────────────────────────────┐
│                      Nginx 反向代理                            │
│              端口 80/443 → 转发到 3000                          │
└───────────────────────┬───────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────┐
│                   FastAPI 后端服务                             │
│                        端口 3000                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ /api/login  │  │/api/summary │  │/api/positions│           │
│  │   登录      │  │  汇总数据   │  │   持仓列表   │           │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ /api/orders │  │ /api/logs   │  │ /api/chart/*│            │
│  │  订单记录   │  │  日志流     │  │   图表数据  │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└──────────┬────────────────────────────────────────────────────┘
           │
    ┌──────┴──────┬──────────────┬──────────────┐
    │             │              │              │
    ▼             ▼              ▼              ▼
┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ SQLite  │ │ Binance  │ │  心跳    │ │  日志    │
│ 数据库  │ │   API    │ │  文件    │ │  文件    │
│(S001数据)│ │(查价格)  │ │(在线状态)│ │(交易日志)│
└─────────┘ └──────────┘ └──────────┘ └──────────┘
```

---

## 3. 数据库访问（只读）

### 3.1 连接配置
```python
# 只读连接，不影响策略
DATABASE_PATH = "~/S001-Pro/data/klines.db"

# SQLAlchemy 配置
engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False},
    echo=False  # 生产环境关闭日志
)
```

### 3.2 核心查询
```sql
-- 当前持仓
SELECT symbol_a, symbol_b, side, entry_price, quantity, 
       (current_price - entry_price) * quantity as pnl
FROM positions 
WHERE status = 'OPEN';

-- 今日收益
SELECT SUM(pnl) as daily_pnl, COUNT(*) as trade_count
FROM orders 
WHERE DATE(created_at) = DATE('now') 
  AND status = 'FILLED';

-- 历史收益（用于图表）
SELECT DATE(created_at) as date, SUM(pnl) as daily_pnl
FROM orders 
WHERE status = 'FILLED'
GROUP BY DATE(created_at)
ORDER BY date DESC 
LIMIT 30;
```

---

## 4. API 接口清单

### 4.1 认证
```
POST /api/login
Request:  {"username": "admin", "password": "xxx"}
Response: {"token": "jwt_token_here", "expires": "2024-01-01T00:00:00"}

Headers 后续请求:
Authorization: Bearer jwt_token_here
```

### 4.2 汇总数据
```
GET /api/summary
Response:
{
  "today_pnl": 123.45,
  "today_pnl_pct": 1.2,
  "total_positions": 5,
  "running_time": "3d 12h 30m",
  "account_equity": 10234.56,
  "server_status": "online",
  "last_update": "2024-01-01T12:00:00"
}
```

### 4.3 持仓列表
```
GET /api/positions
Response:
{
  "positions": [
    {
      "pair": "BTC/USDT_ETH/USDT",
      "symbol_a": "BTC/USDT",
      "symbol_b": "ETH/USDT",
      "side": "long",
      "entry_price_a": 50000,
      "entry_price_b": 3000,
      "quantity": 0.1,
      "current_pnl": 23.45,
      "z_score": 2.1,
      "opened_at": "2024-01-01T10:00:00"
    }
  ]
}
```

### 4.4 图表数据
```
GET /api/chart/profit?range=7d  (7天/30d/90d)
Response:
{
  "labels": ["2024-01-01", "2024-01-02", ...],
  "data": [100, 120, 115, 130, ...]  // 累计收益曲线
}

GET /api/chart/daily?range=30d
Response:
{
  "labels": ["2024-01-01", ...],
  "data": [20, -5, 15, 8, ...]  // 每日盈亏
}

GET /api/chart/holdings
Response:
{
  "labels": ["BTC_ETH", "SOL_AVAX", ...],
  "data": [40, 30, 20, 10]  // 持仓占比%
}

GET /api/chart/equity?range=30d
Response:
{
  "labels": ["2024-01-01", ...],
  "data": [10000, 10020, 10015, ...]  // 总资产
}
```

### 4.5 交易日志
```
GET /api/logs?level=ALL&limit=50
Query Params:
  - level: ALL | INFO | ORDER | ERROR
  - limit: 20 | 50 | 100

Response:
{
  "logs": [
    {
      "timestamp": "2024-01-01T12:00:00",
      "level": "ORDER",
      "message": "订单成交: BTC/USDT 买入 0.1 @ 50000"
    }
  ]
}
```

---

## 5. 前端页面结构

```
src/
├── components/           # 公共组件
│   ├── Layout.tsx       # 页面布局
│   ├── Header.tsx       # 顶部导航
│   ├── SummaryCard.tsx  # 指标卡片
│   └── ChartCard.tsx    # 图表容器
│
├── pages/               # 页面
│   ├── Login.tsx        # 登录页
│   └── Dashboard.tsx    # 主面板
│
├── hooks/               # React Hooks
│   ├── useAuth.ts       # 登录状态
│   ├── useSummary.ts    # 获取汇总数据
│   ├── usePositions.ts  # 获取持仓
│   └── useLogs.ts       # 获取日志
│
├── services/            # API 调用
│   └── api.ts           # 所有API请求
│
└── utils/               # 工具函数
    └── format.ts        # 数字/日期格式化
```

---

## 6. 实时更新机制

### 6.1 前端轮询
```typescript
// 每5秒刷新一次
useEffect(() => {
  const fetchData = async () => {
    const data = await api.getSummary();
    setSummary(data);
  };
  
  fetchData(); // 立即执行
  const timer = setInterval(fetchData, 5000); // 每5秒
  
  return () => clearInterval(timer); // 清理
}, []);
```

### 6.2 后端缓存优化
```python
# 缓存价格查询（避免频繁调币安API）
from functools import lru_cache

@lru_cache(maxsize=128, ttl=5)  # 5秒缓存
def get_current_price(symbol: str) -> float:
    return binance_client.fetch_ticker(symbol)['last']
```

---

## 7. 错误处理设计

### 7.1 统一错误响应格式

所有 API 错误返回统一格式：

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "用户友好的错误描述",
    "detail": "技术细节（可选）",
    "timestamp": "2024-01-01T12:00:00Z",
    "request_id": "uuid-for-tracing"
  }
}
```

### 7.2 错误码定义

| 错误码 | HTTP状态 | 说明 | 前端处理 |
|--------|---------|------|---------|
| `AUTH_INVALID` | 401 | Token无效或过期 | 跳转登录页 |
| `AUTH_REQUIRED` | 401 | 未提供Token | 跳转登录页 |
| `DB_CONNECTION_ERROR` | 503 | 数据库连接失败 | 显示"数据加载失败，请重试" |
| `DB_QUERY_ERROR` | 500 | 查询执行错误 | 显示"查询失败，联系管理员" |
| `BINANCE_API_ERROR` | 502 | 币安API调用失败 | 显示"价格获取失败，使用缓存数据" |
| `RATE_LIMIT_EXCEEDED` | 429 | 请求过于频繁 | 显示"请求太快，请稍后再试" |
| `VALIDATION_ERROR` | 400 | 参数校验失败 | 显示具体字段错误 |
| `NOT_FOUND` | 404 | 资源不存在 | 显示"数据不存在" |
| `INTERNAL_ERROR` | 500 | 内部服务器错误 | 显示"服务器错误，已记录日志" |

### 7.3 错误处理代码示例

```python
from fastapi import HTTPException
from fastapi.responses import JSONResponse

# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    request_id = generate_request_id()
    
    # 记录详细错误日志
    logger.error(f"Request {request_id}: {exc}", exc_info=True)
    
    # 返回统一格式（生产环境不暴露详细错误）
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误",
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        }
    )

# 数据库错误处理
@app.exception_handler(SQLiteError)
async def db_error_handler(request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "error": {
                "code": "DB_CONNECTION_ERROR",
                "message": "数据服务暂时不可用",
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )
```

### 7.4 前端错误处理

```typescript
// api.ts
async function handleResponse(response: Response) {
  const data = await response.json();
  
  if (!data.success) {
    const error = data.error;
    
    switch (error.code) {
      case 'AUTH_INVALID':
      case 'AUTH_REQUIRED':
        // 清除token，跳转登录
        localStorage.removeItem('token');
        window.location.href = '/login';
        break;
        
      case 'DB_CONNECTION_ERROR':
        // 显示重试按钮
        showErrorToast('数据加载失败，点击重试');
        break;
        
      case 'BINANCE_API_ERROR':
        // 使用缓存数据，提示用户
        showWarningToast('价格数据延迟，使用上次更新');
        return data.data; // 返回缓存数据
        
      default:
        showErrorToast(error.message);
    }
    
    throw new Error(error.message);
  }
  
  return data.data;
}
```

---

## 8. 性能设计

### 8.1 性能指标

| 指标 | 目标值 | 测量方法 |
|------|--------|---------|
| API响应时间 (P95) | < 200ms | 后端日志 |
| API响应时间 (P99) | < 500ms | 后端日志 |
| 页面首屏加载 | < 2s | Lighthouse |
| 数据刷新延迟 | < 5s | 前端计时 |
| 并发用户数 | ≥ 10人 | 压力测试 |
| 服务器CPU占用 | < 30% | 系统监控 |
| 服务器内存占用 | < 500MB | 系统监控 |

### 8.2 优化策略

**后端优化**:
- 数据库查询缓存（5秒）
- Binance API结果缓存（5秒）
- 数据库连接池
- 异步查询

**前端优化**:
- React.memo减少重渲染
- 虚拟滚动（长列表）
- 图片/图标懒加载
- 代码分割（Code Splitting）

### 8.3 性能监控

```python
# 中间件记录API性能
@app.middleware("http")
async def performance_monitor(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    # 记录慢查询
    if duration > 0.5:
        logger.warning(f"Slow API: {request.url.path} took {duration:.2f}s")
    
    # 添加到响应头（调试用）
    response.headers["X-Response-Time"] = f"{duration:.3f}s"
    return response
```

---

## 9. 安全设计

### 9.1 认证
- JWT Token (有效期24小时)
- 密码 bcrypt 加密存储
- 登录失败限制（5次/分钟）

### 9.2 访问控制
- 所有 API 需要 Token
- SQLite 只读连接（防止误改）
- API 限流（100次/分钟/IP）

### 9.3 部署安全
- 防火墙只开放 80/443
- Nginx 反向代理隐藏后端端口
- 日志不记录敏感信息

---

## 8. 开发计划

### Day 1: 后端基础
- [ ] FastAPI 项目初始化
- [ ] SQLite 连接（只读）
- [ ] `/api/summary` 接口
- [ ] JWT 登录认证

### Day 2: 前端基础
- [ ] React + TypeScript 项目搭建
- [ ] Tailwind CSS 配置
- [ ] 登录页面
- [ ] API 调用封装

### Day 3: 核心功能
- [ ] 首页布局（4个指标卡片）
- [ ] 自动刷新（5秒轮询）
- [ ] 持仓列表展示
- [ ] 手机适配

### Day 4: 图表
- [ ] Recharts 集成
- [ ] 收益曲线图
- [ ] 每日收益柱状图
- [ ] 图表时间范围切换

### Day 5: 高级功能
- [ ] 持仓分布饼图
- [ ] 资产曲线图
- [ ] 实时日志流
- [ ] 日志级别筛选

### Day 6: 部署准备
- [ ] 生产环境配置
- [ ] Nginx 配置
- [ ] 环境变量管理

### Day 7: 上线
- [ ] 部署到服务器
- [ ] 域名配置（后续）
- [ ] SSL证书（后续）
- [ ] 生产测试

---

## 9. 风险与应对

| 风险 | 可能性 | 影响 | 应对 |
|-----|--------|------|------|
| 查询慢 | 中 | 体验差 | 加缓存、优化SQL |
| 服务器资源不足 | 低 | 策略受影响 | 限制并发、监控资源 |
| 数据不同步 | 中 | 显示错误 | 使用只读连接、事务 |
| 安全问题 | 低 | 数据泄露 | JWT、密码加密、限流 |

---

## 10. 后续扩展

### Phase 2 (第2周)
- [ ] 历史订单查询（分页、筛选）
- [ ] 风险指标（回撤率、胜率、夏普）
- [ ] 服务器性能监控（CPU/内存图表）
- [ ] 告警通知（WebSocket推送）

### Phase 3 (跟单系统)
- [ ] API Key 管理
- [ ] 跟单用户管理
- [ ] 跟单收益统计
- [ ] 分润系统

---

## 11. 下一步

**技术方案已锁定，现在可以开始编码！**

**选择:**
- **A)** 我立即开始写代码（按Day 1开始）
- **B)** 先检查 S001-Pro 现有数据结构
- **C)** 你有其他问题？

---

**文档位置**: `docs/architecture/monitoring-dashboard-tech.md`
