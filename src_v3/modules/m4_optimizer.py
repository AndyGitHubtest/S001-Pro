"""
M4模块 - 参数优化
使用IS/OS验证框架进行参数优化
"""

import json
import numpy as np
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from ..core.database import DatabaseManager
from ..core.data_packet import ModuleDataPacket
from ..core.module_base import ModuleBase


class M4OptimizerModule(ModuleBase):
    """
    M4参数优化模块
    
    职责:
    1. 读取M3评分后的配对
    2. 执行IS(样本内)参数搜索
    3. OS(样本外)验证PF>=阈值
    4. 选择最优参数组合
    
    优化参数:
    - z_entry: 入场Z-score (1.5-2.5)
    - z_exit: 出场Z-score (0.3-1.0)
    - z_stop: 止损Z-score (2.5-3.5)
    """
    
    def __init__(self, db_manager: DatabaseManager, 
                 timeframe: str = "5m",
                 is_ratio: float = 0.81,
                 min_pf: float = 1.0):
        super().__init__("M4", db_manager)
        self.timeframe = timeframe
        self.is_ratio = is_ratio  # IS样本比例
        self.min_pf = min_pf      # OS最小Profit Factor
        
        self.logger = logging.getLogger("M4.Optimizer")
        
        # 参数搜索空间
        self.param_grid = {
            "z_entry": [1.8, 2.0, 2.2, 2.5],
            "z_exit": [0.2, 0.4, 0.6],
            "z_stop": [3.0, 3.5]
        }
    
    def input(self) -> Optional[ModuleDataPacket]:
        """从M3读取评分后的配对"""
        latest_session = self.db.get_latest_session("M3")
        if not latest_session:
            self.logger.warning("No M3 session found")
            return None
        
        # 读取M3输出的配对
        rows = self.db.execute_read(
            """SELECT * FROM m3_scored_pairs 
               WHERE session_id = ? AND timeframe = ?
               ORDER BY score DESC""",
            (latest_session, self.timeframe)
        )
        
        if not rows:
            self.logger.warning(f"No pairs from M3 session {latest_session}")
            return None
        
        pairs = [dict(row) for row in rows]
        
        self.logger.info(f"M3 input: {len(pairs)} pairs from session {latest_session}")
        
        return ModuleDataPacket(
            module="M3",
            session_id=latest_session,
            data={
                "pairs": pairs,
                "count": len(pairs),
                "timeframe": self.timeframe
            }
        )
    
    def process(self, input_packet: ModuleDataPacket) -> ModuleDataPacket:
        """执行参数优化"""
        pairs = input_packet.data["pairs"]
        
        self.logger.info(f"Optimizing {len(pairs)} pairs...")
        
        optimized = []
        for i, pair in enumerate(pairs):
            if i % 10 == 0:
                self.update_status("running", f"Optimizing pairs {i}/{len(pairs)}",
                    int(50 + 40 * i / len(pairs)))
            
            result = self._optimize_pair(pair)
            if result:
                optimized.append(result)
        
        # 按综合评分排序
        optimized.sort(key=lambda x: x["final_score"], reverse=True)
        
        self.logger.info(f"Optimized {len(optimized)} pairs passing PF>={self.min_pf}")
        
        return ModuleDataPacket(
            module="M4",
            data={
                "pairs": optimized,
                "total_evaluated": len(pairs),
                "total_passed": len(optimized),
                "timeframe": self.timeframe,
                "min_pf": self.min_pf
            }
        )
    
    def output(self, packet: ModuleDataPacket) -> bool:
        """写入M4结果"""
        try:
            pairs = packet.data["pairs"]
            
            with self.db.get_writer() as conn:
                for pair in pairs:
                    conn.execute("""
                        INSERT INTO m4_optimized_pairs
                        (session_id, m3_id, symbol_a, symbol_b, timeframe,
                         z_entry, z_exit, z_stop, beta,
                         is_pf, is_dd, is_n, is_wr, is_sharpe,
                         os_pf, os_dd, os_n, os_wr, os_sharpe,
                         final_score, selected)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        self.session_id,
                        pair.get("m3_id"),
                        pair["symbol_a"],
                        pair["symbol_b"],
                        self.timeframe,
                        pair["params"]["z_entry"],
                        pair["params"]["z_exit"],
                        pair["params"]["z_stop"],
                        pair["params"].get("beta", 1.0),
                        pair["is_results"]["pf"],
                        pair["is_results"]["dd"],
                        pair["is_results"]["n"],
                        pair["is_results"]["wr"],
                        pair["is_results"].get("sharpe", 0),
                        pair["os_results"]["pf"],
                        pair["os_results"]["dd"],
                        pair["os_results"]["n"],
                        pair["os_results"]["wr"],
                        pair["os_results"].get("sharpe", 0),
                        pair["final_score"],
                        1 if pair.get("selected") else 0
                    ))
            
            self.logger.info(f"Written {len(pairs)} pairs to m4_optimized_pairs")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to write M4 output: {e}")
            return False
    
    def _optimize_pair(self, pair: Dict) -> Optional[Dict]:
        """优化单个配对"""
        sym_a = pair["symbol_a"]
        sym_b = pair["symbol_b"]
        
        # 加载数据
        data_a = self._load_klines(sym_a)
        data_b = self._load_klines(sym_b)
        
        if len(data_a) < 500 or len(data_b) < 500:
            return None
        
        # 对齐
        min_len = min(len(data_a), len(data_b))
        closes_a = np.array([x["close"] for x in data_a[:min_len]])
        closes_b = np.array([x["close"] for x in data_b[:min_len]])
        
        # 计算hedge ratio (简化版，可用Kalman filter)
        beta = pair.get("correlation", 0.8)
        
        # 计算spread和z-score
        spread = closes_a - beta * closes_b
        zscore = (spread - np.mean(spread)) / np.std(spread)
        
        # IS/OS分割
        split_idx = int(len(zscore) * self.is_ratio)
        z_is = zscore[:split_idx]
        z_os = zscore[split_idx:]
        
        best_result = None
        best_score = 0
        
        # 网格搜索
        for z_entry in self.param_grid["z_entry"]:
            for z_exit in self.param_grid["z_exit"]:
                for z_stop in self.param_grid["z_stop"]:
                    # IS回测
                    is_result = self._backtest(z_is, z_entry, z_exit, z_stop)
                    
                    # OS验证
                    os_result = self._backtest(z_os, z_entry, z_exit, z_stop)
                    
                    # OS必须满足PF要求
                    if os_result["pf"] >= self.min_pf and os_result["n"] >= 10:
                        # 综合评分
                        score = (is_result["pf"] * 0.4 + os_result["pf"] * 0.4 + 
                                is_result["wr"] * 0.2)
                        
                        if score > best_score:
                            best_score = score
                            best_result = {
                                "symbol_a": sym_a,
                                "symbol_b": sym_b,
                                "m3_id": pair.get("id"),
                                "params": {
                                    "z_entry": z_entry,
                                    "z_exit": z_exit,
                                    "z_stop": z_stop,
                                    "beta": beta
                                },
                                "is_results": is_result,
                                "os_results": os_result,
                                "final_score": round(score, 4),
                                "selected": score > 1.2  # 选中阈值
                            }
        
        return best_result
    
    def _load_klines(self, symbol: str) -> List[Dict]:
        """加载K线"""
        rows = self.db.execute_read(
            """SELECT * FROM m1_raw_klines 
               WHERE symbol = ? AND timeframe = ?
               ORDER BY timestamp DESC LIMIT 5000""",
            (symbol, self.timeframe)
        )
        return [dict(row) for row in rows]
    
    def _backtest(self, zscore: np.ndarray, z_entry: float, 
                  z_exit: float, z_stop: float) -> Dict:
        """简化回测"""
        trades = []
        in_position = False
        entry_z = 0
        
        for i, z in enumerate(zscore):
            if not in_position:
                if abs(z) > z_entry:
                    in_position = True
                    entry_z = z
            else:
                # 出场条件
                exit_condition = (
                    (entry_z > 0 and z < z_exit) or  # 正Z-score回归
                    (entry_z < 0 and z > -z_exit) or  # 负Z-score回归
                    abs(z) > z_stop  # 止损
                )
                
                if exit_condition:
                    pnl = abs(entry_z) - abs(z) if entry_z * z > 0 else -abs(z_stop)
                    trades.append(pnl)
                    in_position = False
        
        if not trades:
            return {"pf": 0, "dd": 0, "n": 0, "wr": 0, "sharpe": 0}
        
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t <= 0]
        
        pf = sum(wins) / abs(sum(losses)) if losses else 999
        wr = len(wins) / len(trades) if trades else 0
        
        return {
            "pf": round(pf, 2),
            "dd": round(min(trades), 4),
            "n": len(trades),
            "wr": round(wr, 2),
            "sharpe": round(np.mean(trades) / np.std(trades) if trades else 0, 2)
        }
