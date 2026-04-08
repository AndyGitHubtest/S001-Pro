# 快速开始 (Quickstart) - 5分钟上手 S001-Pro

**目标**: 在5分钟内启动 S001-Pro 实盘交易  
**前提**: Python 3.12+, Git, Binance API Key

---

## Step 1: 克隆和安装 (1分钟)

```bash
# 克隆仓库
git clone https://github.com/AndyGitHubtest/S001-Pro.git
cd S001-Pro

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

**验证安装**:
```bash
python3 -c "import ccxt, numpy, pandas; print('✅ 依赖安装成功')"
```

---

## Step 2: 配置API (2分钟)

### 2.1 获取Binance API Key

1. 登录 [Binance](https://www.binance.com)
2. 进入 API 管理 → 创建API
3. **权限设置**:
   - ✅ 启用合约交易 (Futures)
   - ❌ 禁用提现 (Withdraw)
   - ❌ 禁用充值 (Deposit)
4. 记录 `API Key` 和 `Secret Key`

### 2.2 编辑配置文件

```bash
cp config/base.yaml.example config/base.yaml
# 编辑 config/base.yaml
```

**最小配置**:

```yaml
exchange:
  name: "binance"
  api_key: "YOUR_API_KEY_HERE"
  api_secret: "YOUR_SECRET_HERE"
  testnet: false  # true=测试网, false=实盘

risk:
  initial_capital: 10000  # 本金 USDT
  max_position_pairs: 6   # 最大持仓对数
  leverage: 3             # 杠杆倍数

notifications:
  enabled: true
  telegram_bot_token: ""  # 可选
  telegram_chat_id: ""    # 可选

scanning:
  min_daily_volume_usd: 2000000  # 最小日成交量2M
  top_n_scan: 100                # 扫描Top 100
  top_n_final: 30                # 最终保留30对
  scan_interval_hours: 1         # 每小时扫描
```

⚠️ **安全**: 不要将包含真实API Key的配置提交到Git！

```bash
echo "config/base.yaml" >> .gitignore
```

---

## Step 3: 准备数据 (1分钟)

```bash
# 确保数据目录存在
mkdir -p data

# 如果你有kline数据库
cp /path/to/your/klines.db data/

# 如果没有，系统会在扫描时提示
```

**数据要求**:
- 格式: SQLite
- 路径: `data/klines.db`
- 表: `klines_1m`, `klines_5m`, `klines_15m`

---

## Step 4: 运行测试 (30秒)

```bash
python3 tests/run_tests.py
```

**预期输出**:
```
======================================================================
测试报告
======================================================================
总测试数: 7
通过: 7
失败: 0

✓ ✅ 全部测试通过！
```

---

## Step 5: 启动系统 (30秒)

### 模拟模式（推荐首次）

```bash
python3 -m src.main --mode full --dry-run
```

### 完整模式（扫描+实盘）

```bash
python3 -m src.main --mode full
```

### 仅扫描

```bash
python3 -m src.main --mode scan
```

### 仅实盘（使用已有配置）

```bash
python3 -m src.main --mode trade
```

---

## Step 6: 验证运行

### 查看进程

```bash
ps aux | grep "src.main" | grep -v grep
```

### 查看日志

```bash
# 实时查看
tail -f logs/live_$(date +%Y%m%d)_*.log
```

**关键日志**:
```
[main] Starting S001-Pro v2.1.0-hardened
[M1] Found XXX symbols in database
[M2] 88 symbols passed all 6 filters
[M3] 5m: Selected 45 pairs
[M4] 5m: 30 pairs optimized
[M5] Saved to pairs_v2.json
[Runtime] Starting main loop...
```

---

## 常用命令

| 命令 | 用途 |
|------|------|
| `python3 -m src.main --mode full` | 启动完整模式 |
| `python3 -m src.main --mode scan` | 仅扫描 |
| `python3 -m src.main --mode trade` | 仅实盘 |
| `python3 -m src.main --dry-run` | 模拟模式 |
| `tail -f logs/live_*.log` | 实时日志 |
| `ps aux \| grep src.main` | 检查进程 |
| `pkill -f src.main` | 停止系统 |

---

## 首次运行检查清单

- [ ] 依赖安装成功
- [ ] API Key配置正确
- [ ] 测试全部通过
- [ ] 系统启动无ERROR
- [ ] 扫描完成并生成pairs_v2.json
- [ ] 日志正常输出

---

## 故障排查

### 问题: 数据库不存在

```
[ERROR] Database not found: data/klines.db
```

**解决**: 准备SQLite数据库放到 `data/klines.db`

### 问题: API认证失败

```
[ERROR] AuthenticationError: Invalid API-key
```

**解决**: 检查API Key和Secret，确认有合约交易权限

### 问题: 测试失败

```
❌ Import: main: No module named 'src'
```

**解决**: 在项目根目录运行，确保虚拟环境激活

---

## 紧急停止

如需立即停止：

```bash
pkill -f src.main
```

系统支持优雅退出（会完成当前订单再停止）。

---

## 下一步

- [系统架构](../10-architecture/SYSTEM_DIAGRAM.md)
- [M6防裸仓机制](../20-modules/M6-05-naked-position-prevention.md)
- [部署检查清单](../40-ops/DEPLOYMENT_CHECKLIST.md)
