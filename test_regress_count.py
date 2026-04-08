#!/usr/bin/env python3
"""测试 _regression_count 性能"""
import sys
sys.path.insert(0, 'src')

import numpy as np
import time
from pairwise_scorer import _regression_count, HAS_NUMBA

print("="*60)
print("_regression_count 性能测试")
print("="*60)
print(f"HAS_NUMBA: {HAS_NUMBA}")

# 生成测试数据
np.random.seed(42)
n = 50000  # 模拟 30 天数据
spread = np.cumsum(np.random.randn(n) * 0.01).astype(np.float32)

print(f"\n测试数据: {n} 点, dtype={spread.dtype}")

# 预热
_ = _regression_count(spread, window=288, z_threshold=1.0)

# 正式测试
start = time.time()
result = _regression_count(spread, window=288, z_threshold=1.0)
elapsed = time.time() - start

print(f"\n结果: reg_count = {result}")
print(f"耗时: {elapsed:.3f}s")

# 多次测试取平均
times = []
for _ in range(5):
    start = time.time()
    r = _regression_count(spread, window=288, z_threshold=1.0)
    times.append(time.time() - start)

avg_time = np.mean(times)
print(f"平均耗时 (5次): {avg_time:.3f}s")

# 对比纯 Python
def _regression_count_py(series, window=288, z_threshold=1.0):
    n = len(series)
    if n < window + 100:
        return 0
    reg_count = 0
    is_outside = False
    for i in range(window, n):
        w = series[i - window:i]
        w_mean = np.mean(w)
        w_std = np.std(w) + 1e-12
        z = abs(series[i] - w_mean) / w_std
        if z > z_threshold:
            is_outside = True
        elif is_outside and z < 0.5:
            reg_count += 1
            is_outside = False
    return reg_count

start = time.time()
result_py = _regression_count_py(spread, window=288, z_threshold=1.0)
elapsed_py = time.time() - start

print(f"\n纯 Python 版本:")
print(f"  结果: {result_py}")
print(f"  耗时: {elapsed_py:.3f}s")
print(f"\n加速比: {elapsed_py/avg_time:.1f}x")

if result == result_py and result > 0:
    print("\n✅ 测试通过: 结果正确且性能提升")
else:
    print(f"\n❌ 测试失败: Numba={result}, Python={result_py}")
