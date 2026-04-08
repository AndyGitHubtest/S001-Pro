#!/usr/bin/env python3
"""
交易对自动更新处理工具

功能:
  1. 检测 pairs_v2.json 是否变更
  2. 自动重启服务应用新配置
  3. 验证新交易对的杠杆设置
  4. 发送 Telegram 通知

用法:
  python tools/auto_pair_update.py --check    # 检查是否有更新
  python tools/auto_pair_update.py --apply    # 应用更新并重启
  python tools/auto_pair_update.py --verify   # 验证当前设置
"""

import argparse
import json
import hashlib
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# 状态文件
STATE_FILE = Path("data/.pairs_hash")


def get_pairs_hash() -> str:
    """计算 pairs_v2.json 的哈希值"""
    pairs_file = Path("config/pairs_v2.json")
    if not pairs_file.exists():
        return ""
    
    content = pairs_file.read_bytes()
    return hashlib.md5(content).hexdigest()[:16]


def get_saved_hash() -> str:
    """获取保存的哈希值"""
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return ""


def save_hash(hash_value: str):
    """保存哈希值"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(hash_value)


def get_pairs_summary() -> dict:
    """获取交易对摘要"""
    pairs_file = Path("config/pairs_v2.json")
    if not pairs_file.exists():
        return {}
    
    with open(pairs_file) as f:
        data = json.load(f)
    
    pairs = data.get("pairs", [])
    symbols = set()
    for p in pairs:
        symbols.add(p.get("symbol_a", ""))
        symbols.add(p.get("symbol_b", ""))
    
    return {
        "count": len(pairs),
        "symbols": len([s for s in symbols if s]),
        "pairs": [f"{p['symbol_a']}_{p['symbol_b']}" for p in pairs[:5]],
    }


def restart_service() -> bool:
    """重启服务"""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "trading-s001"],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ 重启失败: {e}")
        return False


def check_service_status() -> str:
    """检查服务状态"""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "is-active", "trading-s001"],
            capture_output=True,
            text=True
        )
        return result.stdout.strip()
    except:
        return "unknown"


def get_recent_logs(lines: int = 5) -> str:
    """获取最近日志"""
    try:
        result = subprocess.run(
            ["sudo", "journalctl", "-u", "trading-s001", "-n", str(lines), "--no-pager"],
            capture_output=True,
            text=True
        )
        return result.stdout
    except:
        return "无法获取日志"


def send_notification(message: str):
    """发送 Telegram 通知 (如果配置了)"""
    try:
        import yaml
        from src.notifier import TelegramNotifier
        
        with open("config/base.yaml") as f:
            config = yaml.safe_load(f)
        
        notif_config = config.get("notifications", {})
        if notif_config.get("enabled") and notif_config.get("telegram_bot_token"):
            notifier = TelegramNotifier(
                bot_token=notif_config["telegram_bot_token"],
                chat_id=notif_config["telegram_chat_id"],
            )
            import asyncio
            asyncio.run(notifier.send_info(message))
    except Exception as e:
        print(f"⚠️  通知发送失败: {e}")


def check_update():
    """检查是否有更新"""
    current_hash = get_pairs_hash()
    saved_hash = get_saved_hash()
    
    if not saved_hash:
        print("ℹ️  首次运行，保存当前状态")
        save_hash(current_hash)
        return False
    
    if current_hash != saved_hash:
        print("🔔 检测到交易对配置变更!")
        summary = get_pairs_summary()
        print(f"   当前: {summary['count']} 对 ({summary['symbols']} 个币种)")
        print(f"   示例: {', '.join(summary['pairs'])}...")
        return True
    else:
        print("✅ 交易对配置未变更")
        return False


def apply_update():
    """应用更新"""
    print("="*60)
    print("🔄 自动更新交易对配置")
    print("="*60)
    
    # 1. 备份当前配置
    pairs_file = Path("config/pairs_v2.json")
    backup_name = f"config/pairs_v2.json.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    import shutil
    shutil.copy(pairs_file, backup_name)
    print(f"✅ 已备份到: {backup_name}")
    
    # 2. 重启服务
    print("\n🔄 重启服务应用新配置...")
    if not restart_service():
        print("❌ 服务重启失败!")
        send_notification("❌ 交易对更新失败: 服务重启失败")
        return False
    
    # 3. 等待启动
    import time
    time.sleep(10)
    
    # 4. 检查状态
    status = check_service_status()
    if status != "active":
        print(f"❌ 服务状态异常: {status}")
        send_notification(f"❌ 交易对更新失败: 服务状态 {status}")
        return False
    
    # 5. 保存新哈希
    new_hash = get_pairs_hash()
    save_hash(new_hash)
    
    # 6. 获取启动日志
    print("\n📋 启动日志摘要:")
    logs = get_recent_logs(8)
    for line in logs.split('\n'):
        if '杠杆' in line or 'PreFlight' in line or '✓' in line or 'Recovery' in line:
            print(f"   {line}")
    
    # 7. 发送通知
    summary = get_pairs_summary()
    message = f"""🔄 交易对配置已自动更新

配对数量: {summary['count']} 对
币种数量: {summary['symbols']} 个
状态: ✅ 服务运行正常

备份: {backup_name.split('/')[-1]}"""
    
    send_notification(message)
    print("\n✅ 更新完成并已发送通知")
    return True


def verify_settings():
    """验证当前设置"""
    print("="*60)
    print("🔍 验证交易对设置")
    print("="*60)
    
    summary = get_pairs_summary()
    print(f"\n配置统计:")
    print(f"  交易对: {summary['count']} 对")
    print(f"  币种: {summary['symbols']} 个")
    print(f"  示例: {', '.join(summary['pairs'])}...")
    
    print(f"\n服务状态: {check_service_status()}")
    
    print("\n最近日志:")
    logs = get_recent_logs(5)
    for line in logs.split('\n')[-5:]:
        if line.strip():
            print(f"  {line}")


def main():
    parser = argparse.ArgumentParser(description="交易对自动更新工具")
    parser.add_argument("--check", action="store_true", help="检查是否有更新")
    parser.add_argument("--apply", action="store_true", help="应用更新")
    parser.add_argument("--verify", action="store_true", help="验证当前设置")
    parser.add_argument("--cron", action="store_true", help="Cron模式: 有更新时自动应用")
    
    args = parser.parse_args()
    
    if args.check:
        has_update = check_update()
        sys.exit(0 if not has_update else 1)
    
    elif args.apply:
        success = apply_update()
        sys.exit(0 if success else 1)
    
    elif args.verify:
        verify_settings()
    
    elif args.cron:
        # Cron 模式: 检查，如果有更新则自动应用
        if check_update():
            print("\n🔄 自动应用更新...")
            apply_update()
        else:
            print("\n✅ 无需更新")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
