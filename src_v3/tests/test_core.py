"""
单元测试 - 核心模块
"""

import unittest
import tempfile
import os
from pathlib import Path

from ..core.database import DatabaseManager
from ..core.data_packet import ModuleDataPacket
from ..core.data_bus import DataBus


class TestDatabaseManager(unittest.TestCase):
    """测试数据库管理器"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = DatabaseManager(self.db_path)
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_init(self):
        """测试初始化"""
        self.assertTrue(Path(self.db_path).exists())
    
    def test_read_write(self):
        """测试读写操作"""
        # 写入
        self.db.execute_write(
            "INSERT INTO system_config (key, value) VALUES (?, ?)",
            ("test_key", "test_value")
        )
        
        # 读取
        rows = self.db.execute_read(
            "SELECT * FROM system_config WHERE key = ?",
            ("test_key",)
        )
        
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], "test_value")
    
    def test_get_stats(self):
        """测试统计信息"""
        stats = self.db.get_stats()
        self.assertIn("db_size_mb", stats)


class TestModuleDataPacket(unittest.TestCase):
    """测试数据包"""
    
    def test_creation(self):
        """测试创建"""
        packet = ModuleDataPacket(
            module="M3",
            data={"pairs": [], "count": 0}
        )
        
        self.assertEqual(packet.module, "M3")
        self.assertEqual(packet.data["count"], 0)
        self.assertTrue(packet.is_valid())
    
    def test_hash(self):
        """测试哈希计算"""
        packet = ModuleDataPacket(
            module="M3",
            data={"test": "value"}
        )
        
        hash1 = packet.calc_hash()
        packet.update_output_hash()
        
        self.assertEqual(packet.metadata["output_hash"], hash1)
    
    def test_serialization(self):
        """测试序列化"""
        packet = ModuleDataPacket(
            module="M3",
            data={"pairs": [{"a": 1, "b": 2}]}
        )
        
        json_str = packet.to_json()
        restored = ModuleDataPacket.from_json(json_str)
        
        self.assertEqual(restored.module, packet.module)
        self.assertEqual(restored.data, packet.data)


class TestDataBus(unittest.TestCase):
    """测试数据总线"""
    
    def test_subscribe_publish(self):
        """测试订阅发布"""
        bus = DataBus()
        received = []
        
        def callback(data):
            received.append(data)
        
        bus.subscribe("test_event", callback)
        bus.publish("test_event", {"message": "hello"})
        
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["message"], "hello")
    
    def test_multiple_subscribers(self):
        """测试多订阅者"""
        bus = DataBus()
        count = [0]
        
        def callback1(data):
            count[0] += 1
        
        def callback2(data):
            count[0] += 1
        
        bus.subscribe("event", callback1)
        bus.subscribe("event", callback2)
        bus.publish("event", {})
        
        self.assertEqual(count[0], 2)


if __name__ == "__main__":
    unittest.main()
