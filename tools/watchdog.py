#!/usr/bin/env python3
"""
S001-Pro 策略守护进程 (Watchdog)

功能:
  1. 监控策略进程状态
  2. 检测异常（卡死、内存泄漏、交易停滞）
  3. 自动重启服务
  4. 发送告警通知
  5. 记录守护日志

用法:
  python tools/watchdog.py --start    # 启动守护
  python tools/watchdog.py --stop     # 停止守护
  python tools/watchdog.py --status   # 查看状态
  python tools/watchdog.py --check    # 单次检查
"""

import argparse
import json
import os
import sys
import time
import signal
import subprocess
import psutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional
import sqlite3

# 配置
WATCHDOG_PID_FILE = Path("/tmp/s001_watchdog.pid")
WATCHDOG_LOG = Path("logs/watchdog.log")
SERVICE_NAME = "trading-s001"
CHECK_INTERVAL = 60  # 检查间隔（秒）
MAX_RESTARTS = 3  # 每小时最大重启次数


def log(msg: str):
    """记录日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {msg}"
    print(log_line)
    
    WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHDOG_LOG, "a") as f:
        f.write(log_line + "\n")


def get_service_status() -> Dict:
    """获取服务状态"""
    result = {
        "active": False,
        "pid": None,
        "uptime": 0,
        "memory_mb": 0,
        "cpu_percent": 0,
        "last_trade_time": None,
        "errors_last_hour": 0,
    }
    
    try:
        # 检查 systemd 状态
        proc = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            capture_output=True,
            text=True
        )
        result["active"] = proc.stdout.strip() == "active"
        
        if result["active"]:
            # 获取进程信息
            proc = subprocess.run(
                ["systemctl", "show", SERVICE_NAME, "--property=MainPID,ActiveEnterTimestamp"],
                capture_output=True,
                text=True
            )
            
            for line in proc.stdout.strip().split("\n"):
                if line.startswith("MainPID="):
                    pid = int(line.split("=")[1])
                    result["pid"] = pid
                    
                    if pid > 0:
                        try:
                            process = psutil.Process(pid)
                            result["memory_mb"] = process.memory_info().rss / 1024 / 1024
                            result["cpu_percent"] = process.cpu_percent(interval=0.1)
                            
                            # 计算运行时间
                            uptime = time.time() - process.create_time()
                            result["uptime"] = uptime
                        except psutil.NoSuchProcess:
                            pass
                
                elif line.startswith("ActiveEnterTimestamp="):
                    # 解析启动时间
                    try:
                        timestamp_str = line.split("=")[1]
                        if timestamp_str and timestamp_str != "n/a":
                            # 转换为时间戳
                            pass
                    except:
                        pass
        
        # 检查最近交易
        result["last_trade_time"] = get_last_trade_time()
        
        # 统计最近错误
        result["errors_last_hour"] = count_recent_errors()
        
    except Exception as e:
        log(f"获取状态失败: {e}")
    
    return result


def get_last_trade_time() -> Optional[str]:
    """获取最近交易时间"""
    try:
        db_path = Path("data/trades.db")
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute(
                    "SELECT MAX(entry_time) FROM trades"
                )
                row = cursor.fetchone()
                if row and row[0]:
                    return row[0]
    except:
        pass
    return None


def count_recent_errors() -> int:
    """统计最近1小时错误数"""
    try:
        result = subprocess.run(
            ["journalctl", "-u", SERVICE_NAME, "--since", "1 hour ago", "-p", "err", "--no-pager", "-q"],
            capture_output=True,
            text=True
        )
        return len([l for l in result.stdout.split("\n") if l.strip()])
    except:
        return 0


def restart_service() -> bool:
    """重启服务"""
    log("🔄 正在重启服务...")
    try:
        subprocess.run(["sudo", "systemctl", "restart", SERVICE_NAME], check=True)
        time.sleep(10)
        
        # 验证重启成功
        status = get_service_status()
        if status["active"]:
            log("✅ 服务重启成功")
            return True
        else:
            log("❌ 服务重启失败")
            return False
    except Exception as e:
        log(f"❌ 重启失败: {e}")
        return False


def check_and_recover():
    """检查并恢复"""
    status = get_service_status()
    
    log(f"检查服务状态: active={status['active']}, pid={status['pid']}, "
        f"memory={status['memory_mb']:.1f}MB, errors={status['errors_last_hour']}")
    
    need_restart = False
    reason = ""
    
    # 检查1: 服务是否运行
    if not status["active"]:
        need_restart = True
        reason = "服务未运行"
    
    # 检查2: 内存泄漏 (> 1.5GB)
    elif status["memory_mb"] > 1500:
        need_restart = True
        reason = f"内存过高 ({status['memory_mb']:.0f}MB)"
    
    # 检查3: CPU 卡死 (> 90% 持续)
    elif status["cpu_percent"] > 90:
        need_restart = True
        reason = f"CPU 占用过高 ({status['cpu_percent']:.1f}%)"
    
    # 检查4: 错误过多 (> 10个/小时)
    elif status["errors_last_hour"] > 10:
        need_restart = True
        reason = f"错误过多 ({status['errors_last_hour']}个/小时)"
    
    # 检查5: 交易停滞 (> 4小时无交易且应为交易时间)
    elif status["last_trade_time"]:
        last_trade = datetime.fromisoformat(status["last_trade_time"])
        if datetime.now() - last_trade > timedelta(hours=4):
            # 检查是否有持仓（有持仓应该交易）
            if check_has_positions():
                need_restart = True
                reason = "交易停滞 (>4小时无交易但有持仓)"
    
    if need_restart:
        log(f"⚠️ 检测到异常: {reason}")
        
        # 检查重启次数
        restart_count = get_restart_count()
        if restart_count >= MAX_RESTARTS:
            log(f"🚨 重启次数已达上限 ({MAX_RESTARTS}/小时)，停止自动恢复")
            send_alert(f"策略异常但重启次数已用完: {reason}")
            return
        
        # 执行重启
        if restart_service():
            record_restart()
            send_alert(f"策略已自动恢复: {reason}")
        else:
            send_alert(f"🚨 策略恢复失败: {reason}")
    else:
        log("✅ 服务运行正常")


def check_has_positions() -> bool:
    """检查是否有持仓"""
    try:
        result = subprocess.run(
            ["python3", "-c", "import json; d=json.load(open('data/state.json')); print(any(v.get('state')!='IDLE' for v in d.values()))"],
            cwd="/home/ubuntu/strategies/S001-Pro",
            capture_output=True,
            text=True
        )
        return result.stdout.strip() == "True"
    except:
        return False


def get_restart_count() -> int:
    """获取最近1小时重启次数"""
    try:
        conn = sqlite3.connect("data/watchdog.db")
        cursor = conn.execute(
            "SELECT COUNT(*) FROM restarts WHERE datetime > datetime('now', '-1 hour')"
        )
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0


def record_restart():
    """记录重启"""
    try:
        conn = sqlite3.connect("data/watchdog.db")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS restarts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datetime TEXT DEFAULT CURRENT_TIMESTAMP,
                reason TEXT
            )
        """)
        conn.execute("INSERT INTO restarts (reason) VALUES ('automatic')")
        conn.commit()
        conn.close()
    except:
        pass


def send_alert(message: str):
    """发送告警"""
    try:
        import yaml
        with open("config/base.yaml") as f:
            config = yaml.safe_load(f)
        
        notif = config.get("notifications", {})
        if notif.get("enabled") and notif.get("telegram_bot_token"):
            import requests
            token = notif["telegram_bot_token"]
            chat_id = notif["telegram_chat_id"]
            
            text = f"🚨 [WATCHDOG] {message}\n\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10
            )
    except Exception as e:
        log(f"发送告警失败: {e}")


def generate_report() -> str:
    """生成运行报告"""
    status = get_service_status()
    
    report = f"""
{'='*60}
📊 S001-Pro 策略运行报告
{'='*60}

🕐 报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

┌─ 服务状态 ─────────────────────────────────────┐
│                                                │
│  {'🟢' if status['active'] else '🔴'} 运行状态: {'运行中' if status['active'] else '已停止'}                │
│  🆔 进程ID: {status['pid'] or 'N/A'}                          │
│  ⏱️  运行时间: {format_uptime(status['uptime'])}                      │
│  💾 内存使用: {status['memory_mb']:.1f}MB                        │
│  🔥 CPU使用: {status['cpu_percent']:.1f}%                         │
│                                                │
└────────────────────────────────────────────────┘

┌─ 交易状态 ─────────────────────────────────────┐
│                                                │
│  📈 最近交易: {status['last_trade_time'] or '无'}       │
│  ❌ 最近错误: {status['errors_last_hour']}个/小时                    │
│                                                │
└────────────────────────────────────────────────┘

┌─ 守护状态 ─────────────────────────────────────┐
│                                                │
│  🛡️ 最近重启: {get_restart_count()}次/小时                        │
│  📋 守护日志: {WATCHDOG_LOG}              │
│                                                │
└────────────────────────────────────────────────┘

{'='*60}
"""
    return report


def format_uptime(seconds: float) -> str:
    """格式化运行时间"""
    if seconds < 60:
        return f"{int(seconds)}秒"
    elif seconds < 3600:
        return f"{int(seconds/60)}分钟"
    else:
        return f"{int(seconds/3600)}小时{int((seconds%3600)/60)}分钟"


def run_watchdog_loop():
    """守护循环"""
    log("🛡️ 守护进程启动")
    
    while True:
        try:
            check_and_recover()
            
            # 每小时生成报告
            if datetime.now().minute == 0:
                report = generate_report()
                log("\n" + report)
                
        except Exception as e:
            log(f"守护循环异常: {e}")
        
        time.sleep(CHECK_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="S001-Pro 策略守护")
    parser.add_argument("--start", action="store_true", help="启动守护")
    parser.add_argument("--stop", action="store_true", help="停止守护")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--check", action="store_true", help="单次检查")
    parser.add_argument("--report", action="store_true", help="生成报告")
    
    args = parser.parse_args()
    
    if args.start:
        # 检查是否已在运行
        if WATCHDOG_PID_FILE.exists():
            old_pid = int(WATCHDOG_PID_FILE.read_text())
            try:
                os.kill(old_pid, 0)
                log(f"守护进程已在运行 (PID: {old_pid})")
                return
            except:
                pass
        
        # 启动守护
        pid = os.fork()
        if pid == 0:
            # 子进程
            os.setsid()
            run_watchdog_loop()
        else:
            # 父进程
            WATCHDOG_PID_FILE.write_text(str(pid))
            log(f"守护进程已启动 (PID: {pid})")
    
    elif args.stop:
        if WATCHDOG_PID_FILE.exists():
            pid = int(WATCHDOG_PID_FILE.read_text())
            try:
                os.kill(pid, signal.SIGTERM)
                WATCHDOG_PID_FILE.unlink()
                log("守护进程已停止")
            except Exception as e:
                log(f"停止失败: {e}")
        else:
            log("守护进程未运行")
    
    elif args.status:
        status = get_service_status()
        print(f"\n服务状态: {'🟢 运行中' if status['active'] else '🔴 已停止'}")
        print(f"进程ID: {status['pid']}")
        print(f"运行时间: {format_uptime(status['uptime'])}")
        print(f"内存使用: {status['memory_mb']:.1f}MB")
        print(f"最近错误: {status['errors_last_hour']}个/小时")
        
        if WATCHDOG_PID_FILE.exists():
            print(f"\n🛡️ 守护进程: 运行中")
        else:
            print(f"\n🛡️ 守护进程: 未运行")
    
    elif args.check:
        check_and_recover()
    
    elif args.report:
        print(generate_report())
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
