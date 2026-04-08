#!/usr/bin/env python3
"""
币安合约专用 K 线同步工具 — 只下载币安 USDT 永续合约数据
"""

import os
import sys
import sqlite3
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone
import ccxt
import logging

# ── 配置 ──
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "klines.db"
INTERVAL = "1m"
HISTORY_DAYS = 90  # 下载90天历史
BATCH_SIZE = 1000  # 每次下载1000条
RATE_LIMIT_DELAY = 0.5  # 币安API限速保护

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class BinanceFuturesSync:
    """币安合约数据同步器 - 只同步币安当前支持的合约"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.exchange = None
        self.conn = None
        self.valid_symbols = set()  # 币安当前支持的合约列表

    async def initialize(self):
        """初始化币安连接并获取有效合约列表"""
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # USDT永续合约
            }
        })

        # 获取币安当前所有USDT永续合约
        logger.info("正在获取币安合约市场列表...")
        markets = await asyncio.to_thread(self.exchange.load_markets)

        self.valid_symbols = {
            symbol.replace(':USDT', '')  # 转换为标准格式 XXX/USDT
            for symbol, market in markets.items()
            if market.get('quote') == 'USDT'
            and market.get('swap')  # 永续合约
            and market.get('active', True)  # 正在交易的
        }

        logger.info(f"币安当前有效合约: {len(self.valid_symbols)} 个")

        # 初始化数据库
        self.conn = sqlite3.connect(self.db_path)
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS klines (
                ts INTEGER,
                symbol TEXT,
                interval TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (ts, symbol, interval)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_symbol_interval ON klines(symbol, interval)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON klines(ts)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                symbol TEXT PRIMARY KEY,
                last_sync_ts INTEGER,
                record_count INTEGER,
                updated_at TEXT
            )
        """)
        self.conn.commit()

    def get_db_symbols(self) -> list:
        """获取数据库中已有的币种"""
        c = self.conn.cursor()
        c.execute("SELECT DISTINCT symbol FROM klines WHERE interval=?", (INTERVAL,))
        return [row[0] for row in c.fetchall()]

    async def download_symbol(self, symbol: str) -> int:
        """
        下载单个币种的90天历史数据
        返回: 新增记录数
        """
        if symbol not in self.valid_symbols:
            logger.warning(f"跳过无效币种: {symbol}")
            return 0

        # 计算起始时间 (90天前)
        since = int((datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).timestamp() * 1000)

        total_inserted = 0
        retry_count = 0
        max_retries = 3

        while since < int(datetime.now(timezone.utc).timestamp() * 1000):
            try:
                # 下载K线数据
                ohlcv = await asyncio.to_thread(
                    self.exchange.fetch_ohlcv,
                    symbol.replace('/USDT', '/USDT:USDT'),  # 合约格式
                    INTERVAL,
                    since,
                    limit=BATCH_SIZE
                )

                if not ohlcv:
                    break

                # 插入数据库
                c = self.conn.cursor()
                inserted = 0
                for candle in ohlcv:
                    ts, open_p, high, low, close, volume = candle
                    try:
                        c.execute("""
                            INSERT OR IGNORE INTO klines (ts, symbol, interval, open, high, low, close, volume)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (ts, symbol, INTERVAL, open_p, high, low, close, volume))
                        if c.rowcount > 0:
                            inserted += 1
                    except sqlite3.IntegrityError:
                        pass  # 重复数据，忽略

                self.conn.commit()
                total_inserted += inserted

                # 更新下次查询的起始时间
                since = ohlcv[-1][0] + 60000  # 最后一条时间戳 + 1分钟

                # 限速保护
                await asyncio.sleep(RATE_LIMIT_DELAY)
                retry_count = 0  # 重置重试计数

            except ccxt.NetworkError as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"{symbol} 网络错误超过{max_retries}次: {e}")
                    break
                logger.warning(f"{symbol} 网络错误，{3}秒后重试...")
                await asyncio.sleep(3)

            except Exception as e:
                logger.error(f"{symbol} 下载失败: {e}")
                break

        # 更新元数据
        if total_inserted > 0:
            c = self.conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO sync_metadata (symbol, last_sync_ts, record_count, updated_at)
                VALUES (?, ?, COALESCE((SELECT record_count FROM sync_metadata WHERE symbol=?), 0) + ?, ?)
            """, (symbol, since, symbol, total_inserted, datetime.now().isoformat()))
            self.conn.commit()

        return total_inserted

    async def sync_all(self, symbols: list = None):
        """
        同步所有币种
        如果不指定币种，则同步币安所有有效合约
        """
        if symbols is None:
            # 只下载币安当前支持的合约
            symbols = sorted(self.valid_symbols)
            logger.info(f"将下载 {len(symbols)} 个币安合约币种")

        # 过滤无效币种
        valid_symbols = [s for s in symbols if s in self.valid_symbols]
        skipped = len(symbols) - len(valid_symbols)
        if skipped > 0:
            logger.warning(f"跳过 {skipped} 个币安不支持的币种")

        logger.info(f"开始下载 {len(valid_symbols)} 个币种的历史数据...")

        for i, symbol in enumerate(valid_symbols, 1):
            count = await self.download_symbol(symbol)
            logger.info(f"[{i}/{len(valid_symbols)}] {symbol}: +{count} 条")

        logger.info("同步完成")

    def close(self):
        if self.conn:
            self.conn.close()


async def main():
    """主函数"""
    db_path = sys.argv[1] if len(sys.argv) > 1 else str(DB_PATH)

    logger.info("=" * 60)
    logger.info("币安合约数据同步工具启动")
    logger.info("=" * 60)
    logger.info(f"数据库路径: {db_path}")
    logger.info(f"下载周期: {HISTORY_DAYS} 天")
    logger.info(f"时间周期: {INTERVAL}")
    logger.info("=" * 60)

    sync = BinanceFuturesSync(db_path)
    await sync.initialize()

    try:
        await sync.sync_all()
    finally:
        sync.close()

    logger.info("=" * 60)
    logger.info("数据同步完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
