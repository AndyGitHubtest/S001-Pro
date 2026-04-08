"""
模块八：配置与参数管理 (ConfigManager) - P0 LOCKED

数据流转:
  Input:
    Static Config:  config/base.yaml (API Key, DB Path, Risk Limits, ...)
    Dynamic Config: config/pairs_v2.json (M5 生成，含交易参数、执行策略)
  Processing:
    启动加载 -> Schema 校验 -> 合并默认值 -> 注入内存对象
    文件监听 (Watcher) -> 检测变动 -> 热重载 (Hot Reload)
  Output:
    Global Config Object: 供模块 1-9 全局只读调用
    Validation Errors: 若校验失败，阻断启动或回滚配置

文档规范: docs/module_8_config_management.md
"""

import os
import json
import logging
import time
from typing import Dict, Optional, Callable

logger = logging.getLogger("ConfigManager")

# 默认安全值
DEFAULTS = {
    "system": {
        "env": "production",
        "log_level": "INFO",
        "timezone": "Asia/Shanghai",
        "data_dir": "./data",
        "log_dir": "./logs",
    },
    "exchange": {
        "name": "binance",
        "testnet": False,
        "rate_limit_rps": 5.0,
    },
    "risk": {
        "initial_capital": 10000.0,
        "max_drawdown_pct": 15.0,
        "max_daily_loss_pct": 5.0,
        "max_open_positions": 6,
        "isolated_margin": True,
    },
    "notifications": {
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "alert_level": "ERROR",
    },
}


def _load_yaml_safe(path: str) -> Dict:
    """
    安全加载 YAML。优先用 PyYAML，无则用简易解析器。
    """
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        logger.warning("ConfigManager: PyYAML not installed, using simple parser")
        return _simple_yaml_parse(path)


def _simple_yaml_parse(path: str) -> Dict:
    """
    简易 YAML 解析器 (支持两级嵌套的 key: value)。
    仅用于没有 PyYAML 的降级场景。
    """
    result = {}
    current_section = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith(" ") and line.endswith(":"):
                current_section = line[:-1].strip()
                result[current_section] = {}
            elif ":" in line and current_section:
                key, val = line.strip().split(":", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                # 类型转换
                if val.lower() == "true":
                    val = True
                elif val.lower() == "false":
                    val = False
                else:
                    try:
                        val = int(val)
                    except ValueError:
                        try:
                            val = float(val)
                        except ValueError:
                            logging.getLogger("ConfigManager").debug(
                                f"Config: keeping '{key}={val}' as string (not numeric)"
                            )
                result[current_section][key] = val
    return result


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """深度合并两个字典，override 优先"""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


class ConfigManager:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self.base_path = os.path.join(config_dir, "base.yaml")
        self.pairs_path = os.path.join(config_dir, "pairs_v2.json")
        self._config: Dict = {}
        self._pairs_data: Dict = {}
        self._pairs_mtime: float = 0
        self._callback: Optional[Callable] = None
        self._running = False

    def load_and_validate(self) -> Dict:
        """
        启动时加载，失败则抛异常终止进程。
        
        FIX P1-6: 支持环境变量注入敏感配置
          S001_BINANCE_API_KEY    -> exchange.api_key
          S001_BINANCE_API_SECRET -> exchange.api_secret
          S001_TG_BOT_TOKEN       -> notifications.telegram_bot_token
          S001_TG_CHAT_ID         -> notifications.telegram_chat_id
          S001_INITIAL_CAPITAL    -> risk.initial_capital
        """
        # 1. 加载 base.yaml
        if os.path.exists(self.base_path):
            raw = _load_yaml_safe(self.base_path)
            self._config = _deep_merge(DEFAULTS, raw)
            logger.info(f"ConfigManager: loaded base.yaml from {self.base_path}")
        else:
            self._config = DEFAULTS.copy()
            logger.warning("ConfigManager: base.yaml not found, using defaults")

        # FIX P1-6: 环境变量注入 (优先级 > 配置文件)
        self._inject_env_vars()

        # 2. 严格校验 (必填项检查)
        self._validate_base_config()

        # 3. 加载 pairs_v2.json (如果存在)
        if os.path.exists(self.pairs_path):
            self._load_pairs_config()

        return self._config

    def _inject_env_vars(self):
        """FIX P1-6: 从环境变量注入敏感配置"""
        env_map = {
            "S001_BINANCE_API_KEY": ("exchange", "api_key"),
            "S001_BINANCE_API_SECRET": ("exchange", "api_secret"),
            "S001_TG_BOT_TOKEN": ("notifications", "telegram_bot_token"),
            "S001_TG_CHAT_ID": ("notifications", "telegram_chat_id"),
            "S001_TESTNET": ("exchange", "testnet"),
        }
        for env_name, (section, key) in env_map.items():
            val = os.environ.get(env_name)
            if val:
                if section not in self._config:
                    self._config[section] = {}
                # Boolean conversion for known boolean fields
                if key == "testnet":
                    self._config[section][key] = val.lower() in ("true", "1", "yes")
                else:
                    self._config[section][key] = val
                logger.info(f"ConfigManager: injected {env_name} -> {section}.{key}")

        # initial_capital
        capital = os.environ.get("S001_INITIAL_CAPITAL")
        if capital:
            if "risk" not in self._config:
                self._config["risk"] = {}
            try:
                self._config["risk"]["initial_capital"] = float(capital)
            except ValueError:
                logger.warning(f"ConfigManager: invalid S001_INITIAL_CAPITAL={capital}")

    def _validate_base_config(self):
        """
        严格校验 base.yaml。
        必填项: api_key, api_secret (非 testnet 时)
        范围检查: max_drawdown_pct > 0, leverage >= 1
        """
        exchange = self._config.get("exchange", {})
        risk = self._config.get("risk", {})

        # 必填项: 非 testnet 时必须有 API key
        if not exchange.get("testnet", False):
            if not exchange.get("api_key") or not exchange.get("api_secret"):
                raise ValueError(
                    "ConfigManager: api_key and api_secret are required for live trading. "
                    "Set testnet=true for testing."
                )

        # 范围检查
        mdd = risk.get("max_drawdown_pct", 0)
        if mdd <= 0:
            raise ValueError(f"ConfigManager: max_drawdown_pct must be > 0, got {mdd}")

        daily_loss = risk.get("max_daily_loss_pct", 0)
        if daily_loss <= 0:
            raise ValueError(f"ConfigManager: max_daily_loss_pct must be > 0, got {daily_loss}")

        max_pos = risk.get("max_open_positions", 0)
        if max_pos <= 0:
            raise ValueError(f"ConfigManager: max_open_positions must be > 0, got {max_pos}")

        logger.info("ConfigManager: base config validation passed")

    def _load_pairs_config(self) -> bool:
        """
        加载 pairs_v2.json 并校验。
        """
        try:
            with open(self.pairs_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"ConfigManager: failed to load pairs_v2.json: {e}")
            return False

        # 校验
        if not self._validate_pairs_data(data):
            return False

        self._pairs_data = data
        self._pairs_mtime = os.path.getmtime(self.pairs_path)
        logger.info(f"ConfigManager: loaded {len(data.get('pairs', []))} pairs from pairs_v2.json")
        return True

    def _validate_pairs_data(self, data: Dict) -> bool:
        """
        校验 pairs_v2.json 结构 - 加固版
        
        HARDENING:
        1. 最大配对数量限制
        2. 参数范围检查
        3. symbol格式验证
        4. beta值合理性检查
        """
        if not isinstance(data, dict):
            logger.error("ConfigManager: pairs_v2.json must be a dict")
            return False

        pairs = data.get("pairs", [])
        if not isinstance(pairs, list):
            logger.error("ConfigManager: pairs must be a list")
            return False
        
        # HARDENING: 最大配对数量限制 (防止配置错误导致资源耗尽)
        MAX_PAIRS = 100
        if len(pairs) > MAX_PAIRS:
            logger.error(f"[HARDENING] Too many pairs: {len(pairs)} > {MAX_PAIRS}")
            return False
        
        seen_pairs = set()  # 用于检测重复配对

        for i, pair in enumerate(pairs):
            # 必填字段 (兼容旧格式：允许params字段直接放在pair中)
            for field in ["symbol_a", "symbol_b", "beta"]:
                if field not in pair:
                    logger.error(f"ConfigManager: pair[{i}] missing field '{field}'")
                    return False
            
            # HARDENING: symbol格式验证
            symbol_a = pair.get("symbol_a", "")
            symbol_b = pair.get("symbol_b", "")
            
            if not isinstance(symbol_a, str) or not isinstance(symbol_b, str):
                logger.error(f"[HARDENING] pair[{i}] symbols must be strings")
                return False
            
            if "/" not in symbol_a or "/" not in symbol_b:
                logger.error(f"[HARDENING] pair[{i}] invalid symbol format: {symbol_a}, {symbol_b}")
                return False
            
            # HARDENING: 检测重复配对
            pair_key = f"{symbol_a}_{symbol_b}"
            if pair_key in seen_pairs:
                logger.error(f"[HARDENING] Duplicate pair: {pair_key}")
                return False
            seen_pairs.add(pair_key)
            
            # HARDENING: beta值检查
            beta = pair.get("beta", 0)
            if not isinstance(beta, (int, float)):
                logger.error(f"[HARDENING] pair[{i}] beta must be numeric")
                return False
            
            if beta <= 0 or beta > 10:  # 合理范围
                logger.error(f"[HARDENING] pair[{i}] beta out of range: {beta}")
                return False

            # 兼容旧格式：params可以是嵌套对象或直接字段
            params = pair.get("params", {})
            # 如果params为空，从pair直接读取参数
            if not params:
                params = {
                    "z_entry": pair.get("z_entry", 2.0),
                    "z_exit": pair.get("z_exit", 0.2),
                    "z_stop": pair.get("z_stop", 3.5),
                    "max_hold_hours": pair.get("max_hold_hours", 24)
                }
            
            # 逻辑检查: z_entry < z_stop
            z_entry = params.get("z_entry", 0)
            z_stop = params.get("z_stop", 0)
            if z_entry >= z_stop:
                logger.error(f"ConfigManager: pair[{i}] z_entry ({z_entry}) must be < z_stop ({z_stop})")
                return False
            
            # HARDENING: 参数范围检查
            if z_entry < 0.5 or z_entry > 5.0:
                logger.warning(f"[HARDENING] pair[{i}] unusual z_entry: {z_entry}")
            
            if z_stop < 2.0 or z_stop > 10.0:
                logger.warning(f"[HARDENING] pair[{i}] unusual z_stop: {z_stop}")

            # 校验 scale_in ratios 总和 == 1.0 (兼容旧格式，允许无execution字段)
            execution = pair.get("execution", {})
            if not execution:
                # 旧格式使用默认配置
                continue
            scale_in = execution.get("scale_in", [])
            if scale_in:
                total_ratio = sum(s.get("ratio", 0) for s in scale_in)
                if abs(total_ratio - 1.0) > 0.01:
                    logger.error(f"ConfigManager: pair[{i}] scale_in ratios sum to {total_ratio}, expected 1.0")
                    return False

            # 校验 tolerance_ms > 0
            legs_sync = execution.get("legs_sync", {})
            tolerance = legs_sync.get("tolerance_ms", 0)
            if tolerance <= 0:
                logger.error(f"ConfigManager: pair[{i}] tolerance_ms must be > 0")
                return False

        logger.info(f"ConfigManager: pairs_v2.json validation passed ({len(pairs)} pairs)")
        return True

    def watch_config(self, callback: Callable):
        """
        启动后台线程/协程监控文件变动，触发回调。
        """
        import threading

        self._callback = callback
        self._running = True

        def _watcher():
            logger.info("ConfigManager: file watcher started")
            while self._running:
                time.sleep(2)

                # 检查 pairs_v2.json mtime 变动
                if os.path.exists(self.pairs_path):
                    mtime = os.path.getmtime(self.pairs_path)
                    if mtime > self._pairs_mtime:
                        logger.info("ConfigManager: pairs_v2.json changed, hot reloading...")
                        if self._load_pairs_config():
                            self._pairs_mtime = mtime
                            if self._callback:
                                self._callback("pairs_updated", self._pairs_data)
                        else:
                            logger.error("ConfigManager: hot reload failed, keeping old config")

        thread = threading.Thread(target=_watcher, daemon=True)
        thread.start()
        logger.info("ConfigManager: watcher thread started")

    def stop_watching(self):
        """停止文件监控"""
        self._running = False
        logger.info("ConfigManager: watcher stopped")

    def get_pair_config(self, symbol_pair: str) -> Optional[Dict]:
        """
        获取指定配对的完整执行参数。
        symbol_pair 格式: "BTC/USDT_ETH/USDT" 或 "BTC/USDT-ETH/USDT"
        """
        pairs = self._pairs_data.get("pairs", [])
        # 规范化 key
        key_normalized = symbol_pair.replace("-", "_")
        for pair in pairs:
            pair_key = f"{pair['symbol_a']}_{pair['symbol_b']}"
            if pair_key == key_normalized:
                return pair
        return None

    @property
    def config(self) -> Dict:
        """全局配置 (只读)"""
        return self._config

    @property
    def pairs_data(self) -> Dict:
        """配对配置 (只读)"""
        return self._pairs_data
