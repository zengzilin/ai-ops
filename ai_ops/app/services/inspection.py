#!/usr/bin/env python3
"""
自动化巡检模块
实现定时巡检、数据存储、告警通知等功能
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, asdict

from app.core.config import SETTINGS, CACHE
from app.services.prom_client import PrometheusClient, run_health_checks, run_comprehensive_inspection
from app.models.db import insert_inspections, get_connection
from app.services.notifiers import notify_all

logger = logging.getLogger(__name__)


@dataclass
class InspectionResult:
    """巡检结果数据类"""
    timestamp: str
    check_name: str
    status: str  # ok, alert, error
    detail: str
    severity: str  # info, warning, critical
    category: str
    score: float
    labels: Dict[str, Any]
    instance: Optional[str] = None
    value: Optional[float] = None


@dataclass
class InspectionSummary:
    """巡检摘要数据类"""
    timestamp: str
    total_checks: int
    alert_count: int
    error_count: int
    ok_count: int
    health_score: float
    duration: float
    targets_status: Dict[str, Any]
    alerts_status: Dict[str, Any]


class InspectionEngine:
    """巡检引擎"""
    
    def __init__(self, prom_url: Optional[str] = None):
        self.prom_client = PrometheusClient(prom_url)
        self.cache = CACHE
        self.last_inspection = None
        
    def run_basic_inspection(self) -> List[InspectionResult]:
        """执行基础巡检"""
        logger.info("开始执行基础巡检")
        start_time = time.time()
        
        try:
            # 执行健康检查
            checks = run_health_checks(self.prom_client)
            
            # 转换为InspectionResult对象
            results = []
            for check in checks:
                result = InspectionResult(
                    timestamp=check["@timestamp"],
                    check_name=check["check"],
                    status=check["status"],
                    detail=check["detail"],
                    severity=check["severity"],
                    category=check["category"],
                    score=check["score"],
                    labels=check["labels"]
                )
                results.append(result)
            
            duration = time.time() - start_time
            logger.info(f"基础巡检完成，耗时: {duration:.2f}s，检查项: {len(results)}")
            
            return results
            
        except Exception as e:
            logger.error(f"基础巡检失败: {e}")
            return []
    
    def get_server_resources(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """获取服务器资源信息（Redis优先；可强制刷新）
        refresh=True 时忽略缓存，直接从Prometheus拉取并写入Redis
        """
        from app.services.prom_client import get_server_resources
        from config import REDIS_CACHE
        
        # 缓存键（包含Prometheus基地址后缀，避免多环境冲突）
        base = getattr(self.prom_client, "base_url", "prom")
        safe_base = base.replace("http://", "").replace("https://", "").replace(":", "_")
        cache_key = f"server_resources:{safe_base}"
        
        # 尝试从Redis缓存获取（非刷新模式）
        if not refresh:
            cached_data = REDIS_CACHE.get(cache_key)
            if cached_data is not None:
                try:
                    count = len(cached_data) if isinstance(cached_data, list) else 0
                except Exception:
                    count = 0
                logger.info(f"使用Redis缓存键 '{cache_key}' 命中，实例数={count}")
                return cached_data
        
        # 缓存未命中，从Prometheus获取
        logger.info("从Prometheus获取服务器资源信息")
        try:
            resources = get_server_resources(self.prom_client)
            
            # 存储到Redis缓存
            if resources:
                REDIS_CACHE.set(cache_key, resources)
                # 额外：写入快照到数据库
                try:
                    from db import insert_server_resource_snapshots
                    inserted = insert_server_resource_snapshots(resources)
                    logger.info(f"服务器资源快照入库完成，条数={inserted}")
                except Exception as db_err:
                    logger.error(f"服务器资源快照入库失败: {db_err}")
                from config import REDIS_CACHE as RC
                key_ttl = None
                try:
                    key_ttl = RC.get_key_ttl(cache_key)  # type: ignore[attr-defined]
                except Exception:
                    pass
                logger.info(
                    f"Prometheus数据写入Redis，key='{cache_key}', 实例数={len(resources)}, TTL={key_ttl}"
                )
            
            return resources
        except Exception as e:
            logger.error(f"获取服务器资源信息失败: {e}")
            return []
    
    def run_comprehensive_inspection(self) -> Dict[str, Any]:
        """执行综合巡检"""
        logger.info("开始执行综合巡检")
        start_time = time.time()
        
        try:
            # 执行综合巡检
            inspection_data = run_comprehensive_inspection(self.prom_client)
            
            # 获取服务器资源信息
            server_resources = self.get_server_resources()
            
            # 转换为InspectionResult对象
            results = []
            for check in inspection_data["checks"]:
                result = InspectionResult(
                    timestamp=check["@timestamp"],
                    check_name=check["check"],
                    status=check["status"],
                    detail=check["detail"],
                    severity=check["severity"],
                    category=check["category"],
                    score=check["score"],
                    labels=check["labels"]
                )
                results.append(result)
            
            duration = time.time() - start_time
            
            # 创建摘要
            summary = InspectionSummary(
                timestamp=inspection_data["timestamp"],
                total_checks=inspection_data["summary"]["total_checks"],
                alert_count=inspection_data["summary"]["alert_count"],
                error_count=inspection_data["summary"]["error_count"],
                ok_count=inspection_data["summary"]["ok_count"],
                health_score=inspection_data["summary"]["health_score"],
                duration=duration,
                targets_status=inspection_data.get("targets", {}),
                alerts_status=inspection_data.get("alerts", {})
            )
            
            logger.info(f"综合巡检完成，耗时: {duration:.2f}s，健康评分: {summary.health_score:.1f}%")
            
            return {
                "results": results,
                "summary": summary,
                "server_resources": server_resources,
                "raw_data": inspection_data
            }
            
        except Exception as e:
            logger.error(f"综合巡检失败: {e}")
            return {
                "results": [],
                "summary": None,
                "server_resources": [],
                "error": str(e)
            }
    
    def store_inspection_results(self, results: List[InspectionResult]) -> int:
        """存储巡检结果到数据库"""
        if not results:
            return 0
        
        try:
            # 转换为字典格式
            rows = []
            for result in results:
                row = {
                    "@timestamp": result.timestamp,
                    "check": result.check_name,
                    "status": result.status,
                    "detail": result.detail,
                    "severity": result.severity,
                    "score": result.score,
                    "labels": result.labels
                }
                rows.append(row)
            
            # 插入数据库
            inserted = insert_inspections(rows)
            logger.info(f"巡检结果已存储到数据库，共 {inserted} 条记录")
            return inserted
            
        except Exception as e:
            logger.error(f"存储巡检结果失败: {e}")
            return 0
    
    def check_alerts(self, results: List[InspectionResult]) -> List[InspectionResult]:
        """检查告警项"""
        alerts = [r for r in results if r.status == "alert"]
        return alerts
    
    def send_notifications(self, alerts: List[InspectionResult]) -> bool:
        """发送告警通知"""
        if not alerts:
            return True
        
        try:
            # 按严重程度分组
            critical_alerts = [a for a in alerts if a.severity == "critical"]
            warning_alerts = [a for a in alerts if a.severity == "warning"]
            
            # 构建通知消息
            message_lines = ["[巡检告警]"]
            
            if critical_alerts:
                message_lines.append("🚨 严重告警:")
                for alert in critical_alerts:
                    message_lines.append(f"  - {alert.check_name}: {alert.detail}")
            
            if warning_alerts:
                message_lines.append("⚠️ 警告:")
                for alert in warning_alerts:
                    message_lines.append(f"  - {alert.check_name}: {alert.detail}")
            
            message = "\n".join(message_lines)
            
            # 发送通知
            notify_all(message)
            logger.info(f"告警通知已发送，严重告警: {len(critical_alerts)}，警告: {len(warning_alerts)}")
            return True
            
        except Exception as e:
            logger.error(f"发送告警通知失败: {e}")
            return False
    
    def get_inspection_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取巡检历史"""
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ts, check_name, status, detail, severity, category, score, 
                           instance, value, labels
                    FROM inspection_results 
                    WHERE ts >= DATE_SUB(NOW(), INTERVAL %s HOUR)
                    ORDER BY ts DESC
                """, (hours,))
                rows = cur.fetchall()
                return rows
        except Exception as e:
            logger.error(f"获取巡检历史失败: {e}")
            return []
    
    def get_health_trends(self, days: int = 7) -> Dict[str, Any]:
        """获取健康趋势"""
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                # 按天统计健康评分
                cur.execute("""
                    SELECT 
                        DATE(ts) as date,
                        COUNT(*) as total_checks,
                        SUM(CASE WHEN status = 'alert' THEN 1 ELSE 0 END) as alert_count,
                        SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                        SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as ok_count
                    FROM inspection_results 
                    WHERE ts >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    GROUP BY DATE(ts)
                    ORDER BY date DESC
                """, (days,))
                rows = cur.fetchall()
                
                trends = []
                for row in rows:
                    total = row['total_checks']
                    if total > 0:
                        health_score = ((total - row['alert_count'] - row['error_count']) / total) * 100
                    else:
                        health_score = 0
                    
                    trends.append({
                        'date': row['date'].isoformat(),
                        'total_checks': total,
                        'alert_count': row['alert_count'],
                        'error_count': row['error_count'],
                        'ok_count': row['ok_count'],
                        'health_score': health_score
                    })
                
                return {'trends': trends}
                
        except Exception as e:
            logger.error(f"获取健康趋势失败: {e}")
            return {'trends': []}

    def send_trend_alert_notifications(self, trend_alerts: List[Dict[str, Any]]) -> bool:
        """发送趋势预警通知"""
        if not trend_alerts:
            return False
        
        try:
            # 构建趋势预警通知消息
            message_lines = [f"📈 趋势预警通知 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
            message_lines.append(f"\n⚠️ 检测到 {len(trend_alerts)} 个趋势预警:")
            
            for alert in trend_alerts:
                instance = alert.get("instance", "未知")
                metric = alert.get("metric", "未知").upper()
                prediction = alert.get("prediction", 0)
                threshold = alert.get("threshold", 0)
                trend = alert.get("trend", "未知")
                
                message_lines.append(
                    f"  - {instance} {metric}: 预测值 {prediction:.1f}% > 阈值 {threshold}% "
                    f"(趋势: {trend})"
                )
            
            message = "\n".join(message_lines)
            
            # 发送通知
            notify_all(message)
            logger.info(f"趋势预警通知已发送，预警数量: {len(trend_alerts)}")
            return True
            
        except Exception as e:
            logger.error(f"发送趋势预警通知失败: {e}")
            return False

    def check_trend_alerts(self) -> List[Dict[str, Any]]:
        """检查趋势预警"""
        try:
            from db import get_connection
            
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT instance, hostname, ts, cpu_usage, mem_usage, disk_usage
                    FROM server_resource_snapshots
                    WHERE ts >= DATE_SUB(NOW(), INTERVAL 2 HOUR)
                    ORDER BY instance ASC, ts ASC
                    """
                )
                rows = cur.fetchall()
            conn.close()
            
            if not rows:
                return []
            
            # 数据聚合
            series: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                inst = r.get("instance")
                if not inst:
                    continue
                ent = series.setdefault(inst, {
                    "instance": inst, 
                    "hostname": r.get("hostname"), 
                    "cpu": [], 
                    "mem": [], 
                    "disk": []
                })
                ent["cpu"].append(float(r.get("cpu_usage") or 0.0))
                ent["mem"].append(float(r.get("mem_usage") or 0.0))
                ent["disk"].append(float(r.get("disk_usage") or 0.0))
            
            # 趋势预测
            def tail5(arr: List[float]) -> List[float]:
                return arr[-5:]
            
            def predict(seq: List[float]) -> Dict[str, Any]:
                seq = tail5([float(x) for x in seq if x is not None])
                if len(seq) < 3:
                    return {"trend": "insufficient", "prediction": seq[-1] if seq else 0}
                
                n = len(seq)
                x = list(range(n))
                sx = sum(x); sy = sum(seq)
                sxx = sum(i*i for i in x); sxy = sum(i*seq[i] for i in range(n))
                denom = n*sxx - sx*sx
                
                if denom == 0:
                    return {"trend": "stable", "prediction": seq[-1]}
                
                a = (n*sxy - sx*sy) / denom
                b = (sy - a*sx) / n
                pred = a*(n) + b  # 外推下一个点
                trend = "rising" if a > 0 else ("falling" if a < 0 else "stable")
                return {"trend": trend, "prediction": max(0.0, pred)}
            
            # 阈值设置
            CPU_TH, MEM_TH, DISK_TH = 60.0, 90.0, 85.0
            
            # 检查趋势预警
            trend_alerts = []
            for inst, ent in series.items():
                cpu_p = predict(ent.get("cpu", []))
                mem_p = predict(ent.get("mem", []))
                disk_p = predict(ent.get("disk", []))
                
                # 检查CPU趋势预警
                if cpu_p["trend"] == "rising" and cpu_p["prediction"] > CPU_TH:
                    trend_alerts.append({
                        "instance": inst,
                        "metric": "cpu",
                        "series": tail5(ent.get("cpu", [])),
                        "prediction": cpu_p["prediction"],
                        "threshold": CPU_TH,
                        "trend": cpu_p["trend"]
                    })
                
                # 检查内存趋势预警
                if mem_p["trend"] == "rising" and mem_p["prediction"] > MEM_TH:
                    trend_alerts.append({
                        "instance": inst,
                        "metric": "mem",
                        "series": tail5(ent.get("mem", [])),
                        "prediction": mem_p["prediction"],
                        "threshold": MEM_TH,
                        "trend": mem_p["trend"]
                    })
                
                # 检查磁盘趋势预警
                if disk_p["trend"] == "rising" and disk_p["prediction"] > DISK_TH:
                    trend_alerts.append({
                        "instance": inst,
                        "metric": "disk",
                        "series": tail5(ent.get("disk", [])),
                        "prediction": disk_p["prediction"],
                        "threshold": DISK_TH,
                        "trend": disk_p["trend"]
                    })
            
            # 按预测超阈幅度降序排列
            trend_alerts.sort(
                key=lambda x: float(x.get("prediction", 0)) - float(x.get("threshold", 0)), 
                reverse=True
            )
            
            return trend_alerts
            
        except Exception as e:
            logger.error(f"检查趋势预警失败: {e}")
            return []


class InspectionScheduler:
    """巡检调度器"""
    
    def __init__(self, engine: InspectionEngine):
        self.engine = engine
        self.running = False
        self.callbacks: List[Callable] = []
    
    def add_callback(self, callback: Callable) -> None:
        """添加回调函数"""
        self.callbacks.append(callback)
    
    def run_inspection_cycle(self) -> None:
        """执行巡检周期"""
        if not self.running:
            return
        
        logger.info("开始执行巡检周期")
        start_time = time.time()
        
        try:
            # 执行综合巡检
            inspection_data = self.engine.run_comprehensive_inspection()
            results = inspection_data.get("results", [])
            summary = inspection_data.get("summary")
            
            if results:
                # 存储结果
                self.engine.store_inspection_results(results)
                
                # 检查告警
                alerts = self.engine.check_alerts(results)
                if alerts:
                    self.engine.send_notifications(alerts)
                
                # 检查趋势预警
                trend_alerts = self.engine.check_trend_alerts()
                if trend_alerts:
                    self.engine.send_trend_alert_notifications(trend_alerts)
                
                # 执行回调
                for callback in self.callbacks:
                    try:
                        callback(results, summary)
                    except Exception as e:
                        logger.error(f"回调函数执行失败: {e}")
            
            duration = time.time() - start_time
            logger.info(f"巡检周期完成，耗时: {duration:.2f}s")
            
        except Exception as e:
            logger.error(f"巡检周期执行失败: {e}")
    
    def start(self, interval_seconds: int = 300) -> None:
        """启动调度器"""
        self.running = True
        logger.info(f"巡检调度器已启动，间隔: {interval_seconds}s")
        
        while self.running:
            try:
                self.run_inspection_cycle()
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                logger.info("巡检调度器被用户中断")
                break
            except Exception as e:
                logger.error(f"巡检调度器异常: {e}")
                time.sleep(60)  # 异常时等待1分钟再重试
    
    def stop(self) -> None:
        """停止调度器"""
        self.running = False
        logger.info("巡检调度器已停止")


def create_inspection_engine() -> InspectionEngine:
    """创建巡检引擎实例"""
    return InspectionEngine()


def create_inspection_scheduler(engine: Optional[InspectionEngine] = None) -> InspectionScheduler:
    """创建巡检调度器实例"""
    if engine is None:
        engine = create_inspection_engine()
    return InspectionScheduler(engine)


# 便捷函数
def run_quick_inspection() -> List[InspectionResult]:
    """快速巡检"""
    engine = create_inspection_engine()
    return engine.run_basic_inspection()


def run_full_inspection() -> Dict[str, Any]:
    """完整巡检"""
    engine = create_inspection_engine()
    return engine.run_comprehensive_inspection()


def get_recent_inspections(hours: int = 24) -> List[Dict[str, Any]]:
    """获取最近的巡检记录"""
    engine = create_inspection_engine()
    return engine.get_inspection_history(hours)


def get_health_trends(days: int = 7) -> Dict[str, Any]:
    """获取健康趋势"""
    engine = create_inspection_engine()
    return engine.get_health_trends(days)


def check_and_notify_trend_alerts() -> bool:
    """检查趋势预警并发送通知"""
    engine = create_inspection_engine()
    trend_alerts = engine.check_trend_alerts()
    if trend_alerts:
        return engine.send_trend_alert_notifications(trend_alerts)
    return False


def check_and_notify_current_alerts() -> bool:
    """检查当前告警并发送通知"""
    engine = create_inspection_engine()
    # 获取最近的巡检结果
    recent_results = engine.get_inspection_history(hours=1)  # 最近1小时
    
    # 转换为InspectionResult对象
    results = []
    for row in recent_results:
        result = InspectionResult(
            timestamp=row["ts"].isoformat() if hasattr(row["ts"], 'isoformat') else str(row["ts"]),
            check_name=row["check_name"],
            status=row["status"],
            detail=row["detail"],
            severity=row["severity"],
            category=row["category"],
            score=float(row["score"]) if row["score"] else 0.0,
            labels=row.get("labels", {}),
            instance=row.get("instance"),
            value=float(row["value"]) if row["value"] else None
        )
        results.append(result)
    
    # 检查告警
    alerts = engine.check_alerts(results)
    if alerts:
        return engine.send_notifications(alerts)
    return False
