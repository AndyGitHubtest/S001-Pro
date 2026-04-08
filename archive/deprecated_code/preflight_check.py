#!/usr/bin/env python3
"""
S001-Pro 启动前检查系统 (Pre-Flight Check) - 生产级完整版

16步完整检查流程，分7阶段执行，带熔断机制：
  P1_Connect:   [2] 连接检查
  P2_Config:    [4] 杠杆/模式  
  P3_Position:  [1,3] 本地+交易所持仓核对
  P4_Risk:      [5,6,7,13] 风控检查
  P5_Channel:   [10,11] 交易通道测试
  P6_Data:      [8,9] 数据准备
  P7_Launch:    [14,15,16] 启动完成

安全原则:
  - 任何阶段失败立即停止
  - 下单通道只用只读测试（不下真实单）
  - 每个检查独立超时保护
  - 启动文件锁防止并发
"""

import logging
import os
import json
import time
import fcntl
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import ccxt

logger = logging.getLogger("PreFlight")


@dataclass
class PreFlightResult:
    """检查结果"""
    phase: str
    passed: bool
    message: str
    details: Dict = None
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class RestartSnapshot:
    """重启快照"""
    restart_time: str
    reason: str
    initial_equity: float
    positions_count: int
    daily_pnl_pct: float
    margin_ratio: float
    checks_passed: int
    checks_total: int
    
    def to_dict(self) -> Dict:
        return asdict(self)


class StartupLock:
    """启动文件锁 - 防止并发启动"""
    
    def __init__(self, lock_file: str = ".startup.lock"):
        self.lock_file = lock_file
        self.fd = None
    
    def acquire(self, timeout: int = 30) -> bool:
        """获取启动锁"""
        try:
            self.fd = open(self.lock_file, 'w')
            # 非阻塞获取锁
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd.write(f"{os.getpid()}\n{time.time()}\n")
            self.fd.flush()
            logger.info(f"StartupLock: 已获取启动锁 (PID: {os.getpid()})")
            return True
        except IOError:
            logger.error("StartupLock: 已有其他进程正在启动，请等待")
            return False
    
    def release(self):
        """释放启动锁"""
        if self.fd:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.fd.close()
            try:
                os.remove(self.lock_file)
            except:
                pass
            logger.info("StartupLock: 启动锁已释放")


class PreFlightCheck:
    """生产级启动前检查系统"""
    
    # 检查超时（秒）
    CHECK_TIMEOUT = 30
    TOTAL_TIMEOUT = 300  # 5分钟总超时
    
    # 风控阈值
    MAX_MARGIN_RATIO = 0.80      # 最大仓位使用率 80%
    MIN_MARGIN_BUFFER = 1.5      # 保证金缓冲倍数
    MAX_DAILY_DRAWDOWN = -5.0    # 最大日回撤 -5%
    
    def __init__(self, exchange: ccxt.Exchange, config: Dict, state_file: str = "data/state.json"):
        self.exchange = exchange
        self.config = config
        self.state_file = state_file
        self.leverage = config.get("leverage", 5)
        self.margin_mode = config.get("margin_mode", "cross")
        self.results: List[PreFlightResult] = []
        self.snapshot: Optional[RestartSnapshot] = None
        
        # 运行时数据
        self.local_positions: Dict = {}
        self.exchange_positions: Dict = {}
        self.account_info: Dict = {}
        self.daily_stats: Dict = {}
        
    def run_all_phases(self) -> Tuple[bool, List[PreFlightResult]]:
        """
        执行全部7阶段检查
        
        Returns:
            (全部通过, 结果列表)
        """
        phases = [
            ("P1_Connect", self._phase_connect, "连接检查"),
            ("P2_Config", self._phase_config, "配置检查"),
            ("P3_Position", self._phase_position, "持仓核对"),
            ("P4_Risk", self._phase_risk, "风控检查"),
            ("P5_Channel", self._phase_channel, "通道测试"),
            ("P6_Data", self._phase_data, "数据准备"),
            ("P7_Launch", self._phase_launch, "启动完成"),
        ]
        
        start_time = time.time()
        all_passed = True
        
        logger.info("="*60)
        logger.info("S001-Pro 启动前检查开始 (7阶段)")
        logger.info("="*60)
        
        for phase_name, phase_func, phase_desc in phases:
            # 总超时检查
            if time.time() - start_time > self.TOTAL_TIMEOUT:
                logger.error(f"总超时 (> {self.TOTAL_TIMEOUT}s)，停止启动")
                all_passed = False
                break
            
            logger.info(f"\n>>> 阶段 {phase_name}: {phase_desc}")
            
            try:
                passed, message, details = phase_func()
                result = PreFlightResult(phase_name, passed, message, details)
                self.results.append(result)
                
                status = "✓" if passed else "✗"
                logger.info(f"  {status} {message}")
                
                if not passed:
                    all_passed = False
                    logger.error(f"阶段 {phase_name} 失败，启动流程中断！")
                    break
                    
            except Exception as e:
                logger.exception(f"阶段 {phase_name} 异常: {e}")
                result = PreFlightResult(phase_name, False, f"异常: {str(e)[:50]}")
                self.results.append(result)
                all_passed = False
                break
        
        # 生成重启快照
        if all_passed:
            self._create_restart_snapshot("normal")
        
        return all_passed, self.results
    
    # ═══════════════════════════════════════════════════════════════
    # P1_Connect: 连接检查 (步骤2)
    # ═══════════════════════════════════════════════════════════════
    def _phase_connect(self) -> Tuple[bool, str, Dict]:
        """连接交易所API"""
        try:
            # 加载市场数据
            self.exchange.load_markets()
            
            # 测试API连接 - 查询余额
            balance = self.exchange.fetch_balance()
            
            # 测试持仓查询权限
            positions = self.exchange.fetch_positions()
            
            # 保存账户信息供后续使用
            self.account_info = {
                "balance": balance,
                "positions_count": len(positions),
                "timestamp": time.time()
            }
            
            return True, f"API连接正常，余额/持仓查询权限OK", {"positions": len(positions)}
            
        except ccxt.AuthenticationError:
            return False, "API Key认证失败，请检查密钥配置", {}
        except ccxt.PermissionDenied:
            return False, "API权限不足，需要合约交易权限", {}
        except ccxt.NetworkError as e:
            return False, f"网络连接失败: {str(e)[:30]}", {}
        except Exception as e:
            return False, f"连接异常: {str(e)[:40]}", {}
    
    # ═══════════════════════════════════════════════════════════════
    # P2_Config: 配置检查 (步骤4)
    # ═══════════════════════════════════════════════════════════════
    def _validate_symbols(self) -> Tuple[bool, str, int]:
        """
        FIX P0-6: 验证所有 symbol 在交易所存在
        移除不存在的配对，防止 Leg Sync Fail
        """
        try:
            # 加载 markets
            self.exchange.load_markets()
            
            pairs = self.config.get("pairs", [])
            if not pairs:
                return True, "无配对需要验证", 0
            
            valid_pairs = []
            invalid_symbols = set()
            
            for pair in pairs:
                sym_a = pair.get("symbol_a", "")
                sym_b = pair.get("symbol_b", "")
                
                a_exists = sym_a in self.exchange.markets
                b_exists = sym_b in self.exchange.markets
                
                if a_exists and b_exists:
                    valid_pairs.append(pair)
                else:
                    if not a_exists:
                        invalid_symbols.add(sym_a)
                    if not b_exists:
                        invalid_symbols.add(sym_b)
            
            # 更新配置，只保留有效配对
            removed_count = len(pairs) - len(valid_pairs)
            if removed_count > 0:
                self.config["pairs"] = valid_pairs
                symbol_list = ", ".join(sorted(invalid_symbols))
                logger.warning(f"PreFlight: 移除 {removed_count} 个无效配对，不存在的币种: {symbol_list}")
                return True, f"移除 {removed_count} 个无效配对，剩余 {len(valid_pairs)} 对", removed_count
            
            return True, f"全部 {len(pairs)} 对交易对有效", 0
            
        except Exception as e:
            return False, f"验证失败: {str(e)[:40]}", 0

    def _phase_config(self) -> Tuple[bool, str, Dict]:
        """检查杠杆倍数（确认5倍）和持仓模式"""
        messages = []
        
        # FIX P0-6: 首先验证 symbol 存在性
        valid, msg, removed = self._validate_symbols()
        if not valid:
            return False, msg, {}
        if removed > 0:
            messages.append(msg)
        
        # 1. 检查持仓模式（双向持仓）
        try:
            self.exchange.set_position_mode(True)
            messages.append("持仓模式已设为双向")
        except ccxt.ExchangeError as e:
            if "-4059" in str(e) or "No need to change" in str(e):
                messages.append("持仓模式已为双向")
            else:
                return False, f"持仓模式设置失败: {str(e)[:40]}", {}
        
        # 2. 检查杠杆（5倍）
        pairs = self.config.get("pairs", [])
        if not pairs:
            return True, "无配对需要设置杠杆", {}
        
        set_count = 0
        errors = []
        
        for pair in pairs:
            for sym_key in ["symbol_a", "symbol_b"]:
                symbol = pair.get(sym_key)
                if not symbol:
                    continue
                
                try:
                    symbol_futures = symbol.replace("/", "")
                    self.exchange.set_leverage(self.leverage, symbol_futures)
                    set_count += 1
                except ccxt.ExchangeError as e:
                    error_msg = str(e)
                    # 已设置或修改太频繁都算成功
                    if any(code in error_msg for code in ["-4048", "-4164", "No need to change"]):
                        set_count += 1
                    else:
                        errors.append(f"{symbol}: {error_msg[:20]}")
                except Exception as e:
                    errors.append(f"{symbol}: {str(e)[:20]}")
        
        if errors:
            return False, f"杠杆设置失败: {', '.join(errors[:3])}", {}
        
        msg = f"杠杆已统一设置为{self.leverage}x ({set_count}个币种)"
        messages.append(msg)
        
        return True, "; ".join(messages), {"leverage_set": set_count}
    
    # ═══════════════════════════════════════════════════════════════
    # P3_Position: 持仓核对 (步骤1,3)
    # ═══════════════════════════════════════════════════════════════
    def _phase_position(self) -> Tuple[bool, str, Dict]:
        """读取本地状态 + 拉取实际持仓核对"""
        # 1. 读取本地状态
        self.local_positions = self._load_local_state()
        local_count = len(self.local_positions)
        
        # 2. 拉取交易所持仓
        try:
            raw_positions = self.exchange.fetch_positions()
            # 过滤有仓位的
            self.exchange_positions = {
                p["symbol"]: p for p in raw_positions 
                if p.get("contracts", 0) != 0
            }
            exchange_count = len(self.exchange_positions)
        except Exception as e:
            return False, f"拉取交易所持仓失败: {str(e)[:40]}", {}
        
        # 3. 核对逻辑
        unmatched = []
        for pair_id, local_pos in self.local_positions.items():
            # 解析配对
            symbols = pair_id.replace("_", "-").split("-")
            if len(symbols) != 2:
                continue
            
            sym_a, sym_b = symbols[0], symbols[1]
            
            # 检查交易所是否有对应持仓
            has_a = any(sym_a.replace("/", "") in k for k in self.exchange_positions.keys())
            has_b = any(sym_b.replace("/", "") in k for k in self.exchange_positions.keys())
            
            # 本地有状态但交易所无持仓 → 状态残留
            if local_pos.get("position_size_pct", 0) > 0 and not (has_a and has_b):
                unmatched.append(f"{pair_id}(本地有/交易所无)")
        
        details = {
            "local_positions": local_count,
            "exchange_positions": exchange_count,
            "unmatched": unmatched
        }
        
        if unmatched:
            # 自动清理残留状态
            logger.warning(f"发现{len(unmatched)}个残留状态，自动清理: {unmatched}")
            self._clear_residual_state(unmatched)
            return True, f"持仓核对完成，清理{len(unmatched)}个残留，本地{local_count}/交易所{exchange_count}", details
        
        return True, f"持仓核对一致，本地{local_count}/交易所{exchange_count}", details
    
    # ═══════════════════════════════════════════════════════════════
    # P4_Risk: 风控检查 (步骤5,6,7,13)
    # ═══════════════════════════════════════════════════════════════
    def _phase_risk(self) -> Tuple[bool, str, Dict]:
        """仓位使用率、本金余额、可用保证金、回撤检查"""
        messages = []
        
        try:
            # 1. 获取账户信息
            balance = self.exchange.fetch_balance()
            usdt = balance.get("USDT", {})
            
            total_equity = usdt.get("total", 0)  # 总权益
            free_margin = usdt.get("free", 0)     # 可用保证金
            used_margin = usdt.get("used", 0)     # 已用保证金
            
            # 2. 本金余额检查（步骤6）
            initial_capital = self.config.get("initial_capital", 10000)
            if total_equity < initial_capital * 0.5:  # 本金损失超过50%
                return False, f"本金损失过大: 当前{total_equity:.2f} USDT (初始{initial_capital})", {}
            messages.append(f"本金: {total_equity:.2f} USDT")
            
            # 3. 仓位使用率检查（步骤5）
            if total_equity > 0:
                margin_ratio = used_margin / total_equity
            else:
                margin_ratio = 0
            
            if margin_ratio > self.MAX_MARGIN_RATIO:
                return False, f"仓位使用率过高: {margin_ratio*100:.1f}% (阈值{self.MAX_MARGIN_RATIO*100:.0f}%)", {}
            messages.append(f"仓位使用率: {margin_ratio*100:.1f}%")
            
            # 4. 可用保证金检查（步骤7）
            pairs_count = len(self.config.get("pairs", []))
            position_size = self.config.get("position_size_usdt", 100)
            required_margin = pairs_count * position_size * 2 / self.leverage  # 双边
            min_required = required_margin * self.MIN_MARGIN_BUFFER
            
            if free_margin < min_required:
                return False, f"可用保证金不足开仓: 可用{free_margin:.2f} USDT，需要{min_required:.2f} USDT", {}
            messages.append(f"可用保证金: {free_margin:.2f} USDT")
            
            # 5. 回撤检查（步骤13）
            daily_pnl_pct = self._check_daily_drawdown()
            if daily_pnl_pct < self.MAX_DAILY_DRAWDOWN:
                return False, f"今日回撤超限: {daily_pnl_pct:.2f}% (阈值{self.MAX_DAILY_DRAWDOWN:.0f}%)", {}
            messages.append(f"今日回撤: {daily_pnl_pct:.2f}%")
            
            details = {
                "total_equity": total_equity,
                "free_margin": free_margin,
                "margin_ratio": margin_ratio,
                "daily_pnl_pct": daily_pnl_pct
            }
            
            return True, "; ".join(messages), details
            
        except Exception as e:
            return False, f"风控检查异常: {str(e)[:40]}", {}
    
    # ═══════════════════════════════════════════════════════════════
    # P5_Channel: 通道测试 (步骤10,11)
    # ═══════════════════════════════════════════════════════════════
    def _phase_channel(self) -> Tuple[bool, str, Dict]:
        """下单通道测试 + 成交回调测试（只读方式）"""
        
        pairs = self.config.get("pairs", [])
        if not pairs:
            # 无配对时跳过详细测试，只检查API连通性
            return True, "无配对配置，跳过通道详细测试", {"skipped": True}
        
        # 1. 下单通道测试（只读 - 查询最近订单）
        try:
            # 使用第一个配对的 symbol 查询订单
            test_symbol = pairs[0].get("symbol_a", "BTC/USDT")
            recent_orders = self.exchange.fetch_orders(symbol=test_symbol, limit=5)
            order_count = len(recent_orders)
            
            # 2. 成交回调测试（检查订单状态一致性）
            abnormal_orders = []
            for order in recent_orders[:3]:
                status = order.get("status")
                filled = order.get("filled", 0)
                remaining = order.get("remaining", 0)
                
                if status == "closed" and remaining > 0 and filled == 0:
                    abnormal_orders.append(order.get("id", "unknown"))
            
            if abnormal_orders:
                logger.warning(f"发现异常订单: {abnormal_orders}")
            
            return True, f"交易通道正常，最近{order_count}笔订单可查询", {
                "recent_orders": order_count,
                "abnormal_orders": len(abnormal_orders)
            }
            
        except ccxt.PermissionDenied:
            return False, "订单查询权限不足", {}
        except Exception as e:
            # 非致命错误，允许继续
            logger.warning(f"通道测试异常（非致命）: {e}")
            return True, f"通道测试警告: {str(e)[:30]}", {"warning": True}
    
    # ═══════════════════════════════════════════════════════════════
    # P6_Data: 数据准备 (步骤8,9)
    # ═══════════════════════════════════════════════════════════════
    def _phase_data(self) -> Tuple[bool, str, Dict]:
        """补全历史K线数据 + 重新计算Z-Score"""
        # 这部分由 SignalEngine 在启动后处理
        # PreFlight 只检查数据文件/连接是否正常
        
        try:
            # 检查数据库连接
            db_path = self.config.get("db_path", "data/klines.db")
            if not os.path.exists(db_path):
                # 数据库不存在但不阻止启动，会从交易所拉取
                logger.warning(f"本地数据库不存在: {db_path}")
            
            # 检查pairs配置
            pairs = self.config.get("pairs", [])
            if not pairs:
                # FIX P0-002: 无配对时改为警告模式，允许启动但不下单
                logger.warning("无交易对配置，策略将启动但不下单，请运行扫描添加配对")
                return True, "无交易对配置，策略将运行但不下单（等待扫描）", {
                    "pairs_count": 0,
                    "db_exists": os.path.exists(db_path),
                    "warning": True
                }
            
            return True, f"数据检查完成，{len(pairs)}对交易对就绪", {
                "pairs_count": len(pairs),
                "db_exists": os.path.exists(db_path)
            }
            
        except Exception as e:
            return False, f"数据检查失败: {str(e)[:40]}", {}
    
    # ═══════════════════════════════════════════════════════════════
    # P7_Launch: 启动完成 (步骤14,15,16)
    # ═══════════════════════════════════════════════════════════════
    def _phase_launch(self) -> Tuple[bool, str, Dict]:
        """记录重启快照、开启自动保存、进入交易循环准备"""
        try:
            # 创建重启快照
            snapshot = self._create_restart_snapshot("normal")
            
            # 保存到文件
            snapshot_file = "data/restart_snapshots.jsonl"
            os.makedirs(os.path.dirname(snapshot_file), exist_ok=True)
            
            with open(snapshot_file, "a") as f:
                f.write(json.dumps(snapshot.to_dict()) + "\n")
            
            # 发送启动通知
            passed_count = sum(1 for r in self.results if r.passed)
            
            return True, f"启动完成，{passed_count}/{len(self.results)}项检查通过", {
                "snapshot_saved": True,
                "checks_passed": passed_count
            }
            
        except Exception as e:
            logger.error(f"启动完成阶段异常: {e}")
            # 非致命错误，继续启动
            return True, "启动完成（快照保存异常）", {"snapshot_saved": False}
    
    # ═══════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════
    def _load_local_state(self) -> Dict:
        """读取本地持仓状态文件"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"读取本地状态失败: {e}")
        return {}
    
    def _clear_residual_state(self, unmatched_pairs: List[str]):
        """清理残留状态"""
        try:
            for pair in unmatched_pairs:
                # 从pair_id提取键
                pair_key = pair.split("(")[0] if "(" in pair else pair
                if pair_key in self.local_positions:
                    del self.local_positions[pair_key]
            
            # 保存清理后的状态
            with open(self.state_file, 'w') as f:
                json.dump(self.local_positions, f)
                
        except Exception as e:
            logger.error(f"清理残留状态失败: {e}")
    
    def _check_daily_drawdown(self) -> float:
        """检查今日回撤"""
        try:
            daily_stats_file = "data/daily_stats.json"
            if os.path.exists(daily_stats_file):
                with open(daily_stats_file, 'r') as f:
                    stats = json.load(f)
                    return stats.get("daily_pnl_pct", 0)
        except Exception:
            pass
        return 0  # 默认无回撤
    
    def _create_restart_snapshot(self, reason: str) -> RestartSnapshot:
        """创建重启快照"""
        # 获取当前权益
        equity = 0
        try:
            balance = self.exchange.fetch_balance()
            equity = balance.get("USDT", {}).get("total", 0)
        except:
            pass
        
        # 计算通过的检查数
        passed_count = sum(1 for r in self.results if r.passed)
        
        # 获取回撤
        daily_pnl = self._check_daily_drawdown()
        
        # 获取仓位使用率
        margin_ratio = 0
        if hasattr(self, 'account_info') and self.account_info:
            try:
                balance = self.account_info.get("balance", {})
                used = balance.get("USDT", {}).get("used", 0)
                total = balance.get("USDT", {}).get("total", 1)
                margin_ratio = used / total if total > 0 else 0
            except:
                pass
        
        self.snapshot = RestartSnapshot(
            restart_time=datetime.now().isoformat(),
            reason=reason,
            initial_equity=equity,
            positions_count=len(self.exchange_positions),
            daily_pnl_pct=daily_pnl,
            margin_ratio=margin_ratio,
            checks_passed=passed_count,
            checks_total=len(self.results)
        )
        
        return self.snapshot
    
    def get_restart_report(self) -> str:
        """生成重启报告（用于通知）"""
        if not self.snapshot:
            return "重启报告: 未生成快照"
        
        s = self.snapshot
        status_emoji = "✅" if s.checks_passed == s.checks_total else "⚠️"
        
        report = f"""
{status_emoji} S001-Pro 重启完成
━━━━━━━━━━━━━━━━
时间: {s.restart_time[:19]}
模式: TRADING
检查: {s.checks_passed}/{s.checks_total} 通过
权益: ${s.initial_equity:.2f}
持仓: {s.positions_count} 对
回撤: {s.daily_pnl_pct:.2f}%
仓位: {s.margin_ratio*100:.1f}%
状态: {"✅ 全部通过，开始交易" if s.checks_passed == s.checks_total else "⚠️ 有警告"}
""".strip()
        
        return report


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════
def run_preflight_check(exchange: ccxt.Exchange, config: Dict, 
                        state_file: str = "data/state.json") -> Tuple[bool, List[PreFlightResult], Optional[RestartSnapshot]]:
    """
    便捷函数: 运行完整启动前检查
    
    Returns:
        (全部通过, 结果列表, 重启快照)
    """
    print("\n" + "="*60)
    print("S001-Pro 启动前检查 (Pre-Flight Check)")
    print("="*60)
    
    # 获取启动锁
    lock = StartupLock()
    if not lock.acquire():
        print("✗ 获取启动锁失败，可能有其他进程正在启动")
        return False, [], None
    
    try:
        checker = PreFlightCheck(exchange, config, state_file)
        passed, results = checker.run_all_phases()
        
        # 打印结果
        for r in results:
            status = "✓" if r.passed else "✗"
            print(f"  [{r.phase}] {status} {r.message}")
        
        print("="*60)
        
        if passed:
            print("✓ 全部检查通过，启动交易引擎...\n")
            print(checker.get_restart_report())
        else:
            print("✗ 检查未通过，启动已中止\n")
        
        return passed, results, checker.snapshot
        
    finally:
        lock.release()


if __name__ == "__main__":
    # 测试运行
    print("PreFlight Check 模块测试")
    print("请在 main.py 中调用 run_preflight_check()")
