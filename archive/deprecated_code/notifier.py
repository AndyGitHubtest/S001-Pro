#!/usr/bin/env python3
"""
通知模块 - Telegram 推送与每日报告

功能:
  1. Telegram 实时通知 (交易/告警)
  2. 每日交易报告定时推送
  3. 配置验证与诊断
"""

import logging
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger("Notifier")


@dataclass
class TradeRecord:
    """交易记录"""
    timestamp: str
    pair: str
    action: str  # OPEN / CLOSE / SCALE_IN / SCALE_OUT
    side: str    # LONG / SHORT
    amount: float
    price: float
    pnl: Optional[float] = None


class TelegramNotifier:
    """增强版 Telegram 通知器"""

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)  # 确保是字符串
        self.enabled = enabled
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._tested = False
        self._test_result = None

    async def validate_config(self) -> tuple[bool, str]:
        """
        验证 Telegram 配置是否正确
        Returns: (is_valid, message)
        """
        try:
            import aiohttp
        except ImportError:
            return False, "aiohttp 未安装"

        try:
            url = f"{self._base_url}/getMe"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok"):
                            bot_name = data["result"].get("username", "Unknown")
                            # 测试发送消息
                            test_result = await self._send("🔧 S001-Pro 配置测试消息\n如果收到此消息，说明配置正确。")
                            if test_result:
                                return True, f"Bot @{bot_name} 连接正常"
                            else:
                                return False, "Bot 正常但无法发送消息 (chat_id 可能错误)"
                        else:
                            return False, f"Bot API 错误: {data}"
                    elif resp.status == 404:
                        return False, "Bot Token 无效 (404)"
                    elif resp.status == 401:
                        return False, "Bot Token 未授权 (401)"
                    else:
                        return False, f"HTTP {resp.status}"
        except Exception as e:
            return False, f"连接异常: {str(e)[:50]}"

    async def send_info(self, message: str):
        """发送 INFO 级别消息"""
        if not self.enabled:
            return
        await self._send(f"ℹ️ {message}")

    async def send_trade(self, message: str):
        """发送交易通知"""
        if not self.enabled:
            return
        await self._send(f"💰 <b>交易</b>\n{message}")

    async def send_profit(self, daily_pnl: float, total_trades: int, win_rate: float):
        """发送盈亏报告"""
        if not self.enabled:
            return
        emoji = "🟢" if daily_pnl >= 0 else "🔴"
        message = f"""{emoji} <b>每日盈亏报告</b>

💵 当日盈亏: <code>{daily_pnl:+.2f}</code> USDT
📊 交易次数: {total_trades}
🎯 胜率: {win_rate:.1f}%
⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
        await self._send(message)

    async def send_warning(self, message: str):
        """发送 WARNING 级别消息"""
        if not self.enabled:
            return
        await self._send(f"⚠️ <b>警告</b>\n{message}")

    async def send_critical(self, message: str):
        """发送 CRITICAL 级别消息 (加紧急标记)"""
        if not self.enabled:
            return
        await self._send(f"🚨 <b>紧急</b>\n{message}")

    async def _send(self, message: str) -> bool:
        """
        实际发送 (HTTP POST)
        Returns: 是否发送成功
        """
        if not self.enabled:
            return False

        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
        }

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        return True
                    else:
                        text = await resp.text()
                        logger.error(f"Telegram send failed: {resp.status} {text[:100]}")
                        return False
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False


class DailyReportManager:
    """
    每日交易报告管理器

    功能:
      - 定时生成每日盈亏报告
      - 统计交易数据
      - 推送到 Telegram
    """

    def __init__(self, notifier: TelegramNotifier, stats_path: str = "data/daily_stats.json"):
        self.notifier = notifier
        self.stats_path = stats_path
        self._running = False
        self._report_time = "21:00"  # 每天21:00发送报告 (UTC+8)
        self._trades: List[TradeRecord] = []

    async def start(self):
        """启动定时报告任务"""
        self._running = True
        logger.info(f"DailyReport: 启动，每日 {self._report_time} 发送报告")

        while self._running:
            try:
                now = datetime.now()
                target_time = datetime.strptime(self._report_time, "%H:%M").time()

                # 检查是否到了报告时间且今天未发送
                today_str = now.strftime("%Y-%m-%d")
                last_report = self._get_last_report_date()

                if now.time() >= target_time and last_report != today_str:
                    await self._send_daily_report()
                    self._set_last_report_date(today_str)
                    self._clear_daily_stats()  # 清空今日统计

                # 每分钟检查一次
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"DailyReport: 定时任务异常 - {e}")
                await asyncio.sleep(300)

    def stop(self):
        """停止定时任务"""
        self._running = False

    def record_trade(self, trade: TradeRecord):
        """记录一笔交易"""
        self._trades.append(trade)

    async def _send_daily_report(self):
        """生成并发送每日报告"""
        try:
            # 计算统计数据
            total_pnl = sum(t.pnl for t in self._trades if t.pnl is not None)
            total_trades = len(self._trades)
            wins = sum(1 for t in self._trades if t.pnl and t.pnl > 0)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            # 按配对统计
            pair_stats: Dict[str, Dict] = {}
            for t in self._trades:
                if t.pair not in pair_stats:
                    pair_stats[t.pair] = {"trades": 0, "pnl": 0}
                pair_stats[t.pair]["trades"] += 1
                if t.pnl:
                    pair_stats[t.pair]["pnl"] += t.pnl

            # 构建报告
            top_pairs = sorted(pair_stats.items(), key=lambda x: abs(x[1]["pnl"]), reverse=True)[:5]
            pair_text = "\n".join([
                f"  <code>{p}</code>: {s['pnl']:+.2f} ({s['trades']}笔)"
                for p, s in top_pairs
            ]) if top_pairs else "  无交易"

            emoji = "🟢" if total_pnl >= 0 else "🔴"
            report = f"""{emoji} <b>S001-Pro 每日交易报告</b>

<b>📊 总体统计</b>
💵 当日盈亏: <code>{total_pnl:+.2f}</code> USDT
📈 交易笔数: {total_trades}
🎯 胜率: {win_rate:.1f}%
🏆 盈利笔数: {wins}

<b>📉 最佳/最差配对</b>
{pair_text}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC+8"""

            await self.notifier.send_info(report)
            logger.info(f"DailyReport: 已发送每日报告 (PnL: {total_pnl:.2f})")

        except Exception as e:
            logger.error(f"DailyReport: 生成报告失败 - {e}")

    def _get_last_report_date(self) -> Optional[str]:
        """获取上次报告日期"""
        try:
            import os
            flag_file = self.stats_path + ".last_report"
            if os.path.exists(flag_file):
                with open(flag_file, "r") as f:
                    return f.read().strip()
        except Exception:
            # 读取失败（文件可能不存在），返回 None
            pass
        return None

    def _set_last_report_date(self, date: str):
        """设置上次报告日期"""
        try:
            flag_file = self.stats_path + ".last_report"
            with open(flag_file, "w") as f:
                f.write(date)
        except Exception as e:
            logger.error(f"DailyReport: 保存日期失败 - {e}")

    def _clear_daily_stats(self):
        """清空今日统计"""
        self._trades = []
