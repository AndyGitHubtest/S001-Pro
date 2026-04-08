"""
模块七 + 模块九：监控、统计与日志 (Monitor + LoggerManager) - P0 LOCKED

M7 职责:
  - 实时跟踪账户状态、交易盈亏
  - Kill Switch 控制 (MaxDD/KillSwitch 触发时通知 Runtime 暂停开仓)
  - 生成统计报表并推送通知

M9 职责:
  - 结构化 JSON 日志
  - 日志分级与路由 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
  - 日志轮转与持久化
  - 启动自检: 清理过期日志

文档规范:
  docs/module_7_monitoring.md
  docs/module_9_logging_monitoring.md
"""

import json
import os
import logging
import time
import glob
from typing import Dict, List, Optional
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


# ──────────────────────────────────────────────
# M9: LoggerManager (结构化 JSON 日志)
# ──────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """
    单行 JSON 格式化器。
    输出: {"ts": "...", "level": "...", "module": "...", "event": "...", "data": {...}, "trace_id": "..."}
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "event": record.getMessage(),
        }
        if hasattr(record, "pair"):
            log_entry["pair"] = record.pair
        if hasattr(record, "trace_id"):
            log_entry["trace_id"] = record.trace_id
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        return json.dumps(log_entry, ensure_ascii=False)


class LoggerManager:
    """
    日志管理器: 结构化 JSON 输出 + 轮转 + 分级路由。
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._loggers: Dict[str, logging.Logger] = {}
        # 启动自检: 清理过期日志
        self.cleanup_old_logs(max_age_days=30)

    def get_logger(self, module_name: str) -> logging.Logger:
        """
        返回配置好 JSON 格式与轮转策略的 Logger 实例。
        """
        if module_name in self._loggers:
            return self._loggers[module_name]

        logger = logging.getLogger(module_name)
        logger.setLevel(logging.DEBUG)

        # 防止重复添加 handler
        if logger.handlers:
            return logger

        # 轮转策略: 50MB, 保留 30 个文件
        system_handler = RotatingFileHandler(
            os.path.join(self.log_dir, "system.log"),
            maxBytes=50 * 1024 * 1024,  # 50MB
            backupCount=30,
            encoding="utf-8",
        )
        system_handler.setFormatter(JSONFormatter())
        system_handler.setLevel(logging.INFO)

        error_handler = RotatingFileHandler(
            os.path.join(self.log_dir, "error.log"),
            maxBytes=50 * 1024 * 1024,
            backupCount=30,
            encoding="utf-8",
        )
        error_handler.setFormatter(JSONFormatter())
        error_handler.setLevel(logging.ERROR)

        # Console handler (INFO+)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        console_handler.setLevel(logging.INFO)

        logger.addHandler(system_handler)
        logger.addHandler(error_handler)
        logger.addHandler(console_handler)

        self._loggers[module_name] = logger
        return logger

    def cleanup_old_logs(self, max_age_days: int = 30):
        """启动自检: 清理过期日志"""
        now = time.time()
        cleaned = 0
        for pattern in ["system.log*", "error.log*", "trade.log*", "debug.log*"]:
            for f in glob.glob(os.path.join(self.log_dir, pattern)):
                if now - os.path.getmtime(f) > max_age_days * 86400:
                    try:
                        os.unlink(f)
                        cleaned += 1
                    except OSError as e:
                        logging.getLogger("LoggerManager").debug(f"Failed to cleanup old log {f}: {e}")
        if cleaned > 0:
            logging.getLogger("LoggerManager").info(f"cleanup_old_logs: removed {cleaned} expired log files")


# ──────────────────────────────────────────────
# M7: Monitor (监控与统计)
# ──────────────────────────────────────────────

class TradeRecord:
    """单笔交易记录"""

    def __init__(self, pair: str, realized_pnl: float, hold_time_min: float = 0, z_in: float = 0, z_out: float = 0):
        self.pair = pair
        self.realized_pnl = realized_pnl
        self.hold_time_min = hold_time_min
        self.z_in = z_in
        self.z_out = z_out
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # 记录归属日期


class Monitor:
    """
    实时监控: 账户权益、PnL、回撤、胜率、盈亏比、Kill Switch、Telegram 推送。

    FIX P0: Kill Switch 实际生效 (设置 trading_paused 标志, Runtime 检查后暂停开仓)
    FIX P0: 与 Runtime 对接, 成交后自动调用 record_trade
    FIX P1: _notify_sync 安全处理 async (保存引用防 GC)
    FIX P2: 先保存再发送, 发送失败不清零
    """

    def __init__(self, notifier=None, stats_path: str = "data/daily_stats.json"):
        self.notifier = notifier
        self.stats_path = stats_path
        self.start_equity = 0.0
        self.peak_equity = 0.0
        self.current_equity = 0.0
        self.daily_pnl = 0.0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.wins = 0
        self.losses = 0
        self.max_drawdown = 0.0
        self.trades: List[TradeRecord] = []
        self._daily_stats: Dict = {}
        self._alert_flags = {"risk_high": False}

        # FIX P0: Kill Switch 状态 (供 Runtime 检查)
        self.trading_paused = False
        self.pause_reason = ""
        self.pause_time = 0.0

    def is_trading_paused(self) -> bool:
        """
        供 Runtime 检查是否应该暂停开仓。
        Kill Switch 触发时返回 True。
        """
        return self.trading_paused

    def get_pause_reason(self) -> str:
        """返回暂停原因"""
        return self.pause_reason

    def resume_trading(self):
        """
        手动恢复交易 (需人工确认后调用)。
        """
        self.trading_paused = False
        self.pause_reason = ""
        logging.getLogger("Monitor").info("Monitor: trading resumed by manual override")

    def initialize(self, equity: float):
        """初始化监控 (启动时调用)"""
        self.start_equity = equity
        self.current_equity = equity
        self.peak_equity = equity
        self._load_daily_stats()
        logging.getLogger("Monitor").info(f"Monitor: initialized with equity ${equity:,.0f}")

    def record_trade(self, trade: TradeRecord):
        """
        记录单笔交易结果，更新胜率、PF。
        FIX: 由 Runtime 在成交确认后调用。
        """
        self.trades.append(trade)
        self.daily_pnl += trade.realized_pnl
        self.current_equity = self.start_equity + self.daily_pnl

        if trade.realized_pnl > 0:
            self.gross_profit += trade.realized_pnl
            self.wins += 1
        else:
            self.gross_loss += abs(trade.realized_pnl)
            self.losses += 1

        # 更新峰值和回撤
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        if self.peak_equity > 0:
            dd = (self.peak_equity - self.current_equity) / self.peak_equity
            if dd > self.max_drawdown:
                self.max_drawdown = dd

        # 推送成交通知
        if self.notifier:
            msg = (
                f"✅ [CLOSED] {trade.pair} | "
                f"PnL: {'+' if trade.realized_pnl >= 0 else ''}${trade.realized_pnl:.2f} "
                f"({'+' if trade.realized_pnl >= 0 else ''}{trade.realized_pnl / (self.start_equity + 1e-8) * 100:.2f}%) | "
                f"Hold: {trade.hold_time_min:.0f}m | "
                f"Z_In: {trade.z_in:.2f} -> Z_Out: {trade.z_out:.2f}"
            )
            self._notify_sync("INFO", msg)

        # 保存统计
        self._save_daily_stats()

    def _notify_sync(self, level: str, message: str):
        """
        同步通知包装器 (处理 async notifier 在 sync 上下文)。
        FIX P1: 保存 task 引用防止被 GC 回收。
        """
        import asyncio
        import inspect
        method = getattr(self.notifier, {
            "INFO": "send_info",
            "WARNING": "send_warning",
            "CRITICAL": "send_critical",
        }.get(level, "send_info"), None)
        if method is None:
            return
        if inspect.iscoroutinefunction(method):
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(method(message))
                # FIX P1: 保存 task 引用, 防止被 GC 回收
                if not hasattr(self, "_pending_tasks"):
                    self._pending_tasks = []
                self._pending_tasks.append(task)
                task.add_done_callback(self._cleanup_task)
            except RuntimeError:
                # 没有运行中的事件循环, 缓存消息
                if not hasattr(self, "_message_queue"):
                    self._message_queue = []
                self._message_queue.append((level, message))
        else:
            method(message)

    def _cleanup_task(self, task):
        """清理已完成的任务引用"""
        if hasattr(self, "_pending_tasks"):
            try:
                self._pending_tasks.remove(task)
            except ValueError:
                logging.getLogger("Monitor").debug("_cleanup_task: task already removed (race condition)")

    def update_account(self, equity: float):
        """
        更新权益，计算回撤，检查报警阈值。
        由外部定时调用 (建议每 5 分钟)。
        """
        self.current_equity = equity

        if equity > self.peak_equity:
            self.peak_equity = equity

        if self.peak_equity > 0:
            dd = (self.peak_equity - equity) / self.peak_equity
            if dd > self.max_drawdown:
                self.max_drawdown = dd

        # 报警检查
        self._check_alerts(equity)

    def _check_alerts(self, equity: float):
        """
        检查报警阈值。
        FIX P0: Kill Switch 触发时设置 trading_paused, 通知 Runtime 暂停开仓。
        """
        # Kill Switch: MaxDD > 15% → 暂停所有开仓
        if self.max_drawdown > 0.15 and not self.trading_paused:
            self.trading_paused = True
            self.pause_reason = f"Max Drawdown {self.max_drawdown:.2%} exceeds 15% limit"
            self.pause_time = time.time()
            self._notify_sync("CRITICAL", (
                f"🚨 KILL SWITCH ACTIVATED: Max Drawdown {self.max_drawdown:.2%} exceeds 15%. "
                f"All new positions paused. Manual review required."
            ))
            logging.getLogger("Monitor").critical(f"KILL SWITCH: {self.pause_reason}")
        elif self.start_equity > 0:
            daily_loss_pct = -self.daily_pnl / self.start_equity
            if daily_loss_pct > 0.03 and not self._alert_flags["risk_high"]:
                self._notify_sync("WARNING", (
                    f"⚠️ RISK_HIGH: Daily loss {daily_loss_pct:.2%} exceeds 3%. "
                    f"Monitor closely."
                ))
                self._alert_flags["risk_high"] = True

    def get_stats(self) -> Dict:
        """获取当前统计数据"""
        total_trades = self.wins + self.losses
        win_rate = self.wins / total_trades if total_trades > 0 else 0
        pf = self.gross_profit / (self.gross_loss + 1e-8)

        return {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "start_equity": self.start_equity,
            "current_equity": self.current_equity,
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_pct": round(self.daily_pnl / (self.start_equity + 1e-8) * 100, 2),
            "trades_count": total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(win_rate, 4),
            "profit_factor": round(pf, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "peak_equity": round(self.peak_equity, 2),
            "trading_paused": self.trading_paused,
            "pause_reason": self.pause_reason if self.trading_paused else "",
        }

    def send_daily_report(self):
        """
        生成并发送 Telegram 日报。
        FIX P2: 先保存再发送, 发送失败不清零。
        """
        stats = self.get_stats()

        # FIX P2: 先保存当前统计
        self._save_daily_stats()

        if self.notifier:
            msg = (
                f"📊 [日报] {stats['date']}\n"
                f"💰 净值: {stats['current_equity']:.0f} "
                f"({'+' if stats['daily_pnl'] >= 0 else ''}{stats['daily_pnl']:.0f} "
                f"({'+' if stats['daily_pnl_pct'] >= 0 else ''}{stats['daily_pnl_pct']:.1f}%))\n"
                f"📈 交易: {stats['trades_count']} 笔 "
                f"(胜率 {stats['win_rate']:.0%} | PF {stats['profit_factor']:.1f})\n"
                f"📉 最大回撤: {stats['max_drawdown_pct']:.1f}%\n"
                f"{'✅ 系统状态: Normal' if not self._alert_flags['risk_high'] and not self.trading_paused else '⚠️ 系统状态: PAUSED' if self.trading_paused else '⚠️ 系统状态: RISK_HIGH'}"
            )
            self._notify_sync("INFO", msg)

        # 重置当日计数器
        self.daily_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.start_equity = self.current_equity
        self._alert_flags = {"risk_high": False}

    def _load_daily_stats(self):
        """加载历史每日统计"""
        if os.path.exists(self.stats_path):
            try:
                with open(self.stats_path, "r") as f:
                    self._daily_stats = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._daily_stats = {}

    def _save_daily_stats(self):
        """保存当前统计到文件 - FIX BUG-006: 原子写入防止数据损坏"""
        import tempfile
        
        stats = self.get_stats()
        stats_dir = os.path.dirname(os.path.abspath(self.stats_path))
        os.makedirs(stats_dir, exist_ok=True)
        
        tmp_path = None
        try:
            # 原子写入: tmpfile -> os.replace
            with tempfile.NamedTemporaryFile(
                mode="w", 
                dir=stats_dir, 
                suffix=".tmp", 
                delete=False,
                encoding="utf-8"
            ) as tmp:
                json.dump(stats, tmp, indent=2)
                tmp_path = tmp.name
            
            # 备份旧文件
            if os.path.exists(self.stats_path):
                backup_path = self.stats_path + ".bak"
                os.replace(self.stats_path, backup_path)
            
            # 原子替换
            os.replace(tmp_path, self.stats_path)
            
        except OSError as e:
            logging.getLogger("Monitor").error(f"Failed to save daily stats: {e}")
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)


# ──────────────────────────────────────────────
# 简易 Notifier (Telegram)
# ──────────────────────────────────────────────

class TelegramNotifier:
    """
    Telegram 通知器。
    
    FIX BUG-008: 实现速率限制，每分钟最多10条，超出压制+汇总
    """
    
    MAX_MESSAGES_PER_MINUTE = 10
    RATE_LIMIT_WINDOW = 60  # 秒

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        
        # FIX BUG-008: 速率限制状态
        self._message_times: List[float] = []  # 记录发送时间
        self._dropped_count = 0  # 被丢弃的消息计数
        self._last_drop_notify = 0.0  # 上次通知被丢弃的时间

    async def send_info(self, message: str):
        """发送 INFO 级别消息"""
        await self._send_with_rate_limit(message, "INFO")

    async def send_warning(self, message: str):
        """发送 WARNING 级别消息"""
        await self._send_with_rate_limit(f"⚠️ {message}", "WARNING")

    async def send_critical(self, message: str):
        """发送 CRITICAL 级别消息 (加紧急标记，不受速率限制)"""
        # CRITICAL级别不受速率限制，确保紧急告警必达
        await self._send(f"🚨🚨 {message}")
    
    async def _send_with_rate_limit(self, message: str, level: str):
        """FIX BUG-008: 带速率限制的发送"""
        now = time.time()
        
        # 清理过期的时间记录
        self._message_times = [t for t in self._message_times if now - t < self.RATE_LIMIT_WINDOW]
        
        # 检查是否超出限制
        if len(self._message_times) >= self.MAX_MESSAGES_PER_MINUTE:
            # 超出限制，记录丢弃
            self._dropped_count += 1
            
            # 每分钟最多通知一次被丢弃的消息
            if now - self._last_drop_notify >= 60:
                self._last_drop_notify = now
                dropped_msg = f"⚠️ Rate limit: {self._dropped_count} messages dropped in last minute"
                logging.getLogger("Notifier").warning(dropped_msg)
                # 尝试发送汇总通知（CRITICAL级别确保送达）
                await self._send(f"🚨 {dropped_msg}")
            else:
                logging.getLogger("Notifier").debug(f"Message dropped due to rate limit: {message[:50]}...")
            return
        
        # 记录发送时间
        self._message_times.append(now)
        
        # 发送消息
        await self._send(message)
        
        # 重置丢弃计数（成功发送后）
        if self._dropped_count > 0:
            self._dropped_count = 0

    async def _send(self, message: str):
        """实际发送 (HTTP POST)"""
        try:
            import aiohttp
        except ImportError:
            # Fallback: 用 urllib 同步发送 (避免 aiohttp 依赖)
            import urllib.request
            import urllib.parse
            url = f"{self._base_url}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
            }).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status != 200:
                        logging.getLogger("Notifier").error(f"Telegram send failed: {resp.status}")
            except Exception as e:
                logging.getLogger("Notifier").error(f"Telegram send error: {e}")
            return

        # aiohttp 路径
        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logging.getLogger("Notifier").error(f"Telegram send failed: {resp.status} {text}")
        except Exception as e:
            logging.getLogger("Notifier").error(f"Telegram send error: {e}")


class MockNotifier:
    """测试用 Mock 通知器"""

    def __init__(self):
        self.messages: List[str] = []

    async def send_info(self, message: str):
        self.messages.append(("INFO", message))

    async def send_warning(self, message: str):
        self.messages.append(("WARNING", message))

    async def send_critical(self, message: str):
        self.messages.append(("CRITICAL", message))