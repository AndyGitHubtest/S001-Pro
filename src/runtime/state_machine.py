"""状态机模块"""
import logging
from src.runtime.position_state import PositionState, STATE_IDLE, STATE_SCALING_IN, STATE_IN_POSITION, STATE_EXITED
from src.constants import DEFAULT_Z_ENTRY, POSITION_COMPLETE_THRESHOLD, POSITION_EMPTY_THRESHOLD

logger = logging.getLogger("StateMachine")

class StateMachine:
    def __init__(self, runtime):
        self.runtime = runtime
        self.order_executor = getattr(runtime, 'order_executor', None)
        self.risk_guard = getattr(runtime, 'risk_guard', None)

    async def on_signal(self, ps: PositionState, pair_key: str, z: float) -> None:
        params = ps.pair_config.get("params", {})
        execution = ps.pair_config.get("execution", {})
        abs_z = abs(z)

        stop_loss = execution.get("stop_loss", {})
        stop_trigger = stop_loss.get("trigger_z", 999)
        if abs_z >= stop_trigger and ps.state not in (STATE_IDLE, STATE_EXITED):
            if self.order_executor:
                await self.order_executor.execute_stop_loss(ps)
            return

        if ps.state == STATE_IDLE:
            await self._on_idle(ps, pair_key, z, params, execution)
        elif ps.state == STATE_SCALING_IN:
            await self._on_scaling_in(ps, pair_key, z, execution)
        elif ps.state == STATE_IN_POSITION:
            await self._on_in_position(ps, pair_key, z, execution)

    async def _on_idle(self, ps, pair_key, z, params, execution):
        if self.risk_guard and not self.risk_guard.check_kill_switch():
            return
        z_entry = params.get("z_entry", DEFAULT_Z_ENTRY)
        scale_in = execution.get("scale_in", [])
        if z >= z_entry:
            ps.direction = -1
            ps.state = STATE_SCALING_IN
            if self.order_executor:
                await self.order_executor.execute_scale_in(ps, scale_in, z)
            await self.runtime._save_state()
        elif z <= -z_entry:
            ps.direction = 1
            ps.state = STATE_SCALING_IN
            if self.order_executor:
                await self.order_executor.execute_scale_in(ps, scale_in, z)
            await self.runtime._save_state()

    async def _on_scaling_in(self, ps, pair_key, z, execution):
        if ps.position_size_pct >= POSITION_COMPLETE_THRESHOLD:
            ps.state = STATE_IN_POSITION

    async def _on_in_position(self, ps, pair_key, z, execution):
        """持仓中状态处理 - 止盈/平仓逻辑"""
        params = ps.pair_config.get("params", {})
        z_exit = params.get("z_exit", 0.5)
        abs_z = abs(z)

        # ═══════════════════════════════════════════════════
        # 止盈逻辑: Z-Score 回归时触发分层止盈
        # ═══════════════════════════════════════════════════
        # 根据 direction 判断止盈方向:
        # - direction=1 (多A空B): Z从负值回归，当 Z >= -z_exit*0.6 时止盈
        # - direction=-1 (空A多B): Z从正值回归，当 Z <= z_exit*0.6 时止盈

        scale_out_triggers = execution.get("scale_out", [])

        # 找到当前应触发的止盈档位
        current_layer = ps.scale_out_layer
        if current_layer < len(scale_out_triggers):
            trigger = scale_out_triggers[current_layer]
            trigger_z = trigger.get("trigger_z", z_exit)

            # 判断止盈条件
            should_scale_out = False
            if ps.direction == 1:  # 多A空B，Z从负值回归
                should_scale_out = z >= -trigger_z
            elif ps.direction == -1:  # 空A多B，Z从正值回归
                should_scale_out = z <= trigger_z

            if should_scale_out:
                logger.info(f"[TakeProfit] {pair_key} 触发止盈档位{current_layer+1}: |Z|={abs_z:.2f} <= {trigger_z}")
                if self.order_executor:
                    await self.order_executor.execute_scale_out(ps, [trigger], z)
                await self.runtime._save_state()
                return

        # 检查是否完全平仓
        if ps.position_size_pct <= POSITION_EMPTY_THRESHOLD:
            ps.state = STATE_EXITED
            await self.runtime._save_state()
