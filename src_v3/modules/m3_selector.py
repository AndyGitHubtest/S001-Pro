"""
M3 Selector Module V3
配对精选模块 - 使用混合架构
"""

import logging
from typing import Optional, List, Dict

from src_v3.core import ModuleBase, HybridManager, ModuleDataPacket


class M3SelectorModule(ModuleBase):
    """
    M3配对精选模块
    
    输入: M2过滤后的币种列表 (从SQLite读取)
    处理: 协整检验、评分、排序
    输出: 精选配对列表 (发布到Redis + 持久化到SQLite)
    """
    
    def __init__(self, hybrid_manager: HybridManager, timeframe: str = "5m"):
        super().__init__("M3", hybrid_manager)
        self.timeframe = timeframe
        self.logger = logging.getLogger("M3Selector")
    
    def input(self) -> Optional[ModuleDataPacket]:
        """
        从M2读取过滤后的币种
        
        策略: 查询SQLite获取最新M2输出
        """
        # 从SQLite读取M2最新session的币种
        with self.hm.sqlite.get_reader() as conn:
            cursor = conn.execute("""
                SELECT symbol FROM m2_filtered_symbols
                WHERE session_id = (
                    SELECT MAX(session_id) FROM m2_filtered_symbols
                )
                AND filter_passed = 1
            """)
            symbols = [row["symbol"] for row in cursor.fetchall()]
        
        if not symbols:
            self.logger.warning("No symbols from M2")
            return None
        
        self.logger.info(f"M2 input: {len(symbols)} symbols")
        
        return ModuleDataPacket(
            module="M2",
            data={"symbols": symbols, "count": len(symbols)}
        )
    
    def process(self, input_packet: ModuleDataPacket) -> ModuleDataPacket:
        """
        执行配对精选
        
        简化版实现，实际应包含:
        - 从SQLite读取K线数据
        - 协整检验 (ADF测试)
        - 半衰期计算
        - 评分排序
        """
        symbols = input_packet.data["symbols"]
        total_pairs = len(symbols) * (len(symbols) - 1) // 2
        
        self.logger.info(f"Evaluating {total_pairs} pairs...")
        
        # 模拟配对计算 (实际应读取K线数据并计算)
        scored_pairs = []
        
        for i, sym_a in enumerate(symbols):
            for sym_b in symbols[i+1:]:
                # 这里应该从数据库读取K线并计算
                # 简化：模拟评分
                score = self._calculate_mock_score(sym_a, sym_b)
                
                if score > 0.3:  # 阈值过滤
                    scored_pairs.append({
                        "symbol_a": sym_a,
                        "symbol_b": sym_b,
                        "timeframe": self.timeframe,
                        "score": score,
                        "correlation": 0.8,  # 模拟值
                        "coint_pvalue": 0.05,
                        "half_life": 10.0,
                        "zscore_range": 3.0,
                        "status": "selected"
                    })
        
        # 按评分排序
        scored_pairs.sort(key=lambda x: x["score"], reverse=True)
        
        self.logger.info(f"Selected {len(scored_pairs)} pairs")
        
        return ModuleDataPacket(
            module="M3",
            data={
                "pairs": scored_pairs[:100],  # Top 100
                "count": len(scored_pairs),
                "total_evaluated": total_pairs,
                "timeframe": self.timeframe
            },
            metadata={"status": "success"}
        )
    
    def _calculate_mock_score(self, sym_a: str, sym_b: str) -> float:
        """模拟评分 (实际应基于真实数据)"""
        # 简化：基于symbol长度计算伪随机分数
        import hashlib
        h = hashlib.md5(f"{sym_a}_{sym_b}".encode()).hexdigest()
        return int(h[:4], 16) / 65535.0
    
    def output(self, packet: ModuleDataPacket) -> bool:
        """
        发布M3结果
        
        使用HybridManager:
        1. 持久化到SQLite (m3_scored_pairs表)
        2. 发布到Redis (通知M4)
        """
        pairs = packet.data.get("pairs", [])
        
        if not pairs:
            self.logger.warning("No pairs to output")
            return False
        
        try:
            # 通过HybridManager发布 (同时写入SQLite和Redis)
            success = self.hm.publish_module_output(
                module="M3",
                data=packet.data,
                session_id=self.session_id,
                persist=True
            )
            
            if success:
                packet.set_record_count(len(pairs))
                self.logger.info(f"Published {len(pairs)} pairs to M4")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to publish M3 output: {e}")
            return False
