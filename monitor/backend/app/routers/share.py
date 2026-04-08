"""
分享面板接口
生成只读分享链接，让朋友/投资人查看交易数据
"""
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..auth import get_current_user
from ..database import get_monitor_db, get_trades_db

router = APIRouter()


# ============ 请求/响应模型 ============

class CreateShareRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="分享名称")
    expire_days: int = Field(7, ge=0, le=365, description="有效期天数(0=永久)")
    password: Optional[str] = Field(None, max_length=20, description="访问密码(可选)")


class ShareResponse(BaseModel):
    id: int
    name: str
    token: str
    share_url: str
    created_at: str
    expires_at: Optional[str]
    has_password: bool
    is_active: bool
    view_count: int
    last_viewed_at: Optional[str]


class ShareAccessRequest(BaseModel):
    password: Optional[str] = None


# ============ 工具函数 ============

def generate_token() -> str:
    """生成随机分享令牌"""
    return secrets.token_urlsafe(16)  # 22字符


def hash_password(password: str) -> str:
    """密码哈希 (使用 SHA256，避免 bcrypt 72字节限制)"""
    return hashlib.sha256(password.encode()).hexdigest()[:32]


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    """验证密码"""
    if not password_hash:
        return True  # 无密码保护
    try:
        return hash_password(password) == password_hash
    except Exception:
        return False


def check_share_valid(share: dict) -> tuple[bool, str]:
    """检查分享是否有效，返回 (是否有效, 错误信息)"""
    if not share:
        return False, "分享链接不存在"
    
    if share.get("is_active") != 1:
        return False, "分享链接已禁用"
    
    expires_at = share.get("expires_at")
    if expires_at and isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
    if expires_at and datetime.now() > expires_at:
        return False, "分享链接已过期"
    
    return True, ""


# ============ API 路由 ============

@router.post("/share/create", response_model=dict)
async def create_share(
    req: CreateShareRequest,
    user: dict = Depends(get_current_user)
):
    """
    创建分享链接
    - 自动生成随机token
    - 支持设置有效期
    - 支持密码保护
    """
    with get_monitor_db() as db:
        # 生成唯一token
        token = generate_token()
        
        # 计算过期时间
        expires_at = None
        if req.expire_days > 0:
            expires_at = datetime.now() + timedelta(days=req.expire_days)
        
        # 密码哈希
        password_hash = None
        if req.password:
            password_hash = hash_password(req.password)
        
        # 插入数据库
        result = db.execute(text("""
            INSERT INTO share_links (
                token, name, created_by, created_at, expires_at,
                password_hash, is_active, view_count, permissions
            ) VALUES (
                :token, :name, :created_by, :created_at, :expires_at,
                :password_hash, 1, 0, 'readonly'
            )
        """), {
            "token": token,
            "name": req.name,
            "created_by": user["username"],
            "created_at": datetime.now(),
            "expires_at": expires_at,
            "password_hash": password_hash
        })
        
        db.commit()
        
        # 获取刚插入的记录ID
        share_id = result.lastrowid
        
        # 构建分享URL
        share_url = f"/share/{token}"
        
        return {
            "success": True,
            "data": {
                "id": share_id,
                "token": token,
                "name": req.name,
                "share_url": share_url,
                "full_url": f"http://localhost:3000/share/{token}",  # 前端地址
                "expires_at": expires_at.isoformat() if expires_at else None,
                "has_password": bool(req.password),
                "created_at": datetime.now().isoformat()
            }
        }


@router.get("/share/list", response_model=dict)
async def list_shares(
    user: dict = Depends(get_current_user)
):
    """
    获取当前用户的所有分享链接
    """
    with get_monitor_db() as db:
        result = db.execute(text("""
            SELECT 
                id, token, name, created_at, expires_at,
                password_hash, is_active, view_count, last_viewed_at
            FROM share_links
            WHERE created_by = :username
            ORDER BY created_at DESC
        """), {"username": user["username"]})
        
        shares = []
        for row in result:
            expires_at = row[4]
            is_expired = False
            if expires_at:
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                is_expired = datetime.now() > expires_at
            
            shares.append({
                "id": row[0],
                "token": row[1],
                "name": row[2],
                "created_at": row[3] if isinstance(row[3], str) else row[3].isoformat() if row[3] else None,
                "expires_at": row[4] if isinstance(row[4], str) else row[4].isoformat() if row[4] else None,
                "has_password": bool(row[5]),
                "is_active": bool(row[6]) and not is_expired,
                "view_count": row[7] or 0,
                "last_viewed_at": row[8] if isinstance(row[8], str) else row[8].isoformat() if row[8] else None,
                "share_url": f"/share/{row[1]}"
            })
        
        return {
            "success": True,
            "data": {
                "shares": shares,
                "total": len(shares)
            }
        }


@router.delete("/share/{share_id}", response_model=dict)
async def delete_share(
    share_id: int,
    user: dict = Depends(get_current_user)
):
    """
    删除分享链接
    """
    with get_monitor_db() as db:
        # 先检查是否存在且属于当前用户
        result = db.execute(text("""
            SELECT id FROM share_links
            WHERE id = :id AND created_by = :username
        """), {"id": share_id, "username": user["username"]})
        
        if not result.fetchone():
            raise HTTPException(
                status_code=404,
                detail={"success": False, "error": "分享链接不存在或无权限"}
            )
        
        # 删除
        db.execute(text("""
            DELETE FROM share_links WHERE id = :id
        """), {"id": share_id})
        db.commit()
        
        return {
            "success": True,
            "data": {"message": "分享链接已删除"}
        }


@router.post("/share/{share_id}/toggle", response_model=dict)
async def toggle_share(
    share_id: int,
    user: dict = Depends(get_current_user)
):
    """
    启用/禁用分享链接
    """
    with get_monitor_db() as db:
        # 检查权限
        result = db.execute(text("""
            SELECT id, is_active FROM share_links
            WHERE id = :id AND created_by = :username
        """), {"id": share_id, "username": user["username"]})
        
        row = result.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"success": False, "error": "分享链接不存在或无权限"}
            )
        
        new_status = 0 if row[1] == 1 else 1
        
        db.execute(text("""
            UPDATE share_links SET is_active = :status WHERE id = :id
        """), {"status": new_status, "id": share_id})
        db.commit()
        
        return {
            "success": True,
            "data": {
                "id": share_id,
                "is_active": bool(new_status),
                "message": "分享链接已" + ("启用" if new_status else "禁用")
            }
        }


# ============ 公开访问接口 (无需认证) ============

@router.get("/share/public/{token}", response_model=dict)
async def access_share(
    token: str,
    password: Optional[str] = Query(None, description="访问密码")
):
    """
    访问分享链接 (公开接口，无需登录)
    - 如果设置了密码，需要传入password参数
    """
    with get_monitor_db() as db:
        # 查询分享
        result = db.execute(text("""
            SELECT 
                id, token, name, created_at, expires_at,
                password_hash, is_active, view_count, permissions
            FROM share_links
            WHERE token = :token
        """), {"token": token})
        
        row = result.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"success": False, "error": "分享链接不存在"}
            )
        
        share = {
            "id": row[0],
            "token": row[1],
            "name": row[2],
            "created_at": row[3],
            "expires_at": row[4],
            "password_hash": row[5],
            "is_active": row[6],
            "view_count": row[7],
            "permissions": row[8]
        }
        
        # 检查有效性
        valid, error_msg = check_share_valid(share)
        if not valid:
            raise HTTPException(
                status_code=403,
                detail={"success": False, "error": error_msg}
            )
        
        # 验证密码
        if share["password_hash"] and not verify_password(password or "", share["password_hash"]):
            raise HTTPException(
                status_code=401,
                detail={"success": False, "error": "密码错误", "require_password": True}
            )
        
        # 更新访问统计
        db.execute(text("""
            UPDATE share_links 
            SET view_count = view_count + 1, last_viewed_at = :now
            WHERE id = :id
        """), {"now": datetime.now(), "id": share["id"]})
        db.commit()
        
        # 获取汇总数据 (从trades.db)
        summary_data = {}
        try:
            with get_trades_db() as tdb:
                today_str = datetime.now().strftime("%Y-%m-%d")
                
                # 今日盈亏
                result = tdb.execute(text("""
                    SELECT COALESCE(SUM(realized_pnl), 0)
                    FROM trades 
                    WHERE DATE(exit_time) = DATE('now')
                    AND status = 'closed'
                """))
                today_pnl = float(result.fetchone()[0] or 0)
                
                # 持仓数量
                result = tdb.execute(text("""
                    SELECT COUNT(*) FROM trades WHERE status = 'open'
                """))
                position_count = result.fetchone()[0] or 0
                
                # 总盈亏
                result = tdb.execute(text("""
                    SELECT COALESCE(SUM(realized_pnl), 0) 
                    FROM trades WHERE status = 'closed'
                """))
                total_pnl = float(result.fetchone()[0] or 0)
                
                # 胜率
                result = tdb.execute(text("""
                    SELECT 
                        COUNT(CASE WHEN realized_pnl > 0 THEN 1 END),
                        COUNT(*)
                    FROM trades WHERE status = 'closed'
                """))
                row = result.fetchone()
                win_rate = 0
                if row and row[1] and row[1] > 0:
                    win_rate = round(row[0] / row[1] * 100, 1)
                
                summary_data = {
                    "today_pnl": round(today_pnl, 2),
                    "position_count": position_count,
                    "total_pnl": round(total_pnl, 2),
                    "win_rate": win_rate
                }
        except Exception as e:
            summary_data = {
                "today_pnl": 0,
                "position_count": 0,
                "total_pnl": 0,
                "win_rate": 0,
                "note": "暂无交易数据"
            }
        
        return {
            "success": True,
            "data": {
                "share_name": share["name"],
                "permissions": share["permissions"],
                "summary": summary_data
            }
        }


@router.get("/share/public/{token}/positions", response_model=dict)
async def get_share_positions(
    token: str,
    password: Optional[str] = Query(None)
):
    """
    获取分享的持仓数据 (公开接口)
    """
    # 先验证分享链接
    with get_monitor_db() as db:
        result = db.execute(text("""
            SELECT id, password_hash, is_active, expires_at 
            FROM share_links WHERE token = :token
        """), {"token": token})
        
        row = result.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"success": False, "error": "分享链接不存在"}
            )
        
        share = {
            "id": row[0],
            "password_hash": row[1],
            "is_active": row[2],
            "expires_at": row[3]
        }
        
        valid, error_msg = check_share_valid(share)
        if not valid:
            raise HTTPException(status_code=403, detail={"success": False, "error": error_msg})
        
        if share["password_hash"] and not verify_password(password or "", share["password_hash"]):
            raise HTTPException(
                status_code=401,
                detail={"success": False, "error": "密码错误", "require_password": True}
            )
    
    # 查询持仓
    try:
        with get_trades_db() as db:
            result = db.execute(text("""
                SELECT 
                    pair, symbol_a, symbol_b, direction,
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
                    "pair": row[0],
                    "symbol_a": row[1],
                    "symbol_b": row[2],
                    "direction": row[3],
                    "side": "long" if row[3] == 1 else "short",
                    "entry_time": row[4],
                    "entry_z": float(row[5]) if row[5] else 0,
                    "leg_a": {"side": row[6], "amount": float(row[7]) if row[7] else 0, "price": float(row[8]) if row[8] else 0},
                    "leg_b": {"side": row[9], "amount": float(row[10]) if row[10] else 0, "price": float(row[11]) if row[11] else 0}
                })
            
            return {
                "success": True,
                "data": {
                    "positions": positions,
                    "total": len(positions)
                }
            }
    except Exception as e:
        return {
            "success": True,
            "data": {
                "positions": [],
                "total": 0,
                "note": "暂无持仓数据"
            }
        }


@router.get("/share/public/{token}/orders", response_model=dict)
async def get_share_orders(
    token: str,
    limit: int = Query(20, ge=1, le=50),
    password: Optional[str] = Query(None)
):
    """
    获取分享的历史订单 (公开接口)
    """
    # 验证分享
    with get_monitor_db() as db:
        result = db.execute(text("""
            SELECT id, password_hash, is_active, expires_at 
            FROM share_links WHERE token = :token
        """), {"token": token})
        
        row = result.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"success": False, "error": "分享链接不存在"}
            )
        
        share = {"id": row[0], "password_hash": row[1], "is_active": row[2], "expires_at": row[3]}
        
        valid, error_msg = check_share_valid(share)
        if not valid:
            raise HTTPException(status_code=403, detail={"success": False, "error": error_msg})
        
        if share["password_hash"] and not verify_password(password or "", share["password_hash"]):
            raise HTTPException(
                status_code=401,
                detail={"success": False, "error": "密码错误", "require_password": True}
            )
    
    # 查询订单
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
            
            return {
                "success": True,
                "data": {
                    "orders": orders,
                    "total": len(orders)
                }
            }
    except Exception as e:
        return {
            "success": True,
            "data": {
                "orders": [],
                "total": 0,
                "note": "暂无订单数据"
            }
        }
