"""
自诊断机制模块
统一格式的日志追踪和故障定位
"""

import time
import sys
import logging
from functools import wraps
from datetime import datetime
from typing import Any, Optional, Dict
import traceback

# 全局诊断配置
DIAG_CONFIG = {
    "enabled": True,
    "log_level": "INFO",
    "include_timestamp": True,
    "include_lineno": True,
    "include_module": True,
}

# 步骤计数器
_step_counters: Dict[str, int] = {}
_progress_counters: Dict[str, Dict] = {}


def _get_caller_info():
    """获取调用者信息"""
    frame = sys._getframe(2)  # 跳过当前函数和调用者
    filename = frame.f_code.co_filename
    lineno = frame.f_lineno
    module = frame.f_globals.get('__name__', 'unknown')
    
    # 简化文件名
    if '/' in filename:
        filename = filename.split('/')[-1]
    if '\\' in filename:
        filename = filename.split('\\')[-1]
    
    return module, lineno, filename


def _format_prefix(module: str = None, lineno: int = None) -> str:
    """格式化诊断前缀"""
    parts = []
    
    if DIAG_CONFIG["include_timestamp"]:
        parts.append(datetime.now().strftime("%H:%M:%S.%f")[:-3])
    
    if DIAG_CONFIG["include_module"] and module:
        parts.append(module)
    
    if DIAG_CONFIG["include_lineno"] and lineno:
        parts.append(f"L{lineno}")
    
    return "[" + "|".join(parts) + "]"


def diag_step(step_num: int, description: str, **context):
    """
    [STEP X] 执行追踪
    
    Args:
        step_num: 步骤编号
        description: 步骤描述
        **context: 额外上下文信息
    """
    if not DIAG_CONFIG["enabled"]:
        return
    
    module, lineno, _ = _get_caller_info()
    prefix = _format_prefix(module, lineno)
    
    context_str = " ".join([f"{k}={v}" for k, v in context.items()]) if context else ""
    
    logging.info(f"{prefix} [STEP {step_num}] {description} {context_str}".strip())


def diag_state(variable_name: str, value: Any, **extra):
    """
    [STATE] 状态快照
    
    Args:
        variable_name: 变量名
        value: 变量值
        **extra: 额外状态
    """
    if not DIAG_CONFIG["enabled"]:
        return
    
    module, lineno, _ = _get_caller_info()
    prefix = _format_prefix(module, lineno)
    
    # 格式化值
    if isinstance(value, float):
        value_str = f"{value:.6f}"
    elif isinstance(value, dict):
        value_str = str({k: f"{v:.4f}" if isinstance(v, float) else v for k, v in list(value.items())[:5]})
    else:
        value_str = str(value)[:100]
    
    extra_str = " ".join([f"{k}={v}" for k, v in extra.items()]) if extra else ""
    
    logging.info(f"{prefix} [STATE] {variable_name}={value_str} {extra_str}".strip())


def diag_error(location: str, error: Exception, **context):
    """
    [ERROR @位置] 故障定位
    
    Args:
        location: 错误发生位置描述
        error: 异常对象
        **context: 当时的上下文变量
    """
    if not DIAG_CONFIG["enabled"]:
        return
    
    module, lineno, _ = _get_caller_info()
    prefix = _format_prefix(module, lineno)
    
    error_type = type(error).__name__
    error_msg = str(error)[:200]
    
    context_str = " ".join([f"{k}={v}" for k, v in context.items()]) if context else ""
    
    logging.error(f"{prefix} [ERROR @{location}] {error_type}: {error_msg}")
    if context_str:
        logging.error(f"{prefix} [ERROR_CONTEXT] {context_str}")
    
    # 打印堆栈跟踪（调试级别）
    logging.debug(f"{prefix} [ERROR_TRACE] {traceback.format_exc()}")


def diag_progress(current: int, total: int, operation: str = "", **metrics):
    """
    [PROGRESS] 进度看板
    
    Args:
        current: 当前进度
        total: 总数
        operation: 操作名称
        **metrics: 额外指标
    """
    if not DIAG_CONFIG["enabled"]:
        return
    
    module, lineno, _ = _get_caller_info()
    prefix = _format_prefix(module, lineno)
    
    pct = (current / total * 100) if total > 0 else 0
    
    metrics_str = " ".join([f"{k}={v}" for k, v in metrics.items()]) if metrics else ""
    
    logging.info(f"{prefix} [PROGRESS] {current}/{total} ({pct:.1f}%) {operation} {metrics_str}".strip())


def diag_timeout(location: str, timeout_sec: float, **context):
    """
    [TIMEOUT] 死锁检测
    
    Args:
        location: 卡住的位置
        timeout_sec: 超时时间(秒)
        **context: 上下文信息
    """
    if not DIAG_CONFIG["enabled"]:
        return
    
    module, lineno, _ = _get_caller_info()
    prefix = _format_prefix(module, lineno)
    
    context_str = " ".join([f"{k}={v}" for k, v in context.items()]) if context else ""
    
    logging.error(f"{prefix} [TIMEOUT] 卡在 {location} 超过 {timeout_sec}s {context_str}".strip())


class DiagTimer:
    """计时器上下文管理器"""
    
    def __init__(self, operation: str, timeout_sec: Optional[float] = None):
        self.operation = operation
        self.timeout_sec = timeout_sec
        self.start_time = None
        self.module = None
        self.lineno = None
    
    def __enter__(self):
        frame = sys._getframe(1)
        self.module = frame.f_globals.get('__name__', 'unknown')
        self.lineno = frame.f_lineno
        
        self.start_time = time.time()
        prefix = _format_prefix(self.module, self.lineno)
        logging.info(f"{prefix} [TIMER_START] {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.time() - self.start_time
        prefix = _format_prefix(self.module, self.lineno)
        
        if exc_type:
            logging.error(f"{prefix} [TIMER_FAIL] {self.operation} 失败 after {elapsed:.3f}s: {exc_type.__name__}")
        else:
            level = logging.WARNING if (self.timeout_sec and elapsed > self.timeout_sec) else logging.INFO
            logging.log(level, f"{prefix} [TIMER_END] {self.operation} 完成 in {elapsed:.3f}s")
        
        return False


class ProgressTracker:
    """进度追踪器"""
    
    def __init__(self, total: int, operation: str, report_every: int = 10):
        self.total = total
        self.operation = operation
        self.report_every = report_every
        self.current = 0
        self.start_time = time.time()
        self.module = None
        self.lineno = None
        
        frame = sys._getframe(1)
        self.module = frame.f_globals.get('__name__', 'unknown')
        self.lineno = frame.f_lineno
        
        prefix = _format_prefix(self.module, self.lineno)
        logging.info(f"{prefix} [PROGRESS_START] {operation} 总数={total}")
    
    def update(self, increment: int = 1, **metrics):
        """更新进度"""
        self.current += increment
        
        if self.current % self.report_every == 0 or self.current == self.total:
            elapsed = time.time() - self.start_time
            avg_time = elapsed / self.current if self.current > 0 else 0
            remaining = (self.total - self.current) * avg_time
            
            diag_progress(
                self.current, 
                self.total, 
                self.operation,
                elapsed=f"{elapsed:.1f}s",
                remaining=f"{remaining:.1f}s",
                avg=f"{avg_time*1000:.1f}ms",
                **metrics
            )
    
    def finish(self):
        """完成进度"""
        elapsed = time.time() - self.start_time
        prefix = _format_prefix(self.module, self.lineno)
        logging.info(f"{prefix} [PROGRESS_END] {self.operation} 完成 {self.current}/{self.total} in {elapsed:.3f}s")


# 装饰器版本
def diag_step_decorator(step_num: int, description: str):
    """步骤追踪装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            diag_step(step_num, description, func=func.__name__)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def diag_timer_decorator(operation: str, timeout_sec: Optional[float] = None):
    """计时装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with DiagTimer(operation, timeout_sec):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def enable_diagnostics(enabled: bool = True):
    """启用/禁用诊断"""
    DIAG_CONFIG["enabled"] = enabled


def configure_diagnostics(**kwargs):
    """配置诊断参数"""
    DIAG_CONFIG.update(kwargs)


# 便捷的grep搜索关键词
def print_diag_help():
    """打印诊断帮助信息"""
    help_text = """
    ╔══════════════════════════════════════════════════════════════╗
    ║              S001-Pro 自诊断系统 - 搜索指南                    ║
    ╚══════════════════════════════════════════════════════════════╝
    
    诊断标签:
      [STEP X]        - 执行步骤追踪
      [STATE]         - 状态快照
      [ERROR @位置]   - 故障定位
      [PROGRESS]      - 进度看板
      [TIMEOUT]       - 死锁检测
      [TIMER_START]   - 计时开始
      [TIMER_END]     - 计时结束
    
    搜索示例:
      grep "\[ERROR" live_v3.log          # 查找所有错误
      grep "\[STEP" live_v3.log           # 查看执行流程
      grep "\[STATE.*position" live_v3.log # 查看持仓状态变化
      grep "\[TIMEOUT" live_v3.log        # 查找超时问题
    
    前缀格式: [HH:MM:SS.mmm|模块名|L行号]
    """
    print(help_text)
