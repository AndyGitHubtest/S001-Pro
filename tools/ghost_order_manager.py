#!/usr/bin/env python3
"""
幽灵订单管理工具 (同步版本)

用法:
  python tools/ghost_order_manager.py --check    # 检查幽灵订单
  python tools/ghost_order_manager.py --cancel   # 撤销所有幽灵订单 (试运行)
  python tools/ghost_order_manager.py --cancel --force  # 实际撤销
  python tools/ghost_order_manager.py --list     # 列出所有活跃挂单
"""

import argparse
import sys
import yaml
from pathlib import Path
from typing import List, Dict

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def load_config():
    """加载配置"""
    config_path = Path("config/base.yaml")
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        sys.exit(1)
    
    with open(config_path) as f:
        return yaml.safe_load(f)


def init_exchange(config: dict):
    """初始化交易所连接 (同步)"""
    import ccxt
    
    exchange_config = config.get("exchange", {})
    
    exchange = ccxt.binance({
        'apiKey': exchange_config.get("api_key", ""),
        'secret': exchange_config.get("api_secret", ""),
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',
            'adjustForTimeDifference': True,
            'warnOnFetchOpenOrdersWithoutSymbol': False,
        }
    })
    
    # 测试网络支持
    if exchange_config.get("testnet", False):
        exchange.set_sandbox_mode(True)
    
    return exchange


def is_ghost_order(order: Dict) -> bool:
    """
    判断是否为幽灵订单
    
    幽灵单定义:
      1. 无 clientOrderId 或 clientOrderId 不以 s001_ 开头
      2. 非保护单 (reduceOnly=False)
    """
    client_oid = order.get("clientOrderId", "")
    is_reduce_only = order.get("reduceOnly", False)
    
    # 保护单不是幽灵单
    if is_reduce_only:
        return False
    
    # 策略单不是幽灵单
    if client_oid and client_oid.startswith("s001_"):
        return False
    
    return True


def check_ghost_orders(exchange):
    """检查幽灵订单"""
    print("="*60)
    print("🔍 幽灵订单检查")
    print("="*60)
    
    # 拉取交易所挂单
    print("\n[1/2] 拉取交易所挂单...")
    try:
        orders = exchange.fetch_open_orders()
        print(f"   共 {len(orders)} 个活跃挂单")
    except Exception as e:
        print(f"❌ 拉取失败: {e}")
        return 0
    
    # 分析幽灵订单
    print("\n[2/2] 分析幽灵订单...")
    ghosts = [o for o in orders if is_ghost_order(o)]
    
    if not ghosts:
        print("\n✅ 未发现幽灵订单")
        return 0
    
    print(f"\n⚠️  发现 {len(ghosts)} 个幽灵订单:")
    print("-"*60)
    
    for i, order in enumerate(ghosts, 1):
        client_oid = order.get("clientOrderId", "(无)")
        print(f"\n  [{i}] {order['symbol']}")
        print(f"      订单ID: {order['id'][:40]}")
        print(f"      ClientOID: {client_oid}")
        print(f"      方向: {order['side'].upper()} {order['amount']}")
        print(f"      价格: {order.get('price', 'MARKET')}")
        print(f"      类型: {order['type']}")
    
    print("\n" + "="*60)
    print(f"\n共 {len(ghosts)} 个幽灵订单需要处理")
    return len(ghosts)


def cancel_ghost_orders(exchange, dry_run=True):
    """撤销幽灵订单"""
    print("="*60)
    print("🧹 幽灵订单清理")
    print("="*60)
    
    if dry_run:
        print("\n⚠️  试运行模式 (不会真正撤销)")
        print("    使用 --force 参数执行实际撤销\n")
    
    # 拉取订单
    try:
        orders = exchange.fetch_open_orders()
    except Exception as e:
        print(f"❌ 拉取订单失败: {e}")
        return
    
    ghosts = [o for o in orders if is_ghost_order(o)]
    
    if not ghosts:
        print("\n✅ 没有需要处理的幽灵订单")
        return
    
    print(f"\n发现 {len(ghosts)} 个幽灵订单")
    
    if dry_run:
        print("\n试运行 - 将撤销以下订单:")
        for order in ghosts:
            print(f"  - {order['symbol']}: {order['side']} {order['amount']} @ {order.get('price', 'market')}")
        print("\n使用 --force 执行实际撤销")
        return
    
    # 实际撤销
    print("\n开始撤销...")
    canceled = 0
    failed = 0
    
    for order in ghosts:
        try:
            exchange.cancel_order(order["id"], order["symbol"])
            canceled += 1
            print(f"  ✅ 已撤销: {order['symbol']} {order['id'][:20]}...")
        except Exception as e:
            failed += 1
            error_msg = str(e)
            if "-2011" in error_msg or "Unknown order" in error_msg:
                print(f"  ⚠️  订单已不存在: {order['symbol']}")
            else:
                print(f"  ❌ 撤销失败 {order['symbol']}: {error_msg[:50]}")
    
    print(f"\n{'='*60}")
    print(f"结果: 成功={canceled}, 失败={failed}")


def list_all_orders(exchange):
    """列出所有活跃挂单"""
    print("="*60)
    print("📋 所有活跃挂单")
    print("="*60)
    
    try:
        orders = exchange.fetch_open_orders()
    except Exception as e:
        print(f"❌ 拉取失败: {e}")
        return
    
    if not orders:
        print("\n无活跃挂单")
        return
    
    print(f"\n共 {len(orders)} 个挂单:\n")
    
    # 分组显示
    by_symbol = {}
    for order in orders:
        sym = order.get("symbol", "Unknown")
        if sym not in by_symbol:
            by_symbol[sym] = []
        by_symbol[sym].append(order)
    
    for sym, sym_orders in sorted(by_symbol.items()):
        print(f"\n{sym}:")
        for order in sym_orders:
            cid = order.get("clientOrderId", "")
            is_strategy = cid.startswith("s001_") if cid else False
            is_reduce = order.get("reduceOnly", False)
            is_ghost = not is_strategy and not is_reduce
            
            if is_strategy:
                marker = "🤖 策略"
            elif is_reduce:
                marker = "🛡️ 保护"
            else:
                marker = "👻 幽灵"
            
            price = order.get('price', 'market')
            print(f"  {marker} {order['side'].upper()} {order['amount']} @ {price}")
            print(f"     ID: {order['id'][:35]}")
            if cid:
                print(f"     CID: {cid[:40]}")


def main():
    parser = argparse.ArgumentParser(description="幽灵订单管理工具")
    parser.add_argument(
        "--check", 
        action="store_true", 
        help="检查幽灵订单"
    )
    parser.add_argument(
        "--cancel", 
        action="store_true", 
        help="撤销幽灵订单 (试运行)"
    )
    parser.add_argument(
        "--force", 
        action="store_true", 
        help="配合 --cancel 执行实际撤销"
    )
    parser.add_argument(
        "--list", 
        action="store_true", 
        help="列出所有挂单"
    )
    
    args = parser.parse_args()
    
    if not any([args.check, args.cancel, args.list]):
        parser.print_help()
        return
    
    # 加载配置
    config = load_config()
    
    # 初始化交易所
    exchange = init_exchange(config)
    
    try:
        if args.check:
            count = check_ghost_orders(exchange)
            sys.exit(1 if count > 0 else 0)
        
        elif args.cancel:
            cancel_ghost_orders(exchange, dry_run=not args.force)
        
        elif args.list:
            list_all_orders(exchange)
    
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
