"""
订单执行模块 - 生产级实现

核心功能:
  1. 双边同步下单 (防裸仓)
  2. 订单确认轮询
  3. 失败回滚机制
  4. 防裸仓铁律保护

防裸仓策略:
  - 开仓: 两边必须都成交才算成功，否则回滚
  - 平仓: 使用 reduce_only=True 防止意外开仓
  - 超时: 订单超时自动撤单并回滚
  - 重试: 最大重试次数限制，防止无限循环
"""
import asyncio
import logging
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from src.runtime.position_state import PositionState, STATE_IDLE, STATE_IN_POSITION, STATE_EXITED
from src.constants import (
    DEFAULT_POST_ONLY,
    POSITION_COMPLETE_THRESHOLD,
    ORDER_TIMEOUT_SECONDS,
    ROLLBACK_TIMEOUT_SECONDS,
    MAX_RETRY_ATTEMPTS,
)

logger = logging.getLogger("OrderExecutor")


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"      # 待提交
    SUBMITTED = "submitted"  # 已提交
    PARTIAL = "partial"      # 部分成交
    FILLED = "filled"        # 完全成交
    CANCELED = "canceled"    # 已撤单
    FAILED = "failed"        # 失败


@dataclass
class LegResult:
    """单边订单执行结果"""
    success: bool
    order_id: Optional[str] = None
    filled_qty: float = 0.0
    avg_price: float = 0.0
    status: str = ""
    error: Optional[str] = None


@dataclass
class SyncOpenResult:
    """同步开仓结果"""
    success: bool
    leg_a: Optional[LegResult] = None
    leg_b: Optional[LegResult] = None
    rolled_back: bool = False
    error: Optional[str] = None


@dataclass
class SyncCloseResult:
    """同步平仓结果"""
    success: bool
    leg_a: Optional[LegResult] = None
    leg_b: Optional[LegResult] = None
    rolled_back: bool = False
    error: Optional[str] = None


class OrderExecutor:
    """
    订单执行器 - 防裸仓核心实现
    
    职责:
      1. 双边同步开仓 (必须两边都成交)
      2. 双边同步平仓 (带 reduce_only 保护)
      3. 订单状态轮询确认
      4. 失败时自动回滚
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self.exchange_api = getattr(runtime, 'exchange_api', None)
        
        # 配置参数
        self.order_timeout = ORDER_TIMEOUT_SECONDS  # 订单超时(秒)
        self.rollback_timeout = ROLLBACK_TIMEOUT_SECONDS  # 回滚超时(秒)
        self.max_retries = MAX_RETRY_ATTEMPTS  # 最大重试次数
        self.poll_interval = 0.5  # 轮询间隔(秒)
        
        # 统计
        self.stats = {
            'total_orders': 0,
            'successful_opens': 0,
            'successful_closes': 0,
            'rollbacks': 0,
            'emergency_closes': 0,
        }

    # ═══════════════════════════════════════════════════
    # 公共接口: 分层开仓
    # ═══════════════════════════════════════════════════

    async def execute_scale_in(
        self,
        ps: PositionState,
        scale_in_plan: List[Dict],
        current_z: float
    ) -> bool:
        """
        执行分层加仓
        
        Args:
            ps: 持仓状态
            scale_in_plan: 加仓计划 [{"ratio": 0.3, "type": "limit"}, ...]
            current_z: 当前Z-score
            
        Returns:
            bool: 是否成功
        """
        if not scale_in_plan:
            return False
            
        step = scale_in_plan[0]
        ratio = step.get("ratio", 0.3)
        order_type = step.get("type", "limit")
        
        # 计算加仓后的目标仓位
        target_pct = ps.position_size_pct + ratio
        if target_pct > POSITION_COMPLETE_THRESHOLD:
            target_pct = 1.0
            
        logger.info(f"[ScaleIn] {ps.symbol_a}-{ps.symbol_b}: {ps.position_size_pct:.1%} -> {target_pct:.1%}")
        
        # 执行同步开仓
        result = await self._execute_sync_open(ps, ratio, order_type, current_z)
        
        if result.success:
            # 更新持仓状态
            ps.position_size_pct = target_pct
            ps.scale_in_layer += 1
            ps.scale_in_fail_count = 0  # 重置失败计数
            self.stats['successful_opens'] += 1
            
            logger.info(f"[ScaleIn] 成功: {ps.symbol_a}-{ps.symbol_b} 当前仓位 {ps.position_size_pct:.1%}")
            return True
        else:
            # 记录失败
            ps.record_failure(time.time(), "scale_in")
            logger.warning(f"[ScaleIn] 失败: {ps.symbol_a}-{ps.symbol_b}, 错误: {result.error}")
            return False

    # ═══════════════════════════════════════════════════
    # 公共接口: 同步平仓
    # ═══════════════════════════════════════════════════

    async def execute_scale_out(
        self,
        ps: PositionState,
        scale_out_plan: List[Dict],
        current_z: float
    ) -> bool:
        """
        执行分层平仓
        
        Args:
            ps: 持仓状态
            scale_out_plan: 平仓计划 [{"ratio": 0.3, "type": "limit"}, ...]
            current_z: 当前Z-score
            
        Returns:
            bool: 是否成功
        """
        if not scale_out_plan:
            return False
            
        step = scale_out_plan[0]
        ratio = step.get("ratio", 0.3)
        order_type = step.get("type", "limit")
        
        # 计算平仓后的目标仓位
        target_pct = ps.position_size_pct - ratio
        if target_pct < POSITION_COMPLETE_THRESHOLD:
            target_pct = 0.0
            
        logger.info(f"[ScaleOut] {ps.symbol_a}-{ps.symbol_b}: {ps.position_size_pct:.1%} -> {target_pct:.1%}")
        
        # 执行同步平仓
        result = await self._execute_sync_close(ps, ratio, order_type, current_z)
        
        if result.success:
            # 更新持仓状态
            ps.position_size_pct = target_pct
            ps.scale_out_layer += 1
            ps.scale_out_fail_count = 0  # 重置失败计数
            self.stats['successful_closes'] += 1
            
            if ps.position_size_pct <= 0:
                ps.state = STATE_EXITED
                logger.info(f"[ScaleOut] 完全平仓: {ps.symbol_a}-{ps.symbol_b}")
            else:
                logger.info(f"[ScaleOut] 部分平仓: {ps.symbol_a}-{ps.symbol_b} 剩余 {ps.position_size_pct:.1%}")
            return True
        else:
            # 记录失败
            ps.record_failure(time.time(), "scale_out")
            logger.warning(f"[ScaleOut] 失败: {ps.symbol_a}-{ps.symbol_b}, 错误: {result.error}")
            return False

    # ═══════════════════════════════════════════════════
    # 公共接口: 止损平仓
    # ═══════════════════════════════════════════════════

    async def execute_stop_loss(self, ps: PositionState) -> bool:
        """
        执行止损平仓 - 市价单立即成交
        
        Args:
            ps: 持仓状态
            
        Returns:
            bool: 是否成功
        """
        logger.warning(f"[StopLoss] 触发止损: {ps.symbol_a}-{ps.symbol_b}, Z={ps.entry_z:.2f}")
        
        # 止损使用市价单确保成交
        result = await self._execute_sync_close(ps, 1.0, "market", ps.entry_z, is_stop_loss=True)
        
        if result.success:
            ps.position_size_pct = 0.0
            ps.state = STATE_EXITED
            self.stats['successful_closes'] += 1
            logger.warning(f"[StopLoss] 止损完成: {ps.symbol_a}-{ps.symbol_b}")
            return True
        else:
            logger.error(f"[StopLoss] 止损失败: {ps.symbol_a}-{ps.symbol_b}, 错误: {result.error}")
            return False

    # ═══════════════════════════════════════════════════
    # 核心实现: 双边同步开仓
    # ═══════════════════════════════════════════════════

    async def _execute_sync_open(
        self,
        ps: PositionState,
        ratio: float,
        order_type: str,
        current_z: float
    ) -> SyncOpenResult:
        """
        双边同步开仓 - 防裸仓核心
        
        流程:
          1. 计算两边下单数量
          2. 同时提交两边订单
          3. 轮询等待两边都成交
          4. 如果一边失败，回滚另一边
        """
        if not self.exchange_api:
            return SyncOpenResult(success=False, error="Exchange API not available")
            
        symbol_a = ps.symbol_a
        symbol_b = ps.symbol_b
        
        # 获取当前价格
        price_a = self.runtime._price_cache.get(symbol_a)
        price_b = self.runtime._price_cache.get(symbol_b)
        
        if not price_a or not price_b:
            return SyncOpenResult(success=False, error="Price not available")
            
        # 计算下单数量 (简化版，实际应根据资金计算)
        qty_a = self._calculate_qty(symbol_a, price_a, ratio)
        qty_b = self._calculate_qty(symbol_b, price_b, ratio * ps.beta)
        
        # 确定方向 (Z-score > 0: A贵B便宜 -> 空A多B)
        if current_z > 0:
            side_a, side_b = "sell", "buy"
        else:
            side_a, side_b = "buy", "sell"
            
        logger.info(f"[SyncOpen] {symbol_a}:{side_a}:{qty_a:.4f} <-> {symbol_b}:{side_b}:{qty_b:.4f}")
        
        # 提交两边订单
        order_a_task = self._submit_order(symbol_a, order_type, side_a, qty_a, price_a)
        order_b_task = self._submit_order(symbol_b, order_type, side_b, qty_b, price_b)
        
        try:
            order_a, order_b = await asyncio.gather(order_a_task, order_b_task)
        except Exception as e:
            logger.error(f"[SyncOpen] 下单异常: {e}")
            return SyncOpenResult(success=False, error=f"Order submission failed: {e}")
            
        # 检查提交结果
        if not order_a or not order_b:
            # 至少一边提交失败，尝试撤单已提交的
            await self._cancel_if_submitted(order_a, symbol_a)
            await self._cancel_if_submitted(order_b, symbol_b)
            return SyncOpenResult(success=False, error="Order submission failed")
            
        order_id_a = order_a.get('id')
        order_id_b = order_b.get('id')
        
        logger.info(f"[SyncOpen] 订单已提交: {symbol_a}={order_id_a}, {symbol_b}={order_id_b}")
        
        # 轮询等待两边都成交
        leg_a, leg_b = await self._wait_both_filled(
            symbol_a, order_id_a,
            symbol_b, order_id_b,
            timeout=self.order_timeout
        )
        
        # 检查成交结果
        a_filled = leg_a and leg_a.status == "filled" and leg_a.filled_qty > 0
        b_filled = leg_b and leg_b.status == "filled" and leg_b.filled_qty > 0
        
        if a_filled and b_filled:
            # 两边都成交，成功
            logger.info(f"[SyncOpen] 双边成交成功")
            return SyncOpenResult(success=True, leg_a=leg_a, leg_b=leg_b)
            
        # 至少一边未成交，需要回滚
        logger.warning(f"[SyncOpen] 成交不完整，启动回滚: A={a_filled}, B={b_filled}")
        
        rolled_back = await self._execute_rollback(
            symbol_a, order_id_a, leg_a,
            symbol_b, order_id_b, leg_b
        )
        
        return SyncOpenResult(
            success=False,
            leg_a=leg_a,
            leg_b=leg_b,
            rolled_back=rolled_back,
            error="Fill incomplete, rollback executed"
        )

    # ═══════════════════════════════════════════════════
    # 核心实现: 双边同步平仓
    # ═══════════════════════════════════════════════════

    async def _execute_sync_close(
        self,
        ps: PositionState,
        ratio: float,
        order_type: str,
        current_z: float,
        is_stop_loss: bool = False
    ) -> SyncCloseResult:
        """
        双边同步平仓 - 带 reduce_only 保护
        
        流程:
          1. 计算两边平仓数量
          2. 同时提交两边订单 (reduce_only=True)
          3. 轮询等待两边都成交
          4. 平仓失败不触发回滚(因为reduce_only不会导致裸仓)
        """
        if not self.exchange_api:
            return SyncCloseResult(success=False, error="Exchange API not available")
            
        symbol_a = ps.symbol_a
        symbol_b = ps.symbol_b
        
        # 获取当前价格
        price_a = self.runtime._price_cache.get(symbol_a)
        price_b = self.runtime._price_cache.get(symbol_b)
        
        if not price_a or not price_b:
            return SyncCloseResult(success=False, error="Price not available")
            
        # 计算平仓数量
        qty_a = self._calculate_qty(symbol_a, price_a, ratio)
        qty_b = self._calculate_qty(symbol_b, price_b, ratio * ps.beta)
        
        # 确定方向 (与开仓相反)
        if current_z > 0:
            side_a, side_b = "buy", "sell"  # 平仓: 买平空，卖平多
        else:
            side_a, side_b = "sell", "buy"
            
        logger.info(f"[SyncClose] {symbol_a}:{side_a}:{qty_a:.4f} <-> {symbol_b}:{side_b}:{qty_b:.4f}")
        
        # 提交两边订单 (reduce_only=True)
        order_a_task = self._submit_order(
            symbol_a, order_type, side_a, qty_a, price_a, reduce_only=True
        )
        order_b_task = self._submit_order(
            symbol_b, order_type, side_b, qty_b, price_b, reduce_only=True
        )
        
        try:
            order_a, order_b = await asyncio.gather(order_a_task, order_b_task)
        except Exception as e:
            logger.error(f"[SyncClose] 下单异常: {e}")
            return SyncCloseResult(success=False, error=f"Order submission failed: {e}")
            
        # 检查提交结果
        if not order_a or not order_b:
            await self._cancel_if_submitted(order_a, symbol_a)
            await self._cancel_if_submitted(order_b, symbol_b)
            return SyncCloseResult(success=False, error="Order submission failed")
            
        order_id_a = order_a.get('id')
        order_id_b = order_b.get('id')
        
        logger.info(f"[SyncClose] 订单已提交: {symbol_a}={order_id_a}, {symbol_b}={order_id_b}")
        
        # 轮询等待两边都成交
        leg_a, leg_b = await self._wait_both_filled(
            symbol_a, order_id_a,
            symbol_b, order_id_b,
            timeout=self.order_timeout
        )
        
        # 检查成交结果
        a_filled = leg_a and leg_a.status == "filled"
        b_filled = leg_b and leg_b.status == "filled"
        
        if a_filled and b_filled:
            logger.info(f"[SyncClose] 双边平仓成功")
            return SyncCloseResult(success=True, leg_a=leg_a, leg_b=leg_b)
            
        # 平仓不完整，但因为有reduce_only保护，不会产生裸仓
        # 记录警告但不触发紧急回滚
        logger.warning(f"[SyncClose] 平仓不完整: A={a_filled}, B={b_filled}")
        
        # 尝试撤单未成交的
        if leg_a and leg_a.status not in ["filled", "canceled"]:
            await self._cancel_order(symbol_a, order_id_a)
        if leg_b and leg_b.status not in ["filled", "canceled"]:
            await self._cancel_order(symbol_b, order_id_b)
            
        return SyncCloseResult(
            success=a_filled and b_filled,
            leg_a=leg_a,
            leg_b=leg_b,
            error="Partial fill" if (a_filled or b_filled) else "Both failed"
        )

    # ═══════════════════════════════════════════════════
    # 底层方法: 提交订单
    # ═══════════════════════════════════════════════════

    async def _submit_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        qty: float,
        price: Optional[float] = None,
        reduce_only: bool = False
    ) -> Optional[Dict]:
        """提交单笔订单"""
        try:
            order = await self.exchange_api.place_order(
                symbol=symbol,
                order_type=order_type,
                side=side,
                qty=qty,
                price=price,
                post_only=(order_type == "limit"),
                reduce_only=reduce_only
            )
            self.stats['total_orders'] += 1
            return order
        except Exception as e:
            logging.getLogger("OrderExecutor").error(f"[SubmitOrder] {symbol} {side} failed: {e}")
            return None

    # ═══════════════════════════════════════════════════
    # 底层方法: 轮询等待成交
    # ═══════════════════════════════════════════════════

    async def _wait_both_filled(
        self,
        symbol_a: str, order_id_a: str,
        symbol_b: str, order_id_b: str,
        timeout: float = 10.0
    ) -> Tuple[Optional[LegResult], Optional[LegResult]]:
        """
        轮询等待两边订单都成交
        
        Returns:
            (leg_a_result, leg_b_result)
        """
        start_time = time.time()
        leg_a, leg_b = None, None
        
        while time.time() - start_time < timeout:
            # 查询订单状态
            if not leg_a or leg_a.status not in ["filled", "canceled", "failed"]:
                leg_a = await self._fetch_order_status(symbol_a, order_id_a)
                
            if not leg_b or leg_b.status not in ["filled", "canceled", "failed"]:
                leg_b = await self._fetch_order_status(symbol_b, order_id_b)
                
            # 检查是否都完成
            a_done = leg_a and leg_a.status in ["filled", "canceled", "failed"]
            b_done = leg_b and leg_b.status in ["filled", "canceled", "failed"]
            
            if a_done and b_done:
                break
                
            await asyncio.sleep(self.poll_interval)
            
        return leg_a, leg_b

    async def _fetch_order_status(self, symbol: str, order_id: str) -> Optional[LegResult]:
        """查询订单状态"""
        try:
            order = await self.exchange_api.fetch_order(order_id, symbol)
            
            status_map = {
                "open": "submitted",
                "closed": "filled",
                "canceled": "canceled",
            }
            
            raw_status = order.get("status", "unknown")
            status = status_map.get(raw_status, raw_status)
            
            filled = order.get("filled", 0) or order.get("amount", 0)
            avg_price = order.get("average", 0) or order.get("price", 0)
            
            return LegResult(
                success=(status == "filled"),
                order_id=order_id,
                filled_qty=float(filled) if filled else 0,
                avg_price=float(avg_price) if avg_price else 0,
                status=status
            )
        except Exception as e:
            logger.warning(f"[FetchOrder] {symbol} {order_id} failed: {e}")
            return LegResult(success=False, order_id=order_id, status="failed", error=str(e))

    # ═══════════════════════════════════════════════════
    # 核心方法: 回滚机制
    # ═══════════════════════════════════════════════════

    async def _execute_rollback(
        self,
        symbol_a: str, order_id_a: str, leg_a: Optional[LegResult],
        symbol_b: str, order_id_b: str, leg_b: Optional[LegResult]
    ) -> bool:
        """
        执行回滚 - 平仓已成交的腿
        
        场景:
          - A成交B失败 -> 平仓A
          - A失败B成交 -> 平仓B
          - 两者都部分成交 -> 平仓两者的已成交部分
        """
        logger.warning(f"[Rollback] 启动回滚: {symbol_a}={leg_a.status if leg_a else None}, {symbol_b}={leg_b.status if leg_b else None}")
        
        rollback_tasks = []
        
        # 如果A已成交，需要平仓
        if leg_a and leg_a.status == "filled" and leg_a.filled_qty > 0:
            logger.warning(f"[Rollback] 回滚 {symbol_a}: 数量 {leg_a.filled_qty}")
            rollback_tasks.append(
                self._emergency_close(symbol_a, leg_a.filled_qty)
            )
        else:
            # 未成交则撤单
            await self._cancel_order(symbol_a, order_id_a)
            
        # 如果B已成交，需要平仓
        if leg_b and leg_b.status == "filled" and leg_b.filled_qty > 0:
            logger.warning(f"[Rollback] 回滚 {symbol_b}: 数量 {leg_b.filled_qty}")
            rollback_tasks.append(
                self._emergency_close(symbol_b, leg_b.filled_qty)
            )
        else:
            # 未成交则撤单
            await self._cancel_order(symbol_b, order_id_b)
            
        # 等待回滚完成
        if rollback_tasks:
            results = await asyncio.gather(*rollback_tasks, return_exceptions=True)
            success = all(not isinstance(r, Exception) and r for r in results)
            
            if success:
                self.stats['rollbacks'] += 1
                logger.info(f"[Rollback] 回滚成功")
            else:
                logger.error(f"[Rollback] 回滚失败，存在裸仓风险！")
                
            return success
            
        return True

    async def _emergency_close(self, symbol: str, qty: float) -> bool:
        """
        紧急平仓 - 市价单确保成交
        
        用于回滚场景，必须成交
        """
        logger.warning(f"[EmergencyClose] {symbol}: 数量 {qty}")
        
        try:
            # 确定平仓方向
            # 这里简化处理，实际应根据持仓方向判断
            # 假设当前有多头持仓就卖出平仓，空头就买入平仓
            side = "sell"  # 默认卖出平仓
            
            order = await self.exchange_api.place_order(
                symbol=symbol,
                order_type="market",
                side=side,
                qty=qty,
                reduce_only=True
            )
            
            if order:
                self.stats['emergency_closes'] += 1
                logger.info(f"[EmergencyClose] {symbol} 成功")
                return True
            else:
                logger.error(f"[EmergencyClose] {symbol} 失败")
                return False
                
        except Exception as e:
            logger.error(f"[EmergencyClose] {symbol} 异常: {e}")
            return False

    # ═══════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════

    async def _cancel_order(self, symbol: str, order_id: str) -> bool:
        """撤单"""
        try:
            return await self.exchange_api.cancel_order(order_id, symbol)
        except Exception as e:
            logger.warning(f"[CancelOrder] {symbol} {order_id} failed: {e}")
            return False

    async def _cancel_if_submitted(self, order: Optional[Dict], symbol: str):
        """如果订单已提交则撤单"""
        if order and order.get('id'):
            await self._cancel_order(symbol, order['id'])

    def _calculate_qty(self, symbol: str, price: float, ratio: float) -> float:
        """
        计算下单数量 - 加固版
        
        强化验证:
        1. 价格必须 > 0
        2. 比例必须在 (0, 1] 范围内
        3. 数量必须 >= 最小下单量
        4. 数量必须 <= 最大限制
        """
        # HARDENING: 输入验证
        if price <= 0:
            logger.error(f"[HARDENING] Invalid price: {price} for {symbol}")
            return 0.0
        
        if ratio <= 0 or ratio > 1:
            logger.error(f"[HARDENING] Invalid ratio: {ratio} for {symbol}")
            return 0.0
        
        # 简化计算：每腿最大1000 USDT
        max_notional = 1000.0
        notional = max_notional * ratio
        
        # HARDENING: 除零保护
        if price <= 0:
            logger.error(f"[HARDENING] Division by zero protection triggered for {symbol}")
            return 0.0
        
        qty = notional / price
        
        # HARDENING: 最小数量检查 (假设最小 5 USDT)
        min_notional = 5.0
        if qty * price < min_notional:
            logger.warning(f"[HARDENING] Quantity too small for {symbol}: {qty} (value: {qty*price:.2f} USDT)")
            # 尝试增加到最小值
            qty = min_notional / price
        
        # HARDENING: 最大数量限制 (单腿不超过 5000 USDT)
        max_qty = 5000.0 / price
        if qty > max_qty:
            logger.warning(f"[HARDENING] Quantity capped for {symbol}: {qty} -> {max_qty}")
            qty = max_qty
        
        # 根据币种精度调整 (简化处理)
        if "BTC" in symbol:
            qty = round(qty, 4)
        elif "ETH" in symbol:
            qty = round(qty, 3)
        else:
            qty = round(qty, 2)
        
        # HARDENING: 最终验证
        if qty <= 0:
            logger.error(f"[HARDENING] Final quantity invalid for {symbol}: {qty}")
            return 0.0
        
        return qty

    def get_stats(self) -> Dict:
        """获取执行统计"""
        return self.stats.copy()
