#!/usr/bin/env python3
"""
S001-Pro 运行报告生成器

生成策略运行状况的详细报告

用法:
  python tools/generate_report.py              # 生成完整报告
  python tools/generate_report.py --daily      # 生成日报
  python tools/generate_report.py --weekly     # 生成周报
  python tools/generate_report.py --export     # 导出CSV
"""

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any
import csv


class ReportGenerator:
    """报告生成器"""
    
    def __init__(self):
        self.db_path = Path("data/trades.db")
        self.state_file = Path("data/state.json")
        self.log_dir = Path("logs")
    
    def get_service_status(self) -> Dict:
        """获取服务状态"""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "trading-s001"],
                capture_output=True,
                text=True
            )
            active = result.stdout.strip() == "active"
            
            # 获取资源使用
            result = subprocess.run(
                ["ps", "-o", "pid,rss,etime,args", "-C", "python"],
                capture_output=True,
                text=True
            )
            
            memory_mb = 0
            uptime = "未知"
            for line in result.stdout.split("\n"):
                if "main.py" in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            memory_kb = int(parts[1])
                            memory_mb = memory_kb / 1024
                            uptime = parts[2]
                        except:
                            pass
            
            return {
                "active": active,
                "memory_mb": memory_mb,
                "uptime": uptime
            }
        except:
            return {"active": False, "memory_mb": 0, "uptime": "未知"}
    
    def get_account_info(self) -> Dict:
        """获取账户信息"""
        try:
            import ccxt
            import yaml
            
            with open("config/base.yaml") as f:
                config = yaml.safe_load(f)
            
            exchange = ccxt.binance({
                "apiKey": config["exchange"]["api_key"],
                "secret": config["exchange"]["api_secret"],
                "options": {"defaultType": "swap"}
            })
            
            balance = exchange.fetch_balance()
            usdt = balance.get("USDT", {})
            
            positions = exchange.fetch_positions()
            active_positions = [p for p in positions if float(p.get("contracts", 0)) != 0]
            
            return {
                "total_usdt": usdt.get("total", 0),
                "free_usdt": usdt.get("free", 0),
                "used_usdt": usdt.get("used", 0),
                "position_count": len(active_positions)
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_trade_stats(self, days: int = 1) -> Dict:
        """获取交易统计"""
        if not self.db_path.exists():
            return {"error": "交易数据库不存在"}
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # 时间范围
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                
                # 总体统计
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losses,
                        SUM(realized_pnl) as total_pnl,
                        AVG(realized_pnl) as avg_pnl,
                        AVG(holding_minutes) as avg_holding
                    FROM trades
                    WHERE date(entry_time) >= ? AND status = 'closed'
                """, (start_date,))
                
                row = cursor.fetchone()
                
                # 按配对统计
                cursor = conn.execute("""
                    SELECT 
                        pair,
                        COUNT(*) as count,
                        SUM(realized_pnl) as pnl
                    FROM trades
                    WHERE date(entry_time) >= ? AND status = 'closed'
                    GROUP BY pair
                    ORDER BY pnl DESC
                """, (start_date,))
                
                by_pair = [dict(r) for r in cursor.fetchall()]
                
                # 未平仓
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE status = 'open'"
                )
                open_count = cursor.fetchone()[0]
                
                return {
                    "total_trades": row[0] or 0,
                    "winning_trades": row[1] or 0,
                    "losing_trades": row[2] or 0,
                    "total_pnl": row[3] or 0,
                    "avg_pnl": row[4] or 0,
                    "avg_holding_min": row[5] or 0,
                    "open_positions": open_count,
                    "by_pair": by_pair[:5]  # Top 5
                }
        except Exception as e:
            return {"error": str(e)}
    
    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """获取最近交易"""
        if not self.db_path.exists():
            return []
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM trades
                    ORDER BY entry_time DESC
                    LIMIT ?
                """, (limit,))
                return [dict(r) for r in cursor.fetchall()]
        except:
            return []
    
    def generate_full_report(self) -> str:
        """生成完整报告"""
        service = self.get_service_status()
        account = self.get_account_info()
        stats = self.get_trade_stats(days=1)
        recent = self.get_recent_trades(5)
        
        report = f"""
{'='*70}
📊 S001-Pro 策略运行报告
{'='*70}

🕐 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                        📈 服务状态                                    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

  {'🟢' if service['active'] else '🔴'} 服务状态: {'运行中' if service['active'] else '已停止'}
  💾 内存使用: {service['memory_mb']:.1f} MB
  ⏱️  运行时间: {service['uptime']}

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                        💰 账户信息                                    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
"""
        
        if "error" in account:
            report += f"\n  ⚠️  获取失败: {account['error']}\n"
        else:
            report += f"""
  💵 总余额: {account['total_usdt']:.2f} USDT
  🆓 可用:   {account['free_usdt']:.2f} USDT
  🔒 已用:   {account['used_usdt']:.2f} USDT
  📊 持仓数: {account['position_count']} 个
"""
        
        report += """
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                        📊 今日交易统计                                ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
"""
        
        if "error" in stats:
            report += f"\n  ⚠️  {stats['error']}\n"
        else:
            win_rate = (stats['winning_trades'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
            pnl_emoji = "🟢" if stats['total_pnl'] >= 0 else "🔴"
            
            report += f"""
  📈 总交易:   {stats['total_trades']} 笔
  🏆 盈利:     {stats['winning_trades']} 笔
  💔 亏损:     {stats['losing_trades']} 笔
  🎯 胜率:     {win_rate:.1f}%
  {pnl_emoji} 盈亏:     {stats['total_pnl']:+.2f} USDT
  ⏱️  平均持仓: {stats['avg_holding_min']:.1f} 分钟
  🈶 未平仓:   {stats['open_positions']} 个
"""
            
            if stats['by_pair']:
                report += "\n  📋 配对盈亏 (Top 5):\n"
                for p in stats['by_pair']:
                    emoji = "🟢" if p['pnl'] >= 0 else "🔴"
                    report += f"     {emoji} {p['pair']}: {p['pnl']:+.2f} ({p['count']}笔)\n"
        
        if recent:
            report += """
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                        📝 最近交易                                    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

"""
            for t in recent:
                emoji = "🟢" if t.get('realized_pnl', 0) >= 0 else "🔴"
                status = "已平" if t['status'] == 'closed' else "持仓"
                report += f"  {emoji} {t['pair']} | {status} | 入场Z: {t['entry_z']:.2f}"
                if t['status'] == 'closed':
                    report += f" | 盈亏: {t['realized_pnl']:+.2f}"
                report += "\n"
        
        report += f"""
{'='*70}
"""
        
        return report
    
    def export_csv(self, filepath: str = None):
        """导出CSV"""
        if filepath is None:
            filepath = f"reports/trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        trades = self.get_recent_trades(1000)
        
        if not trades:
            print("⚠️  无交易记录可导出")
            return
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        
        print(f"✅ 已导出 {len(trades)} 条交易记录到: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="S001-Pro 报告生成器")
    parser.add_argument("--daily", action="store_true", help="生成日报")
    parser.add_argument("--weekly", action="store_true", help="生成周报")
    parser.add_argument("--export", action="store_true", help="导出CSV")
    parser.add_argument("--output", type=str, help="输出文件路径")
    
    args = parser.parse_args()
    
    generator = ReportGenerator()
    
    if args.export:
        generator.export_csv(args.output)
    else:
        report = generator.generate_full_report()
        print(report)
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(report)
            print(f"✅ 报告已保存到: {args.output}")


if __name__ == "__main__":
    main()
