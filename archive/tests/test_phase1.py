"""
Phase 1 单元测试: DataEngine + InitialFilter

测试数据准备 (临时文件 SQLite):
  - BTC/USDT:   正常数据 (Vol 500 万, Count 130k, Price 60000)
  - USDC/USDT:  稳定币 (应被剔除)
  - DEAD/USDT:  僵尸盘 (High 1.0, Low 0.99, Close 1.0, Vol 500 万)
  - NEWB/USDT:  新币 (Count 5000)
  - GAP/USDT:   缺失数据 (Count 50000)

文档规范: docs/DEV_PHASE_1_DATA_FILTER.md
"""

import sys
import os
import sqlite3
import unittest
import tempfile
import numpy as np
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_engine import DataEngine
from src.filters.initial_filter import InitialFilter


def create_test_db() -> str:
    """
    创建临时文件 SQLite 测试数据库，写入 Mock 数据。
    返回临时文件路径 (调用方负责清理)。
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 创建表结构 (与文档一致)
    cursor.execute("""
        CREATE TABLE klines (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            ts INTEGER NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL
        )
    """)
    cursor.execute("CREATE INDEX idx_k ON klines(symbol, interval, ts)")

    cursor.execute("""
        CREATE TABLE market_stats (
            symbol TEXT PRIMARY KEY,
            vol_24h_usdt REAL,
            high_24h REAL,
            low_24h REAL,
            close REAL,
            kline_count INTEGER,
            atr_14 REAL,
            kurtosis REAL,
            first_ts INTEGER
        )
    """)

    now_ms = int(time.time() * 1000)

    # ── BTC/USDT: 正常数据 (Vol 500 万, Count 130k, Price 60000) ──
    _insert_klines(conn, "BTC/USDT", 130_000, 60000, now_ms)
    cursor.execute(
        "INSERT INTO market_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("BTC/USDT", 5_000_000, 61000, 59000, 60000, 130_000, 500, 2.0, now_ms - 90 * 86400 * 1000)
    )

    # ── USDC/USDT: 稳定币 (应被剔除) ──
    _insert_klines(conn, "USDC/USDT", 130_000, 1.0, now_ms)
    cursor.execute(
        "INSERT INTO market_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("USDC/USDT", 5_000_000, 1.01, 0.99, 1.0, 130_000, 10, 0.5, now_ms - 90 * 86400 * 1000)
    )

    # ── DEAD/USDT: 僵尸盘 (波幅 < 0.15%) ──
    _insert_klines(conn, "DEAD/USDT", 130_000, 1.0, now_ms, high=1.0, low=0.999)
    cursor.execute(
        "INSERT INTO market_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("DEAD/USDT", 5_000_000, 1.0, 0.999, 1.0, 130_000, 10, 0.5, now_ms - 90 * 86400 * 1000)
    )

    # ── NEWB/USDT: 新币 (Count 5000) ──
    _insert_klines(conn, "NEWB/USDT", 5000, 100, now_ms)
    cursor.execute(
        "INSERT INTO market_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("NEWB/USDT", 5_000_000, 105, 95, 100, 5000, 500, 2.0, now_ms - 3 * 86400 * 1000)
    )

    # ── GAP/USDT: 缺失数据 (Count 50000 < 120k) ──
    _insert_klines(conn, "GAP/USDT", 50000, 50, now_ms)
    cursor.execute(
        "INSERT INTO market_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("GAP/USDT", 5_000_000, 55, 45, 50, 50000, 500, 2.0, now_ms - 90 * 86400 * 1000)
    )

    # ── LOWVOL/USDT: 低流动性 (Vol < 200 万) ──
    _insert_klines(conn, "LOWVOL/USDT", 130_000, 10, now_ms)
    cursor.execute(
        "INSERT INTO market_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("LOWVOL/USDT", 500_000, 11, 9, 10, 130_000, 500, 2.0, now_ms - 90 * 86400 * 1000)
    )

    # ── NANTEST/USDT: 含脏数据 (close=0, volume=-1, volume=0) ──
    _insert_klines_with_dirty(conn, "NANTEST/USDT", now_ms)
    cursor.execute(
        "INSERT INTO market_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("NANTEST/USDT", 5_000_000, 210, 190, 200, 130_000, 500, 2.0, now_ms - 90 * 86400 * 1000)
    )

    conn.commit()
    conn.close()
    return db_path


def _insert_klines(conn, symbol, count, base_price, now_ms, high=None, low=None):
    """批量插入 K 线数据 (优化: 使用 executemany)"""
    cursor = conn.cursor()
    interval = 60_000
    rows = []
    for i in range(count):
        ts = now_ms - (count - i) * interval
        price = base_price + np.sin(i / 100) * 100
        h = high if high is not None else price + 30
        l = low if low is not None else price - 30
        vol = 500
        rows.append((symbol, "1m", ts, price, h, l, price, vol))
        if len(rows) >= 10000:
            cursor.executemany("INSERT INTO klines VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            rows = []
    if rows:
        cursor.executemany("INSERT INTO klines VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _insert_klines_with_dirty(conn, symbol, now_ms):
    """
    插入含脏数据的 K 线。
    脏数据放在最近 5000 根以内 (i 接近 count)，确保 build_hot_pool(limit=5000) 能读到。
    """
    cursor = conn.cursor()
    interval = 60_000
    count = 130_000
    rows = []
    for i in range(count):
        ts = now_ms - (count - i) * interval
        # 脏数据放在最近的位置 (i = 129970, 129980, 129990)，
        # 对应 DESC 查询的第 20, 10, 30 行，在 limit=5000 范围内
        if i == 129970:
            close = 200
            vol = 0  # volume == 0 -> 应标记 Mask
        elif i == 129980:
            close = 0
            vol = 100  # close <= 0 -> 应剔除
        elif i == 129990:
            close = 200
            vol = -1  # volume < 0 -> 应剔除
        else:
            close = 200 + np.sin(i / 100) * 10
            vol = 500
        h = close + 5
        l = close - 5
        rows.append((symbol, "1m", ts, close, h, l, close, vol))
        if len(rows) >= 10000:
            cursor.executemany("INSERT INTO klines VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            rows = []
    if rows:
        cursor.executemany("INSERT INTO klines VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


class TestDataEngine(unittest.TestCase):
    """DataEngine 单元测试"""

    @classmethod
    def setUpClass(cls):
        cls.db_path = create_test_db()
        cls.engine = DataEngine(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()
        try:
            os.unlink(cls.db_path)
        except OSError:
            pass

    def test_wal_mode(self):
        """测试 1: 检查连接建立后 journal_mode 是否为 WAL"""
        cursor = self.engine.conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        self.assertEqual(mode, "wal", f"Expected WAL mode, got {mode}")

    def test_load_market_stats(self):
        """测试 load_market_stats 返回正确数据"""
        stats = self.engine.load_market_stats(min_vol=2_000_000)
        # BTC, USDC, DEAD, NANTEST 应该通过 (Vol >= 2M)
        # LOWVOL 应被过滤 (Vol < 2M)
        self.assertIn("BTC/USDT", stats)
        self.assertNotIn("LOWVOL/USDT", stats)
        self.assertGreaterEqual(stats["BTC/USDT"]["vol_24h_usdt"], 2_000_000)

    def test_hot_pool_dtype(self):
        """测试 2: 检查返回的 numpy 数组 dtype 是否为 float32"""
        pool = self.engine.build_hot_pool(["BTC/USDT"], limit=500)
        self.assertIn("BTC/USDT", pool)
        data = pool["BTC/USDT"]
        self.assertEqual(data["close"].dtype, np.float32, f"Expected float32, got {data['close'].dtype}")
        self.assertEqual(data["log_close"].dtype, np.float32)
        self.assertEqual(data["volume"].dtype, np.float32)
        self.assertEqual(data["high"].dtype, np.float32)
        self.assertEqual(data["low"].dtype, np.float32)

    def test_log_calc(self):
        """测试 3: 验证 log_close 是否等于 np.log(close)"""
        pool = self.engine.build_hot_pool(["BTC/USDT"], limit=500)
        data = pool["BTC/USDT"]
        expected = np.log(data["close"])
        np.testing.assert_array_almost_equal(data["log_close"], expected, decimal=5)

    def test_cleaning_nan(self):
        """测试 4: 注入含 NaN 和 0 的数据，验证 Mask 是否正确应用"""
        pool = self.engine.build_hot_pool(["NANTEST/USDT"], limit=5000)
        self.assertIn("NANTEST/USDT", pool)
        data = pool["NANTEST/USDT"]

        # close <= 0 和 volume < 0 的行应被剔除
        self.assertTrue(np.all(data["close"] > 0), "close 不应包含 <= 0 的值")
        self.assertTrue(np.all(data["volume"] >= 0), "volume 不应包含 < 0 的值")

        # 不应有 NaN
        self.assertFalse(np.any(np.isnan(data["close"])), "close 不应包含 NaN")
        self.assertFalse(np.any(np.isnan(data["volume"])), "volume 不应包含 NaN")

        # zero_vol_mask 应包含 volume == 0 的标记
        self.assertTrue(np.any(data["zero_vol_mask"]), "应有 volume == 0 的 Mask 标记")

    def test_build_hot_pool_empty(self):
        """测试空输入返回空字典"""
        pool = self.engine.build_hot_pool([])
        self.assertEqual(pool, {})

    def test_get_all_symbols(self):
        """测试获取所有 symbol"""
        symbols = self.engine.get_all_symbols(interval="1m")
        self.assertIn("BTC/USDT", symbols)
        self.assertIn("USDC/USDT", symbols)
        self.assertIn("DEAD/USDT", symbols)


class TestInitialFilter(unittest.TestCase):
    """InitialFilter 单元测试"""

    @classmethod
    def setUpClass(cls):
        cls.db_path = create_test_db()
        cls.engine = DataEngine(cls.db_path)
        cls.filter = InitialFilter()

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()
        try:
            os.unlink(cls.db_path)
        except OSError:
            pass

    def test_filter_stablecoin(self):
        """测试 5: 验证 USDC/USDT 被剔除 (稳定币黑名单)"""
        all_symbols = self.engine.get_all_symbols()
        stats = self.engine.load_market_stats(min_vol=0)
        qualified = self.filter.run(all_symbols, stats)
        self.assertNotIn("USDC/USDT", qualified, "USDC/USDT 应被稳定币过滤器剔除")

    def test_filter_liquidity(self):
        """测试 6: 注入低量币，验证被剔除"""
        all_symbols = self.engine.get_all_symbols()
        stats = self.engine.load_market_stats(min_vol=0)
        qualified = self.filter.run(all_symbols, stats)
        self.assertNotIn("LOWVOL/USDT", qualified, "LOWVOL/USDT 应被流动性过滤器剔除")

    def test_filter_zombie(self):
        """测试 7: 注入 DEAD/USDT，验证被剔除 (波幅 < 0.15%)"""
        all_symbols = self.engine.get_all_symbols()
        stats = self.engine.load_market_stats(min_vol=0)
        qualified = self.filter.run(all_symbols, stats)
        self.assertNotIn("DEAD/USDT", qualified, "DEAD/USDT 应被僵尸盘过滤器剔除")

    def test_filter_new_coin(self):
        """测试: NEWB/USDT (Count < 10080) 应被新币冷却期过滤器剔除"""
        all_symbols = self.engine.get_all_symbols()
        stats = self.engine.load_market_stats(min_vol=0)
        qualified = self.filter.run(all_symbols, stats)
        self.assertNotIn("NEWB/USDT", qualified, "NEWB/USDT 应被新币冷却期过滤器剔除")

    def test_filter_incomplete_data(self):
        """测试: GAP/USDT (Count < 120000) 应被数据完整度过滤器剔除"""
        all_symbols = self.engine.get_all_symbols()
        stats = self.engine.load_market_stats(min_vol=0)
        qualified = self.filter.run(all_symbols, stats)
        self.assertNotIn("GAP/USDT", qualified, "GAP/USDT 应被数据完整度过滤器剔除")

    def test_btc_passes(self):
        """测试: BTC/USDT (正常数据) 应通过所有过滤器"""
        all_symbols = self.engine.get_all_symbols()
        stats = self.engine.load_market_stats(min_vol=0)
        qualified = self.filter.run(all_symbols, stats)
        self.assertIn("BTC/USDT", qualified, "BTC/USDT 应通过所有过滤器")

    def test_filter_pipeline_order(self):
        """测试: 过滤器按顺序执行，稳定币先于流动性检查"""
        filter_instance = InitialFilter()
        stats = {"vol_24h_usdt": 100, "close": 1, "kline_count": 200000}
        result = filter_instance._check("USDT/USDT", stats)
        self.assertFalse(result, "USDT 应在过滤器 1 (稳定币) 被剔除")


if __name__ == "__main__":
    unittest.main(verbosity=2)
