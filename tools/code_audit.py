#!/usr/bin/env python3
"""
S001-Pro 代码审计工具

检查项:
  1. 重复代码检测
  2. 死代码(未引用函数)
  3. 潜在Bug模式
  4. 硬编码值
  5. 异常处理缺失
  6. 文档同步检查

用法:
  python tools/code_audit.py
"""

import ast
import re
import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple
from collections import defaultdict


class CodeAuditor:
    """代码审计器"""
    
    def __init__(self, src_dir: str = "src"):
        self.src_dir = Path(src_dir)
        self.issues: List[Dict] = []
        self.stats = {
            "total_files": 0,
            "total_lines": 0,
            "functions": 0,
            "classes": 0,
        }
    
    def audit_all(self):
        """执行完整审计"""
        print("="*70)
        print("🔍 S001-Pro 代码审计")
        print("="*70)
        
        py_files = list(self.src_dir.rglob("*.py"))
        py_files = [f for f in py_files if "__pycache__" not in str(f)]
        
        self.stats["total_files"] = len(py_files)
        
        # 1. 检查重复代码
        self.check_duplicate_code(py_files)
        
        # 2. 检查死代码
        self.check_dead_code(py_files)
        
        # 3. 检查潜在Bug
        self.check_potential_bugs(py_files)
        
        # 4. 检查硬编码
        self.check_hardcoded_values(py_files)
        
        # 5. 检查异常处理
        self.check_exception_handling(py_files)
        
        # 6. 检查导入
        self.check_imports(py_files)
        
        self.print_report()
    
    def check_duplicate_code(self, files: List[Path]):
        """检查重复代码块"""
        print("\n📋 检查重复代码...")
        
        # 提取函数体进行比较
        function_bodies = {}
        
        for f in files:
            try:
                content = f.read_text()
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # 提取函数体前5行
                        lines = content.split('\n')[node.lineno:node.lineno+5]
                        body = '\n'.join(lines)
                        
                        if len(body) > 100:  # 只比较足够大的函数
                            if body in function_bodies:
                                other_file, other_name = function_bodies[body]
                                if node.name != other_name:  # 不同函数名但内容相似
                                    self.issues.append({
                                        "type": "重复代码",
                                        "severity": "MEDIUM",
                                        "file": str(f),
                                        "line": node.lineno,
                                        "message": f"函数 {node.name} 与 {other_file}:{other_name} 前5行相似"
                                    })
                            else:
                                function_bodies[body] = (str(f), node.name)
            except:
                pass
        
        # 检查重复的常量定义
        constants = defaultdict(list)
        for f in files:
            try:
                content = f.read_text()
                # 匹配类似 STATE_IDLE = "IDLE" 的常量
                for match in re.finditer(r'^([A-Z_]+)\s*=\s*(.+)$', content, re.MULTILINE):
                    name, value = match.groups()
                    constants[(name, value)].append((str(f), match.start()))
            except:
                pass
        
        for (name, value), locations in constants.items():
            if len(locations) > 1:
                self.issues.append({
                    "type": "重复常量",
                    "severity": "LOW",
                    "file": locations[0][0],
                    "line": 0,
                    "message": f"常量 {name} = {value} 在 {len(locations)} 个文件中重复定义"
                })
    
    def check_dead_code(self, files: List[Path]):
        """检查死代码"""
        print("\n📋 检查死代码...")
        
        all_defined = set()
        all_used = set()
        
        for f in files:
            try:
                content = f.read_text()
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        all_defined.add(node.name)
                        # 检查函数内部调用
                        for child in ast.walk(node):
                            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                                all_used.add(child.func.id)
                    elif isinstance(node, ast.ClassDef):
                        all_defined.add(node.name)
            except:
                pass
        
        # 检查私有函数(下划线开头)是否被使用
        private_functions = [f for f in all_defined if f.startswith('_') and not f.startswith('__')]
        for func in private_functions:
            if func not in all_used and func != '_':
                self.issues.append({
                    "type": "死代码",
                    "severity": "LOW",
                    "file": "src",
                    "line": 0,
                    "message": f"私有函数 {func} 可能未被使用"
                })
    
    def check_potential_bugs(self, files: List[Path]):
        """检查潜在Bug"""
        print("\n📋 检查潜在Bug...")
        
        bug_patterns = [
            (r'time\.sleep\s*\(\s*0\s*\)', "time.sleep(0) 无意义"),
            (r'while\s+True\s*:\s*\n\s*if\s+.*:\s*break', "危险的while True循环，确保有退出条件"),
            (r'except\s*:\s*\n\s*pass', "裸except:pass会吞掉所有异常"),
            (r'==\s*None', "使用 'is None' 而不是 '== None'"),
            (r'!=\s*None', "使用 'is not None' 而不是 '!= None'"),
            (r'\.get\([^)]+\)\s*\[', "dict.get()可能返回None，不能直接索引"),
            (r'asyncio\.gather\([^)]+\)', "asyncio.gather需要return_exceptions=True防止一个失败全失败"),
        ]
        
        for f in files:
            try:
                content = f.read_text()
                for pattern, message in bug_patterns:
                    for match in re.finditer(pattern, content):
                        line = content[:match.start()].count('\n') + 1
                        self.issues.append({
                            "type": "潜在Bug",
                            "severity": "HIGH" if "except" in message else "MEDIUM",
                            "file": str(f),
                            "line": line,
                            "message": message
                        })
            except:
                pass
    
    def check_hardcoded_values(self, files: List[Path]):
        """检查硬编码值"""
        print("\n📋 检查硬编码值...")
        
        # 应该提取到配置的硬编码
        magic_numbers = [
            (r'5000\.0', "max_position_value_usd"),
            (r'300\s*\*\s*1000', "冷却时间300秒"),
            (r'90\s*\*\s*1000', "ORDER_CONFIRM_TIMEOUT"),
            (r'5\s*\*\s*1000', "ORDER_CONFIRM_INTERVAL"),
        ]
        
        for f in files:
            if "config" in str(f) or "test" in str(f):
                continue
            
            try:
                content = f.read_text()
                for pattern, desc in magic_numbers:
                    for match in re.finditer(pattern, content):
                        line = content[:match.start()].count('\n') + 1
                        self.issues.append({
                            "type": "硬编码",
                            "severity": "LOW",
                            "file": str(f),
                            "line": line,
                            "message": f"硬编码值 '{match.group()}' 应该提取为常量: {desc}"
                        })
            except:
                pass
    
    def check_exception_handling(self, files: List[Path]):
        """检查异常处理"""
        print("\n📋 检查异常处理...")
        
        for f in files:
            try:
                content = f.read_text()
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Try):
                        # 检查是否有空的except块
                        for handler in node.handlers:
                            if handler.body and len(handler.body) == 1:
                                if isinstance(handler.body[0], ast.Pass):
                                    self.issues.append({
                                        "type": "异常处理",
                                        "severity": "MEDIUM",
                                        "file": str(f),
                                        "line": handler.lineno,
                                        "message": "空的except块会吞掉异常"
                                    })
                            
                            # 检查是否捕获了具体异常
                            if not handler.type:
                                self.issues.append({
                                    "type": "异常处理",
                                    "severity": "HIGH",
                                    "file": str(f),
                                    "line": handler.lineno,
                                    "message": "裸except会捕获所有异常包括KeyboardInterrupt"
                                })
            except:
                pass
    
    def check_imports(self, files: List[Path]):
        """检查导入问题"""
        print("\n📋 检查导入...")
        
        imports_by_name = defaultdict(list)
        
        for f in files:
            try:
                content = f.read_text()
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        for alias in node.names:
                            name = alias.name
                            imports_by_name[name].append(str(f))
            except:
                pass
        
        # 检查重复导入
        for name, locations in imports_by_name.items():
            if len(locations) > 3:  # 在超过3个文件中导入
                self.issues.append({
                    "type": "导入优化",
                    "severity": "INFO",
                    "file": locations[0],
                    "line": 0,
                    "message": f"{name} 在 {len(locations)} 个文件中导入，考虑提取到公共模块"
                })
    
    def print_report(self):
        """打印审计报告"""
        print("\n" + "="*70)
        print("📊 审计报告")
        print("="*70)
        
        # 按严重度分组
        by_severity = defaultdict(list)
        for issue in self.issues:
            by_severity[issue["severity"]].append(issue)
        
        for severity in ["HIGH", "MEDIUM", "LOW", "INFO"]:
            issues = by_severity.get(severity, [])
            if issues:
                print(f"\n🔴 {severity} 级别 ({len(issues)}项):")
                for issue in issues[:10]:  # 只显示前10个
                    print(f"  [{issue['type']}] {issue['file']}:{issue['line']}")
                    print(f"    → {issue['message']}")
                if len(issues) > 10:
                    print(f"  ... 还有 {len(issues)-10} 项")
        
        print("\n" + "="*70)
        print(f"总计: {len(self.issues)} 个问题")
        print(f"  HIGH: {len(by_severity.get('HIGH', []))}")
        print(f"  MEDIUM: {len(by_severity.get('MEDIUM', []))}")
        print(f"  LOW: {len(by_severity.get('LOW', []))}")
        print(f"  INFO: {len(by_severity.get('INFO', []))}")
        print("="*70)
        
        return len(by_severity.get('HIGH', [])) == 0


def main():
    auditor = CodeAuditor()
    success = auditor.audit_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
