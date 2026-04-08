"""
S001-Pro 常量定义
集中管理所有硬编码参数，消除魔法数字
"""

# ==================== 信号参数 ====================
DEFAULT_Z_ENTRY = 2.5
DEFAULT_Z_EXIT = 1.0
DEFAULT_Z_STOP = 3.5
MIN_Z_ENTRY = 1.5
MAX_Z_ENTRY = 5.0

# ==================== 仓位管理 ====================
POSITION_COMPLETE_THRESHOLD = 0.99  # 仓位完成阈值
POSITION_EMPTY_THRESHOLD = 0.01     # 仓位清空阈值
DEFAULT_POSITION_SIZE_PCT = 1.0     # 默认仓位百分比

# ==================== 分配限制 ====================
DEFAULT_MAX_POSITION_VALUE_USD = 5000.0
MAX_POSITION_VALUE_USD_LIMIT = 10000.0

# ==================== 执行参数 ====================
DEFAULT_POST_ONLY = True
ROLLBACK_TIMEOUT_SECONDS = 30
ORDER_TIMEOUT_SECONDS = 10
MAX_RETRY_ATTEMPTS = 3

# ==================== 风控限制 ====================
MAX_DAILY_DRAWDOWN_PCT = -5.0
MIN_LEVERAGE = 1
MAX_LEVERAGE = 20

# ==================== 数据参数 ====================
MIN_LIQUIDITY_VOLUME_USD = 2_000_000  # 200万U流动性门槛
MIN_HISTORY_DAYS = 90
DEFAULT_LOOKBACK_BARS = 5000

# ==================== 扫描参数 ====================
SCANNER_TOP_N_SYMBOLS = 150
SCANNER_MIN_PAIRS = 10
SCANNER_MAX_PAIRS = 50

# ==================== 时间参数 ====================
POSITION_SYNC_INTERVAL_SECONDS = 60
HEARTBEAT_INTERVAL_SECONDS = 30
WATCHDOG_CHECK_INTERVAL_SECONDS = 60

# ==================== 文件路径 ====================
DEFAULT_PAIRS_FILE = "config/pairs_v2.json"
DEFAULT_STATE_FILE = "data/state.json"
DEFAULT_LOG_DIR = "logs"
DEFAULT_SNAPSHOT_FILE = "data/restart_snapshots.jsonl"
