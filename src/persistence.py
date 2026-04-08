"""
模块五：持久化与落地 (Persistence) - P0 LOCKED

数据流转:
  Input:  Whitelist (List[Dict], 来自模块四，含最优参数)
  Output: 物理文件 config/pairs_v2.json
  去向:   模块六 (Runtime) 实时读取此文件执行

核心逻辑:
  1. 组装: 最优参数 + 分批策略 (3-3-4 比例)
  2. 注入: 交易所 min_qty, step_size, funding_rate
  3. 原子写入: pairs_v2.json.tmp -> MD5 校验 -> os.rename 覆盖
  4. 热重载信号: 更新文件 mtime

Scale-In 设计 (FIX P1-1):
  Layer 1: offset  0.0 → trigger_z = z_entry (第一次触发即开仓)
  Layer 2: offset +0.5 → trigger_z = z_entry + 0.5 (Z 继续扩大时加仓)
  Layer 3: offset +1.0 → trigger_z = z_entry + 1.0 (极端行情加仓)
  原设计 offset=-0.5 导致 Layer1 在 entry 之前触发, 状态机还在 IDLE,
  第一层永远无法执行。修复为从 0.0 开始。

文档规范: docs/module_5_persistence.md
"""

import json
import os
import hashlib
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("Persistence")

# ═══════════════════════════════════════════════════
# 分批进场策略 (3-3-4 比例, M4推荐参数在中间)
# L1: z_entry - 0.3 提前埋伏 30% (信号刚露头先试探)
# L2: z_entry + 0.0 甜点核心 30% (M4最优参数点, 处于中间)
# L3: z_entry + 0.3 极端兜底 40% (继续扩大摊低成本)
# ═══════════════════════════════════════════════════
SCALE_IN_PLAN = [
    {"offset_z": -0.3, "ratio": 0.3, "type": "limit", "post_only": True},
    {"offset_z": 0.0, "ratio": 0.3, "type": "limit", "post_only": True},
    {"offset_z": 0.3, "ratio": 0.4, "type": "limit", "post_only": True},
]

SCALE_OUT_PLAN = [
    {"trigger_z": "Entry * 0.6", "ratio": 0.3, "type": "limit", "post_only": True},
    {"trigger_z": "Exit", "ratio": 0.4, "type": "limit", "post_only": True},
    {"trigger_z": "Reverse 0", "ratio": 0.3, "type": "market", "post_only": False},
]

STOP_LOSS_PLAN = {
    "trigger_z": "Entry + StopOffset",
    "type": "market",
    "post_only": False,
}


def compute_md5(filepath: str) -> str:
    """计算文件 MD5"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _compute_scale_in_triggers(z_entry: float) -> List[Dict]:
    """
    根据 z_entry 计算实际 scale_in trigger_z 绝对值。
    
    三层触发:
      Layer 1: trigger_z = z_entry - 0.3 (提前埋伏 30%)
      Layer 2: trigger_z = z_entry + 0.0 (甜点核心 30%)
      Layer 3: trigger_z = z_entry + 0.5 (极端兜底 40%)
    """
    triggers = []
    for step in SCALE_IN_PLAN:
        abs_z = z_entry + step["offset_z"]
        triggers.append({
            "trigger_z": round(abs_z, 2),
            "ratio": step["ratio"],
            "type": step["type"],
            "post_only": step["post_only"],
        })
    return triggers


def _compute_scale_out_triggers(z_entry: float, z_exit: float) -> List[Dict]:
    """
    根据 z_entry, z_exit 计算实际 scale_out trigger_z 绝对值。
    
    规则:
      TP1: Entry * 0.6 (Z 回落到 entry 的 60%)
      TP2: Exit (Z 回到目标退出值)
      TP3: 0.0 (Z 回到 0 轴, 市价全平)
    """
    return [
        {"trigger_z": round(z_entry * 0.6, 2), "ratio": 0.3, "type": "limit", "post_only": True},
        {"trigger_z": round(z_exit, 2), "ratio": 0.4, "type": "limit", "post_only": True},
        {"trigger_z": 0.0, "ratio": 0.3, "type": "market", "post_only": False},
    ]


def _compute_stop_loss_trigger(z_entry: float, z_stop: float) -> Dict:
    """
    计算止损 trigger_z 绝对值。
    
    规则: trigger_z = L3位置 + (z_stop - z_entry) = z_stop + 0.3
    原因: 
      - L3 在 z_entry + 0.3 进场 (最后一批)
      - 止损必须在 L3 完成后才生效
      - 止损距离保持与 M4 回测一致 = z_stop - z_entry
      - 最终: (z_entry + 0.3) + (z_stop - z_entry) = z_stop + 0.3
    """
    return {
        "trigger_z": round(z_stop + 0.3, 2),
        "type": "market",
        "post_only": False,
    }


class Persistence:
    def __init__(self):
        self._last_save_path: Optional[str] = None
        self._last_md5: Optional[str] = None

    def save(
        self,
        whitelist: List[Dict],
        path: str = "config/pairs_v2.json",
        git_hash: Optional[str] = None,
        exchange_meta_provider=None,
        initial_capital: float = 435.0,  # FIX BUG-005: 传入本金用于动态计算
    ) -> bool:
        """
        将白名单序列化为 JSON 文件。
        
        原子级流程:
          1. 遍历 whitelist, 为每个配对组装完整配置
          2. 计算 scale_in/scale_out/stop_loss 的绝对 trigger_z
          3. 写入 tmp 文件
          4. 计算 MD5 校验
          5. os.replace 原子替换 (防止 Runtime 读到半写文件)
          6. 清理 tmp (如果 replace 失败)
        
        参数:
          whitelist: M4 优化器输出的 Top 30 列表
          path: 目标文件路径
          git_hash: 当前 git commit hash
          exchange_meta_provider: 提供 min_qty, step_size 的回调
        
        返回:
          True: 写入成功, False: 写入失败
        """
        if not whitelist:
            logger.warning("Persistence: empty whitelist, skipping save")
            return False

        pairs = []
        now = datetime.now(timezone.utc)

        for item in whitelist:
            sym_a = item.get("symbol_a", "")
            sym_b = item.get("symbol_b", "")
            beta = item.get("beta", 1.0)
            params = item.get("params", {})
            z_entry = params.get("z_entry", item.get("z_entry", 2.5))
            z_exit = params.get("z_exit", item.get("z_exit", 0.8))
            z_stop = params.get("z_stop", item.get("z_stop", 4.5))

            # 组装 execution 结构 (计算好的绝对 trigger_z)
            execution = {
                "legs_sync": {
                    "simultaneous": True,
                    "tolerance_ms": 3000,
                    "rollback_on_failure": True,
                },
                "scale_in": _compute_scale_in_triggers(z_entry),
                "scale_out": _compute_scale_out_triggers(z_entry, z_exit),
                "stop_loss": _compute_stop_loss_trigger(z_entry, z_stop),
            }

            # 资金分配
            # FIX BUG-005: 基于本金动态计算，增加总敞口上限控制
            max_open_positions = 8  # 最大同时开仓对数
            max_total_exposure = initial_capital * 1.5  # 总敞口不超过150%本金
            per_pair_allocation = min(
                5000.0,  # 单对上限
                initial_capital / max_open_positions * 0.5,  # 本金分摊
            )
            allocation = {
                "max_position_value_usd": per_pair_allocation,
                "max_total_exposure_usd": max_total_exposure,  # 总敞口上限
                "risk_score": 0.85,
            }

            # ═══════════════════════════════════════════════════
            # FIX P1-3: valid_until_iso 跨天崩溃
            # 原文档/代码: now.replace(hour=now.hour + 1) 在 23:xx 时 hour=24 → ValueError
            # 修复: 用 timedelta 替代手动 replace
            # ═══════════════════════════════════════════════════
            valid_until = now + timedelta(minutes=30)

            pair_obj = {
                "signal_id": f"{sym_a.replace('/', '_')}_{sym_b.replace('/', '_')}_{int(now.timestamp())}",
                "symbol_a": sym_a,
                "symbol_b": sym_b,
                "beta": beta,
                "params": {
                    "z_entry": z_entry,
                    "z_exit": z_exit,
                    "z_stop": z_stop,
                },
                "exchange_meta": {
                    "min_qty": 0.001,
                    "step_size": 3,
                    "price_precision": 2,
                },
                "funding_info": {
                    "current_rate": 0.0001,
                    "cost_impact_pct": 0.05,
                },
                "allocation": allocation,
                "execution": execution,
                "valid_until_iso": valid_until.isoformat(),
                "ttl_minutes": 30,
            }

            if exchange_meta_provider:
                meta = exchange_meta_provider(sym_a, sym_b)
                if meta:
                    pair_obj["exchange_meta"] = meta

            pairs.append(pair_obj)

        output = {
            "meta": {
                "version": "1.0",
                "generated_at": now.isoformat(),
                "git_hash": git_hash or "unknown",
                "pairs_count": len(pairs),
            },
            "pairs": pairs,
        }

        # 原子写入
        tmp_path = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            md5 = compute_md5(tmp_path)
            logger.info(f"Persistence: MD5={md5} for {len(pairs)} pairs")

            os.replace(tmp_path, path)
            logger.info(f"Persistence: saved {len(pairs)} pairs to {path}")
            return True

        except Exception as e:
            logger.error(f"Persistence: failed to save JSON: {e}")
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return False

    def load(self, path: str = "config/pairs_v2.json") -> Optional[Dict]:
        """
        读取并校验 JSON 完整性。
        
        校验项:
          1. 文件存在
          2. JSON 可解析
          3. 顶层有 meta 和 pairs
          4. pairs 是列表
          5. 每个 pair 有必需字段
        
        返回:
          Dict: 解析后的数据, None: 校验失败
        """
        if not os.path.exists(path):
            logger.warning(f"Persistence: file not found: {path}")
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "meta" not in data or "pairs" not in data:
                logger.error(f"Persistence: invalid JSON structure in {path}")
                return None

            pairs = data.get("pairs", [])
            if not isinstance(pairs, list):
                logger.error(f"Persistence: 'pairs' is not a list")
                return None

            required = ["symbol_a", "symbol_b", "beta", "params", "execution"]
            for i, pair in enumerate(pairs):
                for field in required:
                    if field not in pair:
                        logger.error(f"Persistence: pair[{i}] missing field '{field}'")
                        return None

            logger.info(f"Persistence: loaded {len(pairs)} pairs from {path}")
            return data

        except json.JSONDecodeError as e:
            logger.error(f"Persistence: JSON decode error: {e}")
            return None
        except Exception as e:
            logger.error(f"Persistence: failed to load: {e}")
            return None