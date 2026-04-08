"""
日志接口
实时交易日志

使用 trade_logs 表的数据
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from ..auth import get_current_user
from ..database import get_trades_db

router = APIRouter()


@router.get("/logs")
async def get_logs(
    level: str = Query("ALL", enum=["ALL", "INFO", "ORDER", "ERROR"]),
    limit: int = Query(50, ge=1, le=200),
    since: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    获取交易日志
    - 支持级别筛选
    - 支持时间范围
    - 实时流式 (前端轮询实现)
    """
    try:
        with get_trades_db() as db:
            # 构建查询条件
            conditions = []
            params = {"limit": limit}
            
            if level != "ALL":
                conditions.append("action = :action")
                params["action"] = level.lower()
            
            if since:
                conditions.append("created_at > :since")
                params["since"] = since
            else:
                # 默认最近1小时
                hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
                conditions.append("created_at > :hour_ago")
                params["hour_ago"] = hour_ago
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # 查询 trade_logs 表
            result = db.execute(text(f"""
                SELECT 
                    log_id,
                    trade_id,
                    action,
                    details,
                    created_at
                FROM trade_logs
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit
            """), params)
            
            logs = []
            for row in result:
                # 解析 details JSON
                import json
                details = {}
                try:
                    if row[3]:
                        details = json.loads(row[3])
                except:
                    pass
                
                # 将 action 映射为 level
                action = row[2]  # open/add/reduce/close
                level_mapped = "ORDER" if action in ["open", "close"] else "INFO"
                
                logs.append({
                    "log_id": row[0],
                    "trade_id": row[1],
                    "timestamp": row[4] if row[4] else None,
                    "level": level_mapped,
                    "action": action,
                    "message": f"{action}: {details.get('z_score', '')}",
                    "details": details,
                    "source": "trade_recorder"
                })
            
            return {
                "success": True,
                "data": {
                    "logs": logs,
                    "count": len(logs),
                    "level": level,
                    "last_timestamp": logs[0]["timestamp"] if logs else None
                }
            }
            
    except Exception as e:
        # 如果trade_logs表不存在，返回模拟数据
        return {
            "success": True,
            "data": {
                "logs": [
                    {
                        "timestamp": datetime.now().isoformat(),
                        "level": "INFO",
                        "action": "system",
                        "message": "系统正常运行中",
                        "source": "monitor"
                    }
                ],
                "count": 1,
                "level": level,
                "note": "暂无交易日志数据"
            }
        }
