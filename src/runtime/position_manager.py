"""持仓管理模块"""
import logging
from typing import Dict
from src.runtime.position_state import PositionState, STATE_IN_POSITION, STATE_IDLE
from src.constants import DEFAULT_POSITION_SIZE_PCT, DEFAULT_Z_ENTRY

logger = logging.getLogger("PositionManager")

class PositionManager:
    def __init__(self, runtime):
        self.runtime = runtime
        self.exchange_api = getattr(runtime, 'exchange_api', None)
        self.positions = runtime.positions

    async def reconcile_positions(self) -> None:
        if not self.exchange_api:
            return
        try:
            exchange_positions = await self.exchange_api.get_positions()
        except Exception as e:
            logger.error(f"获取交易所持仓失败: {e}")
            return

        ex_map = {pos.get("symbol"): pos for pos in exchange_positions if float(pos.get("contracts", 0)) != 0}
        ex_keys = set(ex_map.keys())
        local_syms = set()
        for ps in self.positions.values():
            if ps.state != STATE_IDLE:
                local_syms.add(ps.symbol_a)
                local_syms.add(ps.symbol_b)

        for sym in ex_keys - local_syms:
            await self._handle_ghost_position(sym, ex_map[sym])
        for sym in local_syms - ex_keys:
            await self._handle_orphan_position(sym)

    async def _handle_ghost_position(self, symbol: str, position_data: Dict) -> None:
        for pk, ps in self.positions.items():
            if ps.symbol_a == symbol or ps.symbol_b == symbol:
                ps.state = STATE_IN_POSITION
                ps.position_size_pct = DEFAULT_POSITION_SIZE_PCT
                ps.direction = 1 if position_data.get("side") == "long" else -1
                ps.entry_z = ps.pair_config.get("params", {}).get("z_entry", DEFAULT_Z_ENTRY)
                logger.info(f"GHOST {pk} taken over")
                break

    async def _handle_orphan_position(self, symbol: str) -> None:
        for pk, ps in self.positions.items():
            if ps.symbol_a == symbol or ps.symbol_b == symbol:
                ps.state = STATE_IDLE
                ps.direction = 0
                ps.position_size_pct = 0.0
                logger.info(f"ORPHAN {pk} cleaned up")
                break
