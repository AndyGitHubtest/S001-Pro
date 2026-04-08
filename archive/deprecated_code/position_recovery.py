#!/usr/bin/env python3
"""
仓位恢复管理器 - 服务重启后恢复持仓状态

功能:
  1. 定期持久化持仓状态到磁盘
  2. 启动时读取并恢复未平仓订单
  3. 与交易所同步验证仓位
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger("PositionRecovery")


@dataclass
class PositionState:
    """持仓状态"""
    pair: str
    symbol_a: str
    symbol_b: str
    direction: int  # 1 = Long Spread, -1 = Short Spread
    quantity_a: float
    quantity_b: float
    entry_price_a: float
    entry_price_b: float
    entry_z: float
    entry_time: str
    current_layer: int  # 当前加仓层级 0-2
    status: str  # IDLE / IN_POSITION / EXITING


class PositionRecoveryManager:
    """
    仓位恢复管理器

    职责:
      - 定期保存持仓状态 (每30秒或状态变更时)
      - 启动时从磁盘恢复
      - 与交易所对账验证
    """

    def __init__(self, state_path: str = "data/position_state.json"):
        self.state_path = state_path
        self._positions: Dict[str, PositionState] = {}
        self._last_save = 0
        self._save_interval = 30  # 秒

    def update_position(self, position: PositionState):
        """更新持仓状态"""
        self._positions[position.pair] = position
        self._save_if_needed()

    def remove_position(self, pair: str):
        """移除持仓 (平仓后)"""
        if pair in self._positions:
            del self._positions[pair]
            self._save_if_needed()

    def _save_if_needed(self):
        """必要时保存到磁盘"""
        import time
        now = time.time()
        if now - self._last_save > self._save_interval:
            self.save_state()
            self._last_save = now

    def save_state(self):
        """立即保存状态到磁盘"""
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            data = {
                "timestamp": datetime.now().isoformat(),
                "positions": {k: asdict(v) for k, v in self._positions.items()}
            }
            # 原子写入
            tmp_path = self.state_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.state_path)
            logger.debug(f"PositionRecovery: 已保存 {len(self._positions)} 个持仓")
        except Exception as e:
            logger.error(f"PositionRecovery: 保存失败 - {e}")

    def load_state(self) -> Dict[str, PositionState]:
        """从磁盘加载状态"""
        try:
            if not os.path.exists(self.state_path):
                return {}

            with open(self.state_path, "r") as f:
                data = json.load(f)

            positions = {}
            for pair, pos_data in data.get("positions", {}).items():
                positions[pair] = PositionState(**pos_data)

            self._positions = positions
            logger.info(f"PositionRecovery: 已加载 {len(positions)} 个历史持仓")
            return positions

        except Exception as e:
            logger.error(f"PositionRecovery: 加载失败 - {e}")
            return {}

    async def sync_with_exchange(self, exchange) -> List[PositionState]:
        """
        与交易所同步验证持仓

        Returns:
            需要恢复的持仓列表 (本地有但交易所无，或数量不一致)
        """
        try:
            # 获取交易所持仓
            exchange_positions = await exchange.fetch_positions()
            exchange_by_symbol = {
                p["symbol"]: p for p in exchange_positions
                if float(p.get("contracts", 0)) != 0
            }

            to_recover = []

            for pair, local_pos in self._positions.items():
                sym_a = local_pos.symbol_a.replace("/", "")
                sym_b = local_pos.symbol_b.replace("/", "")

                pos_a = exchange_by_symbol.get(sym_a)
                pos_b = exchange_by_symbol.get(sym_b)

                if not pos_a or not pos_b:
                    # 交易所没有持仓，需要恢复
                    logger.warning(f"PositionRecovery: {pair} 本地有持仓但交易所无记录")
                    to_recover.append(local_pos)
                    continue

                # 检查数量是否一致
                contracts_a = float(pos_a.get("contracts", 0))
                contracts_b = float(pos_b.get("contracts", 0))

                if (abs(contracts_a - local_pos.quantity_a) > 0.01 or
                    abs(contracts_b - local_pos.quantity_b) > 0.01):
                    logger.warning(f"PositionRecovery: {pair} 持仓数量不一致")
                    to_recover.append(local_pos)

            return to_recover

        except Exception as e:
            logger.error(f"PositionRecovery: 同步失败 - {e}")
            return []

    def clear_state(self):
        """清空所有状态 (谨慎使用)"""
        self._positions = {}
        try:
            if os.path.exists(self.state_path):
                os.remove(self.state_path)
            logger.info("PositionRecovery: 已清空状态")
        except Exception as e:
            logger.error(f"PositionRecovery: 清空失败 - {e}")


async def recover_positions_on_startup(exchange, config: Dict) -> bool:
    """
    启动时恢复持仓的便捷函数

    Returns:
        True: 恢复成功或无需恢复
        False: 有需要人工介入的异常
    """
    recovery = PositionRecoveryManager()

    # 加载历史持仓
    saved_positions = recovery.load_state()
    if not saved_positions:
        logger.info("PositionRecovery: 无历史持仓需要恢复")
        return True

    # 与交易所对账
    to_recover = await recovery.sync_with_exchange(exchange)

    if not to_recover:
        logger.info("PositionRecovery: 所有持仓已与交易所同步")
        return True

    # 有需要恢复的持仓
    logger.warning(f"PositionRecovery: 发现 {len(to_recover)} 个持仓需要恢复")

    for pos in to_recover:
        logger.warning(f"  - {pos.pair}: {pos.quantity_a}/{pos.quantity_b} "
                      f"(层级: {pos.current_layer}, 状态: {pos.status})")

    # 通知用户
    notifier = config.get("notifier")
    if notifier:
        pairs_text = "\n".join([f"• {p.pair}" for p in to_recover])
        await notifier.send_warning(
            f"服务重启后发现未恢复持仓:\n{pairs_text}\n\n"
            f"请检查这些持仓是否需要人工处理。"
        )

    # TODO: 实现自动恢复逻辑 (根据策略判断是否重新开仓)
    # 当前仅记录，不自动开仓 (安全第一)

    return True
