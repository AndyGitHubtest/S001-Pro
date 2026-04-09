"""
Pipeline调度器 - 编排M1-M5执行流程
"""

import logging
import time
from typing import Dict, List, Optional, Type
from datetime import datetime

from ..core.database import DatabaseManager
from ..core.module_base import ModuleBase
from ..core.data_bus import DataBus, get_data_bus


class Pipeline:
    """
    Pipeline调度器
    
    职责:
    1. 注册和管理M1-M5模块
    2. 按顺序执行管道流程
    3. 状态监控和错误处理
    4. 模块间事件协调
    
    执行顺序:
        M1 → M2 → M3 → M4 → M5
    
    Example:
        pipeline = Pipeline(db)
        pipeline.register_module(M1Module(db))
        pipeline.register_module(M2Module(db))
        ...
        success = pipeline.run_pipeline()
    """
    
    def __init__(self, db_manager: DatabaseManager, 
                 data_bus: Optional[DataBus] = None):
        """
        初始化Pipeline
        
        Args:
            db_manager: 数据库管理器
            data_bus: 数据总线 (默认使用全局实例)
        """
        self.db = db_manager
        self.data_bus = data_bus or get_data_bus()
        self.logger = logging.getLogger("Pipeline")
        
        # 模块注册表
        self.modules: Dict[str, ModuleBase] = {}
        
        # 执行配置
        self.execution_order = ["M1", "M2", "M3", "M4", "M5"]
        
        # 统计信息
        self.stats = {
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "total_duration_ms": 0
        }
    
    def register_module(self, module: ModuleBase):
        """
        注册模块
        
        Args:
            module: 模块实例
        """
        self.modules[module.module_name] = module
        self.logger.info(f"Registered module: {module.module_name}")
    
    def register_modules(self, modules: List[ModuleBase]):
        """批量注册模块"""
        for module in modules:
            self.register_module(module)
    
    def run_pipeline(self, continue_on_error: bool = False) -> bool:
        """
        执行完整管道
        
        Args:
            continue_on_error: 模块失败时是否继续执行后续模块
            
        Returns:
            bool: 整体是否成功
        """
        pipeline_id = f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start_time = time.time()
        
        self.logger.info(f"="*60)
        self.logger.info(f"Pipeline started: {pipeline_id}")
        self.logger.info(f"="*60)
        
        # 广播管道开始事件
        self.data_bus.notify_pipeline_started(
            pipeline_id, 
            self.execution_order
        )
        
        success_count = 0
        failed_modules = []
        
        try:
            for module_name in self.execution_order:
                module = self.modules.get(module_name)
                
                if not module:
                    self.logger.error(f"Module {module_name} not registered")
                    failed_modules.append(module_name)
                    if not continue_on_error:
                        break
                    continue
                
                self.logger.info(f"Running {module_name}...")
                
                # 执行模块
                success = module.run()
                
                if success:
                    success_count += 1
                    # 广播完成事件
                    self.data_bus.notify_module_complete(
                        module_name,
                        module.session_id,
                        {"record_count": module._progress}
                    )
                else:
                    failed_modules.append(module_name)
                    # 广播失败事件
                    self.data_bus.notify_module_failed(
                        module_name,
                        module.session_id,
                        "Module execution failed"
                    )
                    
                    if not continue_on_error:
                        self.logger.error(f"Pipeline stopped at {module_name}")
                        break
            
            # 计算耗时
            duration_ms = int((time.time() - start_time) * 1000)
            
            # 更新统计
            self.stats["total_runs"] += 1
            self.stats["total_duration_ms"] += duration_ms
            
            all_success = len(failed_modules) == 0
            
            if all_success:
                self.stats["successful_runs"] += 1
                self.logger.info(f"✓ Pipeline completed successfully in {duration_ms}ms")
            else:
                self.stats["failed_runs"] += 1
                self.logger.warning(
                    f"✗ Pipeline completed with {len(failed_modules)} failures: "
                    f"{failed_modules}"
                )
            
            # 广播管道完成事件
            self.data_bus.notify_pipeline_completed(
                pipeline_id,
                all_success,
                duration_ms
            )
            
            return all_success
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.logger.error(f"Pipeline crashed: {e}", exc_info=True)
            
            self.data_bus.notify_pipeline_completed(
                pipeline_id,
                False,
                duration_ms
            )
            
            self.stats["failed_runs"] += 1
            return False
    
    def run_single_module(self, module_name: str) -> bool:
        """
        运行单个模块
        
        Args:
            module_name: 模块名称
            
        Returns:
            bool: 是否成功
        """
        module = self.modules.get(module_name)
        if not module:
            self.logger.error(f"Module {module_name} not found")
            return False
        
        return module.run()
    
    def get_pipeline_status(self) -> Dict:
        """获取管道状态"""
        return {
            "registered_modules": list(self.modules.keys()),
            "execution_order": self.execution_order,
            "stats": self.stats.copy()
        }
    
    def get_module_status(self, module_name: str) -> Optional[Dict]:
        """获取模块状态"""
        return self.db.get_module_status(module_name)
    
    def get_latest_session_chain(self) -> Dict[str, str]:
        """获取最新会话链"""
        return {
            name: self.db.get_latest_session(name) or "N/A"
            for name in self.execution_order
        }
    
    def reset_stats(self):
        """重置统计"""
        self.stats = {
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "total_duration_ms": 0
        }
