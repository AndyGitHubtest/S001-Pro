#!/usr/bin/env python3
"""
币安实时扫描器 - 直接从币安API获取数据，不依赖本地数据库

特性:
1. 直接从币安获取 24h 成交量和 K线数据
2. 只扫描流动性前 150 的币种
3. 自动过滤币安已下架的币
"""

import asyncio
import json
import ccxt
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class BinanceLiveScanner:
    """币安实时扫描器"""

    def __init__(self, top_n: int = 150):
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        self.top_n = top_n
        self.valid_symbols: List[str] = []

    def fetch_top_symbols(self) -> List[str]:
        """
        获取币安 USDT 永续合约中成交量前 N 的币种
        """
        logger.info("正在获取币安合约 24h 成交量...")

        # 获取所有合约的 24h 统计数据
        tickers = self.exchange.fetch_tickers()

        # 筛选 USDT 永续合约并计算成交量
        volumes = []
        for symbol, ticker in tickers.items():
            if not symbol.endswith(':USDT'):
                continue

            # 转换为标准格式
            base_symbol = symbol.replace(':USDT', '')
            vol = ticker.get('quoteVolume', 0) or 0

            if vol > 0:
                volumes.append((base_symbol, vol))

        # 按成交量排序，取前 N
        volumes.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [s for s, v in volumes[:self.top_n]]

        logger.info(f"币安合约总数: {len(volumes)}, 取前 {self.top_n} 个")
        logger.info(f"成交量最高: {volumes[0][0]} ({volumes[0][1]/1e6:.1f}M USDT)")
        logger.info(f"成交量最低: {volumes[self.top_n-1][0]} ({volumes[self.top_n-1][1]/1e6:.1f}M USDT)")

        return top_symbols

    def fetch_ohlcv(self, symbol: str, limit: int = 5000) -> Optional[Dict]:
        """
        获取单个币种的 OHLCV 数据
        返回: {'close': np.array, 'volume': np.array, 'atr': float}
        """
        try:
            # 币安合约格式
            contract_symbol = symbol.replace('/USDT', '/USDT:USDT')

            # 获取 1m K线 (约 3.5 天)
            ohlcv = self.exchange.fetch_ohlcv(contract_symbol, '1m', limit=limit)

            if len(ohlcv) < 1000:  # 数据不足
                return None

            closes = np.array([c[4] for c in ohlcv], dtype=np.float32)
            volumes = np.array([c[5] for c in ohlcv], dtype=np.float32)

            # 计算 ATR (简化版)
            highs = np.array([c[2] for c in ohlcv], dtype=np.float32)
            lows = np.array([c[3] for c in ohlcv], dtype=np.float32)
            atr = np.mean(highs[-14:] - lows[-14:])

            return {
                'close': closes,
                'volume': volumes,
                'atr': atr,
                'last_close': closes[-1],
                'kline_count': len(closes)
            }

        except Exception as e:
            logger.warning(f"获取 {symbol} 数据失败: {e}")
            return None

    def fetch_all_data(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        批量获取所有币种的数据
        """
        data = {}

        for i, symbol in enumerate(symbols, 1):
            result = self.fetch_ohlcv(symbol)
            if result:
                data[symbol] = result

            if i % 10 == 0:
                logger.info(f"已获取 {i}/{len(symbols)} 个币种数据")

            # 限速保护
            # ccxt 内部有 rate limit，这里额外加点延迟
            import time
            time.sleep(0.1)

        logger.info(f"成功获取 {len(data)}/{len(symbols)} 个币种数据")
        return data

    def run(self) -> List[str]:
        """
        执行完整扫描流程
        返回: 通过筛选的币种列表
        """
        logger.info("=" * 60)
        logger.info("币安实时扫描器启动")
        logger.info("=" * 60)

        # Step 1: 获取 Top N 币种
        symbols = self.fetch_top_symbols()

        # Step 2: 获取 K 线数据
        data = self.fetch_all_data(symbols)

        # Step 3: 应用筛选条件
        qualified = []
        for symbol, info in data.items():
            close = info['last_close']
            atr = info['atr']
            klines = info['kline_count']

            # 筛选条件
            if close < 0.0005:  # 价格过低
                continue
            if klines < 1000:  # K线不足
                continue
            if close > 0 and (atr / close) > 0.12:  # 波动过大
                continue

            qualified.append(symbol)

        logger.info(f"通过筛选: {len(qualified)}/{len(symbols)} 个币种")
        logger.info("=" * 60)

        return qualified


def main():
    scanner = BinanceLiveScanner(top_n=150)
    symbols = scanner.run()

    # 保存结果
    output = {
        "symbols": symbols,
        "count": len(symbols),
        "generated_at": datetime.now().isoformat(),
        "source": "binance_futures_live"
    }

    with open('/tmp/binance_qualified_symbols.json', 'w') as f:
        json.dump(output, f, indent=2)

    logger.info(f"结果已保存到 /tmp/binance_qualified_symbols.json")


if __name__ == "__main__":
    main()
