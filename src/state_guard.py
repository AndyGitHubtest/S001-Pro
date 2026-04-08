"""
状态一致性保护模块
S001-Pro 数据完整性保障

提供:
- 状态不变量检查
- 数据一致性验证
- 自动修复机制
- 异常状态回滚
"""

import json
import logging
from typing import Dict, List, Callable, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path
import asyncio

logger = logging.getLogger("StateGuard")


@dataclass
class StateInvariant:
    """状态不变量定义"""
    name: str
    check_func: Callable[[Dict], Tuple[bool, str]]
    auto_fix: Optional[Callable[[Dict], Dict]] = None
    critical: bool = True


class StateGuard:
    """
    状态守卫
    
    确保系统状态始终满足关键不变量，自动检测并修复异常状态
    """
    
    def __init__(self, state_file: Path = Path("data/state_guard.json")):
        self.state_file = state_file
        self.invariants: List[StateInvariant] = []
        self.violations: List[Dict] = []
        self._register_default_invariants()
        logger.info("StateGuard initialized")
    
    def _register_default_invariants(self):
        """注册默认不变量"""
        # 不变量1: 持仓数量不能为负
        self.register_invariant(StateInvariant(
            name="non_negative_position",
            check_func=self._check_non_negative_position,
            auto_fix=self._fix_non_negative_position,
            critical=True
        ))
        
        # 不变量2: 杠杆必须在合理范围
        self.register_invariant(StateInvariant(
            name="valid_leverage",
            check_func=self._check_valid_leverage,
            auto_fix=None,  # 不自动修复，需要人工确认
            critical=True
        ))
        
        # 不变量3: 配对状态一致性
        self.register_invariant(StateInvariant(
            name="position_state_consistency",
            check_func=self._check_state_consistency,
            auto_fix=self._fix_state_consistency,
            critical=False
        ))
    
    def register_invariant(self, invariant: StateInvariant):
        """注册状态不变量"""
        self.invariants.append(invariant)
        logger.debug(f"Invariant registered: {invariant.name}")
    
    def validate_state(self, state: Dict) -> Tuple[bool, List[str]]:
        """
        验证状态一致性
        
        Args:
            state: 当前状态
            
        Returns:
            (是否通过, 错误列表)
        """
        errors = []
        fixed_state = state.copy()
        
        for invariant in self.invariants:
            try:
                passed, message = invariant.check_func(fixed_state)
                
                if not passed:
                    error_msg = f"Invariant violated: {invariant.name} - {message}"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    
                    # 记录违规
                    self.violations.append({
                        "invariant": invariant.name,
                        "message": message,
                        "state": str(state)[:200]  # 截断避免过大
                    })
                    
                    # 尝试自动修复
                    if invariant.auto_fix:
                        try:
                            fixed_state = invariant.auto_fix(fixed_state)
                            logger.info(f"Auto-fixed invariant: {invariant.name}")
                        except Exception as e:
                            logger.error(f"Auto-fix failed for {invariant.name}: {e}")
                            if invariant.critical:
                                return False, errors
            
            except Exception as e:
                logger.error(f"Invariant check failed: {invariant.name} - {e}")
                if invariant.critical:
                    return False, [f"Check error: {e}"]
        
        return len(errors) == 0, errors
    
    # ═══════════════════════════════════════════════════
    # 默认不变量检查
    # ═══════════════════════════════════════════════════
    
    def _check_non_negative_position(self, state: Dict) -> Tuple[bool, str]:
        """检查持仓非负"""
        for pair_key, pos in state.items():
            if isinstance(pos, dict):
                contracts = pos.get("contracts", 0)
                if isinstance(contracts, (int, float)) and contracts < 0:
                    return False, f"Negative contracts: {pair_key} = {contracts}"
        return True, ""
    
    def _fix_non_negative_position(self, state: Dict) -> Dict:
        """修复负持仓"""
        fixed = state.copy()
        for pair_key, pos in fixed.items():
            if isinstance(pos, dict):
                contracts = pos.get("contracts", 0)
                if isinstance(contracts, (int, float)) and contracts < 0:
                    pos["contracts"] = 0
                    logger.warning(f"Fixed negative contracts for {pair_key}")
        return fixed
    
    def _check_valid_leverage(self, state: Dict) -> Tuple[bool, str]:
        """检查杠杆有效性"""
        for pair_key, pos in state.items():
            if isinstance(pos, dict):
                leverage = pos.get("leverage", 1)
                if not (1 <= leverage <= 125):
                    return False, f"Invalid leverage: {pair_key} = {leverage}"
        return True, ""
    
    def _check_state_consistency(self, state: Dict) -> Tuple[bool, str]:
        """检查状态一致性"""
        for pair_key, pos in state.items():
            if isinstance(pos, dict):
                # 检查状态字符串有效性
                status = pos.get("status", "")
                valid_statuses = ["IDLE", "SCALING_IN", "IN_POSITION", "COOLDOWN", "STOPPING"]
                if status and status not in valid_statuses:
                    return False, f"Invalid status: {pair_key} = {status}"
        return True, ""
    
    def _fix_state_consistency(self, state: Dict) -> Dict:
        """修复状态一致性"""
        fixed = state.copy()
        valid_statuses = ["IDLE", "SCALING_IN", "IN_POSITION", "COOLDOWN", "STOPPING"]
        
        for pair_key, pos in fixed.items():
            if isinstance(pos, dict):
                status = pos.get("status", "")
                if status and status not in valid_statuses:
                    pos["status"] = "IDLE"  # 重置为IDLE
                    logger.warning(f"Fixed invalid status for {pair_key}: {status} -> IDLE")
        
        return fixed
    
    def get_violations_report(self) -> Dict:
        """获取违规报告"""
        return {
            "total_violations": len(self.violations),
            "recent_violations": self.violations[-10:],
            "invariants_count": len(self.invariants)
        }


# 全局实例
state_guard = StateGuard()
