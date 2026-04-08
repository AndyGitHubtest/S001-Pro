#!/usr/bin/env python3
"""
S001-Pro 利润管理器

功能:
  1. 每日定时划转利润到资金账户
  2. 保留本金+风险准备金在合约账户
  3. 记录所有划转日志
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional
import ccxt

logger = logging.getLogger("ProfitManager")


class ProfitManager:
    """利润自动划转管理"""

    def __init__(self, exchange: ccxt.Exchange, config: Dict):
        self.exchange = exchange
        self.config = config

        # 配置项
        self.daily_transfer_time = config.get("profit_transfer_time", "02:00")  # 每天2点
        self.reserve_ratio = config.get("reserve_ratio", 1.2)  # 保留本金的120%
        self.min_transfer = config.get("min_transfer_usdt", 10)  # 最小划转金额
        self.capital = config.get("capital", 10000)

        self._last_transfer_date: Optional[str] = None
        self._running = False

    async def start(self):
        """启动利润划转定时任务"""
        self._running = True
        logger.info(f"ProfitManager: 启动，每日 {self.daily_transfer_time} 划转利润")

        while self._running:
            try:
                now = datetime.now()
                target_time = datetime.strptime(self.daily_transfer_time, "%H:%M").time()

                # 检查是否到了划转时间且今天未划转
                today_str = now.strftime("%Y-%m-%d")
                if (now.time() >= target_time and
                    self._last_transfer_date != today_str):

                    await self._do_profit_transfer()
                    self._last_transfer_date = today_str

                # 每分钟检查一次
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"ProfitManager: 定时任务异常 - {e}")
                await asyncio.sleep(300)  # 出错后5分钟再试

    def stop(self):
        """停止定时任务"""
        self._running = False

    async def _do_profit_transfer(self):
        """执行利润划转"""
        try:
            logger.info("ProfitManager: 开始计算利润划转...")

            # 获取合约账户余额
            balance = await self._fetch_futures_balance()
            available = balance.get("free", 0)
            total = balance.get("total", 0)

            # 计算应保留金额 (本金 × 保留比例)
            reserve_amount = self.capital * self.reserve_ratio

            # 计算可划转利润
            profit = total - self.capital
            transfer_amount = min(available - reserve_amount, profit)

            if transfer_amount < self.min_transfer:
                logger.info(f"ProfitManager: 利润不足 {self.min_transfer} USDT，跳过划转 "
                           f"(利润: {profit:.2f}, 可用: {available:.2f})")
                return

            # 执行划转 (合约账户 -> 资金账户)
            logger.info(f"ProfitManager: 划转 {transfer_amount:.2f} USDT 到资金账户")
            await self._transfer_to_spot(transfer_amount)

            # 记录日志
            await self._record_transfer({
                "timestamp": datetime.now().isoformat(),
                "amount": transfer_amount,
                "total_profit": profit,
                "contract_balance_before": total,
                "contract_balance_after": total - transfer_amount,
            })

            logger.info(f"ProfitManager: 划转成功 {transfer_amount:.2f} USDT")

        except Exception as e:
            logger.error(f"ProfitManager: 划转失败 - {e}")

    async def _fetch_futures_balance(self) -> Dict:
        """获取合约账户余额"""
        balance = await asyncio.to_thread(self.exchange.fetch_balance)
        usdt = balance.get("USDT", {})
        return {
            "free": usdt.get("free", 0),
            "used": usdt.get("used", 0),
            "total": usdt.get("total", 0),
        }

    async def _transfer_to_spot(self, amount: float):
        """
        从合约账户划转 USDT 到现货/资金账户

        注意: 币安需要调用 futures_transfer API
        """
        try:
            # 币安合约 -> 现货划转
            await asyncio.to_thread(
                self.exchange.transfer,
                code="USDT",
                amount=amount,
                fromAccount="future",
                toAccount="spot"
            )
        except Exception as e:
            logger.error(f"划转 API 调用失败: {e}")
            raise

    async def _record_transfer(self, record: Dict):
        """记录划转到日志文件"""
        import json
        import os

        log_file = "data/profit_transfers.jsonl"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        with open(log_file, "a") as f:
            f.write(json.dumps(record) + "\n")

    async def get_profit_summary(self) -> Dict:
        """获取利润汇总统计"""
        try:
            balance = await self._fetch_futures_balance()
            total = balance.get("total", 0)
            profit = total - self.capital

            return {
                "capital": self.capital,
                "current_balance": total,
                "total_profit": profit,
                "profit_pct": (profit / self.capital) * 100 if self.capital > 0 else 0,
                "last_transfer_date": self._last_transfer_date,
            }
        except Exception as e:
            logger.error(f"获取利润统计失败: {e}")
            return {}
