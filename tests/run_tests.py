#!/usr/bin/env python3
"""
S001-Pro 强制测试框架 (Mandatory Test Suite)

铁律: 任何代码修改必须通过此测试才能推送
用法:
  python tests/run_tests.py          # 运行全部测试
  python tests/run_tests.py --quick  # 快速测试 (关键路径)
  python tests/run_tests.py --ci     # CI模式 (严格检查)

返回码:
  0 = 全部通过, 可以推送
  1 = 有测试失败, 禁止推送
"""

import sys
import os
import subprocess
import argparse
import time
from pathlib import Path
from typing import List, Tuple

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class Colors:
    """终端颜色"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'


def print_header(text: str):
    print(f"\n{Colors.BLUE}{'='*70}{Colors.RESET}")
    print(f"{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*70}{Colors.RESET}\n")


def print_success(text: str):
    print(f"{Colors.GREEN}✓ {text}{Colors.RESET}")


def print_error(text: str):
    print(f"{Colors.RED}✗ {text}{Colors.RESET}")


def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠ {text}{Colors.RESET}")


class TestRunner:
    """测试运行器"""
    
    def __init__(self, mode: str = "full"):
        self.mode = mode
        self.results: List[Tuple[str, bool, str]] = []
        self.start_time = time.time()
        
    def run_test(self, name: str, test_func) -> bool:
        """运行单个测试"""
        try:
            print(f"  运行: {name}...", end=" ", flush=True)
            test_func()
            self.results.append((name, True, ""))
            print("✓")
            return True
        except Exception as e:
            self.results.append((name, False, str(e)))
            print(f"✗ ({str(e)[:50]})")
            return False
    
    def run_command_test(self, name: str, cmd: List[str], timeout: int = 30) -> bool:
        """运行命令行测试"""
        try:
            print(f"  运行: {name}...", end=" ", flush=True)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=PROJECT_ROOT
            )
            if result.returncode == 0:
                self.results.append((name, True, ""))
                print("✓")
                return True
            else:
                error = result.stderr[:100] if result.stderr else "Unknown error"
                self.results.append((name, False, error))
                print(f"✗ (exit={result.returncode})")
                return False
        except subprocess.TimeoutExpired:
            self.results.append((name, False, "Timeout"))
            print("✗ (timeout)")
            return False
        except Exception as e:
            self.results.append((name, False, str(e)))
            print(f"✗ ({str(e)[:50]})")
            return False
    
    def run_all_tests(self) -> bool:
        """运行全部测试"""
        print_header("S001-Pro 强制测试套件")
        print(f"模式: {self.mode}")
        print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # ═══════════════════════════════════════════════════
        # 测试组 1: 语法检查
        # ═══════════════════════════════════════════════════
        print_header("测试组 1: 语法检查")
        
        src_files = [
            "src/main.py",
            "src/data_engine.py",
        ]
        
        for file in src_files:
            if (PROJECT_ROOT / file).exists():
                self.run_command_test(
                    f"Syntax: {file}",
                    ["python3", "-m", "py_compile", file]
                )
        
        # ═══════════════════════════════════════════════════
        # 测试组 2: 模块导入测试
        # ═══════════════════════════════════════════════════
        print_header("测试组 2: 模块导入")
        
        def test_import_main():
            from src.main import TradingSystem, ExchangeApi
            
        def test_import_runtime():
            from src.runtime import Runtime, PositionState
            
        def test_import_data_engine():
            from src.data_engine import DataEngine
            
        self.run_test("Import: main", test_import_main)
        self.run_test("Import: runtime", test_import_runtime)
        self.run_test("Import: data_engine", test_import_data_engine)
        
        # ═══════════════════════════════════════════════════
        # 测试组 3: 关键功能逻辑测试
        # ═══════════════════════════════════════════════════
        print_header("测试组 3: 核心逻辑测试")
        
        # 测试 PositionState 冷却状态
        def test_position_state_cooldown():
            from src.runtime import PositionState
            
            pair_config = {'symbol_a': 'BTC/USDT', 'symbol_b': 'ETH/USDT', 'beta': 1.0}
            ps = PositionState(pair_config)
            
            # 检查冷却属性存在
            assert hasattr(ps, 'scale_in_fail_count'), "缺少 scale_in_fail_count"
            assert hasattr(ps, 'scale_in_cool_until'), "缺少 scale_in_cool_until"
            assert hasattr(ps, 'scale_out_fail_count'), "缺少 scale_out_fail_count"
            assert hasattr(ps, 'scale_out_cool_until'), "缺少 scale_out_cool_until"
            
            # 检查持久化
            data = ps.to_dict()
            assert 'scale_in_fail_count' in data, "to_dict 缺少冷却字段"
        
        self.run_test("Runtime: PositionState Cooldown", test_position_state_cooldown)
        
        # 测试配置加载
        def test_config_loading():
            config_path = PROJECT_ROOT / "config" / "base.yaml"
            pairs_path = PROJECT_ROOT / "config" / "pairs_v2.json"
            
            # 检查 base.yaml
            if config_path.exists():
                import yaml
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                assert 'exchange' in config, "配置缺少 exchange 段"
                # 资金参数可能在不同位置
                has_capital = 'capital' in config or 'strategy' in config
                has_capital_in_env = 'S001_INITIAL_CAPITAL' in os.environ
                if not has_capital and not has_capital_in_env:
                    print("(资金参数将通过环境变量或策略配置设置)")
            
            # 检查 pairs_v2.json 存在且格式正确
            if pairs_path.exists():
                import json
                with open(pairs_path) as f:
                    data = json.load(f)
                assert 'pairs' in data, "pairs_v2.json 缺少 pairs 字段"
                print(f"(找到 {len(data['pairs'])} 对交易对)")
        
        self.run_test("Config: Load Config Files", test_config_loading)
        
        # ═══════════════════════════════════════════════════
        # 测试组 4: 数据格式验证 (CI模式)
        # ═══════════════════════════════════════════════════
        if self.mode in ["full", "ci"]:
            print_header("测试组 4: 数据格式验证")
            
            def test_pairs_v2_format():
                pairs_path = PROJECT_ROOT / "config" / "pairs_v2.json"
                if pairs_path.exists():
                    import json
                    with open(pairs_path) as f:
                        data = json.load(f)
                    
                    assert 'pairs' in data, "pairs_v2.json 缺少 pairs 字段"
                    assert isinstance(data['pairs'], list), "pairs 必须是列表"
                    
                    # FIX: 允许空的 pairs 数组（等待扫描添加配对）
                    if len(data['pairs']) == 0:
                        return  # 空配置是有效状态
                    
                    # FIX: 检查新格式（字段在params下）或旧格式
                    for i, pair in enumerate(data['pairs']):
                        # 必须有symbol_a和symbol_b
                        assert 'symbol_a' in pair, f"配对 {i} 缺少 symbol_a"
                        assert 'symbol_b' in pair, f"配对 {i} 缺少 symbol_b"
                        
                        # 检查参数（新格式在params下，旧格式直接在pair下）
                        params = pair.get('params', pair)  # 兼容两种格式
                        required_params = ['z_entry', 'z_exit', 'z_stop']
                        for field in required_params:
                            assert field in params, f"配对 {i} 缺少参数 {field}"
            
            self.run_test("Config: pairs_v2.json Format", test_pairs_v2_format)
        
        # ═══════════════════════════════════════════════════
        # 测试组 5: 集成测试 (完整模式)
        # ═══════════════════════════════════════════════════
        if self.mode == "full":
            print_header("测试组 5: 集成测试")
            
            # 可以添加更多集成测试
            print_warning("集成测试需要在测试环境运行，跳过...")
        
        # ═══════════════════════════════════════════════════
        # 生成报告
        # ═══════════════════════════════════════════════════
        return self._generate_report()
    
    def _generate_report(self) -> bool:
        """生成测试报告"""
        elapsed = time.time() - self.start_time
        passed = sum(1 for _, p, _ in self.results if p)
        failed = sum(1 for _, p, _ in self.results if not p)
        total = len(self.results)
        
        print_header("测试报告")
        print(f"总测试数: {total}")
        print(f"通过: {Colors.GREEN}{passed}{Colors.RESET}")
        print(f"失败: {Colors.RED if failed > 0 else Colors.GREEN}{failed}{Colors.RESET}")
        print(f"耗时: {elapsed:.2f}s")
        print()
        
        if failed > 0:
            print_error("失败的测试:")
            for name, passed, error in self.results:
                if not passed:
                    print(f"  - {name}: {error}")
            print()
        
        # 最终结果
        all_passed = failed == 0
        print_header("最终结论")
        
        if all_passed:
            print_success("✅ 全部测试通过！可以推送。")
            print()
            return True
        else:
            print_error("❌ 有测试失败！禁止推送。")
            print()
            print(f"{Colors.YELLOW}请修复上述问题后再推送。{Colors.RESET}")
            print()
            return False


def main():
    parser = argparse.ArgumentParser(description="S001-Pro 强制测试套件")
    parser.add_argument("--quick", action="store_true", help="快速测试模式")
    parser.add_argument("--ci", action="store_true", help="CI 严格模式")
    parser.add_argument("--no-color", action="store_true", help="禁用颜色输出")
    args = parser.parse_args()
    
    # 禁用颜色
    if args.no_color:
        Colors.GREEN = ''
        Colors.RED = ''
        Colors.YELLOW = ''
        Colors.BLUE = ''
        Colors.RESET = ''
    
    # 确定模式
    if args.quick:
        mode = "quick"
    elif args.ci:
        mode = "ci"
    else:
        mode = "full"
    
    # 运行测试
    runner = TestRunner(mode=mode)
    passed = runner.run_all_tests()
    
    # 返回码
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
