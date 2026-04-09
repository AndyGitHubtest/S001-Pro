"""
调度器 - 定时触发Pipeline执行
"""

import time
import threading
import logging
from typing import Optional, Callable
from datetime import datetime, timedelta

from .pipeline import Pipeline


class Scheduler:
    """
    Pipeline调度器
    
    支持两种模式:
    1. 定时模式: 每N分钟/小时执行一次
    2. 事件模式: 数据更新触发
    
    Example:
        scheduler = Scheduler(pipeline)
        scheduler.start(interval_minutes=60)  # 每小时运行
    """
    
    def __init__(self, pipeline: Pipeline):
        """
        初始化调度器
        
        Args:
            pipeline: Pipeline实例
        """
        self.pipeline = pipeline
        self.logger = logging.getLogger("Scheduler")
        
        # 运行状态
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 配置
        self.interval_seconds = 3600  # 默认1小时
        self.on_completion: Optional[Callable] = None
    
    def start(self, interval_minutes: int = 60, blocking: bool = False):
        """
        启动调度器
        
        Args:
            interval_minutes: 执行间隔(分钟)
            blocking: 是否阻塞主线程
        """
        if self._running:
            self.logger.warning("Scheduler already running")
            return
        
        self.interval_seconds = interval_minutes * 60
        self._running = True
        self._stop_event.clear()
        
        self.logger.info(f"Scheduler started, interval={interval_minutes}min")
        
        if blocking:
            self._run_loop()
        else:
            self._thread = threading.Thread(target=self._run_loop, name="PipelineScheduler")
            self._thread.daemon = True
            self._thread.start()
    
    def _run_loop(self):
        """主循环"""
        while not self._stop_event.is_set():
            try:
                self.logger.info("Triggering pipeline execution...")
                
                # 执行Pipeline
                success = self.pipeline.run_pipeline()
                
                # 回调通知
                if self.on_completion:
                    try:
                        self.on_completion(success)
                    except Exception as e:
                        self.logger.error(f"Completion callback error: {e}")
                
                # 等待下一次执行
                self._stop_event.wait(self.interval_seconds)
                
            except Exception as e:
                self.logger.error(f"Scheduler loop error: {e}", exc_info=True)
                time.sleep(60)  # 出错后等待1分钟再试
    
    def stop(self):
        """停止调度器"""
        if not self._running:
            return
        
        self.logger.info("Stopping scheduler...")
        self._running = False
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=10)
        
        self.logger.info("Scheduler stopped")
    
    def run_once(self) -> bool:
        """
        立即执行一次
        
        Returns:
            bool: 是否成功
        """
        return self.pipeline.run_pipeline()
    
    def is_running(self) -> bool:
        """检查是否运行中"""
        return self._running
