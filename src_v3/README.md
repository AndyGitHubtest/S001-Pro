# S001-Pro V3 - 混合架构设计

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                     混合存储架构                                 │
│                                                                  │
│   ┌──────────────┐          ┌──────────────┐                    │
│   │   Redis      │◄────────►│   SQLite     │                    │
│   │  (内存)       │  实时同步  │  (磁盘)       │                    │
│   │              │          │              │                    │
│   │ • Pub/Sub    │          │ • 不可变存储   │                    │
│   │ • 实时缓存   │          │ • 审计日志    │                    │
│   │ • 临时状态   │          │ • 故障恢复    │                    │
│   └──────────────┘          └──────────────┘                    │
│          │                           │                          │
│          └───────────┬───────────────┘                          │
│                      │                                          │
│              HybridManager (统一接口)                            │
└─────────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. ImmutableStore (不可变存储)
- SQLite封装
- 只INSERT，不UPDATE/DELETE
- 支持数据溯源和审计
- WAL模式支持并发

### 2. RedisBus (实时总线)
- Pub/Sub模块通信
- 实时状态缓存 (价格、Z-score)
- 流式数据记录
- TTL自动过期

### 3. HybridManager (混合管理器)
- 统一接口管理两种存储
- 写操作: 同时写入Redis和SQLite
- 读操作: 优先Redis，回退SQLite
- 故障恢复机制

### 4. ModuleBase (模块基类)
- 标准化接口: input/process/output
- 自动状态追踪
- 支持流式处理 (M6)

## 数据流转

```
M1 ──PUBLISH──┐
M2 ──PUBLISH──┼──► Redis ──SUBSCRIBE──► M3
M3 ──PUBLISH──┤        │                    │
M4 ──PUBLISH──┘        │               [Process]
M5 ──PUBLISH───────────┘                    │
                                      PUBLISH──┐
                                               ▼
M6 ◄──SUBSCRIBE──────────────────────── Redis Channel
 │
 └──► SQLite (永久保存runtime状态)
```

## 优势

| 特性 | 实现 | 效果 |
|------|------|------|
| 数据安全 | SQLite不可变存储 | 历史可追溯，不可篡改 |
| 响应速度 | Redis缓存 | 毫秒级响应 |
| 故障恢复 | SQLite是Source of Truth | Redis丢失可重建 |
| 模块解耦 | Pub/Sub通信 | 无需直接调用 |
| 实时监控 | Redis状态缓存 | 实时查看系统状态 |

## 文件结构

```
src_v3/
├── core/
│   ├── immutable_store.py   # SQLite不可变存储
│   ├── redis_bus.py         # Redis实时总线
│   ├── hybrid_manager.py    # 混合管理器
│   ├── module_base.py       # 模块基类
│   └── data_packet.py       # 数据包格式
├── modules/
│   └── m3_selector.py       # M3示例实现
├── schema/
│   └── init.sql             # 数据库Schema
└── tests/
    └── test_hybrid.py       # 测试脚本
```

## 使用示例

```python
from src_v3.core import create_hybrid_manager, ModuleBase, ModuleDataPacket

# 创建混合管理器
hm = create_hybrid_manager(
    sqlite_path="data/pipeline.db",
    redis_host="localhost"
)

# M3发布结果
hm.publish_module_output(
    module="M3",
    data={"pairs": [...]},
    session_id="M3_20260101_120000",
    persist=True  # 同时写入SQLite
)

# M4订阅M3
hm.subscribe_module_output("M3", callback=process_m3_data)

# 保存持仓状态
hm.save_position_state("BTC_ETH", {"state": "IN_POSITION", ...})

# 读取持仓 (优先Redis，回退SQLite)
position = hm.get_position_state("BTC_ETH")
```

## 部署

### 本地开发

```bash
# Mac安装Redis
brew install redis
brew services start redis
```

### 服务器部署

```bash
# Ubuntu安装Redis
sudo apt-get install redis-server
sudo systemctl start redis-server

# 配置远程访问 (如需)
sudo nano /etc/redis/redis.conf
# 修改 bind 0.0.0.0
```

## 测试

```bash
cd ~/S001-Pro
python3 src_v3/tests/test_hybrid.py
```
