# 部署检查清单

**版本**: 2.1.0-hardened  
**用途**: 生产环境部署前检查  
**最后更新**: 2025-04-08

---

## 环境检查

### 服务器环境

- [ ] 操作系统: Ubuntu 22.04 LTS
- [ ] Python版本: 3.12+
- [ ] 内存: ≥ 2GB
- [ ] 磁盘: ≥ 20GB
- [ ] 网络: 稳定外网连接

### 必备软件

```bash
# 检查Git
git --version  # ≥ 2.30

# 检查Python
python3 --version  # ≥ 3.12

# 检查SQLite
sqlite3 --version  # ≥ 3.35

# 检查SSH
ssh -V
```

---

## 代码部署

### 1. 克隆代码

```bash
cd /home/ubuntu
git clone https://github.com/AndyGitHubtest/S001-Pro.git
cd S001-Pro
```

### 2. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 验证安装

```bash
python3 tests/run_tests.py
# 预期: 7/7 测试通过
```

---

## 配置文件

### 4. base.yaml配置

```bash
cp config/base.yaml.example config/base.yaml
nano config/base.yaml
```

检查项:
- [ ] API Key正确
- [ ] API Secret正确
- [ ] testnet = false (实盘)
- [ ] 本金设置合理
- [ ] 杠杆倍数合适
- [ ] Telegram配置（如需要）

### 5. 配置文件权限

```bash
chmod 600 config/base.yaml
```

### 6. 数据文件

```bash
# 确保数据目录存在
mkdir -p data

# 检查klines.db存在
ls -lh data/klines.db

# 检查数据库完整性
sqlite3 data/klines.db "SELECT COUNT(*) FROM klines_1m;"
```

---

## 安全设置

### 7. API权限检查

登录Binance确认:
- [ ] 合约交易权限已开启
- [ ] 提现权限已关闭
- [ ] IP白名单已配置（推荐）

### 8. 防火墙设置

```bash
# 检查防火墙状态
sudo ufw status

# 只开放必要端口（如SSH）
sudo ufw allow 22/tcp
sudo ufw enable
```

### 9. 系统服务

```bash
# 创建systemd服务
sudo nano /etc/systemd/system/s001-pro.service
```

服务文件内容:
```ini
[Unit]
Description=S001-Pro Trading System
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/strategies/S001-Pro
Environment="PATH=/home/ubuntu/strategies/S001-Pro/venv/bin"
ExecStart=/home/ubuntu/strategies/S001-Pro/venv/bin/python -m src.main --mode full
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## 预启动检查

### 10. 运行模拟模式

```bash
python3 -m src.main --mode full --dry-run
```

检查:
- [ ] 无ERROR级别日志
- [ ] 扫描正常完成
- [ ] 生成pairs_v2.json
- [ ] 信号计算正常

### 11. 检查日志目录

```bash
mkdir -p logs
ls -la logs/
```

### 12. 检查磁盘空间

```bash
df -h
# 确保可用空间 > 5GB
```

---

## 启动系统

### 13. 手动启动（首次）

```bash
# 前台启动，观察日志
python3 -m src.main --mode full 2>&1 | tee logs/startup.log
```

观察:
- [ ] 成功加载配置
- [ ] 成功连接API
- [ ] 扫描完成
- [ ] 进入主循环

### 14. 检查进程

```bash
# 检查进程运行
ps aux | grep src.main | grep -v grep

# 检查资源使用
top -p $(pgrep -f src.main)
```

### 15. 检查日志

```bash
# 实时查看日志
tail -f logs/live_$(date +%Y%m%d)_*.log
```

关键日志:
```
[INFO] [main] Starting S001-Pro v2.1.0-hardened
[INFO] [M1] Found XXX symbols
[INFO] [M2] XX symbols passed
[INFO] [M5] Saved to pairs_v2.json
[INFO] [Runtime] Starting main loop...
```

---

## 验证清单

### 16. 功能验证

- [ ] 扫描周期正常触发
- [ ] pairs_v2.json更新
- [ ] Z-score计算正常
- [ ] Telegram通知收到（如配置）

### 17. 风控验证

- [ ] Kill Switch功能正常
- [ ] 回撤限制生效
- [ ] 持仓限制生效

### 18. 异常处理验证

- [ ] API断开能重连
- [ ] 订单失败能回滚
- [ ] 配置热重载正常

---

## 切换到后台运行

### 19. 使用systemd

```bash
# 启用服务
sudo systemctl enable s001-pro

# 启动服务
sudo systemctl start s001-pro

# 查看状态
sudo systemctl status s001-pro

# 查看日志
sudo journalctl -u s001-pro -f
```

### 20. 或使用screen/tmux

```bash
# 使用screen
screen -S s001
python3 -m src.main --mode full
# Ctrl+A, D  detach

# 重新连接
screen -r s001
```

---

## 监控设置

### 21. 进程监控

```bash
# 添加到crontab
crontab -e

# 添加:
*/5 * * * * /home/ubuntu/S001-Pro/scripts/check_process.sh
```

### 22. 日志轮转

```bash
sudo nano /etc/logrotate.d/s001-pro
```

内容:
```
/home/ubuntu/S001-Pro/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0644 ubuntu ubuntu
}
```

---

## 应急准备

### 23. 停止命令

```bash
# 方式1: systemctl
sudo systemctl stop s001-pro

# 方式2: kill
pkill -f src.main

# 方式3: 紧急停止
pkill -9 -f src.main
```

### 24. 恢复命令

```bash
# 检查持仓
python3 scripts/check_positions.py

# 手动恢复持仓
python3 scripts/recover_positions.py

# 重启系统
sudo systemctl restart s001-pro
```

---

## 最终确认

### 部署完成检查

- [ ] 代码已部署
- [ ] 配置已设置
- [ ] 测试已通过
- [ ] 系统已启动
- [ ] 日志正常
- [ ] 监控已配置
- [ ] 应急方案就绪

### 通知相关人员

- [ ] 部署完成通知
- [ ] 监控面板链接
- [ ] 应急联系方式

---

## 相关文档

- [启动流程](STARTUP_PROCEDURE.md)
- [关闭流程](SHUTDOWN_PROCEDURE.md)
- [日志查看指南](LOG_VIEWING.md)
- [常见问题排查](TROUBLESHOOTING.md)
- [紧急停止流程](EMERGENCY_STOP.md)
