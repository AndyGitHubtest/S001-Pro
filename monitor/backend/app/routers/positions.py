"""
持仓数据接口
读取 S001-Pro 策略的 state.json 获取真实持仓
"""
import json
import os
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import text

from ..auth import get_current_user
from ..database import get_trades_db

router = APIRouter()

# S001-Pro 数据路径 (服务器固定路径)
S001_DATA_PATH = "/home/ubuntu/strategies/S001-Pro/data"
STATE_FILE = os.path.join(S001_DATA_PATH, "state.json")


def read_state_json():
    """读取 S001-Pro 的 state.json 文件"""
    try:
        if not os.path.exists(STATE_FILE):
            return None
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading state.json: {e}")
        return None


def parse_pair_key(pair_key: str):
    """解析配对键名，如 'DOGE/USDT_XLM/USDT' -> ('DOGE/USDT', 'XLM/USDT')"""
    parts = pair_key.split('_')
    if len(parts) >= 2:
        return parts[0], parts[1]
    return pair_key, ""


def state_to_position(pair_key: str, state_data: dict) -> dict:
    """将 state.json 的数据转换为持仓格式"""
    symbol_a, symbol_b = parse_pair_key(pair_key)
    
    direction = state_data.get("direction", 0)
    entry_z = state_data.get("entry_z", 0)
    entry_price_a = state_data.get("entry_price_a", 0)
    entry_price_b = state_data.get("entry_price_b", 0)
    position_size_pct = state_data.get("position_size_pct", 0)
    scale_in_layer = state_data.get("scale_in_layer", 0)
    
    # 计算持仓状态
    state_status = state_data.get("state", "UNKNOWN")
    
    # 方向转换
    # direction=1: 做多价差 (买A卖B)
    # direction=-1: 做空价差 (卖A买B)
    if direction == 1:
        leg_a_side = "LONG"
        leg_b_side = "SHORT"
        side_display = "long"
    elif direction == -1:
        leg_a_side = "SHORT"
        leg_b_side = "LONG"
        side_display = "short"
    else:
        leg_a_side = "NONE"
        leg_b_side = "NONE"
        side_display = "neutral"
    
    # 计算盈亏 (简化版，实际需要实时价格)
    # 这里返回0，后续可以从其他数据源获取
    unrealized_pnl = 0
    
    return {
        "trade_id": pair_key,
        "pair": pair_key,
        "symbol_a": symbol_a,
        "symbol_b": symbol_b,
        "direction": direction,
        "side": side_display,
        "entry_time": datetime.now().isoformat(),  # state.json 没有记录时间
        "entry_z": round(entry_z, 2),
        "z_score_current": round(entry_z, 2),  # 当前就是开仓Z值
        "layer": scale_in_layer,
        "status": state_status,
        "position_size_pct": position_size_pct,
        "leg_a": {
            "side": leg_a_side,
            "symbol": symbol_a,
            "amount": position_size_pct / 2,  # 简化为一半
            "price": entry_price_a,
            "pnl": 0,  # 需要实时价格计算
        },
        "leg_b": {
            "side": leg_b_side,
            "symbol": symbol_b,
            "amount": position_size_pct / 2,
            "price": entry_price_b,
            "pnl": 0,
        },
        "unrealized_pnl": round(unrealized_pnl, 2),
    }


@router.get("/positions")
async def get_positions(user: dict = Depends(get_current_user)):
    """
    获取当前持仓列表
    优先读取 state.json，如果失败则读取数据库
    """
    positions = []
    total_unrealized_pnl = 0
    data_source = "unknown"
    
    # 方法1: 尝试读取 state.json (S001-Pro 实时状态)
    state_data = read_state_json()
    if state_data:
        for pair_key, pair_state in state_data.items():
            # 只显示有持仓或正在建仓的配对
            if pair_state.get("state") in ["OPEN", "SCALING_IN", "SCALING_OUT"]:
                position = state_to_position(pair_key, pair_state)
                positions.append(position)
                total_unrealized_pnl += position["unrealized_pnl"]
        data_source = "state.json"
    else:
        # 方法2: 尝试读取数据库
        try:
            with get_trades_db() as db:
                result = db.execute(text("""
                    SELECT 
                        trade_id, pair, symbol_a, symbol_b, direction,
                        entry_time, entry_z, leg_a_side, leg_a_amount,
                        leg_a_avg_price, leg_b_side, leg_b_amount, leg_b_avg_price, layer
                    FROM trades
                    WHERE status = 'open'
                    ORDER BY entry_time DESC
                """))
                
                for row in result:
                    positions.append({
                        "trade_id": row[0],
                        "pair": row[1],
                        "symbol_a": row[2],
                        "symbol_b": row[3],
                        "direction": row[4],
                        "side": "long" if row[4] == 1 else "short",
                        "entry_time": row[5],
                        "entry_z": float(row[6]) if row[6] else 0,
                        "layer": row[13] or 0,
                        "leg_a": {
                            "side": row[7],
                            "symbol": row[2],
                            "amount": float(row[8]) if row[8] else 0,
                            "price": float(row[9]) if row[9] else 0,
                        },
                        "leg_b": {
                            "side": row[10],
                            "symbol": row[3],
                            "amount": float(row[11]) if row[11] else 0,
                            "price": float(row[12]) if row[12] else 0,
                        },
                        "unrealized_pnl": 0,
                    })
                data_source = "database"
        except Exception as e:
            print(f"Database read error: {e}")
            data_source = "none"
    
    return {
        "success": True,
        "data": {
            "positions": positions,
            "total_count": len(positions),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "last_update": datetime.now().isoformat(),
            "data_source": data_source
        }
    }
