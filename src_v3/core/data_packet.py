"""
标准化数据包格式
用于模块间数据流转，支持版本控制和数据溯源
"""

import json
import hashlib
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
from datetime import datetime


@dataclass
class ModuleDataPacket:
    """
    标准化模块数据包
    
    所有模块间的数据流转必须使用此格式，确保:
    1. 数据版本控制
    2. 完整溯源链 (session_id, input_hash, output_hash)
    3. 元数据标准化 (处理状态、耗时等)
    
    Attributes:
        module: 来源模块名称 (M1, M2, ...)
        version: 数据格式版本
        timestamp: 生成时间戳
        session_id: 本次处理会话ID
        data: 业务数据 (Dict)
        metadata: 元数据 (状态、哈希、耗时等)
    
    Example:
        # 创建输出包
        output = ModuleDataPacket(
            module="M3",
            data={"pairs": [...], "count": 100},
            metadata={"status": "success"}
        )
        
        # 序列化存储
        json_str = output.to_json()
        
        # 计算哈希用于溯源
        data_hash = output.calc_hash()
    """
    
    module: str
    version: str = "1.0"
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=lambda: {
        "input_hash": "",
        "output_hash": "",
        "status": "pending",
        "duration_ms": 0,
        "record_count": 0
    })
    
    def __post_init__(self):
        """数据验证和初始化"""
        if not self.module:
            raise ValueError("module name is required")
        
        # 确保metadata包含所有必需字段
        defaults = {
            "input_hash": "",
            "output_hash": "",
            "status": "pending", 
            "duration_ms": 0,
            "record_count": 0
        }
        for key, value in defaults.items():
            if key not in self.metadata:
                self.metadata[key] = value
    
    def to_json(self) -> str:
        """
        序列化为JSON字符串
        
        Returns:
            JSON字符串
        """
        return json.dumps(asdict(self), default=str, ensure_ascii=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            字典格式
        """
        return asdict(self)
    
    def calc_hash(self) -> str:
        """
        计算数据内容的MD5哈希
        
        用于数据溯源和变更检测
        
        Returns:
            MD5哈希字符串 (32字符)
        """
        # 只计算data字段的哈希
        data_str = json.dumps(self.data, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(data_str.encode('utf-8')).hexdigest()
    
    def update_output_hash(self):
        """更新output_hash为当前数据哈希"""
        self.metadata["output_hash"] = self.calc_hash()
    
    def set_input_hash(self, input_hash: str):
        """
        设置输入数据哈希
        
        Args:
            input_hash: 上游数据包的哈希值
        """
        self.metadata["input_hash"] = input_hash
    
    def set_status(self, status: str, message: str = ""):
        """
        设置处理状态
        
        Args:
            status: pending, running, success, failed, skipped
            message: 状态描述信息
        """
        self.metadata["status"] = status
        if message:
            self.metadata["message"] = message
    
    def set_duration(self, duration_ms: int):
        """
        设置处理耗时
        
        Args:
            duration_ms: 耗时(毫秒)
        """
        self.metadata["duration_ms"] = duration_ms
    
    def set_record_count(self, count: int):
        """
        设置记录数量
        
        Args:
            count: 记录数
        """
        self.metadata["record_count"] = count
    
    def is_valid(self) -> bool:
        """
        验证数据包有效性
        
        Returns:
            bool: 是否有效
        """
        if not self.module:
            return False
        if not isinstance(self.data, dict):
            return False
        return True
    
    def get_data_path(self, path: str, default=None):
        """
        安全获取嵌套数据
        
        Args:
            path: 点分隔路径 (如 "pairs.0.symbol_a")
            default: 默认值
            
        Returns:
            数据值或默认值
        """
        keys = path.split('.')
        value = self.data
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            elif isinstance(value, list) and key.isdigit():
                idx = int(key)
                if idx < len(value):
                    value = value[idx]
                else:
                    return default
            else:
                return default
        
        return value
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ModuleDataPacket':
        """
        从JSON字符串反序列化
        
        Args:
            json_str: JSON字符串
            
        Returns:
            ModuleDataPacket实例
        """
        data = json.loads(json_str)
        return cls(**data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ModuleDataPacket':
        """
        从字典创建实例
        
        Args:
            data: 字典数据
            
        Returns:
            ModuleDataPacket实例
        """
        return cls(**data)
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (f"ModuleDataPacket("
                f"module={self.module}, "
                f"session={self.session_id}, "
                f"status={self.metadata.get('status')}, "
                f"records={self.metadata.get('record_count', 0)})")
