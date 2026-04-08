"""
Phase 4 单元测试: Runtime (M6) + Monitor (M7) + LoggerManager (M9)

测试覆盖:
  M6 Runtime:
    - 状态机流转 (IDLE -> SCALING_IN -> IN_POSITION -> SCALING_OUT -> EXITED)
    - 进场触发 (Long/Short Spread)
    - 止损触发 (最高优先级)
    - 止盈触发
    - 热重载 (新增/移除配对, CLOSING_MODE)
    - 状态恢复 (Ghost/Orphan 检测)
    - Leg Sync 回滚

  M7 Monitor:
    - 交易记录更新 (胜率, PF, MaxDD)
    - 账户权益更新与回撤计算
    - 报警阈值触发 (MaxDD > 15%, 日亏损 > 3%)
    - 每日报表生成与计数器重置
    - daily_stats.json 持久化

  M9 LoggerManager:
    - Logger 实例获取 (幂等)
    - JSON 格式化
    - 日志文件创建

文档规范: docs/module_6_runtime.md, docs/module_7_monitoring.md, docs/module_9_logging_monitoring.md
"""

import sys
import os
import json
import tempfile
import unittest
import asyncio
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.runtime import Runtime, PositionState, STATE_IDLE, STATE_SCALING_IN, STATE_IN_POSITION, STATE_SCALING_OUT, STATE_EXITED, STATE_CLOSING_MODE
from src.monitor_logger import Monitor, TradeRecord, LoggerManager, JSONFormatter, MockNotifier, TelegramNotifier


# ──────────────────────────────────────────────
# M6 Runtime 测试
# ──────────────────────────────────────────────

class TestRuntime(unittest.TestCase):
    """Runtime 单元测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.notifier = MockNotifier()

        # Mock exchange API
        class MockExchange:
            def __init__(self):
                self.orders_placed = []
                self.fail_leg = None  # 设置 "A" 或 "B" 让对应 leg 失败
                self.positions = []

            async def place_order(self, symbol, order_type, side, qty, post_only=True):
                if self.fail_leg == "A" and "SYM0" in symbol:
                    raise Exception("Leg A failed")
                if self.fail_leg == "B" and "SYM1" in symbol:
                    raise Exception("Leg B failed")
                self.orders_placed.append({
                    "symbol": symbol,
                    "type": order_type,
                    "side": side,
                    "qty": qty,
                    "post_only": post_only,
                })
                return {"success": True}

            async def get_positions(self):
                return self.positions

            async def cancel_all_orders(self, symbol):
                pass

        self.exchange = MockExchange()

        # Mock ConfigManager
        class MockConfigManager:
            def __init__(self):
                self._pairs_data = {}

            @property
            def pairs_data(self):
                return self._pairs_data

            def get_pair_config(self, key):
                return None

            def set_pairs_data(self, data):
                self._pairs_data = data

        self.config_manager = MockConfigManager()

        # Runtime 实例
        self.runtime = Runtime(
            config_manager=self.config_manager,
            exchange_api=self.exchange,
            notifier=self.notifier,
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_pair_config(self, sym_a="SYM0/USDT", sym_b="SYM1/USDT", z_entry=2.5, z_exit=0.8, z_stop=4.5):
        return {
            "symbol_a": sym_a,
            "symbol_b": sym_b,
            "beta": 1.0,
            "params": {"z_entry": z_entry, "z_exit": z_exit, "z_stop": z_stop},
            "execution": {
                "legs_sync": {"simultaneous": True, "tolerance_ms": 3000, "rollback_on_failure": True},
                "scale_in": [
                    {"trigger_z": 2.0, "ratio": 0.3, "type": "limit", "post_only": True},
                    {"trigger_z": 2.5, "ratio": 0.3, "type": "limit", "post_only": True},
                    {"trigger_z": 3.0, "ratio": 0.4, "type": "limit", "post_only": True},
                ],
                "scale_out": [
                    {"trigger_z": 1.5, "ratio": 0.3, "type": "limit", "post_only": True},
                    {"trigger_z": 0.8, "ratio": 0.4, "type": "limit", "post_only": True},
                    {"trigger_z": 0.0, "ratio": 0.3, "type": "market", "post_only": False},
                ],
                "stop_loss": {"trigger_z": 4.5, "type": "market", "post_only": False},
            },
            "allocation": {"max_position_value_usd": 5000.0, "risk_score": 0.85},
        }

    def test_position_state_initialization(self):
        """测试: PositionState 初始化"""
        config = self._make_pair_config()
        ps = PositionState(config)
        self.assertEqual(ps.state, STATE_IDLE)
        self.assertEqual(ps.direction, 0)
        self.assertEqual(ps.scale_in_layer, 0)
        self.assertEqual(ps.position_size_pct, 0.0)

    def test_position_state_serialization(self):
        """测试: PositionState 序列化/反序列化"""
        config = self._make_pair_config()
        ps = PositionState(config)
        ps.state = STATE_SCALING_IN
        ps.direction = 1
        ps.entry_z = 2.5
        ps.scale_in_layer = 1
        ps.position_size_pct = 0.6

        data = ps.to_dict()
        ps2 = PositionState.from_dict(config, data)

        self.assertEqual(ps2.state, STATE_SCALING_IN)
        self.assertEqual(ps2.direction, 1)
        self.assertEqual(ps2.entry_z, 2.5)
        self.assertEqual(ps2.position_size_pct, 0.6)

    def test_state_machine_entry_long_spread(self):
        """测试: 状态机 - Long Spread 进场 (Z <= -entry)"""
        config = self._make_pair_config()
        ps = PositionState(config)
        self.runtime.positions["SYM0/USDT_SYM1/USDT"] = ps

        async def run():
            # Z = -3.0 (低于 -2.5 entry)
            await self.runtime.check_signals("SYM0/USDT_SYM1/USDT", -3.0)
            return ps.state, ps.direction

        state, direction = asyncio.get_event_loop().run_until_complete(run())
        self.assertEqual(state, STATE_SCALING_IN)
        self.assertEqual(direction, 1)  # Long Spread

    def test_state_machine_entry_short_spread(self):
        """测试: 状态机 - Short Spread 进场 (Z >= entry)"""
        config = self._make_pair_config()
        ps = PositionState(config)
        self.runtime.positions["SYM0/USDT_SYM1/USDT"] = ps

        async def run():
            await self.runtime.check_signals("SYM0/USDT_SYM1/USDT", 3.0)
            return ps.state, ps.direction

        state, direction = asyncio.get_event_loop().run_until_complete(run())
        self.assertEqual(state, STATE_SCALING_IN)
        self.assertEqual(direction, -1)  # Short Spread

    def test_state_machine_no_trigger_in_idle(self):
        """测试: IDLE 状态下 Z 未达阈值不触发"""
        config = self._make_pair_config(z_entry=2.5)
        ps = PositionState(config)
        self.runtime.positions["SYM0/USDT_SYM1/USDT"] = ps

        async def run():
            await self.runtime.check_signals("SYM0/USDT_SYM1/USDT", 1.0)  # < 2.5
            return ps.state

        state = asyncio.get_event_loop().run_until_complete(run())
        self.assertEqual(state, STATE_IDLE)

    def test_state_machine_stop_loss_priority(self):
        """测试: 止损优先级高于其他信号"""
        config = self._make_pair_config(z_stop=4.5)
        ps = PositionState(config)
        ps.state = STATE_IN_POSITION
        ps.direction = 1
        ps.position_size_pct = 1.0
        self.runtime.positions["SYM0/USDT_SYM1/USDT"] = ps

        async def run():
            # Z = 5.0 > z_stop 4.5, 应触发止损
            await self.runtime.check_signals("SYM0/USDT_SYM1/USDT", 5.0)
            return ps.state

        state = asyncio.get_event_loop().run_until_complete(run())
        self.assertEqual(state, STATE_EXITED)

    def test_state_machine_take_profit(self):
        """测试: 止盈触发"""
        config = self._make_pair_config(z_exit=0.8)
        ps = PositionState(config)
        ps.state = STATE_IN_POSITION
        ps.direction = -1  # Short Spread
        ps.position_size_pct = 1.0
        self.runtime.positions["SYM0/USDT_SYM1/USDT"] = ps

        async def run():
            # Z = 0.5 <= 0.8 (第一个止盈触发点)
            await self.runtime.check_signals("SYM0/USDT_SYM1/USDT", 0.5)
            return ps.state, ps.scale_out_layer, ps.position_size_pct

        state, layer, pct = asyncio.get_event_loop().run_until_complete(run())
        self.assertEqual(layer, 1)  # 平仓一层
        self.assertLess(pct, 1.0)

    def test_hot_reload_add_pair(self):
        """测试: 热重载 - 新增配对"""
        async def run():
            self.config_manager.set_pairs_data({
                "pairs": [self._make_pair_config("NEW_A/USDT", "NEW_B/USDT")]
            })
            self.runtime._load_pair_configs()
            return "NEW_A/USDT_NEW_B/USDT" in self.runtime.positions

        result = asyncio.get_event_loop().run_until_complete(run())
        self.assertTrue(result)

    def test_hot_reload_remove_idle_pair(self):
        """测试: 热重载 - 移除空仓配对"""
        config = self._make_pair_config()
        ps = PositionState(config)
        self.runtime.positions["SYM0/USDT_SYM1/USDT"] = ps

        self.runtime.handle_hot_reload({"pairs": []})  # 空配置
        self.assertNotIn("SYM0/USDT_SYM1/USDT", self.runtime.positions)

    def test_hot_reload_remove_active_pair_closing_mode(self):
        """测试: 热重载 - 移除有持仓配对 -> CLOSING_MODE"""
        config = self._make_pair_config()
        ps = PositionState(config)
        ps.state = STATE_IN_POSITION
        ps.position_size_pct = 1.0
        self.runtime.positions["SYM0/USDT_SYM1/USDT"] = ps

        self.runtime.handle_hot_reload({"pairs": []})
        self.assertEqual(ps.state, STATE_CLOSING_MODE)

    def test_leg_sync_rollback(self):
        """测试: Leg Sync 失败回滚"""
        self.exchange.fail_leg = "B"  # 让 B leg 失败

        async def run():
            config = self._make_pair_config()
            ps = PositionState(config)
            ps.state = STATE_SCALING_IN
            ps.direction = 1
            ps.position_size_pct = 0.0
            self.runtime.positions["SYM0/USDT_SYM1/USDT"] = ps

            # 执行开仓 (B leg 会失败 -> 触发回滚)
            success = await self.runtime.execute_sync_open(ps, 1, 0.3)
            return success, len(self.notifier.messages)

        success, msg_count = asyncio.get_event_loop().run_until_complete(run())
        self.assertFalse(success)
        self.assertGreater(msg_count, 0)  # 应有报警消息

    def test_frequency_limit(self):
        """测试: 1Hz 信号防抖"""
        config = self._make_pair_config()
        ps = PositionState(config)
        self.runtime.positions["SYM0/USDT_SYM1/USDT"] = ps

        async def run():
            # 第一次触发
            await self.runtime.check_signals("SYM0/USDT_SYM1/USDT", 3.0)
            state1 = ps.state
            # 立即第二次调用 (应被限频)
            await self.runtime.check_signals("SYM0/USDT_SYM1/USDT", 5.0)
            return state1, ps.scale_in_layer

        state, layer = asyncio.get_event_loop().run_until_complete(run())
        self.assertEqual(state, STATE_SCALING_IN)
        self.assertEqual(layer, 1)  # 只执行了一次

    def test_reset_position(self):
        """测试: 重置状态为 IDLE"""
        config = self._make_pair_config()
        ps = PositionState(config)
        ps.state = STATE_IN_POSITION
        ps.direction = 1
        ps.entry_z = 2.5
        ps.position_size_pct = 1.0

        async def run():
            await self.runtime._reset_position(ps)
            return ps.state, ps.direction, ps.position_size_pct

        state, direction, pct = asyncio.get_event_loop().run_until_complete(run())
        self.assertEqual(state, STATE_IDLE)
        self.assertEqual(direction, 0)
        self.assertEqual(pct, 0.0)


# ──────────────────────────────────────────────
# M7 Monitor 测试
# ──────────────────────────────────────────────

class TestMonitor(unittest.TestCase):
    """Monitor 单元测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.stats_path = os.path.join(self.tmpdir, "daily_stats.json")
        self.notifier = MockNotifier()
        self.monitor = Monitor(notifier=self.notifier, stats_path=self.stats_path)
        self.monitor.initialize(10000.0)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_initialize(self):
        """测试: 初始化设置"""
        self.assertEqual(self.monitor.start_equity, 10000.0)
        self.assertEqual(self.monitor.current_equity, 10000.0)
        self.assertEqual(self.monitor.peak_equity, 10000.0)
        self.assertEqual(self.monitor.daily_pnl, 0.0)

    def test_record_winning_trade(self):
        """测试: 记录盈利交易"""
        trade = TradeRecord("A/USDT_B/USDT", 150.0, hold_time_min=30, z_in=2.5, z_out=0.8)
        self.monitor.record_trade(trade)

        self.assertEqual(self.monitor.wins, 1)
        self.assertEqual(self.monitor.losses, 0)
        self.assertEqual(self.monitor.daily_pnl, 150.0)
        self.assertAlmostEqual(self.monitor.current_equity, 10150.0)

    def test_record_losing_trade(self):
        """测试: 记录亏损交易"""
        trade = TradeRecord("A/USDT_B/USDT", -200.0, hold_time_min=15, z_in=-2.5, z_out=0.0)
        self.monitor.record_trade(trade)

        self.assertEqual(self.monitor.losses, 1)
        self.assertEqual(self.monitor.daily_pnl, -200.0)

    def test_win_rate_and_pf(self):
        """测试: 胜率和盈亏比计算"""
        self.monitor.record_trade(TradeRecord("A", 100.0))
        self.monitor.record_trade(TradeRecord("A", 200.0))
        self.monitor.record_trade(TradeRecord("A", -50.0))
        self.monitor.record_trade(TradeRecord("A", -50.0))

        stats = self.monitor.get_stats()
        self.assertEqual(stats["win_rate"], 0.5)
        self.assertEqual(stats["trades_count"], 4)
        self.assertEqual(stats["profit_factor"], 300.0 / 100.0)  # 300/100 = 3.0

    def test_max_drawdown(self):
        """测试: 最大回撤计算"""
        # 初始 10000
        self.monitor.record_trade(TradeRecord("A", 500.0))  # equity = 10500, peak = 10500
        self.monitor.record_trade(TradeRecord("A", -1000.0))  # equity = 9500
        self.monitor.record_trade(TradeRecord("A", 200.0))  # equity = 9700

        # MaxDD = (10500 - 9500) / 10500 = 9.52%
        self.assertAlmostEqual(self.monitor.max_drawdown, 0.0952, places=3)

    def test_update_account_drawdown(self):
        """测试: update_account 计算回撤"""
        self.monitor.update_account(11000.0)  # peak -> 11000
        self.monitor.update_account(10000.0)  # DD = 1000/11000 = 9.09%

        self.assertAlmostEqual(self.monitor.max_drawdown, 0.0909, places=3)

    def test_alert_max_drawdown_kill_switch(self):
        """测试: MaxDD > 15% 触发 Kill Switch 报警"""
        self.monitor.max_drawdown = 0.16  # 模拟超过 15%
        self.monitor._check_alerts(8500.0)

        critical_msgs = [m for m in self.notifier.messages if m[0] == "CRITICAL"]
        self.assertGreater(len(critical_msgs), 0)
        self.assertIn("KILL SWITCH", critical_msgs[0][1])
        self.assertTrue(self.monitor._alert_flags["risk_high"])

    def test_alert_daily_loss_warning(self):
        """测试: 日亏损 > 3% 触发 RISK_HIGH 报警"""
        self.monitor.daily_pnl = -350.0  # -3.5% of 10000
        self.monitor._check_alerts(9650.0)

        warning_msgs = [m for m in self.notifier.messages if m[0] == "WARNING"]
        self.assertGreater(len(warning_msgs), 0)
        self.assertIn("RISK_HIGH", warning_msgs[0][1])

    def test_daily_report_and_reset(self):
        """测试: 每日报表生成与计数器重置"""
        self.monitor.record_trade(TradeRecord("A", 100.0))
        self.monitor.record_trade(TradeRecord("A", -50.0))

        self.monitor.send_daily_report()

        # 计数器应重置
        self.assertEqual(self.monitor.daily_pnl, 0.0)
        self.assertEqual(self.monitor.wins, 0)
        self.assertEqual(self.monitor.losses, 0)
        self.assertEqual(self.monitor.gross_profit, 0.0)
        self.assertEqual(self.monitor.gross_loss, 0.0)

        # 通知器应有日报
        info_msgs = [m for m in self.notifier.messages if "日报" in m[1]]
        self.assertGreater(len(info_msgs), 0)

    def test_stats_persistence(self):
        """测试: daily_stats.json 持久化"""
        self.monitor.record_trade(TradeRecord("A", 200.0))

        # 检查文件存在且内容正确
        self.assertTrue(os.path.exists(self.stats_path))
        with open(self.stats_path, "r") as f:
            data = json.load(f)
        self.assertEqual(data["daily_pnl"], 200.0)
        self.assertEqual(data["wins"], 1)


# ──────────────────────────────────────────────
# M9 LoggerManager 测试
# ──────────────────────────────────────────────

class TestLoggerManager(unittest.TestCase):
    """LoggerManager 单元测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logger_manager = LoggerManager(log_dir=os.path.join(self.tmpdir, "logs"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_logger_idempotent(self):
        """测试: 多次获取同一 logger 返回同一实例"""
        l1 = self.logger_manager.get_logger("TestModule")
        l2 = self.logger_manager.get_logger("TestModule")
        self.assertIs(l1, l2)

    def test_logger_creates_files(self):
        """测试: Logger 创建日志文件"""
        log_dir = os.path.join(self.tmpdir, "logs")
        logger = self.logger_manager.get_logger("TestFile")
        logger.info("Test log message")

        # 给一点时间让 handler 写入
        import time
        time.sleep(0.1)

        system_log = os.path.join(log_dir, "system.log")
        self.assertTrue(os.path.exists(system_log))

    def test_json_formatter(self):
        """测试: JSON 格式化器输出合法 JSON"""
        formatter = JSONFormatter()
        import logging
        record = logging.LogRecord(
            name="TestModule",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test event",
            args=(),
            exc_info=None,
        )
        record.created = 1712400000.123
        output = formatter.format(record)
        data = json.loads(output)  # 应能正常解析
        self.assertEqual(data["level"], "INFO")
        self.assertEqual(data["module"], "TestModule")
        self.assertEqual(data["event"], "Test event")
        self.assertIn("ts", data)

    def test_error_handler(self):
        """测试: ERROR 级别日志写入 error.log"""
        log_dir = os.path.join(self.tmpdir, "logs")
        logger = self.logger_manager.get_logger("TestError")
        logger.error("Test error message")

        import time
        time.sleep(0.1)

        error_log = os.path.join(log_dir, "error.log")
        self.assertTrue(os.path.exists(error_log))


if __name__ == "__main__":
    unittest.main(verbosity=2)
