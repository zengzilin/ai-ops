#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预警监控脚本
独立运行，检查趋势预警和当前预警并自动发送通知
"""

import sys
import os
import time
import logging
from datetime import datetime
from typing import Dict, Any

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import setup_logging
from inspection import check_and_notify_trend_alerts, check_and_notify_current_alerts
from log_analyzer import LogAnalyzer

logger = logging.getLogger(__name__)


def main():
    """主函数"""
    print("=" * 60)
    print("  AI-Ops 预警监控系统")
    print("=" * 60)
    
    # 设置日志
    setup_logging()
    
    try:
        print(f"开始检查预警 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 检查趋势预警
        print("\n📈 检查趋势预警...")
        trend_result = check_and_notify_trend_alerts()
        if trend_result:
            print("✅ 趋势预警通知已发送")
        else:
            print("ℹ️ 无趋势预警")
        
        # 检查当前告警
        print("\n🚨 检查当前告警...")
        current_result = check_and_notify_current_alerts()
        if current_result:
            print("✅ 当前告警通知已发送")
        else:
            print("ℹ️ 无当前告警")

        # 检查日志异常阈值告警
        print("\n📝 检查日志异常告警...")
        try:
            analyzer = LogAnalyzer()
            log_alerts = analyzer.run_log_alert_cycle(hours=1)
            if log_alerts:
                print("✅ 日志阈值告警通知已发送")
            else:
                print("ℹ️ 无日志阈值告警")
        except Exception as le:
            logger.error(f"日志告警检查失败: {le}")
            print(f"❌ 日志告警检查失败: {le}")
        
        print(f"\n预警检查完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
    except Exception as e:
        logger.error(f"预警监控执行失败: {e}")
        print(f"❌ 预警监控执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
