"""
风控警报系统
- Z-score 异常警报
- 持仓亏损警报
- 服务器离线警报
- Telegram 推送
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import text

from ..auth import get_current_user
from ..database import get_monitor_db, get_trades_db
from .websocket import broadcast_alert

router = APIRouter()


# ============ 数据模型 ============

class AlertRule(BaseModel):
    """警报规则"""
    name: str = Field(..., min_length=1, max_length=50)
    type: str = Field(..., enum=["zscore", "loss", "server", "position"])
    condition: str = Field(..., enum=["gt", "lt", "eq", "gte", "lte"])  # 大于、小于、等于
    threshold: float = Field(..., description="阈值")
    enabled: bool = True
    cooldown_minutes: int = Field(5, ge=1, le=1440, description="冷却时间(分钟)")
    notify_channels: List[str] = Field(default=["websocket"], enum=[["websocket"], ["telegram"], ["websocket", "telegram"]])


class AlertHistory(BaseModel):
    """警报历史"""
    id: int
    rule_id: int
    rule_name: str
    alert_type: str
    message: str
    severity: str
    triggered_at: str
    resolved_at: Optional[str]


# ============ 警报规则管理 ============

@router.get("/alerts/rules", response_model=dict)
async def get_alert_rules(user: dict = Depends(get_current_user)):
    """获取所有警报规则"""
    with get_monitor_db() as db:
        result = db.execute(text("""
            SELECT id, name, type, condition, threshold, enabled, 
                   cooldown_minutes, notify_channels, created_at
            FROM alert_rules
            ORDER BY created_at DESC
        """))
        
        rules = []
        for row in result:
            import json
            channels = json.loads(row[7]) if row[7] else ["websocket"]
            rules.append({
                "id": row[0],
                "name": row[1],
                "type": row[2],
                "condition": row[3],
                "threshold": row[4],
                "enabled": bool(row[5]),
                "cooldown_minutes": row[6],
                "notify_channels": channels,
                "created_at": row[8] if isinstance(row[8], str) else row[8].isoformat() if row[8] else None
            })
        
        return {"success": True, "data": {"rules": rules}}


@router.post("/alerts/rules", response_model=dict)
async def create_alert_rule(
    rule: AlertRule,
    user: dict = Depends(get_current_user)
):
    """创建警报规则"""
    with get_monitor_db() as db:
        import json
        result = db.execute(text("""
            INSERT INTO alert_rules (
                name, type, condition, threshold, enabled,
                cooldown_minutes, notify_channels, created_by, created_at
            ) VALUES (
                :name, :type, :condition, :threshold, :enabled,
                :cooldown, :channels, :username, :created_at
            )
        """), {
            "name": rule.name,
            "type": rule.type,
            "condition": rule.condition,
            "threshold": rule.threshold,
            "enabled": 1 if rule.enabled else 0,
            "cooldown": rule.cooldown_minutes,
            "channels": json.dumps(rule.notify_channels),
            "username": user["username"],
            "created_at": datetime.now()
        })
        db.commit()
        
        return {
            "success": True,
            "data": {"id": result.lastrowid, "message": "警报规则创建成功"}
        }


@router.delete("/alerts/rules/{rule_id}", response_model=dict)
async def delete_alert_rule(
    rule_id: int,
    user: dict = Depends(get_current_user)
):
    """删除警报规则"""
    with get_monitor_db() as db:
        db.execute(text("DELETE FROM alert_rules WHERE id = :id"), {"id": rule_id})
        db.commit()
        return {"success": True, "data": {"message": "规则已删除"}}


@router.post("/alerts/rules/{rule_id}/toggle", response_model=dict)
async def toggle_alert_rule(
    rule_id: int,
    user: dict = Depends(get_current_user)
):
    """启用/禁用警报规则"""
    with get_monitor_db() as db:
        result = db.execute(text("""
            SELECT enabled FROM alert_rules WHERE id = :id
        """), {"id": rule_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="规则不存在")
        
        new_status = 0 if row[0] == 1 else 1
        db.execute(text("""
            UPDATE alert_rules SET enabled = :status WHERE id = :id
        """), {"status": new_status, "id": rule_id})
        db.commit()
        
        return {
            "success": True,
            "data": {"id": rule_id, "enabled": bool(new_status)}
        }


# ============ 警报历史 ============

@router.get("/alerts/history", response_model=dict)
async def get_alert_history(
    limit: int = 50,
    resolved_only: bool = False,
    user: dict = Depends(get_current_user)
):
    """获取警报历史"""
    with get_monitor_db() as db:
        conditions = []
        if resolved_only:
            conditions.append("resolved_at IS NOT NULL")
        else:
            conditions.append("resolved_at IS NULL")  # 只显示未解决的
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        result = db.execute(text(f"""
            SELECT id, rule_id, rule_name, alert_type, message, 
                   severity, triggered_at, resolved_at
            FROM alert_history
            WHERE {where_clause}
            ORDER BY triggered_at DESC
            LIMIT :limit
        """), {"limit": limit})
        
        alerts = []
        for row in result:
            alerts.append({
                "id": row[0],
                "rule_id": row[1],
                "rule_name": row[2],
                "alert_type": row[3],
                "message": row[4],
                "severity": row[5],
                "triggered_at": row[6] if isinstance(row[6], str) else row[6].isoformat() if row[6] else None,
                "resolved_at": row[7] if isinstance(row[7], str) else row[7].isoformat() if row[7] else None
            })
        
        return {"success": True, "data": {"alerts": alerts}}


@router.post("/alerts/{alert_id}/resolve", response_model=dict)
async def resolve_alert(
    alert_id: int,
    user: dict = Depends(get_current_user)
):
    """标记警报为已解决"""
    with get_monitor_db() as db:
        db.execute(text("""
            UPDATE alert_history 
            SET resolved_at = :now
            WHERE id = :id
        """), {"now": datetime.now(), "id": alert_id})
        db.commit()
        
        return {"success": True, "data": {"message": "警报已标记为已解决"}}


# ============ 警报检查逻辑 ============

class AlertChecker:
    """警报检查器 - 定期检查并触发警报"""
    
    def __init__(self):
        self.last_alert_times = {}  # 记录上次警报时间，用于冷却
    
    async def check_all_rules(self):
        """检查所有启用的规则"""
        with get_monitor_db() as db:
            result = db.execute(text("""
                SELECT id, name, type, condition, threshold, 
                       cooldown_minutes, notify_channels
                FROM alert_rules
                WHERE enabled = 1
            """))
            
            rules = []
            for row in result:
                import json
                rules.append({
                    "id": row[0],
                    "name": row[1],
                    "type": row[2],
                    "condition": row[3],
                    "threshold": row[4],
                    "cooldown": row[5],
                    "channels": json.loads(row[6]) if row[6] else ["websocket"]
                })
        
        # 检查每个规则
        for rule in rules:
            await self.check_rule(rule)
    
    async def check_rule(self, rule: dict):
        """检查单个规则"""
        rule_id = rule["id"]
        
        # 检查冷却时间
        last_alert = self.last_alert_times.get(rule_id)
        if last_alert:
            cooldown = timedelta(minutes=rule["cooldown"])
            if datetime.now() - last_alert < cooldown:
                return  # 还在冷却中
        
        # 根据规则类型检查
        triggered = False
        message = ""
        severity = "info"
        
        if rule["type"] == "zscore":
            triggered, message = await self.check_zscore_rule(rule)
            severity = "warning"
        elif rule["type"] == "loss":
            triggered, message = await self.check_loss_rule(rule)
            severity = "critical"
        elif rule["type"] == "position":
            triggered, message = await self.check_position_rule(rule)
            severity = "info"
        elif rule["type"] == "server":
            triggered, message = await self.check_server_rule(rule)
            severity = "critical"
        
        if triggered:
            # 触发警报
            await self.trigger_alert(rule, message, severity)
            self.last_alert_times[rule_id] = datetime.now()
    
    async def check_zscore_rule(self, rule: dict) -> tuple[bool, str]:
        """检查 Z-score 规则"""
        try:
            with get_trades_db() as db:
                # 获取当前持仓的入场Z-score
                result = db.execute(text("""
                    SELECT pair, entry_z FROM trades
                    WHERE status = 'open'
                """))
                
                for row in result:
                    pair = row[0]
                    entry_z = float(row[1]) if row[1] else 0
                    threshold = rule["threshold"]
                    
                    # 检查条件
                    if self.check_condition(abs(entry_z), rule["condition"], threshold):
                        return True, f"配对 {pair} 的 Z-score 绝对值为 {abs(entry_z):.2f}，超过阈值 {threshold}"
                
                return False, ""
        except Exception as e:
            print(f"Check zscore rule error: {e}")
            return False, ""
    
    async def check_loss_rule(self, rule: dict) -> tuple[bool, str]:
        """检查亏损规则"""
        try:
            with get_trades_db() as db:
                # 计算今日总盈亏
                result = db.execute(text("""
                    SELECT COALESCE(SUM(realized_pnl), 0)
                    FROM trades
                    WHERE DATE(exit_time) = DATE('now')
                    AND status = 'closed'
                """))
                today_pnl = float(result.fetchone()[0] or 0)
                
                threshold = rule["threshold"]
                
                # 亏损是负数，比如 threshold = -500，表示亏损超过500
                if self.check_condition(today_pnl, rule["condition"], threshold):
                    return True, f"今日盈亏为 {today_pnl:.2f}，超过阈值 {threshold}"
                
                return False, ""
        except Exception as e:
            print(f"Check loss rule error: {e}")
            return False, ""
    
    async def check_position_rule(self, rule: dict) -> tuple[bool, str]:
        """检查持仓数量规则"""
        try:
            with get_trades_db() as db:
                result = db.execute(text("""
                    SELECT COUNT(*) FROM trades WHERE status = 'open'
                """))
                count = result.fetchone()[0] or 0
                
                threshold = rule["threshold"]
                
                if self.check_condition(count, rule["condition"], threshold):
                    return True, f"当前持仓数量为 {count}，超过阈值 {threshold}"
                
                return False, ""
        except Exception as e:
            print(f"Check position rule error: {e}")
            return False, ""
    
    async def check_server_rule(self, rule: dict) -> tuple[bool, str]:
        """检查服务器规则"""
        # 这里可以添加健康检查逻辑
        # 比如检查最后心跳时间
        return False, ""
    
    def check_condition(self, value: float, condition: str, threshold: float) -> bool:
        """检查条件"""
        if condition == "gt":
            return value > threshold
        elif condition == "lt":
            return value < threshold
        elif condition == "eq":
            return value == threshold
        elif condition == "gte":
            return value >= threshold
        elif condition == "lte":
            return value <= threshold
        return False
    
    async def trigger_alert(self, rule: dict, message: str, severity: str):
        """触发警报"""
        # 保存到历史
        with get_monitor_db() as db:
            db.execute(text("""
                INSERT INTO alert_history (
                    rule_id, rule_name, alert_type, message, 
                    severity, triggered_at
                ) VALUES (
                    :rule_id, :rule_name, :type, :message,
                    :severity, :triggered_at
                )
            """), {
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "type": rule["type"],
                "message": message,
                "severity": severity,
                "triggered_at": datetime.now()
            })
            db.commit()
        
        # WebSocket 通知
        if "websocket" in rule["channels"]:
            await broadcast_alert({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "type": rule["type"],
                "message": message,
                "severity": severity
            })
        
        # Telegram 通知
        if "telegram" in rule["channels"]:
            await self.send_telegram_alert(rule, message, severity)
    
    async def send_telegram_alert(self, rule: dict, message: str, severity: str):
        """发送 Telegram 警报"""
        # TODO: 实现 Telegram Bot 推送
        print(f"[Telegram Alert] {rule['name']}: {message}")


# 全局检查器实例
alert_checker = AlertChecker()


@router.post("/alerts/check", response_model=dict)
async def manual_check_alerts(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user)
):
    """手动触发警报检查"""
    background_tasks.add_task(alert_checker.check_all_rules)
    return {"success": True, "data": {"message": "警报检查已触发"}}


# ============ 数据库初始化 ============

def init_alert_tables():
    """初始化警报相关表"""
    from sqlalchemy import Column, Integer, String, DateTime, Float, Text, inspect
    from sqlalchemy.ext.declarative import declarative_base
    from ..database import engine_monitor
    
    Base = declarative_base()
    
    class AlertRule(Base):
        __tablename__ = "alert_rules"
        
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String(50), nullable=False)
        type = Column(String(20), nullable=False)  # zscore, loss, position, server
        condition = Column(String(10), default="gt")  # gt, lt, eq, gte, lte
        threshold = Column(Float, nullable=False)
        enabled = Column(Integer, default=1)
        cooldown_minutes = Column(Integer, default=5)
        notify_channels = Column(String(100), default='["websocket"]')
        created_by = Column(String(50))
        created_at = Column(DateTime)
    
    class AlertHistory(Base):
        __tablename__ = "alert_history"
        
        id = Column(Integer, primary_key=True, index=True)
        rule_id = Column(Integer)
        rule_name = Column(String(50))
        alert_type = Column(String(20))
        message = Column(Text)
        severity = Column(String(10), default="info")  # info, warning, critical
        triggered_at = Column(DateTime)
        resolved_at = Column(DateTime, nullable=True)
    
    try:
        Base.metadata.create_all(bind=engine_monitor, checkfirst=True)
        print("Alert tables initialized")
    except Exception as e:
        if "already exists" in str(e):
            print("Alert tables already exist")
        else:
            print(f"Alert tables init warning: {e}")
