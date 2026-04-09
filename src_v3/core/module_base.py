"""
模块基类 V3 - 适配混合架构 (Redis + SQLite)

核心改进:
1. 输出通过HybridManager同时写入Redis和SQLite
2. 输入可以从Redis订阅或SQLite查询
3. 支持实时通信和持久化的双重保障
"""

import uuid
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any

from .data_packet import ModuleDataPacket
from .hybrid_manager import HybridManager


class ModuleBase(ABC):
    """
    模块基类 V3 (混合架构适配)
    
    数据流转:
    1. input() → 从上游获取数据 (Redis优先，SQLite回退)
    2. process() → 业务逻辑处理
    3. output() → 发布到下游 (Redis广播 + SQLite持久化)
    
    状态管理:
    - 通过HybridManager统一管理
    - 实时状态: Redis
    - 持久化: SQLite (不可变)
    """
    
    def __init__(self, module_name: str, hybrid_manager: HybridManager):
        """
        初始化模块
        
        Args:
            module_name: 模块名称 (M1, M2, M3, M4, M5, M6)
            hybrid_manager: 混合存储管理器
        """
        self.module_name = module_name
        self.hm = hybrid_manager
        self.logger = logging.getLogger(f"Module.{module_name}")
        
        # 生成唯一会话ID
        self.session_id = self._generate_session_id()
        
        # 当前状态
        self._status = "idle"
        self._progress = 0
        
        self.logger.debug(f"{module_name} initialized (hybrid mode), session={self.session_id}")
    
    def _generate_session_id(self) -> str:
        """生成唯一会话ID"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rand = uuid.uuid4().hex[:6]
        return f"{self.module_name}_{ts}_{rand}"
    
    def update_status(self, status: str, message: str = "", progress: int = 0):
        """
        更新模块状态
        
        同时更新:
        - SQLite: module_status表 (永久记录)
        - Redis: 模块状态缓存 (实时查看)
        """
        self._status = status
        self._progress = progress
        
        try:
            # 持久化到SQLite
            self.hm.sqlite.append_module_status(
                self.module_name, self.session_id, status, message, progress
            )
            
            # 更新Redis缓存 (短TTL)
            self.hm.redis.set_cache(
                "module_status", self.module_name,
                {"status": status, "message": message, "progress": progress, "session_id": self.session_id},
                ttl=10
            )
        except Exception as e:
            self.logger.error(f"Failed to update status: {e}")
    
    @abstractmethod
    def input(self) -> Optional[ModuleDataPacket]:
        """
        从上游模块读取数据
        
        实现方式:
        - 实时模式: 订阅Redis channel
        - 批处理模式: 查询SQLite最新数据
        
        Returns:
            ModuleDataPacket or None
        """
        pass
    
    @abstractmethod
    def process(self, input_packet: ModuleDataPacket) -> ModuleDataPacket:
        """
        处理数据 (核心业务逻辑)
        
        Args:
            input_packet: 上游输入数据
            
        Returns:
            ModuleDataPacket: 处理结果
        """
        pass
    
    @abstractmethod
    def output(self, packet: ModuleDataPacket) -> bool:
        """
        写入下游模块
        
        必须通过HybridManager:
        - publish_module_output(): 发布到Redis + 持久化到SQLite
        - save_position_state(): 保存状态
        
        Args:
            packet: 处理后的数据包
            
        Returns:
            bool: 是否成功
        """
        pass
    
    def validate_input(self, packet: Optional[ModuleDataPacket]) -> bool:
        """验证输入数据包"""
        if packet is None:
            return False
        return packet.is_valid()
    
    def pre_process(self) -> bool:
        """预处理钩子"""
        return True
    
    def post_process(self, success: bool, packet: Optional[ModuleDataPacket]):
        """后处理钩子"""
        pass
    
    def run(self) -> bool:
        """
        执行完整流程
        
        流程:
        1. pre_process()
        2. input() - 从上游读取
        3. validate_input()
        4. process() - 业务处理
        5. output() - 发布结果 (Redis+SQLite)
        6. post_process()
        """
        start_time = datetime.now()
        output_packet = None
        
        try:
            # Step 0: 预处理
            self.update_status("running", f"{self.module_name} pre-processing", 5)
            if not self.pre_process():
                self.update_status("skipped", f"{self.module_name} pre-process failed", 0)
                return False
            
            # Step 1: 读取输入
            self.update_status("running", f"{self.module_name} reading input", 10)
            input_packet = self.input()
            
            if not self.validate_input(input_packet):
                self.logger.info(f"{self.module_name}: no valid input, skipping")
                self.update_status("skipped", f"{self.module_name} no input", 0)
                return False
            
            # Step 2: 处理数据
            self.update_status("running", f"{self.module_name} processing", 50)
            output_packet = self.process(input_packet)
            
            # 设置元数据
            output_packet.session_id = self.session_id
            output_packet.set_input_hash(input_packet.calc_hash())
            output_packet.update_output_hash()
            
            # Step 3: 写入输出 (关键：通过HybridManager)
            self.update_status("running", f"{self.module_name} publishing output", 90)
            success = self.output(output_packet)
            
            # 计算耗时
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            output_packet.set_duration(duration_ms)
            
            if success:
                output_packet.set_status("success", f"{self.module_name} completed")
                self.update_status("completed", 
                    f"{self.module_name} completed in {duration_ms}ms", 100)
                self.logger.info(f"{self.module_name} completed: "
                    f"{output_packet.metadata.get('record_count', 0)} records, "
                    f"{duration_ms}ms")
            else:
                output_packet.set_status("failed", f"{self.module_name} output failed")
                self.update_status("failed", f"{self.module_name} output failed", 0)
            
            # Step 4: 后处理
            self.post_process(success, output_packet)
            
            return success
            
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            self.logger.error(f"{self.module_name} failed: {e}", exc_info=True)
            self.update_status("failed", f"{self.module_name} error: {str(e)[:100]}", 0)
            self.post_process(False, output_packet)
            return False
    
    def get_status(self) -> str:
        """获取当前状态"""
        return self._status
    
    def get_progress(self) -> int:
        """获取当前进度"""
        return self._progress


class StreamModuleBase(ModuleBase):
    """
    流式处理模块基类 (用于M6执行器)
    
    特点:
    - 持续运行，不是一次性执行
    - 订阅Redis实时数据
    - 状态变化时写入SQLite
    """
    
    def __init__(self, module_name: str, hybrid_manager: HybridManager):
        super().__init__(module_name, hybrid_manager)
        self._running = False
        self._subscribed = False
    
    @abstractmethod
    def on_data(self, data: Dict[str, Any]):
        """
        接收到数据时的处理
        
        Args:
            data: 接收到的数据
        """
        pass
    
    def subscribe_and_run(self, upstream_module: str):
        """
        订阅上游模块并持续运行
        
        Args:
            upstream_module: 上游模块名称
        """
        self._running = True
        
        # 订阅上游输出
        self.hm.subscribe_module_output(upstream_module, self.on_data)
        
        self.logger.info(f"{self.module_name} subscribed to {upstream_module}, running...")
        
        # 保持运行
        import time
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """停止运行"""
        self._running = False
        self.logger.info(f"{self.module_name} stopped")
