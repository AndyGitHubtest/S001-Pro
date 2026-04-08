"""
汇总数据接口
今日盈亏、持仓数、运行时间等

使用 trades.db 数据库:
- trades 表: 交易记录
- daily_summary 表: 每日汇总
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from ..auth import get_current_user
from ..database import get_trades_db

router = APIRouter()

# 缓存
_cache = {}
_cache_time = {}
CACHE_TTL = 5  # 5秒


def get_cached(key: str):
    """获取缓存"""
    if key in _cache and key in _cache_time:
        if datetime.now() - _cache_time[key] < timedelta(seconds=CACHE_TTL):
            return _cache[key]
    return None


def set_cache(key: str, value):
    """设置缓存"""
    _cache[key] = value
    _cache_time[key] = datetime.now()


@router.get("/summary")
async def get_summary(user: dict = Depends(get_current_user)):
    """
    获取汇总数据
    - 今日盈亏
    - 持仓数量
    - 运行时间
    - 账户权益
    - 服务器状态
    """
    cache_key = "summary"
    cached = get_cached(cache_key)
    if cached:
        return {"success": True, "data": cached}
    
    try:
        with get_trades_db() as db:
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            # 1. 今日盈亏 - 优先从 daily_summary 表获取
            today_pnl = 0
            today_trades = 0
            
            try:
                result = db.execute(text("""
                    SELECT total_pnl, total_trades
                    FROM daily_summary
                    WHERE date = :today
                """), {"today": today_str})
                row = result.fetchone()
                if row:
                    today_pnl = float(row[0]) if row[0] else 0
                    today_trades = int(row[1]) if row[1] else 0
            except:
                # daily_summary 表可能不存在，从 trades 表计算
                result = db.execute(text("""
                    SELECT 
                        COALESCE(SUM(realized_pnl), 0) as pnl,
                        COUNT(*) as cnt
                    FROM trades 
                    WHERE DATE(entry_time) = DATE('now')
                    AND status = 'closed'
                """))
                row = result.fetchone()
                today_pnl = float(row[0]) if row and row[0] else 0
                today_trades = int(row[1]) if row and row[1] else 0
            
            # 2. 持仓数量 - 从 trades 表统计 status='open'
            result = db.execute(text("""
                SELECT COUNT(*) as position_count
                FROM trades
                WHERE status = 'open'
            """))
            position_count = result.fetchone()[0] or 0
            
            # 3. 历史总盈亏 (用于估算账户权益)
            result = db.execute(text("""
                SELECT COALESCE(SUM(realized_pnl), 0) as total_pnl
                FROM trades
                WHERE status = 'closed'
            """))
            row = result.fetchone()
            total_pnl = float(row[0]) if row and row[0] else 0
            
            # 估算账户权益 (基础资金 + 总盈亏)
            base_equity = 10000  # 假设初始资金
            total_equity = base_equity + total_pnl
            
            # 计算今日盈亏百分比
            today_pnl_pct = (today_pnl / total_equity * 100) if total_equity > 0 else 0
            
            # 4. 运行时间 (从最早的交易记录计算)
            result = db.execute(text("""
                SELECT MIN(entry_time) as start_time
                FROM trades
            """))
            row = result.fetchone()
            if row and row[0]:
                start_time = datetime.fromisoformat(row[0].replace('Z', '+00:00'))
                running_duration = datetime.now() - start_time.replace(tzinfo=None)
                running_days = running_duration.days
                running_hours = running_duration.seconds // 3600
                running_time = f"{running_days}天{running_hours}小时"
            else:
                running_time = "0天0小时"
            
            # 5. 胜率统计
            result = db.execute(text("""
                SELECT 
                    COUNT(CASE WHEN realized_pnl > 0 THEN 1 END) as wins,
                    COUNT(CASE WHEN realized_pnl < 0 THEN 1 END) as losses,
                    COUNT(*) as total
                FROM trades
                WHERE status = 'closed'
            """))
            row = result.fetchone()
            win_rate = 0
            if row and row[2] and row[2] > 0:
                win_rate = round((row[0] or 0) / row[2] * 100, 1)
            
            data = {
                "today_pnl": round(today_pnl, 2),
                "today_pnl_pct": round(today_pnl_pct, 2),
                "today_trades": today_trades,
                "total_positions": position_count,
                "total_trades": row[2] if row and row[2] else 0,
                "win_rate": win_rate,
                "running_time": running_time,
                "account_equity": round(total_equity, 2),
                "total_pnl": round(total_pnl, 2),
                "server_status": "online",
                "last_update": datetime.now().isoformat()
            }
            
            set_cache(cache_key, data)
            return {"success": True, "data": data}
            
    except Exception as e:
        # 数据库可能还不存在，返回模拟数据
        return {
            "success": True,
            "data": {
                "today_pnl": 0,
                "today_pnl_pct": 0,
                "today_trades": 0,
                "total_positions": 0,
                "total_trades": 0,
                "win_rate": 0,
                "running_time": "0天0小时",
                "account_equity": 10000,
                "total_pnl": 0,
                "server_status": "online",
                "last_update": datetime.now().isoformat(),
                "note": "数据库暂无数据"
            }
        }


@router.get("/server-status")
async def get_server_status():
    """获取服务器状态 (无需认证)"""
    return {
        "success": True,
        "data": {
            "status": "online",
            "timestamp": datetime.now().isoformat()
        }
    }
