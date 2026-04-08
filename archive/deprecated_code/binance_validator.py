"""
币安合约市场验证器 - P0 防护层

防止扫描器选出币安不支持的币对
"""
import logging
from typing import List, Dict, Set

logger = logging.getLogger("BinanceValidator")


class BinanceFuturesValidator:
    """
    验证币对是否在币安合约市场存在
    """

    def __init__(self):
        self._client = None
        self._futures_symbols: Set[str] = set()
        self._initialized = False

    def _init_client(self):
        """懒初始化"""
        if self._initialized:
            return

        try:
            import ccxt
            # 使用公开API，不需要认证
            self._client = ccxt.binance({
                'options': {'defaultType': 'swap'}
            })
            self._client.load_markets()

            # 提取所有USDT永续合约
            for symbol in self._client.markets.keys():
                if symbol.endswith(':USDT'):
                    # 转换为标准格式 XXX/USDT
                    base = symbol.replace(':USDT', '')
                    self._futures_symbols.add(base)

            self._initialized = True
            logger.info(f"BinanceValidator: 加载 {len(self._futures_symbols)} 个合约币种")

        except Exception as e:
            logger.error(f"BinanceValidator: 初始化失败 - {e}")
            # 初始化失败时允许通过（避免阻塞扫描）
            self._initialized = True

    def is_valid_symbol(self, symbol: str) -> bool:
        """
        检查单个币种是否在币安合约存在
        symbol 格式: XXX/USDT
        """
        self._init_client()

        if not self._futures_symbols:
            # 如果无法获取市场数据，默认通过
            return True

        return symbol in self._futures_symbols

    def filter_valid_pairs(self, pairs: List[Dict]) -> List[Dict]:
        """
        过滤币对列表，只保留币安合约支持的
        """
        self._init_client()

        if not self._futures_symbols:
            logger.warning("BinanceValidator: 无法验证，返回原始列表")
            return pairs

        valid_pairs = []
        invalid_symbols = set()

        for pair in pairs:
            sym_a = pair.get('symbol_a', '')
            sym_b = pair.get('symbol_b', '')

            valid_a = sym_a in self._futures_symbols
            valid_b = sym_b in self._futures_symbols

            if valid_a and valid_b:
                valid_pairs.append(pair)
            else:
                if not valid_a:
                    invalid_symbols.add(sym_a)
                if not valid_b:
                    invalid_symbols.add(sym_b)

        if invalid_symbols:
            logger.warning(f"BinanceValidator: 过滤 {len(pairs) - len(valid_pairs)} 个无效币对")
            logger.warning(f"BinanceValidator: 无效币种: {invalid_symbols}")

        return valid_pairs

    def validate_before_trade(self, symbol_a: str, symbol_b: str) -> tuple:
        """
        交易前验证
        返回: (是否可交易, 错误信息)
        """
        self._init_client()

        if not self._futures_symbols:
            # 无法验证时默认通过
            return True, ""

        valid_a = symbol_a in self._futures_symbols
        valid_b = symbol_b in self._futures_symbols

        if valid_a and valid_b:
            return True, ""

        errors = []
        if not valid_a:
            errors.append(f"{symbol_a} 不在币安合约市场")
        if not valid_b:
            errors.append(f"{symbol_b} 不在币安合约市场")

        return False, "; ".join(errors)


# 全局单例
_validator = None


def get_validator() -> BinanceFuturesValidator:
    """获取验证器单例"""
    global _validator
    if _validator is None:
        _validator = BinanceFuturesValidator()
    return _validator
