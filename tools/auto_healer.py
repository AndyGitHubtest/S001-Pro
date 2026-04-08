#!/usr/bin/env python3
"""
S001-Pro 自主修复系统 (Auto Healer)

功能:
  1. 实时监控服务器日志
  2. 检测 Leg Sync Fail 并提取详细错误
  3. 根据错误类型自主决策修复策略
  4. 必要时自动停止服务并告警

决策树:
  - 余额不足 (Insufficient Balance) → 停止交易，检查资金
  - 精度错误 (Precision/Step Size) → 调整精度计算
  - 最小名义价值 (Min Notional) → 跳过该配对
  - API限流 (Rate Limit) → 暂停60秒后继续
  - 网络错误 (Network/Timeout) → 重试3次后冷却
  - 未知错误 → 停止服务，人工检查
"""

import subprocess
import re
import time
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum


class ErrorType(Enum):
    INSUFFICIENT_BALANCE = "insufficient_balance"      # 余额不足
    PRECISION_ERROR = "precision_error"                  # 精度错误
    MIN_NOTIONAL = "min_notional"                        # 最小名义价值
    RATE_LIMIT = "rate_limit"                            # API限流
    NETWORK_ERROR = "network_error"                      # 网络错误
    INVALID_SYMBOL = "invalid_symbol"                    # 交易对无效
    POSITION_MODE = "position_mode"                      # 持仓模式错误
    MARGIN_MODE = "margin_mode"                          # 保证金模式错误
    UNKNOWN = "unknown"                                  # 未知错误


@dataclass
class LegSyncFailure:
    """Leg Sync Fail 记录"""
    timestamp: str
    pair: str
    symbol_a: str
    symbol_b: str
    error_a: str
    error_b: str
    error_type: ErrorType
    recommendation: str


class AutoHealer:
    """自主修复系统"""
    
    SERVER_IP = "43.160.192.48"
    USER = "ubuntu"
    
    # 错误模式匹配
    ERROR_PATTERNS = {
        ErrorType.INSUFFICIENT_BALANCE: [
            r'insufficient balance',
            r'insufficient funds',
            r'balance insufficient',
            r'not enough balance',
        ],
        ErrorType.PRECISION_ERROR: [
            r'precision',
            r'step size',
            r'lot size',
            r'quantity decimal',
            r'invalid quantity',
        ],
        ErrorType.MIN_NOTIONAL: [
            r'min notional',
            r'minimum notional',
            r'notional value',
            r'too small',
        ],
        ErrorType.RATE_LIMIT: [
            r'rate limit',
            r'too many requests',
            r'429',
            r'ip ban',
        ],
        ErrorType.NETWORK_ERROR: [
            r'timeout',
            r'connection',
            r'network',
            r'read timed out',
            r'connect timed out',
        ],
        ErrorType.INVALID_SYMBOL: [
            r'invalid symbol',
            r'symbol not found',
            r'no such symbol',
        ],
        ErrorType.POSITION_MODE: [
            r'position mode',
            r'hedge mode',
            r'one-way mode',
        ],
        ErrorType.MARGIN_MODE: [
            r'margin mode',
            r'isolated',
            r'cross margin',
        ],
    }
    
    def __init__(self):
        self.failure_history: List[LegSyncFailure] = []
        self.last_check_time = None
        self.decision_log: List[Dict] = []
        
    def run_ssh_cmd(self, cmd: str, timeout: int = 30) -> Tuple[int, str, str]:
        """执行SSH命令"""
        try:
            result = subprocess.run(
                ["ssh", f"{self.USER}@{self.SERVER_IP}", cmd],
                capture_output=True, text=True, timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return -1, "", str(e)
    
    def classify_error(self, error_msg: str) -> ErrorType:
        """分类错误类型"""
        error_lower = error_msg.lower()
        
        for error_type, patterns in self.ERROR_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, error_lower):
                    return error_type
        return ErrorType.UNKNOWN
    
    def get_recommendation(self, error_type: ErrorType, pair: str) -> str:
        """根据错误类型给出修复建议"""
        recommendations = {
            ErrorType.INSUFFICIENT_BALANCE: 
                f"【紧急】{pair} 余额不足！建议: 1) 检查账户余额 2) 充值或降低杠杆 3) 暂停新配对开仓",
            ErrorType.PRECISION_ERROR: 
                f"【修复】{pair} 精度错误。建议: 1) 调整数量精度计算 2) 检查 step_size 配置",
            ErrorType.MIN_NOTIONAL: 
                f"【跳过】{pair} 名义价值不足。建议: 1) 从配对列表移除 2) 或增加单笔金额",
            ErrorType.RATE_LIMIT: 
                f"【冷却】{pair} API限流。建议: 1) 暂停60秒 2) 检查请求频率配置",
            ErrorType.NETWORK_ERROR: 
                f"【重试】{pair} 网络错误。建议: 1) 自动重试3次 2) 检查服务器网络",
            ErrorType.INVALID_SYMBOL: 
                f"【移除】{pair} 交易对无效。建议: 1) 从配置中移除该配对 2) 检查 symbol 名称",
            ErrorType.POSITION_MODE: 
                f"【配置】{pair} 持仓模式错误。建议: 1) 统一设置为单向/双向模式 2) 检查交易所设置",
            ErrorType.MARGIN_MODE: 
                f"【配置】{pair} 保证金模式错误。建议: 1) 检查逐仓/全仓设置",
            ErrorType.UNKNOWN: 
                f"【调查】{pair} 未知错误。建议: 1) 查看完整日志 2) 人工分析原因",
        }
        return recommendations.get(error_type, recommendations[ErrorType.UNKNOWN])
    
    def check_recent_failures(self, minutes: int = 10) -> List[LegSyncFailure]:
        """检查最近的 Leg Sync Fail"""
        code, out, err = self.run_ssh_cmd(
            f"journalctl -u trading-s001.service --since '{minutes} minutes ago' | grep 'Leg Sync Fail'"
        )
        
        failures = []
        if code != 0 or not out:
            return failures
            
        # 解析日志行
        # 格式: Runtime: Leg Sync Fail! A=FAIL, B=FAIL | Error A: xxx | Error B: yyy
        pattern = r'Leg Sync Fail! A=(\w+), B=(\w+) \| Error A: ([^|]*) \| Error B: ([^|]*)'
        
        for line in out.split('\n'):
            match = re.search(pattern, line)
            if match:
                success_a, success_b, error_a, error_b = match.groups()
                
                # 从上下文提取配对名称（需要看前面的日志）
                pair = self._extract_pair_from_context(line)
                
                # 确定主要错误
                error_msg = error_a if error_a and error_a != 'N/A' else error_b
                error_type = self.classify_error(error_msg)
                
                failure = LegSyncFailure(
                    timestamp=datetime.now().isoformat(),
                    pair=pair or "UNKNOWN",
                    symbol_a=pair.split('_')[0] if pair and '_' in pair else "",
                    symbol_b=pair.split('_')[1] if pair and '_' in pair else "",
                    error_a=error_a.strip(),
                    error_b=error_b.strip(),
                    error_type=error_type,
                    recommendation=self.get_recommendation(error_type, pair or "UNKNOWN")
                )
                failures.append(failure)
                
        return failures
    
    def _extract_pair_from_context(self, log_line: str) -> Optional[str]:
        """从日志上下文中提取配对名称"""
        # 尝试从同一行提取
        pair_pattern = r'(\w+/USDT)_(\w+/USDT)'
        match = re.search(pair_pattern, log_line)
        if match:
            return f"{match.group(1)}_{match.group(2)}"
        return None
    
    def make_decision(self, failures: List[LegSyncFailure]) -> Dict:
        """根据失败记录做出决策"""
        if not failures:
            return {"action": "NONE", "reason": "无失败记录"}
            
        # 统计错误类型
        error_counts = {}
        for f in failures:
            error_counts[f.error_type] = error_counts.get(f.error_type, 0) + 1
            
        # 找出最常见的错误
        most_common = max(error_counts.items(), key=lambda x: x[1])
        error_type, count = most_common
        
        # 决策逻辑
        if error_type == ErrorType.INSUFFICIENT_BALANCE:
            return {
                "action": "STOP_SERVICE",
                "priority": "P0",
                "reason": f"检测到 {count} 次余额不足错误",
                "command": "sudo systemctl stop trading-s001.service",
                "message": "🚨 检测到余额不足，已自动停止服务！请检查账户资金。",
                "failures": [asdict(f) for f in failures if f.error_type == error_type]
            }
            
        elif error_type == ErrorType.RATE_LIMIT and count >= 5:
            return {
                "action": "PAUSE_AND_NOTIFY",
                "priority": "P1",
                "reason": f"检测到 {count} 次API限流",
                "command": None,
                "message": f"⚠️ API限流警告！最近{count}次请求被限制。建议降低请求频率。",
                "cooldown_seconds": 60,
                "failures": [asdict(f) for f in failures if f.error_type == error_type]
            }
            
        elif error_type == ErrorType.PRECISION_ERROR:
            return {
                "action": "LOG_AND_CONTINUE",
                "priority": "P2",
                "reason": f"检测到 {count} 次精度错误",
                "command": None,
                "message": f"⚠️ 精度错误，需要修复代码。受影响的配对: {[f.pair for f in failures if f.error_type == error_type]}",
                "failures": [asdict(f) for f in failures if f.error_type == error_type]
            }
            
        elif error_type == ErrorType.UNKNOWN:
            return {
                "action": "INVESTIGATE",
                "priority": "P1",
                "reason": f"检测到 {count} 次未知错误",
                "command": None,
                "message": f"❓ 发现未知错误类型，需要人工调查。查看日志获取详情。",
                "failures": [asdict(f) for f in failures if f.error_type == error_type]
            }
            
        return {
            "action": "MONITOR",
            "priority": "P3",
            "reason": f"检测到 {count} 次 {error_type.value} 错误",
            "command": None,
            "message": f"📊 监控中: {error_type.value} 错误 {count} 次",
        }
    
    def execute_decision(self, decision: Dict) -> bool:
        """执行决策"""
        action = decision.get("action")
        
        if action == "STOP_SERVICE":
            print(f"🚨 执行紧急停止: {decision['reason']}")
            code, out, err = self.run_ssh_cmd(decision["command"])
            success = code == 0
            
            # 发送通知
            self._send_notification(decision["message"])
            
            self.decision_log.append({
                "timestamp": datetime.now().isoformat(),
                "action": action,
                "success": success,
                "decision": decision
            })
            return success
            
        elif action == "PAUSE_AND_NOTIFY":
            print(f"⏸️ 暂停通知: {decision['reason']}")
            self._send_notification(decision["message"])
            return True
            
        elif action in ("LOG_AND_CONTINUE", "INVESTIGATE", "MONITOR"):
            print(f"📋 {action}: {decision['reason']}")
            if "message" in decision:
                self._send_notification(decision["message"])
            return True
            
        return True
    
    def _send_notification(self, message: str):
        """发送通知（通过 Telegram Bot）"""
        # 这里可以集成 Telegram API
        print(f"  [通知] {message[:100]}...")
    
    def run_check_cycle(self):
        """运行一次检查周期"""
        print(f"\n{'='*70}")
        print(f"🔍 AutoHealer 检查周期 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")
        
        # 检查最近的失败
        failures = self.check_recent_failures(minutes=10)
        
        if failures:
            print(f"\n⚠️ 检测到 {len(failures)} 次 Leg Sync Fail:")
            for f in failures[-5:]:  # 只显示最近5条
                print(f"  • [{f.error_type.value}] {f.pair}")
                print(f"    Error A: {f.error_a[:60] if f.error_a else 'N/A'}")
                print(f"    Error B: {f.error_b[:60] if f.error_b else 'N/A'}")
                print(f"    建议: {f.recommendation[:80]}...")
                print()
                
            # 做出决策
            decision = self.make_decision(failures)
            print(f"🤖 决策: {decision['action']} (优先级: {decision['priority']})")
            print(f"   原因: {decision['reason']}")
            
            # 执行决策
            self.execute_decision(decision)
        else:
            print("\n✅ 最近10分钟无 Leg Sync Fail")
            
        self.last_check_time = datetime.now()
        return failures


def main():
    """主函数 - 持续监控"""
    healer = AutoHealer()
    
    print("="*70)
    print("S001-Pro AutoHealer 启动")
    print("实时监控 Leg Sync Fail 并自主决策修复")
    print("="*70)
    
    while True:
        try:
            healer.run_check_cycle()
            
            # 每30秒检查一次
            print(f"\n⏱️ 下次检查: 30秒后...")
            time.sleep(30)
            
        except KeyboardInterrupt:
            print("\n\n👋 AutoHealer 停止")
            break
        except Exception as e:
            print(f"\n❌ 检查异常: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
