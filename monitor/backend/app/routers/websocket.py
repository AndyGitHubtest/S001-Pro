"""
WebSocket 实时推送
- 实时推送持仓变化
- 成交通知
- 汇总数据更新
- 警报通知
"""
import asyncio
import json
from typing import Dict, Set
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import text

from ..database import get_trades_db, get_monitor_db

router = APIRouter()

# 连接管理器
class ConnectionManager:
    """管理所有WebSocket连接"""
    
    def __init__(self):
        # 认证连接 (完整权限)
        self.authenticated_connections: Set[WebSocket] = set()
        # 公开连接 (只读，通过分享token)
        self.public_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect_authenticated(self, websocket: WebSocket):
        """添加认证连接"""
        await websocket.accept()
        self.authenticated_connections.add(websocket)
    
    async def connect_public(self, websocket: WebSocket, share_token: str):
        """添加公开连接（分享页面）"""
        await websocket.accept()
        if share_token not in self.public_connections:
            self.public_connections[share_token] = set()
        self.public_connections[share_token].add(websocket)
    
    def disconnect(self, websocket: WebSocket, share_token: str = None):
        """断开连接"""
        self.authenticated_connections.discard(websocket)
        if share_token and share_token in self.public_connections:
            self.public_connections[share_token].discard(websocket)
    
    async def broadcast_to_authenticated(self, message: dict):
        """广播给所有认证用户"""
        disconnected = set()
        for conn in self.authenticated_connections:
            try:
                await conn.send_json(message)
            except:
                disconnected.add(conn)
        # 清理断开的连接
        self.authenticated_connections -= disconnected
    
    async def broadcast_to_public(self, share_token: str, message: dict):
        """广播给特定分享的公开用户"""
        if share_token not in self.public_connections:
            return
        
        disconnected = set()
        for conn in self.public_connections[share_token]:
            try:
                await conn.send_json(message)
            except:
                disconnected.add(conn)
        # 清理断开的连接
        self.public_connections[share_token] -= disconnected


# 全局连接管理器
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_authenticated(websocket: WebSocket):
    """
    认证用户的WebSocket连接
    需要JWT token验证
    """
    # TODO: 验证JWT token
    # token = websocket.query_params.get("token")
    # if not validate_token(token):
    #     await websocket.close(code=1008)
    #     return
    
    await manager.connect_authenticated(websocket)
    
    try:
        # 发送初始数据
        await send_initial_data(websocket)
        
        # 保持连接，接收心跳
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理客户端消息
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
            
            elif message.get("type") == "subscribe":
                # 订阅特定数据频道
                channel = message.get("channel")
                await websocket.send_json({"type": "subscribed", "channel": channel})
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


@router.websocket("/ws/share/{share_token}")
async def websocket_public(websocket: WebSocket, share_token: str):
    """
    公开分享的WebSocket连接（只读）
    """
    # 验证分享token是否有效
    if not await validate_share_token(share_token):
        await websocket.close(code=1008, reason="Invalid share token")
        return
    
    await manager.connect_public(websocket, share_token)
    
    try:
        # 发送初始公开数据
        await send_public_data(websocket, share_token)
        
        # 保持连接
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
    
    except WebSocketDisconnect:
        manager.disconnect(websocket, share_token)
    except Exception as e:
        print(f"Public WebSocket error: {e}")
        manager.disconnect(websocket, share_token)


async def validate_share_token(token: str) -> bool:
    """验证分享token是否有效"""
    try:
        with get_monitor_db() as db:
            result = db.execute(text("""
                SELECT id, is_active, expires_at 
                FROM share_links 
                WHERE token = :token
            """), {"token": token})
            row = result.fetchone()
            
            if not row:
                return False
            
            is_active = row[1]
            expires_at = row[2]
            
            if not is_active:
                return False
            
            if expires_at and isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            if expires_at and datetime.now() > expires_at:
                return False
            
            return True
    except Exception as e:
        print(f"Validate share token error: {e}")
        return False


async def send_initial_data(websocket: WebSocket):
    """发送初始数据给认证用户"""
    try:
        # 汇总数据
        summary = await get_summary_data()
        await websocket.send_json({
            "type": "summary",
            "data": summary
        })
        
        # 持仓数据
        positions = await get_positions_data()
        await websocket.send_json({
            "type": "positions",
            "data": positions
        })
        
        # 最近订单
        orders = await get_recent_orders()
        await websocket.send_json({
            "type": "recent_orders",
            "data": orders
        })
        
    except Exception as e:
        print(f"Send initial data error: {e}")


async def send_public_data(websocket: WebSocket, share_token: str):
    """发送公开数据（只读）"""
    try:
        # 只发送汇总数据，不包含敏感信息
        summary = await get_summary_data()
        await websocket.send_json({
            "type": "summary",
            "data": {
                "today_pnl": summary.get("today_pnl"),
                "position_count": summary.get("total_positions"),
                "total_pnl": summary.get("total_pnl"),
                "win_rate": summary.get("win_rate")
            }
        })
        
        # 持仓数量（不显示具体持仓）
        positions = await get_positions_data()
        await websocket.send_json({
            "type": "positions_count",
            "data": {"count": len(positions)}
        })
        
    except Exception as e:
        print(f"Send public data error: {e}")


async def get_summary_data():
    """获取汇总数据"""
    try:
        with get_trades_db() as db:
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            # 今日盈亏
            result = db.execute(text("""
                SELECT COALESCE(SUM(realized_pnl), 0)
                FROM trades 
                WHERE DATE(exit_time) = DATE('now')
                AND status = 'closed'
            """))
            today_pnl = float(result.fetchone()[0] or 0)
            
            # 持仓数量
            result = db.execute(text("""
                SELECT COUNT(*) FROM trades WHERE status = 'open'
            """))
            position_count = result.fetchone()[0] or 0
            
            # 总盈亏
            result = db.execute(text("""
                SELECT COALESCE(SUM(realized_pnl), 0) 
                FROM trades WHERE status = 'closed'
            """))
            total_pnl = float(result.fetchone()[0] or 0)
            
            # 胜率
            result = db.execute(text("""
                SELECT 
                    COUNT(CASE WHEN realized_pnl > 0 THEN 1 END),
                    COUNT(*)
                FROM trades WHERE status = 'closed'
            """))
            row = result.fetchone()
            win_rate = 0
            if row and row[1] and row[1] > 0:
                win_rate = round(row[0] / row[1] * 100, 1)
            
            return {
                "today_pnl": round(today_pnl, 2),
                "today_pnl_pct": 0,  # 需要计算
                "total_positions": position_count,
                "total_pnl": round(total_pnl, 2),
                "win_rate": win_rate,
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        print(f"Get summary error: {e}")
        return {}


async def get_positions_data():
    """获取持仓数据"""
    try:
        with get_trades_db() as db:
            result = db.execute(text("""
                SELECT 
                    trade_id, pair, symbol_a, symbol_b, direction,
                    entry_time, entry_z,
                    leg_a_side, leg_a_amount, leg_a_avg_price,
                    leg_b_side, leg_b_amount, leg_b_avg_price
                FROM trades
                WHERE status = 'open'
                ORDER BY entry_time DESC
            """))
            
            positions = []
            for row in result:
                positions.append({
                    "trade_id": row[0],
                    "pair": row[1],
                    "direction": row[4],
                    "side": "long" if row[4] == 1 else "short",
                    "entry_time": row[5],
                    "entry_z": float(row[6]) if row[6] else 0,
                    "leg_a": {"side": row[7], "amount": float(row[8]) if row[8] else 0, "price": float(row[9]) if row[9] else 0},
                    "leg_b": {"side": row[10], "amount": float(row[11]) if row[11] else 0, "price": float(row[12]) if row[12] else 0}
                })
            
            return positions
    except Exception as e:
        print(f"Get positions error: {e}")
        return []


async def get_recent_orders(limit: int = 10):
    """获取最近订单"""
    try:
        with get_trades_db() as db:
            result = db.execute(text("""
                SELECT 
                    pair, direction, entry_time, exit_time,
                    entry_z, exit_z, exit_reason, realized_pnl
                FROM trades
                WHERE status = 'closed'
                ORDER BY exit_time DESC
                LIMIT :limit
            """), {"limit": limit})
            
            orders = []
            for row in result:
                orders.append({
                    "pair": row[0],
                    "side": "long" if row[1] == 1 else "short",
                    "entry_time": row[2],
                    "exit_time": row[3],
                    "entry_z": float(row[4]) if row[4] else 0,
                    "exit_z": float(row[5]) if row[5] else 0,
                    "exit_reason": row[6] or "exit",
                    "realized_pnl": float(row[7]) if row[7] else 0
                })
            
            return orders
    except Exception as e:
        print(f"Get orders error: {e}")
        return []


# ============ 广播触发函数 ============

async def broadcast_trade_notification(trade_data: dict):
    """广播交易通知"""
    await manager.broadcast_to_authenticated({
        "type": "trade_notification",
        "data": trade_data,
        "timestamp": datetime.now().isoformat()
    })


async def broadcast_position_update(position_data: dict):
    """广播持仓更新"""
    await manager.broadcast_to_authenticated({
        "type": "position_update",
        "data": position_data,
        "timestamp": datetime.now().isoformat()
    })


async def broadcast_alert(alert_data: dict):
    """广播警报通知"""
    await manager.broadcast_to_authenticated({
        "type": "alert",
        "data": alert_data,
        "timestamp": datetime.now().isoformat()
    })


async def broadcast_summary_update():
    """广播汇总数据更新"""
    summary = await get_summary_data()
    await manager.broadcast_to_authenticated({
        "type": "summary_update",
        "data": summary
    })
