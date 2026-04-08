"""
持仓状态定义模块
PositionState - 单个配对的完整持仓状态
"""

from typing import Dict, Any
from src.constants import DEFAULT_POSITION_SIZE_PCT, DEFAULT_Z_ENTRY


STATE_IDLE = "IDLE"
STATE_SCALING_IN = "SCALING_IN"
STATE_IN_POSITION = "IN_POSITION"
STATE_SCALING_OUT = "SCALING_OUT"
STATE_STOPPING = "STOPPING"
STATE_EXITED = "EXITED"
STATE_CLOSING_MODE = "CLOSING_MODE"


class PositionState:
    """单个配对的持仓状态 - 纯数据类"""

    def __init__(self, pair_config: Dict):
        self.pair_config = pair_config
        self.symbol_a = pair_config["symbol_a"]
        self.symbol_b = pair_config["symbol_b"]
        self.beta = pair_config.get("beta", 1.0)
        self.state = STATE_IDLE
        self.direction = 0
        self.entry_z = 0.0
        self.scale_in_layer = 0
        self.scale_out_layer = 0
        self.position_size_pct = 0.0
        self.pending_orders = {}
        self.entry_price_a = 0.0
        self.entry_price_b = 0.0
        self.last_signal_bar = 0
        self.last_check_time = 0.0

        # 防死循环
        self.scale_out_fail_count = 0
        self.last_scale_out_fail_time = 0
        self.scale_out_cool_until = 0
        self.scale_out_fail_threshold = 3
        self.scale_out_cool_seconds = 300

        self.scale_in_fail_count = 0
        self.last_scale_in_fail_time = 0
        self.scale_in_cool_until = 0
        self.scale_in_fail_threshold = 3
        self.scale_in_cool_seconds = 600

    def to_dict(self) -> Dict:
        """序列化持仓状态 (修复CRIT-008: 包含所有关键字段)"""
        return {
            "symbol_a": self.symbol_a,
            "symbol_b": self.symbol_b,
            "beta": self.beta,
            "state": self.state,
            "direction": self.direction,
            "entry_z": self.entry_z,
            "scale_in_layer": self.scale_in_layer,
            "scale_out_layer": self.scale_out_layer,
            "position_size_pct": self.position_size_pct,
            "entry_price_a": self.entry_price_a,
            "entry_price_b": self.entry_price_b,
            "last_signal_bar": self.last_signal_bar,
            "last_check_time": self.last_check_time,
            # 修复CRIT-008: 添加缺失的关键字段
            "pending_orders": self.pending_orders,
            "scale_out_fail_count": self.scale_out_fail_count,
            "scale_out_fail_threshold": self.scale_out_fail_threshold,
            "scale_out_cool_until": self.scale_out_cool_until,
            "last_scale_out_fail_time": self.last_scale_out_fail_time,
            "scale_in_fail_count": self.scale_in_fail_count,
            "scale_in_fail_threshold": self.scale_in_fail_threshold,
            "scale_in_cool_until": self.scale_in_cool_until,
            "last_scale_in_fail_time": self.last_scale_in_fail_time,
        }
    
    @classmethod
    def from_dict(cls, data: Dict, pair_config: Dict = None) -> 'PositionState':
        """
        从字典恢复持仓状态 (修复CRIT-008)
        
        Args:
            data: 序列化后的状态字典
            pair_config: 配对配置 (可选，如果从保存的状态恢复)
        """
        if pair_config is None:
            # 从保存的数据中重建配置
            pair_config = {
                "symbol_a": data.get("symbol_a", ""),
                "symbol_b": data.get("symbol_b", ""),
                "beta": data.get("beta", 1.0),
            }
        
        ps = cls(pair_config)
        
        # 恢复基本状态
        ps.state = data.get("state", STATE_IDLE)
        ps.direction = data.get("direction", 0)
        ps.entry_z = data.get("entry_z", 0.0)
        ps.scale_in_layer = data.get("scale_in_layer", 0)
        ps.scale_out_layer = data.get("scale_out_layer", 0)
        ps.position_size_pct = data.get("position_size_pct", 0.0)
        ps.entry_price_a = data.get("entry_price_a", 0.0)
        ps.entry_price_b = data.get("entry_price_b", 0.0)
        ps.last_signal_bar = data.get("last_signal_bar", 0)
        ps.last_check_time = data.get("last_check_time", 0.0)
        
        # 修复CRIT-008: 恢复所有关键字段
        ps.pending_orders = data.get("pending_orders", {})
        ps.scale_out_fail_count = data.get("scale_out_fail_count", 0)
        ps.scale_out_fail_threshold = data.get("scale_out_fail_threshold", 3)
        ps.scale_out_cool_until = data.get("scale_out_cool_until", 0)
        ps.last_scale_out_fail_time = data.get("last_scale_out_fail_time", 0)
        ps.scale_in_fail_count = data.get("scale_in_fail_count", 0)
        ps.scale_in_fail_threshold = data.get("scale_in_fail_threshold", 3)
        ps.scale_in_cool_until = data.get("scale_in_cool_until", 0)
        ps.last_scale_in_fail_time = data.get("last_scale_in_fail_time", 0)
        
        return ps

    def is_in_cooldown(self, current_time: float, cooldown_type: str = "scale_out") -> bool:
        if cooldown_type == "scale_out":
            return current_time < self.scale_out_cool_until
        elif cooldown_type == "scale_in":
            return current_time < self.scale_in_cool_until
        return False

    def record_failure(self, current_time: float, failure_type: str = "scale_out") -> None:
        if failure_type == "scale_out":
            self.scale_out_fail_count += 1
            self.last_scale_out_fail_time = current_time
            if self.scale_out_fail_count >= self.scale_out_fail_threshold:
                self.scale_out_cool_until = current_time + self.scale_out_cool_seconds
        elif failure_type == "scale_in":
            self.scale_in_fail_count += 1
            self.last_scale_in_fail_time = current_time
            if self.scale_in_fail_count >= self.scale_in_fail_threshold:
                self.scale_in_cool_until = current_time + self.scale_in_cool_seconds

    def reset_failure_count(self, failure_type: str = "scale_out") -> None:
        if failure_type == "scale_out":
            self.scale_out_fail_count = 0
        elif failure_type == "scale_in":
            self.scale_in_fail_count = 0
