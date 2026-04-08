"""
流式扫描集成模块
将 StreamingScanner 接入主系统，实现 Telegram 滚动推送
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List
import json
import os

logger = logging.getLogger("StreamingIntegration")


class StreamingNotifier:
    """
    流式扫描通知器
    负责将扫描结果实时推送到 Telegram
    """
    
    def __init__(self, telegram_bot=None, chat_id=None):
        self.telegram_bot = telegram_bot
        self.chat_id = chat_id
        self.stats = {
            'phase1_count': 0,
            'phase2_count': 0,
            'scan_rounds': 0,
            'start_time': datetime.now()
        }
    
    async def on_scan_result(self, result):
        """
        扫描结果回调
        每发现一个配对立即推送
        """
        from src.streaming_scanner import ScanResult
        
        if result.stage == 'phase1':
            self.stats['phase1_count'] += 1
            msg = self._format_phase1_msg(result)
            
        elif result.stage == 'optimized':
            self.stats['phase2_count'] += 1
            msg = self._format_optimized_msg(result)
            
            # 保存到文件（供M5使用）
            await self._save_pair(result)
        else:
            return
        
        # 打印到控制台
        print(msg)
        
        # 推送到 Telegram（如果配置了）
        if self.telegram_bot and self.chat_id:
            try:
                await self.telegram_bot.send_message(
                    chat_id=self.chat_id,
                    text=msg,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Telegram推送失败: {e}")
    
    def _format_phase1_msg(self, result) -> str:
        """格式化初筛推送消息"""
        return (
            f"🔍 <b>发现潜在配对</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"{result.symbol_a} ⟷ {result.symbol_b}\n"
            f"\n"
            f"相关系数: <code>{result.metrics.get('corr', 0):.3f}</code>\n"
            f"Spread Std: <code>{result.metrics.get('spread_std', 0):.4f}</code>\n"
            f"Z穿越(120): <code>{result.metrics.get('z_cross_120', 0)}</code>\n"
            f"\n"
            f"⏳ 正在进行深度检测..."
        )
    
    def _format_optimized_msg(self, result) -> str:
        """格式化优化完成推送消息"""
        runtime = datetime.now() - self.stats['start_time']
        
        return (
            f"✅ <b>优质配对确认</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"{result.symbol_a} ⟷ {result.symbol_b}\n"
            f"\n"
            f"📊 <b>质量指标</b>\n"
            f"综合评分: <code>{result.score:.3f}</code>\n"
            f"相关系数: <code>{result.metrics.get('corr_mean', 0):.3f}</code> ± {result.metrics.get('corr_std', 0):.3f}\n"
            f"半衰期: <code>{result.metrics.get('half_life', 0):.1f}</code> 根\n"
            f"\n"
            f"⚙️ <b>推荐参数</b>\n"
            f"Entry: <code>{result.params.get('z_entry', 2.0)}</code>\n"
            f"Exit: <code>{result.params.get('z_exit', 0.5)}</code>\n"
            f"Stop: <code>{result.params.get('z_stop', 3.5)}</code>\n"
            f"\n"
            f"📈 预估PF: <code>{result.metrics.get('expected_pf', 0):.2f}</code>\n"
            f"\n"
            f"⏱️ 运行时间: {runtime.seconds//60}分{runtime.seconds%60}秒\n"
            f"🎯 本轮发现: {self.stats['phase2_count']} 个"
        )
    
    async def _save_pair(self, result):
        """保存配对到文件（供实盘使用）"""
        pair_data = {
            'symbol_a': result.symbol_a,
            'symbol_b': result.symbol_b,
            'params': {
                'z_entry': result.params.get('z_entry', 2.0),
                'z_exit': result.params.get('z_exit', 0.5),
                'z_stop': result.params.get('z_stop', 3.5),
            },
            'execution': {
                'scale_in': [
                    {'layer': 0, 'ratio': 0.3, 'z_threshold': 2.0},
                    {'layer': 1, 'ratio': 0.3, 'z_threshold': 2.5},
                    {'layer': 2, 'ratio': 0.4, 'z_threshold': 3.0},
                ],
                'legs_sync': {
                    'tolerance_ms': 5000,
                    'retry': 3,
                },
            },
            'score': result.score,
            'timestamp': datetime.now().isoformat()
        }
        
        # 追加保存到流式发现文件
        filename = "config/streaming_pairs.jsonl"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with open(filename, 'a') as f:
            f.write(json.dumps(pair_data) + '\n')
        
        logger.info(f"配对已保存: {result.symbol_a}-{result.symbol_b}")
    
    async def send_summary(self):
        """发送扫描统计摘要"""
        runtime = datetime.now() - self.stats['start_time']
        
        msg = (
            f"📊 <b>扫描统计</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"运行时间: {runtime.seconds//3600}小时{runtime.seconds%3600//60}分\n"
            f"扫描轮次: {self.stats['scan_rounds']}\n"
            f"初筛通过: {self.stats['phase1_count']}\n"
            f"二筛通过: {self.stats['phase2_count']}\n"
        )
        
        if self.telegram_bot and self.chat_id:
            try:
                await self.telegram_bot.send_message(
                    chat_id=self.chat_id,
                    text=msg,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"统计推送失败: {e}")


class StreamingScanManager:
    """
    流式扫描管理器
    整合 StreamingScanner + Notifier，提供统一接口
    """
    
    def __init__(self, db_path: str = "data/klines.db"):
        self.db_path = db_path
        self.scanner = None
        self.notifier = None
        self.is_running = False
        self.discovered_pairs = []
    
    async def start(self, telegram_bot=None, chat_id=None):
        """
        启动流式扫描
        """
        from src.streaming_scanner import StreamingPairFinder
        
        logger.info("启动流式扫描系统...")
        
        # 初始化组件
        self.scanner = StreamingPairFinder()
        self.notifier = StreamingNotifier(telegram_bot, chat_id)
        self.is_running = True
        
        # 启动扫描循环
        try:
            await self.scanner.stream_scan(
                callback=self.notifier.on_scan_result
            )
        except Exception as e:
            logger.error(f"流式扫描异常: {e}")
            self.is_running = False
    
    def stop(self):
        """停止扫描"""
        if self.scanner:
            self.scanner.stop()
        self.is_running = False
        logger.info("流式扫描已停止")
    
    def get_discovered_pairs(self) -> List[Dict]:
        """获取已发现的配对列表"""
        if self.scanner:
            return list(self.scanner.found_pairs.values())
        return []
    
    async def export_to_config(self, output_path: str = "config/pairs_v2.json"):
        """
        将发现的配对导出到配置文件（M5）
        """
        pairs = self.get_discovered_pairs()
        
        if not pairs:
            logger.warning("没有可导出的配对")
            return
        
        # 按评分排序
        pairs.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        # 构建配置
        config = {
            'version': '2.0',
            'generated_at': datetime.now().isoformat(),
            'pairs': pairs[:50]  # 最多50对
        }
        
        # 保存
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        logger.info(f"已导出 {len(pairs)} 个配对到 {output_path}")


# ═══════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════

async def run_streaming_scan():
    """
    独立运行流式扫描
    用法: python -m src.streaming_integration
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='流式扫描器')
    parser.add_argument('--telegram', action='store_true', help='启用Telegram推送')
    parser.add_argument('--token', type=str, help='Telegram Bot Token')
    parser.add_argument('--chat', type=str, help='Telegram Chat ID')
    args = parser.parse_args()
    
    # 初始化 Telegram Bot（如果需要）
    telegram_bot = None
    if args.telegram and args.token:
        try:
            from telegram import Bot
            telegram_bot = Bot(token=args.token)
            logger.info("Telegram Bot 已初始化")
        except ImportError:
            logger.error("请安装 python-telegram-bot: pip install python-telegram-bot")
            return
    
    # 启动扫描
    manager = StreamingScanManager()
    
    try:
        await manager.start(
            telegram_bot=telegram_bot,
            chat_id=args.chat
        )
    except KeyboardInterrupt:
        print("\n收到停止信号...")
        manager.stop()


if __name__ == "__main__":
    asyncio.run(run_streaming_scan())
