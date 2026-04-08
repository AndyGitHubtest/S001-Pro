#!/usr/bin/env python3
"""
S001-Pro 实盘监控与汇报脚本
每10分钟自动检查状态并发送到 Telegram
"""

import json
import yaml
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
import asyncio

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

class TradingMonitor:
    def __init__(self, base_path: str = None):
        if base_path is None:
            # 自动检测路径：优先使用当前项目目录
            base_path = str(Path(__file__).parent.parent)
        self.base_path = Path(base_path)
        self.config = self._load_config()
        notif = self.config.get("notifications", {})
        # FIX: 兼容 disabled 的配置键
        self.tg_token = notif.get("telegram_bot_token", notif.get("telegram_bot_token_disabled", ""))
        self.tg_chat = notif.get("telegram_chat_id", "")
        
    def _load_config(self) -> dict:
        """加载配置文件"""
        try:
            with open(self.base_path / "config" / "base.yaml") as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"加载配置失败: {e}")
            return {}
    
    def get_process_status(self) -> dict:
        """检查实盘进程状态"""
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True
            )
            # FIX: 匹配 "src.main" 和 "--mode trade" 模式
            lines = []
            for l in result.stdout.split("\n"):
                if "src.main" in l and "--mode trade" in l and "grep" not in l:
                    lines.append(l)
            
            if lines:
                parts = lines[0].split()
                return {
                    "running": True,
                    "pid": parts[1] if len(parts) > 1 else "unknown",
                    "cpu": parts[2] if len(parts) > 2 else "0.0",
                    "mem": parts[3] if len(parts) > 3 else "0.0",
                    "etime": parts[9] if len(parts) > 9 else "unknown"
                }
            return {"running": False}
        except Exception as e:
            return {"running": False, "error": str(e)}
    
    def get_positions_status(self) -> dict:
        """获取持仓状态"""
        try:
            state_file = self.base_path / "data" / "state.json"
            if not state_file.exists():
                return {"total": 0, "by_state": {}}
            
            with open(state_file) as f:
                state = json.load(f)
            
            by_state = {}
            total_pnl = 0.0
            
            for pair_key, data in state.items():
                s = data.get("state", "UNKNOWN")
                by_state[s] = by_state.get(s, 0) + 1
                
                # 计算未实现盈亏
                if s == "IN_POSITION":
                    unrealized = data.get("unrealized_pnl", 0)
                    total_pnl += unrealized
            
            return {
                "total": len(state),
                "by_state": by_state,
                "unrealized_pnl": total_pnl
            }
        except Exception as e:
            return {"total": 0, "by_state": {}, "error": str(e)}
    
    def get_recent_trades(self, hours: int = 1) -> list:
        """获取最近交易记录"""
        try:
            db_path = self.base_path / "data" / "trades.db"
            if not db_path.exists():
                return []
            
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            since = datetime.now() - timedelta(hours=hours)
            cursor.execute(
                "SELECT timestamp, pair, side, qty, price, realized_pnl FROM trades WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 5",
                (since.isoformat(),)
            )
            
            trades = cursor.fetchall()
            conn.close()
            
            return trades
        except Exception as e:
            return []
    
    def get_account_summary(self) -> dict:
        """获取账户摘要"""
        try:
            # 从监控数据库读取
            monitor_db = self.base_path / "data" / "monitor.db"
            if not monitor_db.exists():
                return {}
            
            conn = sqlite3.connect(str(monitor_db))
            cursor = conn.cursor()
            
            # 最新账户状态
            cursor.execute(
                "SELECT equity, daily_pnl, total_trades, win_rate FROM account_summary ORDER BY timestamp DESC LIMIT 1"
            )
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    "equity": row[0],
                    "daily_pnl": row[1],
                    "total_trades": row[2],
                    "win_rate": row[3]
                }
            return {}
        except Exception as e:
            return {"error": str(e)}
    
    def get_latest_signals(self) -> dict:
        """获取最新 Z-score 信号"""
        try:
            log_file = sorted(self.base_path.glob("logs/live_*.log"))[-1]
            
            # 读取最后100行，找最大 Z-score
            result = subprocess.run(
                ["tail", "-100", str(log_file)],
                capture_output=True,
                text=True
            )
            
            max_z = 0.0
            max_pair = ""
            
            for line in result.stdout.split("\n"):
                if "z=" in line and "ready=True" in line:
                    try:
                        # 提取 z 值
                        z_part = line.split("z=")[1].split(",")[0]
                        z_val = float(z_part)
                        if abs(z_val) > abs(max_z):
                            max_z = z_val
                            # 提取配对名
                            if "DEBUG:" in line:
                                pair_part = line.split("DEBUG: ")[1].split(":")[0]
                                max_pair = pair_part
                    except:
                        continue
            
            return {
                "max_z": max_z,
                "max_pair": max_pair,
                "threshold": 2.0,
                "signal_ready": abs(max_z) >= 2.0
            }
        except Exception as e:
            return {"max_z": 0, "error": str(e)}
    
    def format_report(self) -> str:
        """格式化汇报消息"""
        now = datetime.now().strftime("%m-%d %H:%M")
        
        # 收集数据
        proc = self.get_process_status()
        pos = self.get_positions_status()
        acc = self.get_account_summary()
        sig = self.get_latest_signals()
        
        # 构建消息
        lines = [
            f"📊 S001-Pro 实盘状态 | {now}",
            "",
            f"🔵 进程: {'✅ 运行中' if proc.get('running') else '❌ 已停止'}",
        ]
        
        if proc.get('running'):
            lines.append(f"   PID:{proc.get('pid')} | CPU:{proc.get('cpu')}% | 运行:{proc.get('etime')}")
        
        lines.extend([
            "",
            f"📈 持仓: {pos.get('total', 0)} 对",
        ])
        
        if pos.get('by_state'):
            for state, count in pos.get('by_state', {}).items():
                emoji = "🟢" if state == "IN_POSITION" else "🟡" if state == "SCALING_IN" else "⚪"
                lines.append(f"   {emoji} {state}: {count}")
        
        if pos.get('unrealized_pnl', 0) != 0:
            pnl_emoji = "🟢" if pos['unrealized_pnl'] > 0 else "🔴"
            lines.append(f"   {pnl_emoji} 未实现盈亏: ${pos['unrealized_pnl']:.2f}")
        
        lines.extend([
            "",
            f"📊 信号: Z={sig.get('max_z', 0):.2f} (阈值: 2.0)",
        ])
        
        if sig.get('signal_ready'):
            lines.append(f"   🔔 {sig.get('max_pair', '')} 信号已触发!")
        else:
            lines.append(f"   ⏳ {sig.get('max_pair', 'N/A')} 等待信号...")
        
        if acc:
            lines.extend([
                "",
                f"💰 账户权益: ${acc.get('equity', 0):.2f}",
                f"   今日盈亏: ${acc.get('daily_pnl', 0):.2f}",
                f"   总交易: {acc.get('total_trades', 0)} | 胜率: {acc.get('win_rate', 0):.1f}%",
            ])
        
        return "\n".join(lines)
    
    async def send_telegram(self, message: str):
        """发送 Telegram 消息"""
        if not self.tg_token or not self.tg_chat:
            print("Telegram 配置缺失")
            return
        
        try:
            import aiohttp
            
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            payload = {
                "chat_id": self.tg_chat,
                "text": message,
                "parse_mode": "HTML"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        print(f"✅ Telegram 发送成功")
                    else:
                        print(f"❌ Telegram 发送失败: {resp.status}")
        except Exception as e:
            print(f"❌ Telegram 错误: {e}")
    
    async def run(self):
        """执行监控和汇报"""
        print(f"[{datetime.now()}] 开始监控...")
        
        # 生成报告
        report = self.format_report()
        print(report)
        print("\n" + "="*50 + "\n")
        
        # 发送到 Telegram
        await self.send_telegram(report)

if __name__ == "__main__":
    monitor = TradingMonitor()
    asyncio.run(monitor.run())
