#!/usr/bin/env python3
"""
S001-Pro 重启恢复系统 - Phase 1 核心框架

生产级规范实现:
  1. 三层对账 (持仓/订单/保护单)
  2. 恢复等级判定 (A/B/C/D)
  3. 唯一 ClientOrderId 生成
  4. 订单意图持久化
  5. 仓位快照系统
"""

import json
import os
import time
import logging
import uuid
from enum import Enum
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any
import ccxt

logger = logging.getLogger("RecoverySystem")


class RecoveryLevel(Enum):
    """恢复等级"""
    A_AUTO = "A"       # 全部一致,自动恢复
    B_SEMI = "B"       # 轻微不一致,自动修复
    C_TAKEOVER = "C"   # 有持仓但来源不明,只接管不开仓
    D_EMERGENCY = "D"  # 风险不明,紧急平仓锁定


class SystemMode(Enum):
    """系统运行模式"""
    RECOVERY = "RECOVERY"    # 恢复模式:只读,禁止交易
    SAFE = "SAFE"            # 安全模式:可对账修复,禁止新开仓
    TRADING = "TRADING"      # 交易模式:正常运行


@dataclass
class PositionSnapshot:
    """仓位快照"""
    symbol: str
    side: str           # long / short
    qty: float
    avg_price: float
    leverage: int
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy_id: str = "s001"
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class OrderIntent:
    """订单意图 (发单前持久化)"""
    intent_id: str
    strategy: str
    symbol: str
    action: str         # open / close / scale_in / scale_out
    side: str           # long / short
    qty: float
    price: Optional[float] = None
    order_type: str = "limit"
    reduce_only: bool = False
    expected_position_change: Dict = None
    risk_params: Dict = None
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class OrderRecord:
    """订单记录 (发单后持久化)"""
    intent_id: str
    client_order_id: str
    exchange_order_id: Optional[str] = None
    symbol: str = ""
    status: str = "pending"  # pending / submitted / partial / filled / canceled / error
    result: Optional[str] = None
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class ClientOrderIdGenerator:
    """
    Client Order ID 生成器
    
    格式: {strategy}_{symbol}_{action}_{side}_{timestamp}_{random}
    示例: s001_BTCUSDT_open_long_1712450001_x8k2
    """
    
    @staticmethod
    def generate(
        strategy: str,
        symbol: str,
        action: str,  # open / close / sl / tp / scale_in / scale_out
        side: str,    # long / short
        timestamp: Optional[int] = None
    ) -> str:
        """生成唯一 Client Order ID"""
        if timestamp is None:
            timestamp = int(time.time())
        
        # 格式化 symbol: BTC/USDT -> BTCUSDT
        symbol_clean = symbol.replace("/", "").replace("-", "")
        
        # 6位随机后缀
        random_suffix = uuid.uuid4().hex[:6]
        
        return f"{strategy}_{symbol_clean}_{action}_{side}_{timestamp}_{random_suffix}"
    
    @staticmethod
    def parse(client_order_id: str) -> Optional[Dict]:
        """解析 Client Order ID"""
        try:
            parts = client_order_id.split("_")
            if len(parts) >= 5:
                return {
                    "strategy": parts[0],
                    "symbol": parts[1],
                    "action": parts[2],
                    "side": parts[3],
                    "timestamp": int(parts[4]) if parts[4].isdigit() else 0,
                    "suffix": parts[5] if len(parts) > 5 else "",
                }
        except Exception:
            # 解析失败，返回 None（无效的 Client Order ID）
            pass
        return None


class RecoverySystem:
    """
    重启恢复系统核心
    
    职责:
      1. 进入 RECOVERY 模式
      2. 拉取交易所真实状态
      3. 读取本地持久化状态
      4. 执行三层对账
      5. 判定恢复等级
      6. 执行对应恢复策略
    """
    
    def __init__(
        self,
        exchange: ccxt.Exchange,
        state_dir: str = "data/recovery",
    ):
        self.exchange = exchange
        self.state_dir = state_dir
        self.system_mode = SystemMode.RECOVERY
        self.recovery_level: Optional[RecoveryLevel] = None
        
        # 状态存储
        self._positions_file = os.path.join(state_dir, "positions.json")
        self._orders_file = os.path.join(state_dir, "orders.json")
        self._intents_file = os.path.join(state_dir, "intents.json")
        self._snapshots_file = os.path.join(state_dir, "snapshots.jsonl")
        
        # 内存状态
        self.exchange_positions: Dict[str, Any] = {}
        self.exchange_orders: List[Any] = []
        self.local_positions: Dict[str, PositionSnapshot] = {}
        self.local_orders: Dict[str, OrderRecord] = {}
        
        os.makedirs(state_dir, exist_ok=True)
    
    async def run_recovery(self) -> Tuple[SystemMode, RecoveryLevel, str]:
        """
        执行完整恢复流程
        
        Returns:
            (system_mode, recovery_level, message)
        """
        logger.info("="*60)
        logger.info("S001-Pro 重启恢复系统启动")
        logger.info("="*60)
        logger.info("当前模式: RECOVERY (禁止交易)")
        
        # Step 1: 拉取交易所真实状态
        logger.info("[Step 1/6] 拉取交易所真实状态...")
        await self._fetch_exchange_state()
        
        # Step 2: 读取本地持久化状态
        logger.info("[Step 2/6] 读取本地持久化状态...")
        self._load_local_state()
        
        # Step 3: 持仓对账
        logger.info("[Step 3/6] 执行持仓对账...")
        position_issues = self._reconcile_positions()
        
        # Step 4: 订单对账
        logger.info("[Step 4/6] 执行订单对账...")
        order_issues = self._reconcile_orders()
        
        # Step 5: 保护单对账
        logger.info("[Step 5/6] 执行保护单对账...")
        protection_issues = self._reconcile_protection_orders()
        
        # Step 6: 判定恢复等级
        logger.info("[Step 6/6] 判定恢复等级...")
        self.recovery_level = self._determine_recovery_level(
            position_issues, order_issues, protection_issues
        )
        
        # 执行对应恢复策略
        message = await self._execute_recovery_strategy()
        
        logger.info("="*60)
        logger.info(f"恢复完成: 模式={self.system_mode.value}, 等级={self.recovery_level.value}")
        logger.info(f"结果: {message}")
        logger.info("="*60)
        
        return self.system_mode, self.recovery_level, message
    
    async def _fetch_exchange_state(self):
        """拉取交易所真实状态"""
        import asyncio
        try:
            # 抑制 ccxt 警告
            self.exchange.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
            
            # 持仓 (使用 to_thread 包装同步调用)
            positions = await asyncio.to_thread(self.exchange.fetch_positions)
            self.exchange_positions = {
                p["symbol"]: p for p in positions
                if float(p.get("contracts", 0)) != 0
            }
            logger.info(f"  交易所持仓: {len(self.exchange_positions)} 个")
            
            # 活跃订单 (传入 symbols 列表避免警告)
            symbols = list(self.exchange_positions.keys()) if self.exchange_positions else None
            if symbols:
                orders = await asyncio.to_thread(self.exchange.fetch_open_orders, symbols=symbols)
            else:
                orders = await asyncio.to_thread(self.exchange.fetch_open_orders)
            self.exchange_orders = orders
            logger.info(f"  交易所挂单: {len(self.exchange_orders)} 个")
            
            # 账户信息
            balance = await asyncio.to_thread(self.exchange.fetch_balance)
            usdt = balance.get("USDT", {})
            logger.info(f"  账户余额: {usdt.get('total', 0):.2f} USDT")
            
        except Exception as e:
            logger.error(f"  拉取失败: {e}")
            raise
    
    def _load_local_state(self):
        """读取本地持久化状态"""
        # 持仓快照
        if os.path.exists(self._positions_file):
            try:
                with open(self._positions_file, "r") as f:
                    data = json.load(f)
                    for sym, pos_data in data.items():
                        self.local_positions[sym] = PositionSnapshot(**pos_data)
                logger.info(f"  本地持仓: {len(self.local_positions)} 个")
            except Exception as e:
                logger.warning(f"  读取本地持仓失败: {e}")
        
        # 订单记录
        if os.path.exists(self._orders_file):
            try:
                with open(self._orders_file, "r") as f:
                    data = json.load(f)
                    for oid, ord_data in data.items():
                        self.local_orders[oid] = OrderRecord(**ord_data)
                logger.info(f"  本地订单: {len(self.local_orders)} 个")
            except Exception as e:
                logger.warning(f"  读取本地订单失败: {e}")
    
    def _reconcile_positions(self) -> List[str]:
        """
        持仓对账
        Returns: 问题列表
        """
        issues = []
        
        # 检查所有本地持仓是否在交易所存在
        for sym, local_pos in self.local_positions.items():
            exch_pos = self.exchange_positions.get(sym)
            
            if not exch_pos:
                # 本地有,交易所无
                issues.append(f"{sym}: 本地有仓但交易所无记录(可能已平仓)")
                continue
            
            # 检查方向
            exch_side = "long" if float(exch_pos.get("contracts", 0)) > 0 else "short"
            if exch_side != local_pos.side:
                issues.append(f"{sym}: 方向不一致 本地={local_pos.side} 交易所={exch_side}")
            
            # 检查数量 (允许 1% 误差)
            exch_qty = abs(float(exch_pos.get("contracts", 0)))
            qty_diff = abs(exch_qty - local_pos.qty) / max(local_pos.qty, 1)
            if qty_diff > 0.01:
                issues.append(f"{sym}: 数量不一致 本地={local_pos.qty} 交易所={exch_qty}")
        
        # 检查交易所持仓是否在本地存在
        for sym, exch_pos in self.exchange_positions.items():
            if sym not in self.local_positions:
                # 孤儿持仓
                qty = abs(float(exch_pos.get("contracts", 0)))
                side = "long" if float(exch_pos.get("contracts", 0)) > 0 else "short"
                issues.append(f"{sym}: 孤儿持仓(交易所存在但本地无记录) {side} {qty}")
        
        if issues:
            logger.warning(f"  发现 {len(issues)} 个持仓问题:")
            for issue in issues[:5]:  # 只显示前5个
                logger.warning(f"    - {issue}")
        else:
            logger.info("  持仓对账: 全部一致 ✓")
        
        return issues
    
    def _reconcile_orders(self) -> List[str]:
        """
        订单对账
        Returns: 问题列表
        """
        issues = []
        
        # 按 symbol 分组交易所订单
        exch_orders_by_sym: Dict[str, List] = {}
        for order in self.exchange_orders:
            sym = order.get("symbol", "")
            if sym not in exch_orders_by_sym:
                exch_orders_by_sym[sym] = []
            exch_orders_by_sym[sym].append(order)
        
        # 检查幽灵订单 (交易所有但本地无记录)
        for order in self.exchange_orders:
            client_oid = order.get("clientOrderId", "")
            if client_oid and client_oid not in self.local_orders:
                # 可能是保护单或非策略单
                if order.get("reduceOnly", False):
                    issues.append(f"{order['symbol']}: 幽灵保护单 {client_oid}")
                else:
                    issues.append(f"{order['symbol']}: 幽灵开仓单(建议撤销) {client_oid}")
        
        if issues:
            logger.warning(f"  发现 {len(issues)} 个订单问题")
        else:
            logger.info("  订单对账: 全部一致 ✓")
        
        return issues
    
    def _reconcile_protection_orders(self) -> List[str]:
        """
        保护单对账
        Returns: 问题列表
        """
        issues = []
        
        for sym, pos in self.exchange_positions.items():
            qty = abs(float(pos.get("contracts", 0)))
            if qty == 0:
                continue
            
            # 查找该 symbol 的保护单
            protection_orders = [
                o for o in self.exchange_orders
                if o.get("symbol") == sym and o.get("reduceOnly", False)
            ]
            
            protection_qty = sum(
                float(o.get("amount", 0)) for o in protection_orders
            )
            
            # 保护单数量应等于或大于持仓数量
            if protection_qty < qty * 0.99:
                issues.append(f"{sym}: 保护单不足 持仓={qty} 保护={protection_qty}")
        
        if issues:
            logger.warning(f"  发现 {len(issues)} 个保护问题")
            for issue in issues[:3]:
                logger.warning(f"    - {issue}")
        else:
            logger.info("  保护单对账: 全部正常 ✓")
        
        return issues
    
    def _determine_recovery_level(
        self,
        position_issues: List[str],
        order_issues: List[str],
        protection_issues: List[str],
    ) -> RecoveryLevel:
        """
        判定恢复等级
        
        D级: 有孤儿持仓且保护缺失 / 严重风险
        C级: 有持仓问题或保护问题
        B级: 只有订单问题(幽灵单)
        A级: 全部一致
        """
        # 检查是否有孤儿持仓
        orphan_positions = [i for i in position_issues if "孤儿持仓" in i]
        
        # 检查保护是否严重缺失
        critical_protection = len(protection_issues) > 2
        
        if orphan_positions or critical_protection:
            return RecoveryLevel.D_EMERGENCY
        
        if position_issues or protection_issues:
            return RecoveryLevel.C_TAKEOVER
        
        if order_issues:
            return RecoveryLevel.B_SEMI
        
        return RecoveryLevel.A_AUTO
    
    async def _execute_recovery_strategy(self) -> str:
        """执行对应恢复策略"""
        if self.recovery_level == RecoveryLevel.A_AUTO:
            self.system_mode = SystemMode.TRADING
            return "全部一致,自动恢复交易"
        
        elif self.recovery_level == RecoveryLevel.B_SEMI:
            # 撤销幽灵开仓单
            await self._cancel_ghost_orders()
            self.system_mode = SystemMode.TRADING
            return "已撤销幽灵单,自动恢复交易"
        
        elif self.recovery_level == RecoveryLevel.C_TAKEOVER:
            self.system_mode = SystemMode.SAFE
            return "有持仓问题,进入安全模式(只接管不开新仓)"
        
        elif self.recovery_level == RecoveryLevel.D_EMERGENCY:
            self.system_mode = SystemMode.SAFE
            # 这里可以实现紧急减仓逻辑
            return "风险不明,系统锁定,等待人工处理"
        
        return "未知状态"
    
    async def _cancel_ghost_orders(self) -> int:
        """
        撤销幽灵开仓单
        
        幽灵单定义:
          1. 无 clientOrderId 或 clientOrderId 不以 s001_ 开头
          2. 非保护单 (reduceOnly=False)
          3. 超过 5 分钟的旧挂单
        
        Returns: 撤销的数量
        """
        import time
        now = time.time()
        canceled = 0
        skipped_protection = 0
        skipped_recent = 0
        
        for order in self.exchange_orders:
            client_oid = order.get("clientOrderId", "")
            is_reduce_only = order.get("reduceOnly", False)
            
            # 保护单保留
            if is_reduce_only:
                skipped_protection += 1
                continue
            
            # 检查是否为策略单
            is_strategy_order = client_oid.startswith("s001_") if client_oid else False
            
            # 策略单保留
            if is_strategy_order:
                continue
            
            # 检查订单年龄 (如果时间戳可用)
            order_time = order.get("timestamp", 0)
            if order_time and isinstance(order_time, (int, float)):
                # 时间戳是毫秒
                order_age_sec = (now * 1000 - order_time) / 1000 if order_time > 1e10 else now - order_time
                if order_age_sec < 300:  # 5分钟内的新单不撤销
                    skipped_recent += 1
                    logger.debug(f"  保留新单: {order['symbol']} (age={order_age_sec:.0f}s)")
                    continue
            
            # 确认为幽灵单，执行撤销
            try:
                import asyncio
                await asyncio.to_thread(self.exchange.cancel_order, order["id"], order["symbol"])
                canceled += 1
                logger.info(f"  撤销幽灵单: {order['symbol']} {order['id'][:20]}...")
            except Exception as e:
                error_msg = str(e)
                if "-2011" in error_msg or "Unknown order" in error_msg:
                    # 订单已不存在
                    logger.debug(f"  订单已不存在: {order['symbol']}")
                else:
                    logger.warning(f"  撤销失败 {order['symbol']}: {error_msg[:50]}")
        
        logger.info(f"  幽灵单处理: 撤销={canceled}, 保留保护单={skipped_protection}, 保留新单={skipped_recent}")
        return canceled
    
    def get_ghost_orders_report(self) -> List[Dict]:
        """
        获取幽灵订单报告 (用于人工检查)
        
        Returns: 幽灵订单列表
        """
        ghosts = []
        for order in self.exchange_orders:
            client_oid = order.get("clientOrderId", "")
            is_reduce_only = order.get("reduceOnly", False)
            
            # 保护单不是幽灵单
            if is_reduce_only:
                continue
            
            # 策略单不是幽灵单
            if client_oid.startswith("s001_"):
                continue
            
            ghosts.append({
                "symbol": order.get("symbol"),
                "order_id": order.get("id"),
                "client_oid": client_oid or "(无)",
                "side": order.get("side"),
                "amount": order.get("amount"),
                "price": order.get("price"),
                "type": order.get("type"),
            })
        
        return ghosts
    
    # ============ 持久化接口 ============
    
    def save_position_snapshot(self, snapshot: PositionSnapshot):
        """保存仓位快照"""
        self.local_positions[snapshot.symbol] = snapshot
        self._persist_positions()
    
    def save_order_intent(self, intent: OrderIntent):
        """保存订单意图"""
        data = self._load_json(self._intents_file) or {}
        data[intent.intent_id] = asdict(intent)
        self._persist_json(self._intents_file, data)
    
    def save_order_record(self, record: OrderRecord):
        """保存订单记录"""
        self.local_orders[record.client_order_id] = record
        self._persist_orders()
    
    def _persist_positions(self):
        """持久化持仓到磁盘"""
        data = {sym: asdict(pos) for sym, pos in self.local_positions.items()}
        self._persist_json(self._positions_file, data)
    
    def _persist_orders(self):
        """持久化订单到磁盘"""
        data = {oid: asdict(ord) for oid, ord in self.local_orders.items()}
        self._persist_json(self._orders_file, data)
    
    def _persist_json(self, filepath: str, data: dict):
        """原子写入 JSON"""
        try:
            tmp_path = filepath + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, filepath)
        except Exception as e:
            logger.error(f"持久化失败 {filepath}: {e}")
    
    def _load_json(self, filepath: str) -> Optional[dict]:
        """读取 JSON"""
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return None


# ============ 便捷函数 ============

async def run_recovery_on_startup(exchange: ccxt.Exchange) -> Tuple[bool, str]:
    """
    启动时执行恢复的便捷函数
    
    Returns:
        (success, message)
    """
    try:
        recovery = RecoverySystem(exchange)
        mode, level, message = await recovery.run_recovery()
        
        success = mode in [SystemMode.TRADING, SystemMode.SAFE]
        return success, f"[{level.value}级] {message}"
        
    except Exception as e:
        logger.exception("恢复系统异常")
        return False, f"恢复失败: {str(e)}"
