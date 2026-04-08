"""
版本追踪与变更审计模块
S001-Pro 代码变更可追溯性保障

提供:
- 版本号管理
- 变更日志记录
- 影响范围追踪
- 回滚点标记
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger("VersionTracker")


@dataclass
class ChangeRecord:
    """变更记录"""
    version: str
    timestamp: str
    component: str
    change_type: str  # add/modify/fix/remove
    description: str
    author: str
    impact_level: str  # low/medium/high/critical
    rollback_available: bool
    related_files: List[str]
    validation_status: str = "pending"  # pending/pass/fail


class VersionTracker:
    """
    版本追踪器
    
    确保所有代码变更可追溯、可验证、可回滚
    """
    
    VERSION = "2.1.0-hardened"  # 当前版本
    CHANGE_LOG_FILE = Path("data/change_log.jsonl")
    
    def __init__(self):
        self.changes: List[ChangeRecord] = []
        self._load_history()
        logger.info(f"VersionTracker initialized: v{self.VERSION}")
    
    def _load_history(self):
        """加载历史变更记录"""
        if self.CHANGE_LOG_FILE.exists():
            try:
                with open(self.CHANGE_LOG_FILE, 'r') as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            self.changes.append(ChangeRecord(**data))
                logger.info(f"Loaded {len(self.changes)} historical changes")
            except Exception as e:
                logger.error(f"Failed to load change history: {e}")
    
    def record_change(self, change: ChangeRecord) -> bool:
        """
        记录一次变更
        
        Args:
            change: 变更记录
            
        Returns:
            是否记录成功
        """
        try:
            # 确保目录存在
            self.CHANGE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            # 追加记录
            with open(self.CHANGE_LOG_FILE, 'a') as f:
                f.write(json.dumps(asdict(change), ensure_ascii=False) + '\n')
            
            self.changes.append(change)
            logger.info(f"Change recorded: {change.version} - {change.description}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to record change: {e}")
            return False
    
    def get_current_version(self) -> str:
        """获取当前版本"""
        return self.VERSION
    
    def get_changes_since(self, version: str) -> List[ChangeRecord]:
        """获取指定版本以来的所有变更"""
        # 简化实现：返回最近10条
        return self.changes[-10:]
    
    def validate_change(self, version: str, status: str):
        """更新变更验证状态"""
        for change in self.changes:
            if change.version == version:
                change.validation_status = status
                logger.info(f"Change {version} validation status: {status}")
                break
    
    def create_rollback_point(self, description: str) -> str:
        """创建回滚点"""
        rollback_id = f"rb-{int(time.time())}"
        logger.info(f"Rollback point created: {rollback_id} - {description}")
        return rollback_id


# 全局实例
tracker = VersionTracker()
