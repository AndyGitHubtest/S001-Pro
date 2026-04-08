"""
Runtime 核心模块 - 简化版主入口
协调各子模块，提供统一接口
"""

import json
import os
import logging
import asyncio
from typing import Dict, Optional, Any
from pathlib import Path

from src.runtime.position_state import PositionState
from src.runtime.state_machine import StateMachine
from src.runtime.order_executor import OrderExecutor
from src.runtime.position_manager import PositionManager
from src.runtime.risk_guard import RiskGuard
from src.constants import DEFAULT_PAIRS_FILE, DEFAULT_STATE_FILE

logger = logging.getLogger("Runtime")


class Runtime:
    """
    S001-Pro 实盘运行时 - 模块化重构版
    
    职责:
    1. 初始化各子模块
    2. 管理配对配置加载
    3. 处理外部信号输入
    4. 状态持久化
    5. 价格缓存更新
    
    子模块分工:
    - StateMachine: 状态转换逻辑
    - OrderExecutor: 订单执行
    - PositionManager: 持仓对账
    - RiskGuard: 风险控制
    """

    def __init__(
        self,
        config_manager: Any,
        persistence: Optional[Any] = None,
        exchange_api: Optional[Any] = None,
        notifier: Optional[Any] = None,
        monitor: Optional[Any] = None,
        state_file: str = DEFAULT_STATE_FILE
    ):
        self.config_manager = config_manager
        self.persistence = persistence
        self.exchange_api = exchange_api
        self.notifier = notifier
        self.monitor = monitor
        self.state_file = Path(state_file)
        self.pairs_file = Path(DEFAULT_PAIRS_FILE)

        # 持仓状态映射 {pair_key: PositionState}
        self.positions: Dict[str, PositionState] = {}

        # 价格缓存 {symbol: price}
        self._price_cache: Dict[str, float] = {}

        # 最后配置哈希 (用于热重载检测)
        self._last_pairs_hash: Optional[str] = None

        # ═══════════════════════════════════════════════════
        # 初始化子模块
        # ═══════════════════════════════════════════════════
        # FIX: 先初始化 order_executor，再初始化依赖它的 state_machine
        self.order_executor = OrderExecutor(self)
        self.state_machine = StateMachine(self)
        self.position_manager = PositionManager(self)
        self.risk_guard = RiskGuard(self)

        logger.info("Runtime: 子模块初始化完成")

    # ═══════════════════════════════════════════════════
    # 生命周期管理
    # ═══════════════════════════════════════════════════

    async def start(self) -> None:
        """启动运行时 (修复HIGH-004: 集成RecoverySystem)"""
        logger.info("Runtime: 启动中...")

        # 修复HIGH-004: 步骤1 - 运行恢复系统
        recovery_ok = await self._run_recovery()
        if not recovery_ok:
            logger.error("Runtime: 恢复系统检查失败，进入安全模式")
            # 不返回，继续启动但可能限制交易

        # 2. 加载配对配置
        await self._load_pairs()

        # 3. 恢复状态 (使用新的from_dict方法)
        await self._load_state_v2()

        # 4. 持仓对账
        await self.position_manager.reconcile_positions()

        logger.info(f"Runtime: 启动完成，管理 {len(self.positions)} 个配对")

    async def _run_recovery(self) -> bool:
        """
        运行恢复系统检查 (修复HIGH-004)
        返回: 是否允许继续启动
        """
        try:
            from src.recovery_system import RecoverySystem, SystemMode

            # 初始化恢复系统
            # FIX: 参数名匹配 RecoverySystem.__init__(exchange, state_dir)
            # RecoverySystem 需要原始 ccxt.Exchange 对象，不是 ExchangeApi 包装器
            raw_exchange = self.exchange_api._get_client() if self.exchange_api else None
            recovery = RecoverySystem(
                exchange=raw_exchange,
                state_dir=str(self.state_file.parent / "recovery")
            )
            
            # 执行恢复流程
            # FIX: run_recovery() 返回 tuple (system_mode, recovery_level, message)
            system_mode, recovery_level, message = await recovery.run_recovery()

            # 检查恢复等级
            level = recovery_level.value if hasattr(recovery_level, 'value') else str(recovery_level)
            if level == "D":  # D级 - 紧急状态
                logger.error("Runtime: RecoverySystem 判定为 D级(紧急)，禁止交易")
                return False
            elif level == "C":  # C级 - 接管模式
                logger.warning("Runtime: RecoverySystem 判定为 C级(接管)，只接管不开新仓")
                # 设置安全模式标志
                self._safe_mode = True
            elif level in ["A", "B"]:  # A/B级 - 正常
                logger.info(f"Runtime: RecoverySystem 判定为 {level}级，正常运行")
                self._safe_mode = False
            
            # 保存 recovery_system 引用供 RiskGuard 使用
            self.recovery_system = recovery
            return True
            
        except Exception as e:
            logger.error(f"Runtime: RecoverySystem 运行失败: {e}")
            # 失败时不阻止启动，但记录错误
            return True

    async def _load_state_v2(self) -> None:
        """
        恢复状态 V2 (修复CRIT-008: 使用新的from_dict方法)
        """
        try:
            if not self.state_file.exists():
                logger.info("Runtime: 状态文件不存在，全新启动")
                return

            with open(self.state_file, 'r') as f:
                state = json.load(f)

            # 使用 PositionState.from_dict 恢复完整状态
            for pair_key, ps_data in state.items():
                try:
                    # 从保存的数据中重建 PositionState
                    ps = PositionState.from_dict(ps_data)
                    self.positions[pair_key] = ps
                    logger.debug(f"Runtime: 恢复状态 {pair_key}: {ps.state}")
                except Exception as e:
                    logger.error(f"Runtime: 恢复 {pair_key} 状态失败: {e}")

            logger.info(f"Runtime: 已恢复 {len(self.positions)} 个配对状态")

        except Exception as e:
            logger.error(f"Runtime: 加载状态失败: {e}")

    async def stop(self) -> None:
        """停止运行时"""
        logger.info("Runtime: 停止中...")
        await self._save_state()
        logger.info("Runtime: 已停止")

    # ═══════════════════════════════════════════════════
    # 核心信号处理
    # ═══════════════════════════════════════════════════

    async def on_signal(self, pair_key: str, z: float, timestamp: Optional[int] = None) -> None:
        """
        外部信号输入接口 - 加固版
        
        Args:
            pair_key: 配对标识，如 "BTC_USDT_ETH_USDT"
            z: 当前 Z-Score 值
            timestamp: 信号时间戳
            
        HARDENING:
        1. 验证 pair_key 非空
        2. 验证 z 为有限数值
        3. 验证配对存在
        4. 验证配对配置完整
        5. 信号防抖保护
        """
        # HARDENING: 输入验证
        if not pair_key or not isinstance(pair_key, str):
            logger.error(f"[HARDENING] Invalid pair_key: {pair_key}")
            return
        
        # HARDENING: Z-Score 验证
        if not isinstance(z, (int, float)):
            logger.error(f"[HARDENING] Invalid z type: {type(z)} for {pair_key}")
            return
        
        if not (-10 <= z <= 10):  # 合理范围检查
            logger.warning(f"[HARDENING] Extreme z value: {z} for {pair_key}")
            # 继续处理但记录警告
        
        if z != z:  # NaN 检查
            logger.error(f"[HARDENING] NaN z value for {pair_key}")
            return
        
        # 检查热重载
        await self._check_hot_reload()

        # HARDENING: 验证配对存在
        if pair_key not in self.positions:
            logger.warning(f"Runtime: 未知配对 {pair_key}")
            return

        ps = self.positions[pair_key]
        
        # HARDENING: 验证配对配置
        if not ps.pair_config:
            logger.error(f"[HARDENING] Missing pair_config for {pair_key}")
            return
        
        required_fields = ['symbol_a', 'symbol_b', 'beta']
        for field in required_fields:
            if field not in ps.pair_config:
                logger.error(f"[HARDENING] Missing {field} in pair_config for {pair_key}")
                return

        # 更新价格缓存
        await self._update_price_cache(ps)

        # 检查信号防抖
        current_bar = timestamp // 60000 if timestamp else int(asyncio.get_event_loop().time() // 60)
        if current_bar == ps.last_signal_bar:
            return  # 同一条K线，忽略
        ps.last_signal_bar = current_bar

        # 委托给状态机处理
        await self.state_machine.on_signal(ps, pair_key, z)

    async def check_signals(self, pair_key: str, z: float, current_bar: int = 0) -> None:
        """
        信号检查接口 (兼容旧版 main.py 调用)
        
        Args:
            pair_key: 配对标识
            z: 当前 Z-Score
            current_bar: 当前K线索引 (可选)
        """
        timestamp = current_bar * 60000 if current_bar else None
        await self.on_signal(pair_key, z, timestamp)

    async def on_price_update(self, symbol: str, price: float) -> None:
        """价格更新接口"""
        self._price_cache[symbol] = price

    # ═══════════════════════════════════════════════════
    # 配置管理
    # ═══════════════════════════════════════════════════

    async def _load_pairs(self) -> bool:
        """加载配对配置"""
        try:
            if not self.pairs_file.exists():
                logger.warning(f"Runtime: 配对文件不存在 {self.pairs_file}")
                return False

            with open(self.pairs_file, 'r') as f:
                data = json.load(f)

            pairs = data.get("pairs", [])
            logger.info(f"Runtime: 加载 {len(pairs)} 个配对配置")

            # 初始化持仓状态
            for pair in pairs:
                pair_key = f"{pair['symbol_a']}_{pair['symbol_b']}"
                if pair_key not in self.positions:
                    self.positions[pair_key] = PositionState(pair)

            # 计算哈希用于热重载检测
            self._last_pairs_hash = self._compute_hash(data)
            return True

        except Exception as e:
            logger.error(f"Runtime: 加载配对配置失败: {e}")
            return False

    async def _check_hot_reload(self) -> None:
        """检测配置变更并热重载 (内部方法)"""
        try:
            if not self.pairs_file.exists():
                return

            with open(self.pairs_file, 'r') as f:
                data = json.load(f)

            current_hash = self._compute_hash(data)
            if current_hash != self._last_pairs_hash:
                logger.info("Runtime: 检测到配置变更，执行热重载")
                await self._load_pairs()
                await self._save_state()

        except Exception as e:
            logger.error(f"Runtime: 热重载检查失败: {e}")

    async def handle_hot_reload(self, data: dict) -> None:
        """
        外部触发的热重载 (由ConfigManager调用)

        Args:
            data: 新的配对配置数据
        """
        try:
            logger.info("Runtime: 外部触发热重载")

            # 计算新哈希
            new_hash = self._compute_hash(data)
            if new_hash == self._last_pairs_hash:
                logger.debug("Runtime: 配置未变更，跳过热重载")
                return

            # 执行热重载
            logger.info(f"Runtime: 热重载配置，{len(data.get('pairs', []))} 个配对")
            await self._load_pairs(data)
            await self._save_state()
            logger.info("Runtime: 热重载完成")

        except Exception as e:
            logger.error(f"Runtime: 热重载失败: {e}")
            if self.notifier:
                await self.notifier.send_alert(f"热重载失败: {e}")

    def _compute_hash(self, data: dict) -> str:
        """计算配置哈希"""
        import hashlib
        return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()[:8]

    # ═══════════════════════════════════════════════════
    # 状态持久化
    # ═══════════════════════════════════════════════════

    async def _load_state(self) -> None:
        """从文件恢复状态"""
        try:
            if not self.state_file.exists():
                logger.info("Runtime: 状态文件不存在，使用初始状态")
                return

            with open(self.state_file, 'r') as f:
                state = json.load(f)

            for pair_key, ps_data in state.items():
                if pair_key in self.positions:
                    ps = self.positions[pair_key]
                    # 恢复状态
                    ps.state = ps_data.get("state", "IDLE")
                    ps.direction = ps_data.get("direction", 0)
                    ps.entry_z = ps_data.get("entry_z", 0.0)
                    ps.scale_in_layer = ps_data.get("scale_in_layer", 0)
                    ps.scale_out_layer = ps_data.get("scale_out_layer", 0)
                    ps.position_size_pct = ps_data.get("position_size_pct", 0.0)
                    ps.entry_price_a = ps_data.get("entry_price_a", 0.0)
                    ps.entry_price_b = ps_data.get("entry_price_b", 0.0)
                    logger.info(f"Runtime: 恢复 {pair_key} 状态 {ps.state}")

        except Exception as e:
            logger.error(f"Runtime: 加载状态失败: {e}")

    async def _save_state(self) -> None:
        """保存状态到文件"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

            state = {}
            for pair_key, ps in self.positions.items():
                if ps.state != "IDLE":
                    state[pair_key] = ps.to_dict()

            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)

        except Exception as e:
            logger.error(f"Runtime: 保存状态失败: {e}")

    # ═══════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════

    async def _update_price_cache(self, ps: PositionState) -> None:
        """更新价格缓存"""
        if not self.exchange_api:
            return

        try:
            for symbol in [ps.symbol_a, ps.symbol_b]:
                if symbol not in self._price_cache:
                    ticker = await self.exchange_api.fetch_ticker(symbol)
                    self._price_cache[symbol] = ticker.get('last', 0.0)
        except Exception as e:
            logger.warning(f"Runtime: 获取价格失败: {e}")

    def get_status(self) -> Dict[str, Any]:
        """获取运行时状态摘要"""
        active = sum(1 for ps in self.positions.values() if ps.state != "IDLE")
        return {
            "total_pairs": len(self.positions),
            "active_positions": active,
            "price_cache_size": len(self._price_cache),
        }
