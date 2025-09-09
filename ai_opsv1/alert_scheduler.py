#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预警调度脚本
定期执行预警检查，支持自定义检查间隔
"""

import sys
import os
import time
import logging
import argparse
from datetime import datetime
from typing import Dict, Any

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import setup_logging
from inspection import check_and_notify_trend_alerts, check_and_notify_current_alerts
from log_analyzer import LogAnalyzer
from config import REDIS_CACHE

logger = logging.getLogger(__name__)


class AlertScheduler:
    """预警调度器"""
    
    def __init__(self, interval_seconds: int = 300):
        self.interval = interval_seconds
        self.running = False
        self.last_trend_check = 0
        self.last_current_check = 0
        self.last_log_check = 0
        
        # 趋势预警检查间隔（5分钟）
        self.trend_check_interval = 300
        # 当前告警检查间隔（1分钟）
        self.current_check_interval = 60
        # 日志告警检查间隔（1分钟）
        self.log_check_interval = 60
        # 日志上一分钟分析执行间隔（1分钟）
        self.last_log_minute_run = 0

        # 日志分析器
        self._log_analyzer = LogAnalyzer()
        # 上一分钟总数统计的上次执行时间
        self._last_minute_total_ts = 0
    
    def check_trend_alerts(self) -> bool:
        """检查趋势预警"""
        current_time = time.time()
        if current_time - self.last_trend_check >= self.trend_check_interval:
            logger.info("执行趋势预警检查")
            result = check_and_notify_trend_alerts()
            self.last_trend_check = current_time
            return result
        return False
    
    def check_current_alerts(self) -> bool:
        """检查当前告警"""
        current_time = time.time()
        if current_time - self.last_current_check >= self.current_check_interval:
            logger.info("执行当前告警检查")
            result = check_and_notify_current_alerts()
            self.last_current_check = current_time
            return result
        return False

    def check_log_alerts(self) -> bool:
        """检查日志阈值告警"""
        current_time = time.time()
        if current_time - self.last_log_check >= self.log_check_interval:
            logger.info("执行日志阈值告警检查")
            try:
                # 优先进行上一分钟分析以减少查询量
                # 优先从缓存判断；必要时才调用ES
                cached_alerts = REDIS_CACHE.get("log:threshold_alerts")
                if not cached_alerts:
                    self._log_analyzer.run_last_minute_cycle()
                # 仅返回是否有告警（run_last_minute_cycle已缓存告警）
                alerts = REDIS_CACHE.get("log:threshold_alerts")
                alerts = (alerts or {}).get("alerts", [])
                self.last_log_check = current_time
                return bool(alerts)
            except Exception as e:
                logger.error(f"日志阈值告警检查失败: {e}")
                self.last_log_check = current_time
                return False
        return False
    
    def run_cycle(self) -> None:
        """执行一个检查周期"""
        try:
            # 检查趋势预警
            self.check_trend_alerts()
            
            # 检查当前告警
            self.check_current_alerts()

            # 检查日志阈值告警
            self.check_log_alerts()

            # 每分钟统计上一分钟日志总条数
            now_ts = time.time()
            if now_ts - self._last_minute_total_ts >= 60:
                try:
                    info = self._log_analyzer.count_last_minute_total()
                    logger.info(
                        f"上一分钟日志总数: {info.get('count', 0)} - 窗口 {info.get('window', {}).get('start')} ~ {info.get('window', {}).get('end')}"
                    )
                except Exception as e:
                    logger.error(f"统计上一分钟日志总数失败: {e}")
                finally:
                    self._last_minute_total_ts = now_ts
            
        except Exception as e:
            logger.error(f"预警检查周期执行失败: {e}")
    
    def start(self) -> None:
        """启动调度器"""
        self.running = True
        logger.info(f"预警调度器已启动，主间隔: {self.interval}s")
        logger.info(f"趋势预警检查间隔: {self.trend_check_interval}s")
        logger.info(f"当前告警检查间隔: {self.current_check_interval}s")
        
        print(f"🚀 预警调度器已启动")
        print(f"   主检查间隔: {self.interval}秒")
        print(f"   趋势预警检查间隔: {self.trend_check_interval}秒")
        print(f"   当前告警检查间隔: {self.current_check_interval}秒")
        print(f"   按 Ctrl+C 停止")
        
        while self.running:
            try:
                self.run_cycle()
                time.sleep(self.interval)
            except KeyboardInterrupt:
                logger.info("预警调度器被用户中断")
                break
            except Exception as e:
                logger.error(f"预警调度器异常: {e}")
                time.sleep(60)  # 异常时等待1分钟再重试
    
    def stop(self) -> None:
        """停止调度器"""
        self.running = False
        logger.info("预警调度器已停止")
        print("🛑 预警调度器已停止")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="AI-Ops 预警调度器")
    parser.add_argument(
        "--interval", "-i", 
        type=int, 
        default=300,
        help="主检查间隔（秒），默认300秒"
    )
    parser.add_argument(
        "--trend-interval", 
        type=int, 
        default=300,
        help="趋势预警检查间隔（秒），默认300秒"
    )
    parser.add_argument(
        "--current-interval", 
        type=int, 
        default=60,
        help="当前告警检查间隔（秒），默认60秒"
    )
    parser.add_argument(
        "--log-interval",
        type=int,
        default=60,
        help="日志阈值告警检查间隔（秒），默认60秒"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  AI-Ops 预警调度器")
    print("=" * 60)
    
    # 设置日志
    setup_logging()
    
    try:
        # 创建调度器
        scheduler = AlertScheduler(interval_seconds=args.interval)
        scheduler.trend_check_interval = args.trend_interval
        scheduler.current_check_interval = args.current_interval
        scheduler.log_check_interval = args.log_interval
        
        # 启动调度器
        scheduler.start()
        
    except Exception as e:
        logger.error(f"预警调度器启动失败: {e}")
        print(f"❌ 预警调度器启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
