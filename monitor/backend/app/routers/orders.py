"""
订单记录接口
历史订单、成交记录

使用 trades 表 (status='closed') 的数据
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from ..auth import get_current_user
from ..database import get_trades_db

router = APIRouter()


@router.get("/orders")
async def get_orders(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    获取历史订单（已平仓记录）
    - 支持分页
    - 支持日期筛选
    """
    try:
        with get_trades_db() as db:
            # 构建查询条件
            conditions = ["status = 'closed'"]  # 只查询已平仓
            params = {"limit": limit, "offset": offset}
            
            if start_date:
                conditions.append("DATE(exit_time) >= :start_date")
                params["start_date"] = start_date
            else:
                # 默认最近7天
                week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
                conditions.append("DATE(exit_time) >= :week_ago")
                params["week_ago"] = week_ago
            
            if end_date:
                conditions.append("DATE(exit_time) <= :end_date")
                params["end_date"] = end_date
            
            where_clause = " AND ".join(conditions)
            
            # 查询已平仓订单
            result = db.execute(text(f"""
                SELECT 
                    trade_id,
                    pair,
                    symbol_a,
                    symbol_b,
                    direction,
                    entry_time,
                    exit_time,
                    entry_z,
                    exit_z,
                    exit_reason,
                    realized_pnl,
                    pnl_pct,
                    holding_minutes
                FROM trades
                WHERE {where_clause}
                ORDER BY exit_time DESC
                LIMIT :limit OFFSET :offset
            """), params)
            
            orders = []
            for row in result:
                orders.append({
                    "trade_id": row[0],
                    "pair": row[1],
                    "symbol_a": row[2],
                    "symbol_b": row[3],
                    "direction": row[4],
                    "side": "long" if row[4] == 1 else "short",
                    "entry_time": row[5],
                    "exit_time": row[6],
                    "entry_z": float(row[7]) if row[7] else 0,
                    "exit_z": float(row[8]) if row[8] else 0,
                    "exit_reason": row[9] or "exit",
                    "realized_pnl": float(row[10]) if row[10] else 0,
                    "pnl_pct": float(row[11]) if row[11] else 0,
                    "holding_minutes": float(row[12]) if row[12] else 0,
                })
            
            # 查询总数
            count_result = db.execute(text(f"""
                SELECT COUNT(*) FROM trades WHERE {where_clause}
            """), {k: v for k, v in params.items() if k not in ["limit", "offset"]})
            
            total = count_result.fetchone()[0]
            
            return {
                "success": True,
                "data": {
                    "orders": orders,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + len(orders) < total
                }
            }
            
    except Exception as e:
        # 数据库可能不存在，返回空数据
        return {
            "success": True,
            "data": {
                "orders": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "has_more": False,
                "note": "数据库暂无数据"
            }
        }
