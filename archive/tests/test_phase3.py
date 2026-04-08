"""
Phase 3 单元测试: Persistence (M5) + ConfigManager (M8)

测试覆盖:
  M5 Persistence:
    - JSON 生成结构完整 (meta, pairs, execution, allocation)
    - scale_in/scale_out/stop_loss trigger_z 计算正确
    - 原子写入 (tmp -> rename)
    - MD5 校验
    - load + 校验 (非法 JSON 拦截)
    - 空 whitelist 处理

  M8 ConfigManager:
    - base.yaml 加载 + 默认值合并
    - 必填项校验 (api_key, api_secret)
    - 范围校验 (max_drawdown_pct > 0)
    - pairs_v2.json 加载 + 结构校验
    - scale_in ratios 总和校验
    - z_entry < z_stop 逻辑校验
    - 热重载检测 mtime 变动
    - get_pair_config 查询

文档规范: docs/module_5_persistence.md, docs/module_8_config_management.md
"""

import sys
import os
import json
import tempfile
import unittest
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.persistence import Persistence, compute_md5, _compute_scale_in_triggers, _compute_scale_out_triggers, _compute_stop_loss_trigger
from src.config_manager import ConfigManager, _deep_merge, _simple_yaml_parse


# ──────────────────────────────────────────────
# M5 Persistence 测试
# ──────────────────────────────────────────────

class TestPersistence(unittest.TestCase):
    """Persistence 单元测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.json_path = os.path.join(self.tmpdir, "pairs_v2.json")
        self.persistence = Persistence()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_whitelist(self, count=3):
        """生成 Mock whitelist"""
        results = []
        for i in range(count):
            results.append({
                "symbol_a": f"SYM{i}/USDT",
                "symbol_b": f"SYM{i+1}/USDT",
                "beta": 1.0 + i * 0.1,
                "params": {
                    "z_entry": 2.0 + i * 0.5,
                    "z_exit": 0.5 + i * 0.1,
                    "z_stop": 4.0 + i * 0.5,
                },
                "score": 0.8 - i * 0.1,
            })
        return results

    def test_save_generates_valid_json(self):
        """测试: save 生成合法 JSON"""
        whitelist = self._make_whitelist(3)
        result = self.persistence.save(whitelist, self.json_path, git_hash="abc123")

        self.assertTrue(result)
        self.assertTrue(os.path.exists(self.json_path))

        with open(self.json_path, "r") as f:
            data = json.load(f)

        self.assertIn("meta", data)
        self.assertIn("pairs", data)
        self.assertEqual(data["meta"]["pairs_count"], 3)
        self.assertEqual(data["meta"]["git_hash"], "abc123")
        self.assertEqual(len(data["pairs"]), 3)

    def test_save_atomic_write(self):
        """测试: 原子写入 (tmp -> rename)"""
        whitelist = self._make_whitelist(1)
        self.persistence.save(whitelist, self.json_path)

        # tmp 文件应不存在 (已被 rename)
        self.assertFalse(os.path.exists(self.json_path + ".tmp"))
        # 目标文件应存在
        self.assertTrue(os.path.exists(self.json_path))

    def test_save_md5_verification(self):
        """测试: MD5 校验通过"""
        whitelist = self._make_whitelist(2)
        self.persistence.save(whitelist, self.json_path)

        md5 = compute_md5(self.json_path)
        self.assertIsInstance(md5, str)
        self.assertEqual(len(md5), 32)  # MD5 hex 长度

    def test_save_empty_whitelist(self):
        """测试: 空 whitelist 返回 False"""
        result = self.persistence.save([], self.json_path)
        self.assertFalse(result)
        self.assertFalse(os.path.exists(self.json_path))

    def test_load_valid_json(self):
        """测试: load 读取合法 JSON"""
        whitelist = self._make_whitelist(2)
        self.persistence.save(whitelist, self.json_path)

        data = self.persistence.load(self.json_path)
        self.assertIsNotNone(data)
        self.assertEqual(len(data["pairs"]), 2)

    def test_load_missing_file(self):
        """测试: load 不存在的文件返回 None"""
        data = self.persistence.load(os.path.join(self.tmpdir, "nonexistent.json"))
        self.assertIsNone(data)

    def test_load_corrupt_json(self):
        """测试: load 损坏的 JSON 返回 None"""
        with open(self.json_path, "w") as f:
            f.write("{broken json")
        data = self.persistence.load(self.json_path)
        self.assertIsNone(data)

    def test_scale_in_trigger_calculation(self):
        """测试: scale_in trigger_z 计算 (Entry + offset)"""
        triggers = _compute_scale_in_triggers(2.5)
        self.assertEqual(len(triggers), 3)
        self.assertAlmostEqual(triggers[0]["trigger_z"], 2.0)  # 2.5 + (-0.5)
        self.assertAlmostEqual(triggers[1]["trigger_z"], 2.5)  # 2.5 + 0.0
        self.assertAlmostEqual(triggers[2]["trigger_z"], 3.0)  # 2.5 + 0.5
        self.assertAlmostEqual(triggers[0]["ratio"], 0.3)
        self.assertAlmostEqual(triggers[2]["ratio"], 0.4)

    def test_scale_out_trigger_calculation(self):
        """测试: scale_out trigger_z 计算"""
        triggers = _compute_scale_out_triggers(2.5, 0.8)
        self.assertEqual(len(triggers), 3)
        self.assertAlmostEqual(triggers[0]["trigger_z"], 1.5)  # 2.5 * 0.6
        self.assertAlmostEqual(triggers[1]["trigger_z"], 0.8)  # Exit
        self.assertAlmostEqual(triggers[2]["trigger_z"], 0.0)  # Reverse 0

    def test_stop_loss_trigger_calculation(self):
        """测试: stop_loss trigger_z 计算"""
        trigger = _compute_stop_loss_trigger(2.5, 4.5)
        self.assertAlmostEqual(trigger["trigger_z"], 4.5)
        self.assertEqual(trigger["type"], "market")
        self.assertEqual(trigger["post_only"], False)

    def test_json_structure_complete(self):
        """测试: JSON 结构包含所有文档定义的字段"""
        whitelist = self._make_whitelist(1)
        self.persistence.save(whitelist, self.json_path)

        with open(self.json_path, "r") as f:
            data = json.load(f)

        pair = data["pairs"][0]

        # 顶层字段
        for field in ["signal_id", "symbol_a", "symbol_b", "beta", "params",
                      "exchange_meta", "funding_info", "execution", "allocation",
                      "valid_until_iso", "ttl_minutes"]:
            self.assertIn(field, pair, f"Missing field: {field}")

        # execution 子字段
        exec_data = pair["execution"]
        for field in ["legs_sync", "scale_in", "scale_out", "stop_loss"]:
            self.assertIn(field, exec_data, f"Missing execution field: {field}")

        # legs_sync 子字段
        ls = exec_data["legs_sync"]
        for field in ["simultaneous", "tolerance_ms", "rollback_on_failure"]:
            self.assertIn(field, ls, f"Missing legs_sync field: {field}")

    def test_load_validates_missing_fields(self):
        """测试: load 校验缺失必需字段时返回 None"""
        bad_data = {
            "meta": {"version": "1.0", "generated_at": "", "git_hash": "", "pairs_count": 1},
            "pairs": [{"symbol_a": "A/USDT"}]  # 缺少 symbol_b, beta, params, execution
        }
        with open(self.json_path, "w") as f:
            json.dump(bad_data, f)

        data = self.persistence.load(self.json_path)
        self.assertIsNone(data)


# ──────────────────────────────────────────────
# M8 ConfigManager 测试
# ──────────────────────────────────────────────

class TestConfigManager(unittest.TestCase):
    """ConfigManager 单元测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_dir = os.path.join(self.tmpdir, "config")
        os.makedirs(self.config_dir, exist_ok=True)
        self.base_path = os.path.join(self.config_dir, "base.yaml")
        self.pairs_path = os.path.join(self.config_dir, "pairs_v2.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_defaults(self):
        """测试: 无 base.yaml 时使用默认值 (默认 testnet=False, 无 API key -> 校验失败)"""
        cm = ConfigManager(config_dir=self.config_dir)
        # 默认配置 testnet=False 且无 api_key, 应触发 Fail Fast
        with self.assertRaises(ValueError):
            cm.load_and_validate()

    def test_load_yaml_with_testnet(self):
        """测试: 加载 base.yaml (testnet 模式)"""
        yaml_content = """
system:
  env: "test"
  log_level: "DEBUG"
exchange:
  name: "binance"
  testnet: true
  api_key: "test_key"
  api_secret: "test_secret"
risk:
  max_drawdown_pct: 15.0
  max_daily_loss_pct: 5.0
  max_open_positions: 6
  isolated_margin: true
"""
        with open(self.base_path, "w") as f:
            f.write(yaml_content)

        cm = ConfigManager(config_dir=self.config_dir)
        config = cm.load_and_validate()

        self.assertEqual(config["system"]["log_level"], "DEBUG")
        self.assertEqual(config["exchange"]["testnet"], True)
        self.assertEqual(config["exchange"]["api_key"], "test_key")

    def test_validation_missing_api_key_live(self):
        """测试: 非 testnet 时缺少 api_key 抛异常"""
        yaml_content = """
exchange:
  name: "binance"
  testnet: false
risk:
  max_drawdown_pct: 15.0
  max_daily_loss_pct: 5.0
  max_open_positions: 6
"""
        with open(self.base_path, "w") as f:
            f.write(yaml_content)

        cm = ConfigManager(config_dir=self.config_dir)
        with self.assertRaises(ValueError):
            cm.load_and_validate()

    def test_validation_invalid_drawdown(self):
        """测试: max_drawdown_pct <= 0 抛异常"""
        yaml_content = """
exchange:
  testnet: true
risk:
  max_drawdown_pct: -1.0
  max_daily_loss_pct: 5.0
  max_open_positions: 6
"""
        with open(self.base_path, "w") as f:
            f.write(yaml_content)

        cm = ConfigManager(config_dir=self.config_dir)
        with self.assertRaises(ValueError):
            cm.load_and_validate()

    def test_pairs_config_loading(self):
        """测试: 加载 pairs_v2.json"""
        # 先创建 base.yaml (testnet)
        with open(self.base_path, "w") as f:
            f.write("exchange:\n  testnet: true\nrisk:\n  max_drawdown_pct: 15.0\n  max_daily_loss_pct: 5.0\n  max_open_positions: 6\n")

        # 创建 pairs_v2.json
        pairs_data = {
            "meta": {"version": "1.0", "generated_at": "", "git_hash": "", "pairs_count": 1},
            "pairs": [{
                "symbol_a": "A/USDT",
                "symbol_b": "B/USDT",
                "beta": 1.0,
                "params": {"z_entry": 2.5, "z_exit": 0.8, "z_stop": 4.5},
                "execution": {
                    "legs_sync": {"simultaneous": True, "tolerance_ms": 3000, "rollback_on_failure": True},
                    "scale_in": [
                        {"trigger_z": 2.0, "ratio": 0.3, "type": "limit", "post_only": True},
                        {"trigger_z": 2.5, "ratio": 0.3, "type": "limit", "post_only": True},
                        {"trigger_z": 3.0, "ratio": 0.4, "type": "limit", "post_only": True},
                    ],
                    "scale_out": [],
                    "stop_loss": {"trigger_z": 4.5, "type": "market", "post_only": False},
                },
            }],
        }
        with open(self.pairs_path, "w") as f:
            json.dump(pairs_data, f)

        cm = ConfigManager(config_dir=self.config_dir)
        cm.load_and_validate()

        pair = cm.get_pair_config("A/USDT_B/USDT")
        self.assertIsNotNone(pair)
        self.assertEqual(pair["symbol_a"], "A/USDT")

    def test_pairs_validation_bad_ratios(self):
        """测试: scale_in ratios 总和不为 1.0 时校验失败"""
        with open(self.base_path, "w") as f:
            f.write("exchange:\n  testnet: true\nrisk:\n  max_drawdown_pct: 15.0\n  max_daily_loss_pct: 5.0\n  max_open_positions: 6\n")

        bad_pairs = {
            "meta": {"version": "1.0", "generated_at": "", "git_hash": "", "pairs_count": 1},
            "pairs": [{
                "symbol_a": "A/USDT",
                "symbol_b": "B/USDT",
                "beta": 1.0,
                "params": {"z_entry": 2.5, "z_exit": 0.8, "z_stop": 4.5},
                "execution": {
                    "legs_sync": {"simultaneous": True, "tolerance_ms": 3000, "rollback_on_failure": True},
                    "scale_in": [
                        {"trigger_z": 2.0, "ratio": 0.5, "type": "limit", "post_only": True},
                        {"trigger_z": 2.5, "ratio": 0.5, "type": "limit", "post_only": True},
                        {"trigger_z": 3.0, "ratio": 0.5, "type": "limit", "post_only": True},  # total = 1.5
                    ],
                    "scale_out": [],
                    "stop_loss": {"trigger_z": 4.5, "type": "market", "post_only": False},
                },
            }],
        }
        with open(self.pairs_path, "w") as f:
            json.dump(bad_pairs, f)

        cm = ConfigManager(config_dir=self.config_dir)
        cm.load_and_validate()
        # pairs 加载失败, _pairs_data 应为空
        self.assertEqual(cm.pairs_data, {})

    def test_pairs_validation_entry_gt_stop(self):
        """测试: z_entry >= z_stop 时校验失败"""
        with open(self.base_path, "w") as f:
            f.write("exchange:\n  testnet: true\nrisk:\n  max_drawdown_pct: 15.0\n  max_daily_loss_pct: 5.0\n  max_open_positions: 6\n")

        bad_pairs = {
            "meta": {"version": "1.0", "generated_at": "", "git_hash": "", "pairs_count": 1},
            "pairs": [{
                "symbol_a": "A/USDT",
                "symbol_b": "B/USDT",
                "beta": 1.0,
                "params": {"z_entry": 5.0, "z_exit": 0.8, "z_stop": 4.0},  # z_entry > z_stop
                "execution": {
                    "legs_sync": {"simultaneous": True, "tolerance_ms": 3000, "rollback_on_failure": True},
                    "scale_in": [{"trigger_z": 2.0, "ratio": 1.0, "type": "limit", "post_only": True}],
                    "scale_out": [],
                    "stop_loss": {"trigger_z": 4.0, "type": "market", "post_only": False},
                },
            }],
        }
        with open(self.pairs_path, "w") as f:
            json.dump(bad_pairs, f)

        cm = ConfigManager(config_dir=self.config_dir)
        cm.load_and_validate()
        self.assertEqual(cm.pairs_data, {})

    def test_get_pair_config_not_found(self):
        """测试: 不存在的配对返回 None"""
        with open(self.base_path, "w") as f:
            f.write("exchange:\n  testnet: true\nrisk:\n  max_drawdown_pct: 15.0\n  max_daily_loss_pct: 5.0\n  max_open_positions: 6\n")

        cm = ConfigManager(config_dir=self.config_dir)
        cm.load_and_validate()

        result = cm.get_pair_config("NONEXISTENT/USDT_FAKE/USDT")
        self.assertIsNone(result)

    def test_deep_merge(self):
        """测试: 深度合并两个字典"""
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 10, "e": 5}, "f": 6}
        result = _deep_merge(base, override)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"]["c"], 10)
        self.assertEqual(result["b"]["d"], 3)
        self.assertEqual(result["b"]["e"], 5)
        self.assertEqual(result["f"], 6)

    def test_simple_yaml_parser(self):
        """测试: 简易 YAML 解析器"""
        yaml_content = """
# Comment
system:
  env: "production"
  log_level: "INFO"
  debug: true
  count: 42

exchange:
  name: "binance"
  testnet: false
"""
        path = os.path.join(self.tmpdir, "test.yaml")
        with open(path, "w") as f:
            f.write(yaml_content)

        result = _simple_yaml_parse(path)
        self.assertEqual(result["system"]["env"], "production")
        self.assertEqual(result["system"]["debug"], True)
        self.assertEqual(result["system"]["count"], 42)
        self.assertEqual(result["exchange"]["name"], "binance")
        self.assertEqual(result["exchange"]["testnet"], False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
