from __future__ import annotations

import argparse
import logging
import time
import gc
import threading
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import List, Dict, Any
from dataclasses import asdict

from app.core.config import SETTINGS, setup_logging, CACHE
from app.services.log_analyzer import LogAnalyzer
from app.services.prom_client import PrometheusClient, run_health_checks, run_comprehensive_inspection
from app.models.db import init_schema, insert_inspections, insert_inspection_summary
from app.services.inspection import InspectionEngine, InspectionScheduler, run_quick_inspection, run_full_inspection

logger = logging.getLogger(__name__)

# Performance monitoring
_performance_metrics = {
    "total_runs": 0,
    "total_inspections": 0,
    "total_notifications": 0,
    "avg_processing_time": 0.0,
    "cache_hits": 0,
    "cache_misses": 0,
}

_metrics_lock = threading.Lock()


def update_metrics(metric: str, value: Any) -> None:
    """Update performance metrics thread-safely"""
    with _metrics_lock:
        if metric in _performance_metrics:
            if isinstance(_performance_metrics[metric], (int, float)):
                if metric == "avg_processing_time":
                    # Calculate running average
                    current_avg = _performance_metrics[metric]
                    _performance_metrics["total_runs"] += 1
                    runs = _performance_metrics["total_runs"]
                    _performance_metrics[metric] = (current_avg * (runs - 1) + value) / runs
                else:
                    _performance_metrics[metric] += value
            else:
                _performance_metrics[metric] = value


def force_garbage_collection() -> None:
    """Force garbage collection if needed"""
    logger.info("Forcing garbage collection")
    gc.collect()


@contextmanager
def timer(operation: str):
    """Context manager for timing operations with memory monitoring"""
    start = time.time()
    
    try:
        yield
    finally:
        elapsed = time.time() - start
        logger.info(f"{operation} completed in {elapsed:.2f}s")
        update_metrics("avg_processing_time", elapsed)
        
        # Force GC if processing time is long
        if elapsed > 30:  # More than 30 seconds
            force_garbage_collection()


def cmd_setup() -> None:
    """Setup database schema"""
    try:
        init_schema()
        logger.info("Database schema initialized successfully")
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        raise


def cmd_inspect(notify: bool = False) -> None:
    """执行巡检并存储结果"""
    logger.info("开始执行巡检")
    
    try:
        # 使用巡检引擎
        engine = InspectionEngine()
        
        # 执行综合巡检
        inspection_data = engine.run_comprehensive_inspection()
        results = inspection_data.get("results", [])
        summary = inspection_data.get("summary")
        
        if not results:
            logger.info("没有巡检结果")
            return
        
        # 存储巡检结果到数据库
        stored_count = engine.store_inspection_results(results)
        logger.info(f"巡检结果已存储到数据库，共 {stored_count} 条记录")
        
        # 存储巡检摘要
        if summary:
            insert_inspection_summary(asdict(summary))
            logger.info(f"巡检摘要已存储，健康评分: {summary.health_score:.1f}%")
        
        # 检查告警并发送通知
        if notify:
            alerts = engine.check_alerts(results)
            if alerts:
                engine.send_notifications(alerts)
                logger.info(f"已发送 {len(alerts)} 个告警通知")
            else:
                logger.info("没有告警需要发送")
        
        # 输出巡检摘要
        if summary:
            print(f"\n=== 巡检摘要 ===")
            print(f"检查项总数: {summary.total_checks}")
            print(f"告警数量: {summary.alert_count}")
            print(f"错误数量: {summary.error_count}")
            print(f"正常数量: {summary.ok_count}")
            print(f"健康评分: {summary.health_score:.1f}%")
            print(f"执行耗时: {summary.duration:.2f}s")
        
        update_metrics("total_inspections", 1)
        
    except Exception as e:
        logger.error(f"巡检执行失败: {e}")
        raise


def cmd_schedule(health_interval: int, single_run: bool = False, weekly: bool = False, weekly_day: int = 4, weekly_hour: int = 14, weekly_minute: int = 0) -> None:
    """启动定时巡检服务"""
    logger.info("启动定时巡检服务")
    
    # 初始化数据库
    cmd_setup()
    
    # 创建巡检引擎和调度器
    engine = InspectionEngine()
    scheduler = InspectionScheduler(engine)
    
    # 配置定时调度
    if weekly:
        scheduler.set_weekly_schedule(weekly_day, weekly_hour, weekly_minute)
        logger.info(f"已配置每周定时巡检: 每周{['一', '二', '三', '四', '五', '六', '日'][weekly_day]} {weekly_hour:02d}:{weekly_minute:02d}")
    
    # 后台线程：每分钟统计上一分钟日志总条数
    def start_minute_log_counter() -> None:
        analyzer = LogAnalyzer()
        def worker():
            while True:
                try:
                    # 对齐到下一分钟执行，统计刚结束的一分钟
                    now = datetime.now(timezone.utc)
                    sleep_seconds = 60 - now.second
                    time.sleep(sleep_seconds)
                    info = analyzer.count_last_minute_total()
                    # 打印对比信息（最近1分钟 vs 前一周期）
                    try:
                        from app.core.config import REDIS_CACHE as _RC
                        count = int((info or {}).get("count", 0))
                        prev = _RC.get("log:last_minute:total:prev") or {}
                        prev_count = int(prev.get("count", 0)) if isinstance(prev, dict) and "count" in prev else None
                        if prev_count is None:
                            compare_result = "首次统计"
                        else:
                            if count > prev_count:
                                compare_result = "增加"
                            elif count < prev_count:
                                compare_result = "减少"
                            else:
                                compare_result = "持平"
                        # 更新前一周期计数
                        try:
                            _RC.set_with_ttl("log:last_minute:total:prev", {"count": count, "ts": datetime.now(timezone.utc).isoformat()}, 120)
                        except Exception:
                            pass
                        logger.info(f"ELK 日志统计：最近 1 分钟日志总数：{count} | 与前一周期对比：{compare_result}")
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"上一分钟日志总数统计失败: {e}")
                    time.sleep(5)
        t = threading.Thread(target=worker, name="minute_log_counter", daemon=True)
        t.start()
    
    start_minute_log_counter()

    # 后台线程：每分钟采集上一分钟日志并更新"错误类型"累计分布
    def start_cumulative_error_type_updater() -> None:
        analyzer = LogAnalyzer()
        def worker():
            while True:
                try:
                    # 对齐到下一分钟执行
                    now = datetime.now(timezone.utc)
                    sleep_seconds = 60 - now.second
                    time.sleep(sleep_seconds)
                    # 统计上一分钟窗口
                    start, end = analyzer.get_previous_minute_window()
                    # 拉取上一分钟清洗后的日志
                    logs = analyzer.collect_logs_range(start, end)
                    cleaned = analyzer.clean_log_data(logs)
                    stats = analyzer.aggregate_log_statistics(cleaned)
                    # 仅在上一分钟窗口内累加一次，避免重叠计数
                    increment = stats.get("error_types", {}) or {}
                    analyzer._update_cumulative_error_types(increment)
                    logger.info("累计错误类型统计已更新（上一分钟窗口）")
                except Exception as e:
                    logger.error(f"累计错误类型更新失败: {e}")
                    time.sleep(5)
        t = threading.Thread(target=worker, name="cumulative_error_type_updater", daemon=True)
        t.start()

    start_cumulative_error_type_updater()
    
    # 后台线程：定期刷新Prometheus数据并缓存到Redis（独立于前端访问）
    def start_prometheus_refresher() -> None:
        def worker():
            while True:
                try:
                    resources = engine.get_server_resources(refresh=True)
                    logger.info(f"Prometheus资源缓存已刷新，实例数={len(resources)}")
                    # 计算负载趋势并打印
                    try:
                        from app.core.config import REDIS_CACHE as _RC
                        loads = []
                        for r in resources or []:
                            cpu = r.get("cpu") or {}
                            if "load_1m" in cpu:
                                try:
                                    loads.append(float(cpu.get("load_1m")))
                                except Exception:
                                    pass
                        if loads:
                            avg_load = sum(loads) / max(1, len(loads))
                            hist = _RC.get("prom:load1:history") or []
                            if not isinstance(hist, list):
                                hist = []
                            hist.append(round(avg_load, 2))
                            hist = hist[-5:]
                            try:
                                _RC.set_with_ttl("prom:load1:history", hist, 3600)
                            except Exception:
                                pass
                            trend_str = " → ".join([f"{v:.2f}" if isinstance(v, (int, float)) else str(v) for v in hist])
                            status = "正常" if avg_load < 0.70 else ("偏高" if avg_load < 1.00 else "告警")
                            logger.info(f"Prometheus 监控：当前服务器负载：{avg_load:.2f} | 最近 5 次负载走势：{trend_str} | 状态判断：{status}")
                    except Exception:
                        pass
                    # 刷新后尝试趋势预警（基于资源快照表）
                    try:
                        alerts = engine.check_trend_alerts()
                        if alerts:
                            engine.send_trend_alert_notifications(alerts)
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"Prometheus数据刷新失败: {e}")
                finally:
                    time.sleep(60)
        t = threading.Thread(target=worker, name="prometheus_refresher", daemon=True)
        t.start()

    start_prometheus_refresher()
    
    def inspection_job() -> None:
        """巡检任务"""
        try:
            logger.info("执行定时巡检任务")
            inspection_data = engine.run_comprehensive_inspection()
            results = inspection_data.get("results", [])
            summary = inspection_data.get("summary")
            
            if results:
                # 存储结果
                stored_count = engine.store_inspection_results(results)
                logger.info(f"巡检结果已存储，共 {stored_count} 条记录")
                
                # 存储摘要
                if summary:
                    insert_inspection_summary(asdict(summary))
                    logger.info(f"=== 巡检完成提示 ===")
                    logger.info(f"检查项总数: {summary.total_checks}")
                    logger.info(f"告警数量: {summary.alert_count}")
                    logger.info(f"错误数量: {summary.error_count}")
                    logger.info(f"正常数量: {summary.ok_count}")
                    logger.info(f"健康评分: {summary.health_score:.1f}%")
                    logger.info(f"执行耗时: {summary.duration:.2f}s")
                
                # 检查告警
                alerts = engine.check_alerts(results)
                if alerts:
                    engine.send_notifications(alerts)
                    logger.info(f"已发送 {len(alerts)} 个告警通知")
                else:
                    logger.info("本次巡检未发现需要发送的告警")
            
        except Exception as e:
            logger.error(f"定时巡检任务失败: {e}")
    
    # 添加任务到调度器
    scheduler.add_callback(lambda results, summary: logger.info(f"巡检完成: {len(results)} 项检查"))
    
    # 启动调度器
    if single_run:
        logger.info("启动单次巡检模式")
    elif weekly:
        logger.info(f"启动每周定时巡检模式: 每周{['一', '二', '三', '四', '五', '六', '日'][weekly_day]} {weekly_hour:02d}:{weekly_minute:02d}")
    else:
        logger.info(f"启动间隔巡检模式: 每{health_interval}秒执行一次")
    
    try:
        if single_run:
            # 只执行一次巡检
            inspection_job()
            logger.info("单次巡检已完成，已停止重复巡检")
        elif weekly:
            # 使用每周定时模式
            scheduler.start(use_cron=True)
        else:
            # 使用间隔模式
            scheduler.start(interval_seconds=health_interval, use_cron=False)
                
    except KeyboardInterrupt:
        logger.info("巡检调度器被用户中断")
    except Exception as e:
        logger.error(f"巡检调度器异常: {e}")
    finally:
        scheduler.stop()
        logger.info("巡检调度器已停止")


def cmd_serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """启动FastAPI服务器，提供仪表板和API服务"""
    # 使用现有 frontend 应用构建函数，保证加载完整仪表板模板与端点
    from frontend import create_app
    import uvicorn

    logger.info(f"启动Web服务器: http://{host}:{port}")
    logger.info("可用页面:")
    logger.info(f"  - 主仪表板: http://{host}:{port}/")
    logger.info(f"  - 巡检报告: http://{host}:{port}/reports")
    logger.info(f"  - API文档: http://{host}:{port}/docs")
    
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai_ops", description="AI-Ops: 自动化运维巡检系统")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup")

    p_ins = sub.add_parser("inspect")
    p_ins.add_argument("--notify", action="store_true", help="Send notifications for alerts")

    p_sch = sub.add_parser("schedule")
    p_sch.add_argument("--health-interval", type=int, default=3600, help="巡检间隔(秒)")
    p_sch.add_argument("--single-run", action="store_true", help="仅执行一次巡检后停止")
    p_sch.add_argument("--weekly", action="store_true", help="使用每周定时模式(每周五下午2点)")
    p_sch.add_argument("--weekly-day", type=int, default=4, help="每周执行的日期(0=周一, 4=周五)")
    p_sch.add_argument("--weekly-hour", type=int, default=14, help="每周执行的小时(0-23)")
    p_sch.add_argument("--weekly-minute", type=int, default=0, help="每周执行的分钟(0-59)")

    p_metrics = sub.add_parser("metrics")
    p_metrics.add_argument("--format", choices=["json", "text"], default="text", help="Output format")

    p_srv = sub.add_parser("serve")
    p_srv.add_argument("--host", default="0.0.0.0")
    p_srv.add_argument("--port", type=int, default=8000)

    return p


def print_metrics(format_type: str = "text") -> None:
    """Print current performance metrics"""
    with _metrics_lock:
        if format_type == "json":
            import json
            print(json.dumps(_performance_metrics, indent=2))
        else:
            print("=== AI-Ops Performance Metrics ===")
            for key, value in _performance_metrics.items():
                if isinstance(value, float):
                    print(f"{key}: {value:.2f}")
                else:
                    print(f"{key}: {value}")
            print(f"Cache size: {CACHE.size()}")


def main() -> None:
    """Main entry point"""
    setup_logging()
    logger.info("AI-Ops 巡检系统启动")
    
    try:
        args = build_parser().parse_args()
        if args.cmd == "setup":
            cmd_setup()
        elif args.cmd == "inspect":
            cmd_inspect(args.notify)
        elif args.cmd == "schedule":
            cmd_schedule(
                health_interval=args.health_interval,
                single_run=args.single_run,
                weekly=args.weekly,
                weekly_day=args.weekly_day,
                weekly_hour=args.weekly_hour,
                weekly_minute=args.weekly_minute
            )
        elif args.cmd == "metrics":
            print_metrics(args.format)
        elif args.cmd == "serve":
            cmd_serve(args.host, args.port)
    except Exception as e:
        logger.error(f"Application failed: {e}")
        raise


if __name__ == "__main__":
    main()
