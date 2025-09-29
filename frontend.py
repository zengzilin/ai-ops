from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import json
import logging
import threading
import time
import re

from fastapi import FastAPI, Query, HTTPException, Response
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.models.db import (
    get_connection,
    get_health_thresholds,
    get_inspection_summaries,
    get_inspection_stats,
)
from app.services.inspection import InspectionEngine, get_recent_inspections, get_health_trends
from app.services.log_analyzer import LogAnalyzer
from app.core.config import REDIS_CACHE, SETTINGS

def get_cached_alerts() -> List[Dict[str, Any]]:
    """从Redis缓存中获取告警信息"""
    try:
        # 尝试从Redis获取告警数据
        alerts_data = REDIS_CACHE.get("current_alerts")
        if alerts_data:
            return alerts_data
        
        # 如果Redis中没有数据，从数据库获取最近的告警
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ts, check_name, status, detail, severity, category, 
                           score, instance, value, labels
                    FROM inspection_results 
                    WHERE status = 'alert' 
                    AND ts >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                    ORDER BY ts DESC
                    LIMIT 50
                """)
                rows = cur.fetchall()
                
                alerts = []
                for row in rows:
                    alerts.append({
                        "timestamp": row["ts"].isoformat() if hasattr(row["ts"], "isoformat") else str(row["ts"]),
                        "check_name": row["check_name"],
                        "status": row["status"],
                        "detail": row["detail"],
                        "severity": row["severity"],
                        "category": row["category"],
                        "score": float(row["score"]) if row["score"] else 0.0,
                        "instance": row["instance"],
                        "value": row["value"],
                        "labels": row["labels"]
                    })
                
                return alerts
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"获取告警数据失败: {e}")
        return []

logger = logging.getLogger(__name__)

def create_app() -> FastAPI:
    app = FastAPI(
        title="AI-Ops 巡检系统",
        description="自动化运维巡检系统Web界面",
        version="1.0.0"
    )
    
    # 添加压缩与CORS中间件
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态资源（预留：如需将样式/脚本外置，可挂载到 /static）
    try:
        app.mount("/static", StaticFiles(directory="static"), name="static")
    except Exception:
        # 目录不存在时忽略
        pass
    
    # 新前端静态资源
    try:
        app.mount("/frontend_new", StaticFiles(directory="frontend_new"), name="frontend_new")
    except Exception:
        # 目录不存在时忽略
        pass

    @app.on_event("startup")
    async def _on_startup():
        # 确保数据库表结构存在（兼容首次启动/升级）
        try:
            from app.models.db import init_schema as _init_schema
            _init_schema()
        except Exception as e:
            logger.error(f"数据库schema初始化失败: {e}")

    # 简单的Redis缓存包装器（支持TTL）
    def cached_response(key: str, builder, ttl: int | None = None):
        ttl = ttl if ttl is not None else SETTINGS.redis_cache_ttl
        cached = REDIS_CACHE.get(key)
        if cached is not None:
            return cached
        data = builder()
        if data is not None:
            try:
                # 尝试按TTL写入
                from app.core.config import REDIS_CACHE as _RC
                _RC.set_with_ttl(key, data, ttl)
            except Exception:
                # 退化为默认TTL
                REDIS_CACHE.set(key, data)
        return data

    @app.get("/api/log-stats")
    def get_log_stats(
        hours: int = Query(1, ge=1, le=24, description="分析最近N小时日志"),
    ) -> Dict[str, Any]:
        """获取日志分析统计（分类分布、严重级别分布、实例分布、时间分布、趋势）。"""
        try:
            cache_key = f"log_stats:{hours}"
            def build():
                # 优先读取上一分钟缓存，若用户请求hours>1则再做按小时统计
                analyzer = LogAnalyzer()
                if hours == 1:
                    cached = REDIS_CACHE.get("log:last_minute:stats")
                    if cached:
                        # 返回分钟数据兼容原结构：仅分类/严重级别与趋势为空
                        stats = {
                            "total_logs": cached.get("total", 0),
                            "error_categories": cached.get("category_counts", {}),
                            "severity_distribution": cached.get("severity_counts", {}),
                            "instance_distribution": {},
                            "time_distribution": {},
                            "category_details": {},
                            "critical_errors": [],
                            "trends": {}
                        }
                        return stats
                    # 无缓存则直接计算上一分钟，确保首页分钟视图一致
                    minute_stats = analyzer.analyze_last_minute()
                    try:
                        REDIS_CACHE.set("log:last_minute:stats", minute_stats)
                    except Exception:
                        pass
                    return {
                        "total_logs": minute_stats.get("total", 0),
                        "error_categories": minute_stats.get("category_counts", {}),
                        "severity_distribution": minute_stats.get("severity_counts", {}),
                        "instance_distribution": {},
                        "time_distribution": {},
                        "category_details": {},
                        "critical_errors": [],
                        "trends": {}
                    }
                logs = analyzer.collect_logs(hours=hours)
                return analyzer.analyze_logs(logs)
            return cached_response(cache_key, build, ttl=60)
        except Exception as e:
            logger.error(f"获取日志统计失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取日志统计失败: {e}")

    @app.get("/api/log-threshold-alerts")
    def get_log_threshold_alerts(autogen: bool = Query(False, description="当无数据时自动生成一分钟总量超阈测试告警")) -> Dict[str, Any]:
        """快速返回缓存的日志阈值告警，避免每次实时重扫ES。
        当 autogen=true 且当前无告警时，会自动生成一条上一分钟总量>1000的测试告警，并推送企业微信（若已配置）。
        """
        try:
            cached = REDIS_CACHE.get("log:threshold_alerts") or {}
            alerts = cached.get("alerts", [])
            ts = cached.get("ts")

            # 自动生成测试数据（仅在无数据时触发）
            if autogen and (not alerts):
                from datetime import datetime, timedelta, timezone
                from app.services.notifiers import notify_workwechat
                now = datetime.now()
                total = 1500
                # 写入上一分钟总量
                info = {
                    "window": {"start": (now - timedelta(minutes=1)).isoformat(), "end": now.isoformat()},
                    "count": total,
                    "generated_at": now.isoformat()
                }
                try:
                    REDIS_CACHE.set_with_ttl("log:last_minute:total", info, 60)
                except Exception:
                    pass
                # 组装一条阈值告警
                alert = {
                    "type": "minute_total_threshold",
                    "category": "total",
                    "count": total,
                    "threshold": 1000,
                    "message": f"上一分钟日志总数: {total} 条，超过阈值 1000",
                    "severity": "warning",
                    "timestamp": now.isoformat(),
                    "details": {"time_window": "1分钟"}
                }
                alerts = [alert]
                try:
                    REDIS_CACHE.set_with_ttl("log:threshold_alerts", {"alerts": alerts, "ts": now.isoformat()}, 300)
                except Exception:
                    pass
                # 推送企业微信
                try:
                    notify_workwechat(f"🚨 日志阈值告警\n上一分钟日志总数: {total} 条，超过阈值 1000")
                except Exception:
                    pass
                ts = now.isoformat()
            return {"alerts": alerts, "count": len(alerts), "ts": ts}
        except Exception as e:
            logger.error(f"获取日志阈值告警失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取日志阈值告警失败: {e}")

    @app.post("/api/test/gen-log-threshold-alerts")
    def generate_test_log_threshold_alerts(
        case: str = Query("count", description="测试用例：count|growth|both|minute_total"),
        count: int = Query(60, ge=1, le=5000, description="用于count用例，最近5分钟内同类错误条数"),
        prev: int = Query(10, ge=0, le=5000, description="用于growth用例，前一小时同类错误条数"),
        curr: int = Query(20, ge=0, le=5000, description="用于growth用例，最近一小时同类错误条数"),
        category_count: str = Query("测试错误", description="count用例的错误类别名"),
        category_growth: str = Query("测试增长", description="growth用例的错误类别名"),
        send: bool = Query(True, description="是否实际发送企业微信预警")
    ) -> Dict[str, Any]:
        """生成日志阈值测试数据，写入缓存并可选触发企业微信通知。"""
        try:
            from app.services.log_analyzer import LogAnalyzer
            from app.core.config import SETTINGS, REDIS_CACHE
            from datetime import datetime, timedelta, timezone

            analyzer = LogAnalyzer()
            now = datetime.now()

            def inject_count_alert():
                classified = []
                for i in range(max(1, count)):
                    ts = now - timedelta(seconds=i % 240)  # 最近4分钟内均匀分布
                    classified.append({
                        "timestamp": ts,
                        "message": f"[TEST] {category_count} 第{i+1}条",
                        "category": category_count,
                        "severity": "warning",
                        "instance": "svc-test",
                        "host": "test-host",
                        "logger": "test.logger",
                        "level": "error",
                    })
                analyzer.update_error_stats(classified)

            def inject_growth_alert():
                classified = []
                # 前一小时
                for i in range(max(0, prev)):
                    ts = now - timedelta(minutes=60, seconds=i % 120)
                    classified.append({
                        "timestamp": ts,
                        "message": f"[TEST] {category_growth} prev #{i+1}",
                        "category": category_growth,
                        "severity": "warning",
                        "instance": "svc-test",
                        "host": "test-host",
                        "logger": "test.logger",
                        "level": "error",
                    })
                # 最近一小时
                for i in range(max(0, curr)):
                    ts = now - timedelta(seconds=i % 1800)
                    classified.append({
                        "timestamp": ts,
                        "message": f"[TEST] {category_growth} curr #{i+1}",
                        "category": category_growth,
                        "severity": "warning",
                        "instance": "svc-test",
                        "host": "test-host",
                        "logger": "test.logger",
                        "level": "error",
                    })
                analyzer.update_error_stats(classified)

            if case in ("count", "both"):
                inject_count_alert()
            if case in ("growth", "both"):
                inject_growth_alert()
            if case == "minute_total":
                # 构造上一分钟总量超阈的测试数据
                total = max(1001, int(count))
                info = {
                    "window": {"start": (now - timedelta(minutes=1)).isoformat(), "end": now.isoformat()},
                    "count": total,
                    "generated_at": now.isoformat()
                }
                try:
                    REDIS_CACHE.set_with_ttl("log:last_minute:total", info, 60)
                except Exception:
                    pass
                # 写入阈值告警缓存供页面展示
                alert = {
                    "type": "minute_total_threshold",
                    "category": "total",
                    "count": total,
                    "threshold": 1000,
                    "message": f"上一分钟日志总数: {total} 条，超过阈值 1000",
                    "severity": "warning",
                    "timestamp": now.isoformat(),
                    "details": {"time_window": "1分钟"}
                }
                try:
                    cached = REDIS_CACHE.get("log:threshold_alerts") or {}
                    alerts_cached = (cached.get("alerts") if isinstance(cached, dict) else None) or []
                    alerts_cached.insert(0, alert)
                    REDIS_CACHE.set_with_ttl("log:threshold_alerts", {"alerts": alerts_cached, "ts": now.isoformat()}, 300)
                except Exception:
                    pass

            # 生成并（可选）发送企业微信
            alerts = analyzer.check_thresholds()
            notified = False
            if send:
                try:
                    # minute_total 直接也推送一条
                    if case == "minute_total":
                        from app.services.notifiers import notify_workwechat
                        notify_workwechat(f"🚨 日志阈值告警\n上一分钟日志总数: {total} 条，超过阈值 1000")
                        notified = True
                    elif alerts:
                        notified = analyzer.notify_threshold_alerts(alerts)
                except Exception:
                    notified = False

            # 写入缓存供页面查看
            try:
                REDIS_CACHE.set_with_ttl("log:threshold_alerts", {"alerts": alerts, "ts": now.isoformat()}, 300)
            except Exception:
                pass

            return {
                "ok": True,
                "case": case,
                "alerts": alerts,
                "count": len(alerts),
                "notified": bool(notified),
                "wecom_configured": bool(getattr(SETTINGS, "workwechat_url", None)),
                "ts": now.isoformat(),
            }
        except Exception as e:
            logger.error(f"生成日志阈值测试数据失败: {e}")
            raise HTTPException(status_code=500, detail=f"生成测试数据失败: {e}")

    @app.get("/api/log-last-minute-total")
    def get_log_last_minute_total() -> Dict[str, Any]:
        """强制返回上一分钟的日志总条数。"""
        try:
            cached = REDIS_CACHE.get("log:last_minute:total")
            if cached:
                return cached
            analyzer = LogAnalyzer()
            return analyzer.count_last_minute_total()
        except Exception as e:
            logger.error(f"获取上一分钟日志总数失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取上一分钟日志总数失败: {e}")

    @app.get("/api/log-last-minute-stats")
    def get_log_last_minute_stats() -> Dict[str, Any]:
        """强制返回上一分钟的日志分类统计（不依赖hours参数）。"""
        try:
            cached = REDIS_CACHE.get("log:last_minute:stats")
            if cached:
                return cached
            analyzer = LogAnalyzer()
            result = analyzer.analyze_last_minute()
            try:
                REDIS_CACHE.set("log:last_minute:stats", result)
            except Exception:
                pass
            return result
        except Exception as e:
            logger.error(f"获取上一分钟日志统计失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取上一分钟日志统计失败: {e}")

    @app.get("/api/log-trend-minutely")
    def get_log_trend_minutely(
        minutes: int = Query(60, ge=1, le=1440, description="最近N分钟的日志趋势（每分钟计数）"),
        nocache: bool = Query(False, description="是否跳过缓存强制从ES聚合")
    ) -> Dict[str, Any]:
        """返回最近N分钟的每分钟日志量趋势。"""
        try:
            cache_key = f"log:trend:minutely:{minutes}"
            if not nocache:
                cached = REDIS_CACHE.get(cache_key)
                if cached:
                    return cached
            analyzer = LogAnalyzer()
            # 使用ES按分钟聚合
            if not analyzer.es_client:
                raise HTTPException(status_code=503, detail="Elasticsearch 不可用")
            body = {
                "size": 0,
                "query": {
                    "range": {"@timestamp": {"gte": f"now-{minutes}m", "lt": "now"}}
                },
                "aggs": {
                    "per_minute": {
                        "date_histogram": {
                            "field": "@timestamp",
                            "fixed_interval": "1m",
                            "min_doc_count": 0
                        }
                    }
                }
            }
            resp = analyzer.es_client.search(index=analyzer.es_index_pattern, body=body, request_timeout=SETTINGS.es_query_timeout)
            buckets = (((resp or {}).get("aggregations", {}) or {}).get("per_minute", {}) or {}).get("buckets", [])
            labels = []
            values = []
            for b in buckets:
                ts = b.get("key_as_string") or b.get("key")
                cnt = int(b.get("doc_count", 0))
                # 统一为ISO字符串
                if isinstance(ts, (int, float)):
                    from datetime import datetime, timezone
                    ts = datetime.fromtimestamp(ts/1000.0, tz=timezone.utc).isoformat()
                labels.append(ts)
                values.append(cnt)
            result = {"labels": labels, "values": values}
            try:
                # 每分钟趋势缓存60秒，避免重复ES聚合
                REDIS_CACHE.set_with_ttl(cache_key, result, 60)
            except Exception:
                pass
            return result
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取日志分钟趋势失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取日志分钟趋势失败: {e}")

    # 启动时预热：每分钟预计算分钟趋势与阈值告警
    @app.on_event("startup")
    def _start_log_prefetcher() -> None:
        import threading, time
        def worker():
            analyzer = LogAnalyzer()
            while True:
                try:
                    # 对齐到分钟边界执行
                    now = datetime.now(timezone.utc)
                    sleep_s = 60 - now.second
                    if sleep_s > 0:
                        time.sleep(sleep_s)
                    # 预计算上一分钟统计与阈值告警缓存
                    try:
                        analyzer.run_last_minute_cycle()
                    except Exception:
                        pass
                    # 后端自动累计“类型分布”至全局（无需前端访问），并使用分布式锁避免重复
                    try:
                        from datetime import timedelta
                        from app.core.config import REDIS_CACHE as _RC
                        # 以上一分钟窗口的结束时间作为锁粒度
                        _end = datetime.now(timezone.utc)
                        prev_minute_key = _end.strftime("%Y%m%d%H%M")
                        lock_key = f"log:cumulative:error_types:global:lock:{prev_minute_key}"
                        if _RC.try_acquire_lock(lock_key, ttl_seconds=75):
                            # 统计上一分钟窗口并累加
                            start, end = analyzer.get_previous_minute_window()
                            logs = analyzer.collect_logs_range(start, end)
                            cleaned = analyzer.clean_log_data(logs)
                            stats = analyzer.aggregate_log_statistics(cleaned)
                            increment = stats.get("error_types", {}) or {}
                            if increment:
                                analyzer._update_cumulative_error_types(increment, scope="global")
                    except Exception:
                        pass
                    # 预计算最近60分钟每分钟趋势
                    try:
                        cache_key = "log:trend:minutely:60"
                        # 总是刷新缓存，确保下一分钟命中新数据
                        body = {
                            "size": 0,
                            "query": {"range": {"@timestamp": {"gte": "now-60m", "lt": "now"}}},
                            "aggs": {"per_minute": {"date_histogram": {"field": "@timestamp", "fixed_interval": "1m", "min_doc_count": 0}}}
                        }
                        if analyzer.es_client:
                            resp = analyzer.es_client.search(index=analyzer.es_index_pattern, body=body, request_timeout=SETTINGS.es_query_timeout)
                            buckets = (((resp or {}).get("aggregations", {}) or {}).get("per_minute", {}) or {}).get("buckets", [])
                            labels, values = [], []
                            for b in buckets:
                                ts = b.get("key_as_string") or b.get("key")
                                cnt = int(b.get("doc_count", 0))
                                if isinstance(ts, (int, float)):
                                    ts = datetime.fromtimestamp(ts/1000.0, tz=timezone.utc).isoformat()
                                labels.append(ts)
                                values.append(cnt)
                            REDIS_CACHE.set_with_ttl(cache_key, {"labels": labels, "values": values}, 60)
                    except Exception:
                        pass
                except Exception:
                    time.sleep(5)
        t = threading.Thread(target=worker, name="log_prefetcher", daemon=True)
        t.start()

    @app.get("/api/inspections")
    def get_inspections(
        response: Response,
        hours: int = Query(24, ge=1, le=168, description="查询最近N小时的巡检数据"),
        status: Optional[str] = Query(None, description="过滤状态: ok, alert, error"),
        category: Optional[str] = Query(None, description="过滤类别"),
        limit: int = Query(100, ge=1, le=1000, description="返回记录数量限制(兼容参数)"),
        page: int = Query(1, ge=1, description="分页页码，从1开始"),
        page_size: int = Query(10, ge=1, le=1000, description="分页大小（默认10）")
    ) -> Dict[str, Any]:
        """获取巡检数据（支持分页，带Redis缓存）"""
        try:
            response.headers["Cache-Control"] = "public, max-age=30"
            # 构建缓存键
            cache_key = f"inspections:{hours}:{status}:{category}:{page}:{page_size}"

            def build():
                conn = get_connection()
                try:
                    with conn.cursor() as cur:
                        # 先查询总条数
                        count_sql = (
                            "SELECT COUNT(*) as total "
                            "FROM inspection_results "
                            "WHERE ts >= DATE_SUB(NOW(), INTERVAL %s HOUR)"
                        )
                        count_params = [hours]

                        if status:
                            count_sql += " AND status = %s"
                            count_params.append(status)
                        if category:
                            count_sql += " AND category = %s"
                            count_params.append(category)

                        cur.execute(count_sql, count_params)
                        total_count = cur.fetchone()["total"]

                        # 查询分页数据
                        sql = (
                            "SELECT ts, check_name, status, detail, severity, category, score, "
                            "       instance, value, labels "
                            "FROM inspection_results "
                            "WHERE ts >= DATE_SUB(NOW(), INTERVAL %s HOUR)"
                        )
                        params = [hours]

                        if status:
                            sql += " AND status = %s"
                            params.append(status)
                        if category:
                            sql += " AND category = %s"
                            params.append(category)

                        sql += " ORDER BY ts DESC LIMIT %s OFFSET %s"
                        params.extend([page_size, (page - 1) * page_size])

                        cur.execute(sql, params)
                        rows = cur.fetchall()

                        # 处理JSON字段
                        for row in rows:
                            if row.get("labels"):
                                try:
                                    row["labels"] = json.loads(row["labels"])  # type: ignore
                                except Exception:
                                    row["labels"] = {}

                        return {
                            "items": rows,
                            "page": page,
                            "page_size": page_size,
                            "total": total_count,
                            "has_more": len(rows) == page_size,
                        }
                finally:
                    conn.close()

            return cached_response(cache_key, build, ttl=30)
        except Exception as e:
            logger.error(f"获取巡检数据失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取巡检数据失败: {e}")

    @app.get("/api/inspection-summaries")
    def get_inspection_summaries_api(
        response: Response,
        hours: int = Query(24, ge=1, le=168, description="查询最近N小时的巡检摘要")
    ) -> List[Dict[str, Any]]:
        """获取巡检摘要（Redis缓存）"""
        try:
            response.headers["Cache-Control"] = "public, max-age=60"
            cache_key = f"inspection_summaries:{hours}"
            return cached_response(cache_key, lambda: get_inspection_summaries(hours), ttl=60)
        except Exception as e:
            logger.error(f"获取巡检摘要失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取巡检摘要失败: {e}")

    @app.get("/api/inspection-stats")
    def get_inspection_stats_api(
        response: Response,
        days: int = Query(7, ge=1, le=90, description="查询最近N天的统计信息")
    ) -> Dict[str, Any]:
        """获取巡检统计信息（Redis缓存）"""
        try:
            response.headers["Cache-Control"] = "public, max-age=120"
            cache_key = f"inspection_stats:{days}"
            return cached_response(cache_key, lambda: get_inspection_stats(days), ttl=120)
        except Exception as e:
            logger.error(f"获取巡检统计失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取巡检统计失败: {e}")

    @app.get("/api/health-trends")
    def get_health_trends_api(
        response: Response,
        days: int = Query(7, ge=1, le=90, description="查询最近N天的健康趋势")
    ) -> Dict[str, Any]:
        """获取健康趋势（Redis缓存）"""
        try:
            response.headers["Cache-Control"] = "public, max-age=120"
            cache_key = f"health_trends:{days}"
            return cached_response(cache_key, lambda: get_health_trends(days), ttl=120)
        except Exception as e:
            logger.error(f"获取健康趋势失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取健康趋势失败: {e}")

    @app.get("/api/server-resources")
    def get_server_resources_api(
        response: Response,
        refresh: bool = Query(False, description="是否强制刷新，忽略Redis缓存"),
        quick: bool = Query(True, description="快速模式：仅返回缓存，不从Prometheus拉取"),
        prefetch: bool = Query(True, description="后台预取：若缓存缺失则异步拉取填充缓存")
    ) -> Dict[str, Any]:
        """获取服务器资源信息（带缓存状态）"""
        try:
            response.headers["Cache-Control"] = "public, max-age=15"
            engine = InspectionEngine()

            # 缓存状态
            cache_status = {
                "connected": REDIS_CACHE.is_connected(),
                "size": REDIS_CACHE.size(),
                "host": REDIS_CACHE.host,
                "port": REDIS_CACHE.port,
            }

            # 快速模式：只读缓存；可选后台预取
            if quick and not refresh:
                try:
                    base = getattr(engine.prom_client, "base_url", "prom")
                    safe_base = base.replace("http://", "").replace("https://", "").replace(":", "_")
                    cache_key = f"server_resources:{safe_base}"
                    cached = REDIS_CACHE.get(cache_key) or []
                except Exception:
                    cached = []
                # 若缓存为空且允许后台预取，则异步刷新缓存
                if prefetch and (not cached or len(cached) == 0):
                    try:
                        import threading
                        def _bg_fetch():
                            try:
                                engine.get_server_resources(refresh=True)
                            except Exception:
                                pass
                        threading.Thread(target=_bg_fetch, name="bg_server_resources_prefetch", daemon=True).start()
                    except Exception:
                        pass
                return {
                    "data": cached,
                    "cache": cache_status,
                    "timestamp": datetime.now().isoformat(),
                    "count": len(cached) if cached else 0,
                    "quick": True,
                }

            # 标准模式：允许拉取
            resources = engine.get_server_resources(refresh=refresh)
            return {
                "data": resources,
                "cache": cache_status,
                "timestamp": datetime.now().isoformat(),
                "count": len(resources) if resources else 0,
                "quick": False,
            }
        except Exception as e:
            logger.error(f"获取服务器资源信息失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取服务器资源信息失败: {e}")

    @app.get("/api/current-status")
    def get_current_status(response: Response) -> Dict[str, Any]:
        """获取当前系统状态（Redis缓存）"""
        try:
            response.headers["Cache-Control"] = "public, max-age=15"

            def build():
                engine = InspectionEngine()

                # 获取最近的巡检摘要
                # 将窗口放宽到24小时，便于在无最近巡检时作为回退数据显示
                summaries = get_inspection_summaries(24)
                latest_summary = summaries[0] if summaries else None
                logger.info(f"巡检摘要数量: {len(summaries)}")

                # 获取最近的巡检结果（7天窗，确保有数据显示）
                recent_inspections = get_recent_inspections(168)  # 7天 = 168小时
                logger.info(f"最近巡检记录数: {len(recent_inspections)}")

                # 统计当前状态
                total_checks = len(recent_inspections)
                alert_count = len([r for r in recent_inspections if r["status"] == "alert"])
                error_count = len([r for r in recent_inspections if r["status"] == "error"])
                ok_count = len([r for r in recent_inspections if r["status"] == "ok"])

                health_score = 0.0
                if total_checks > 0:
                    health_score = ((total_checks - alert_count - error_count) / total_checks) * 100
                elif latest_summary:
                    # 回退：使用最近的巡检摘要作为首页卡片数据，避免全部为0
                    total_checks = int(latest_summary.get("total_checks", 0) or 0)
                    alert_count = int(latest_summary.get("alert_count", 0) or 0)
                    error_count = int(latest_summary.get("error_count", 0) or 0)
                    ok_count = int(latest_summary.get("ok_count", 0) or max(0, total_checks - alert_count - error_count))
                    try:
                        health_score = float(latest_summary.get("health_score", 0.0) or 0.0)
                    except Exception:
                        health_score = 0.0

                return {
                    "timestamp": datetime.now().isoformat(),
                    "total_checks": total_checks,
                    "alert_count": alert_count,
                    "error_count": error_count,
                    "ok_count": ok_count,
                    "health_score": round(health_score, 1),
                    "latest_summary": latest_summary,
                    "system_status": "healthy"
                    if health_score >= 80
                    else "warning" if health_score >= 60 else "critical",
                }

            return cached_response("current_status", build, ttl=15)
        except Exception as e:
            logger.error(f"获取当前状态失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取当前状态失败: {e}")

    @app.get("/api/alerts")
    def get_alerts_api(response: Response) -> Dict[str, Any]:
        """获取增强监控当前告警（直接从Redis中读取）"""
        try:
            response.headers["Cache-Control"] = "public, max-age=15"
            alerts = get_cached_alerts()  # 已由增强监控模块写入Redis
            return {"alerts": alerts, "timestamp": datetime.now().isoformat()}
        except Exception as e:
            logger.error(f"获取告警失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取告警失败: {e}")

        

    @app.get("/api/resource-trend-alerts")
    def get_resource_trend_alerts() -> Dict[str, Any]:
        """预测性预警：基于近5次服务器资源快照，线性外推判断是否将在短期触达阈值
        CPU>60、MEM>90、DISK>85 的任一指标，如趋势为上升且预测值超阈，则纳入结果。
        数据源：`server_resource_snapshots` 或 Redis 缓存（回退）。
        """
        try:
            items: List[Dict[str, Any]] = []
            try:
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
            except Exception:
                rows = []

            series: Dict[str, Dict[str, Any]] = {}
            if rows:
                for r in rows:
                    inst = r.get("instance")
                    if not inst:
                        continue
                    ent = series.setdefault(inst, {"instance": inst, "hostname": r.get("hostname"), "cpu": [], "mem": [], "disk": []})
                    ent["cpu"].append(float(r.get("cpu_usage") or 0.0))
                    ent["mem"].append(float(r.get("mem_usage") or 0.0))
                    ent["disk"].append(float(r.get("disk_usage") or 0.0))
            else:
                # fallback to Redis cached snapshot list
                try:
                    engine = InspectionEngine()
                    base = getattr(engine.prom_client, "base_url", "prom")
                    safe_base = base.replace("http://", "").replace("https://", "").replace(":", "_")
                    cache_key = f"server_resources:{safe_base}"
                    cached = REDIS_CACHE.get(cache_key) or []
                except Exception:
                    cached = []
                for sv in cached:
                    inst = sv.get("instance") or ""
                    if not inst:
                        continue
                    ent = series.setdefault(inst, {"instance": inst, "hostname": (sv.get("system") or {}).get("hostname"), "cpu": [], "mem": [], "disk": []})
                    # 只放一个点，也允许被过滤掉
                    ent["cpu"].append(float((sv.get("cpu") or {}).get("usage_percent") or 0.0))
                    ent["mem"].append(float((sv.get("memory") or {}).get("usage_percent") or 0.0))
                    # 取最大磁盘
                    disk_parts = ((sv.get("disk") or {}).get("partitions") or [])
                    dmax = 0.0
                    for p in disk_parts:
                        try:
                            dmax = max(dmax, float(p.get("usage_percent") or 0))
                        except Exception:
                            pass
                    ent["disk"].append(dmax)

            def tail5(arr: List[float]) -> List[float]:
                return arr[-5:]

            def predict(seq: List[float]) -> Dict[str, Any]:
                seq = tail5([float(x) for x in seq if x is not None])
                if len(seq) < 3:
                    return {"trend": "insufficient", "prediction": seq[-1] if seq else 0}
                n = len(seq)
                x = list(range(n))
                # 简单最小二乘直线拟合
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

            CPU_TH, MEM_TH, DISK_TH = 60.0, 90.0, 85.0
            for inst, ent in series.items():
                cpu_p = predict(ent.get("cpu", []))
                mem_p = predict(ent.get("mem", []))
                disk_p = predict(ent.get("disk", []))
                # 命中任一即加入
                if cpu_p["trend"] == "rising" and cpu_p["prediction"] > CPU_TH:
                    items.append({"instance": inst, "metric": "cpu", "series": tail5(ent.get("cpu", [])), "prediction": cpu_p["prediction"], "threshold": CPU_TH, "trend": cpu_p["trend"]})
                if mem_p["trend"] == "rising" and mem_p["prediction"] > MEM_TH:
                    items.append({"instance": inst, "metric": "mem", "series": tail5(ent.get("mem", [])), "prediction": mem_p["prediction"], "threshold": MEM_TH, "trend": mem_p["trend"]})
                if disk_p["trend"] == "rising" and disk_p["prediction"] > DISK_TH:
                    items.append({"instance": inst, "metric": "disk", "series": tail5(ent.get("disk", [])), "prediction": disk_p["prediction"], "threshold": DISK_TH, "trend": disk_p["trend"]})

            # 按预测超阈幅度降序
            items.sort(key=lambda x: float(x.get("prediction", 0)) - float(x.get("threshold", 0)), reverse=True)

            # 尝试触发企业微信通知（带去重，避免频繁推送）
            try:
                if items:
                    from app.services.notifiers import notify_workwechat
                    # 只取前5个，构建签名用于去重
                    top = items[:5]
                    sig = "|".join([f"{it.get('instance')}:{it.get('metric')}:{round(float(it.get('prediction',0)),1)}" for it in top])
                    # 读取最近一次签名，10分钟内相同不重复推送
                    last = REDIS_CACHE.get("predictive_trend:last_notify") or {}
                    last_sig = last.get("sig") if isinstance(last, dict) else None
                    last_ts = last.get("ts") if isinstance(last, dict) else None
                    should_send = (sig and sig != last_sig)
                    if not should_send and last_ts:
                        try:
                            # 若超过10分钟也允许再次推送
                            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                            should_send = (datetime.now() - last_dt).total_seconds() >= 600
                        except Exception:
                            should_send = True
                    if should_send:
                        lines = ["⚡ 预测性服务器资源预警"]
                        for it in top:
                            inst = it.get("instance")
                            metric = str(it.get("metric")).upper()
                            pred = float(it.get("prediction", 0.0))
                            th = float(it.get("threshold", 0.0))
                            trend = it.get("trend", "-")
                            seq = ", ".join([f"{float(v):.1f}%" for v in (it.get('series') or [])])
                            lines.append(f"- {inst} | {metric}: 预测 {pred:.1f}% > 阈值 {th:.0f}% | 趋势 {trend} | 序列 [{seq}]")
                        text = "\n".join(lines)
                        notify_workwechat(text)
                        try:
                            REDIS_CACHE.set_with_ttl("predictive_trend:last_notify", {"sig": sig, "ts": datetime.now().isoformat()}, 600)
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"预测性预警通知失败: {e}")

            return {"items": items, "timestamp": datetime.now().isoformat()}
        except Exception as e:
            logger.error(f"预测性预警接口失败: {e}")
            raise HTTPException(status_code=500, detail=f"预测性预警失败: {e}")

    @app.post("/api/test/clear-predictive-trend")
    def clear_predictive_trend_test_data(
        remove_cache: bool = Query(True, description="是否清除服务器资源缓存"),
        hours: int = Query(24, ge=1, le=168, description="清理最近N小时内的快照"),
        instance_like: str = Query("test", description="仅清理实例名或主机名包含该关键词的快照；为空则不清理DB")
    ) -> Dict[str, Any]:
        """清理预测性预警页面使用的数据：Redis缓存与测试快照。默认仅清缓存；传入关键词可清理DB中近N小时测试快照。"""
        try:
            removed_cache = False
            removed_rows = 0
            # 清理缓存
            if remove_cache:
                try:
                    engine = InspectionEngine()
                    base = getattr(engine.prom_client, "base_url", "prom")
                    safe_base = base.replace("http://", "").replace("https://", "").replace(":", "_")
                    cache_key = f"server_resources:{safe_base}"
                    # 直接覆写为空数组，TTL短一点
                    REDIS_CACHE.set_with_ttl(cache_key, [], 10)
                    removed_cache = True
                except Exception:
                    removed_cache = False

            # 可选：清理数据库中测试快照
            if instance_like:
                try:
                    from app.models.db import get_connection
                    conn = get_connection()
                    with conn.cursor() as cur:
                        sql = (
                            "DELETE FROM server_resource_snapshots "
                            "WHERE ts >= DATE_SUB(NOW(), INTERVAL %s HOUR) "
                            "AND (instance LIKE %s OR hostname LIKE %s)"
                        )
                        like = f"%{instance_like}%"
                        cur.execute(sql, (int(hours), like, like))
                        removed_rows = cur.rowcount or 0
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logger.error(f"清理DB测试快照失败: {e}")
            return {
                "ok": True,
                "removed_cache": removed_cache,
                "removed_rows": removed_rows,
                "hours": hours,
                "instance_like": instance_like,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"清理预测性预警测试数据失败: {e}")
            raise HTTPException(status_code=500, detail=f"清理失败: {e}")

    @app.post("/api/test/clear-log-thresholds")
    def clear_log_thresholds(
        clear_threshold_alerts: bool = Query(True, description="清空页面用的阈值告警缓存"),
        clear_minute_total: bool = Query(True, description="清空上一分钟日志总量缓存"),
        clear_minute_stats: bool = Query(True, description="清空上一分钟日志分类缓存")
    ) -> Dict[str, Any]:
        """清理日志阈值告警页面相关的Redis缓存。"""
        try:
            cleared = {"threshold_alerts": False, "minute_total": False, "minute_stats": False}
            now = datetime.now().isoformat()
            # 清空 /api/log-threshold-alerts 使用的缓存
            if clear_threshold_alerts:
                try:
                    REDIS_CACHE.set_with_ttl("log:threshold_alerts", {"alerts": [], "ts": now}, 5)
                    cleared["threshold_alerts"] = True
                except Exception:
                    pass
            # 清空 /api/log-last-minute-total 使用的缓存
            if clear_minute_total:
                try:
                    REDIS_CACHE.set_with_ttl("log:last_minute:total", {"count": 0, "generated_at": now}, 5)
                    cleared["minute_total"] = True
                except Exception:
                    pass
            # 清空 /api/log-last-minute-stats 使用的缓存
            if clear_minute_stats:
                try:
                    REDIS_CACHE.set_with_ttl("log:last_minute:stats", {}, 5)
                    cleared["minute_stats"] = True
                except Exception:
                    pass
            return {"ok": True, "cleared": cleared, "timestamp": now}
        except Exception as e:
            logger.error(f"清理日志阈值缓存失败: {e}")
            raise HTTPException(status_code=500, detail=f"清理日志阈值缓存失败: {e}")

    @app.get("/api/hot-servers")
    def get_hot_servers() -> Dict[str, Any]:
        """重点关注服务器：CPU>60% 或 MEM>80% 或 DISK>80%，且近15分钟呈非降趋势（MySQL 5.7 兼容实现）"""
        try:
            from app.models.db import get_connection
            conn = get_connection()
            with conn.cursor() as cur:
                # 直接取近20分钟的快照，按实例与时间排序，后续在Python侧聚合与判定
                cur.execute(
                    """
                    SELECT instance, hostname, ts, cpu_usage, mem_usage, disk_usage
                    FROM server_resource_snapshots
                    WHERE ts >= DATE_SUB(NOW(), INTERVAL 20 MINUTE)
                    ORDER BY instance ASC, ts ASC
                    """
                )
                rows = cur.fetchall()
            conn.close()

            # 聚合为每实例的时间序列（取最近4个点）
            series_map: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                inst = r.get("instance")
                if not inst:
                    continue
                entry = series_map.setdefault(inst, {
                    "instance": inst,
                    "hostname": r.get("hostname"),
                    "cpu_series": [],
                    "mem_series": [],
                    "disk_series": [],
                })
                entry["hostname"] = entry.get("hostname") or r.get("hostname")
                entry["cpu_series"].append(float(r.get("cpu_usage") or 0.0))
                entry["mem_series"].append(float(r.get("mem_usage") or 0.0))
                entry["disk_series"].append(float(r.get("disk_usage") or 0.0))

            def tail4(values: list[float]) -> list[float]:
                return values[-4:]

            def is_rising(values: list[float]) -> bool:
                values = tail4(values)
                if len(values) < 3:
                    return False
                return all(values[i] <= values[i+1] for i in range(len(values)-1))

            hot = []
            for inst, entry in series_map.items():
                cpu_s = tail4(entry.get("cpu_series", []))
                mem_s = tail4(entry.get("mem_series", []))
                disk_s = tail4(entry.get("disk_series", []))
                cpu_hot = bool(cpu_s) and cpu_s[-1] > 60 and is_rising(cpu_s)
                mem_hot = bool(mem_s) and mem_s[-1] > 80 and is_rising(mem_s)
                disk_hot = bool(disk_s) and disk_s[-1] > 80 and is_rising(disk_s)
                if cpu_hot or mem_hot or disk_hot:
                    hot.append({
                        "instance": inst,
                        "hostname": entry.get("hostname"),
                        "cpu_series": cpu_s,
                        "mem_series": mem_s,
                        "disk_series": disk_s,
                        "flags": {"cpu": cpu_hot, "mem": mem_hot, "disk": disk_hot},
                    })

            return {"items": hot, "timestamp": datetime.now().isoformat()}
        except Exception as e:
            logger.error(f"获取重点关注服务器失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取重点关注服务器失败: {e}")

    @app.get("/api/config")
    def get_config() -> Dict[str, Any]:
        """获取系统配置"""
        try:
            th = get_health_thresholds()
            cont = 0.1  # Default contamination value
            return {
                "thresholds": th,
                "iforest_contamination": cont,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"获取配置失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取配置失败: {e}")

    @app.post("/api/monitoring/thresholds/lower")
    def lower_monitoring_thresholds(
        response: Response,
        cpu: float = Query(30.0, ge=0, le=100, description="CPU告警阈值%"),
        mem: float = Query(70.0, ge=0, le=100, description="内存告警阈值%"),
        disk: float = Query(70.0, ge=0, le=100, description="磁盘最大分区使用率阈值%")
    ) -> Dict[str, Any]:
        """临时降低增强监控的资源阈值，并触发一次资源刷新用于验证前端告警展示"""
        try:
            # 写入配置（enhanced_monitoring 会读取这些键）
            from app.models.db import set_config
            set_config("monitor.cpu_threshold", str(cpu))
            set_config("monitor.mem_threshold", str(mem))
            set_config("monitor.disk_threshold", str(disk))

            # 立即刷新一次服务器资源缓存
            engine = InspectionEngine()
            engine.get_server_resources(refresh=True)

            # 运行一次增强监控以生成告警并写入Redis
            # from app.services.enhanced_monitoring import run_enhanced_monitoring
            alerts = []  # run_enhanced_monitoring() or []

            response.headers["Cache-Control"] = "no-store"
            return {
                "ok": True,
                "applied": {"cpu": cpu, "mem": mem, "disk": disk},
                "generated_alerts": len(alerts),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"降低阈值并刷新失败: {e}")
            raise HTTPException(status_code=500, detail=f"降低阈值并刷新失败: {e}")

    @app.post("/api/monitoring/thresholds/reset")
    def reset_monitoring_thresholds(response: Response) -> Dict[str, Any]:
        """将增强监控的资源阈值恢复为正常默认值，并刷新数据和告警缓存

        默认阈值：CPU 60%，内存 90%，磁盘(最大分区) 85%
        """
        try:
            DEFAULT_CPU = 60.0
            DEFAULT_MEM = 90.0
            DEFAULT_DISK = 85.0

            from app.models.db import set_config
            set_config("monitor.cpu_threshold", str(DEFAULT_CPU))
            set_config("monitor.mem_threshold", str(DEFAULT_MEM))
            set_config("monitor.disk_threshold", str(DEFAULT_DISK))

            # 刷新一次服务器资源缓存
            engine = InspectionEngine()
            engine.get_server_resources(refresh=True)

            # 运行一次增强监控以更新Redis中的 current_alerts
            # from app.services.enhanced_monitoring import run_enhanced_monitoring
            alerts = []  # run_enhanced_monitoring() or []

            response.headers["Cache-Control"] = "no-store"
            return {
                "ok": True,
                "applied": {"cpu": DEFAULT_CPU, "mem": DEFAULT_MEM, "disk": DEFAULT_DISK},
                "generated_alerts": len(alerts),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"重置阈值并刷新失败: {e}")
            raise HTTPException(status_code=500, detail=f"重置阈值并刷新失败: {e}")

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        """主仪表板页面 - 现代化设计"""
        return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI-Ops 智能运维系统</title>

    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        :root {
            /* 现代化配色方案 - 参照巡检报告中心 */
            --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --secondary-gradient: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            --success-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            --warning-gradient: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            --danger-gradient: linear-gradient(135deg, #ff9a9e 0%, #fecfef 100%);
            --info-gradient: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
            
            /* 阴影系统 - 参照巡检报告中心，更精致 */
            --card-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            --card-hover-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
            --floating-shadow: 0 16px 48px rgba(0, 0, 0, 0.18);
            
            /* 颜色变量 - 更专业 */
            --text-primary: #2c3e50;
            --text-secondary: #495057;
            --text-muted: #6c757d;
            --bg-primary: #ffffff;
            --bg-secondary: #f8f9fa;
            --bg-tertiary: #e9ecef;
            
            /* 间距系统 - 更协调 */
            --spacing-xs: 0.25rem;
            --spacing-sm: 0.5rem;
            --spacing-md: 0.75rem;
            --spacing-lg: 1.5rem;
            --spacing-xl: 2rem;
            
            /* 圆角系统 - 参照巡检报告中心，更精致 */
            --radius-sm: 12px;
            --radius-md: 16px;
            --radius-lg: 20px;
            --radius-xl: 24px;
        }

        /* 全局样式 */
        * {
            box-sizing: border-box;
        }

        body { 
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            min-height: 100vh;
            font-family: 'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            color: var(--text-primary);
            line-height: 1.6;
            overflow-x: hidden;
        }

        /* 滚动条美化 */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: var(--bg-tertiary);
            border-radius: var(--radius-sm);
        }

        ::-webkit-scrollbar-thumb {
            background: var(--primary-gradient);
            border-radius: var(--radius-sm);
        }

        ::-webkit-scrollbar-thumb:hover {
            background: var(--secondary-gradient);
        }

        /* 导航栏优化 - 更紧凑 */
        .navbar {
            background: rgba(255, 255, 255, 0.95) !important;
            backdrop-filter: blur(20px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
            padding: var(--spacing-xs) 0;
        }

        .navbar-brand {
            font-weight: 700;
            font-size: 1.5rem;
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .navbar-nav .nav-link {
            color: var(--text-secondary) !important;
            font-weight: 500;
            padding: var(--spacing-xs) var(--spacing-sm) !important;
            border-radius: var(--radius-sm);
            transition: all 0.3s ease;
            margin: 0 var(--spacing-xs);
        }

        .navbar-nav .nav-link:hover,
        .navbar-nav .nav-link.active {
            color: var(--text-primary) !important;
            background: var(--bg-secondary);
            transform: translateY(-1px);
        }

        /* 页面标题区域 - 参照巡检报告中心，更专业 */
        .page-header {
            background: var(--bg-primary);
            border-radius: var(--radius-xl);
            box-shadow: var(--card-shadow);
            padding: var(--spacing-xl);
            margin-bottom: var(--spacing-xl);
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(0, 0, 0, 0.05);
        }

        .page-header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--primary-gradient);
        }

        .page-header .header-icon {
            width: 70px;
            height: 70px;
            background: var(--primary-gradient);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 2.5rem;
            margin-right: var(--spacing-lg);
            box-shadow: var(--card-shadow);
            transition: all 0.3s ease;
        }

        .page-header .header-icon:hover {
            transform: scale(1.05);
            box-shadow: var(--card-hover-shadow);
        }

        .page-header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: var(--spacing-sm);
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            line-height: 1.2;
        }

        .page-header p {
            font-size: 1.1rem;
            color: var(--text-secondary);
            margin-bottom: 0;
            font-weight: 500;
        }

        /* 指标卡片系统 - 参照巡检报告中心，更精致 */
        .metric-card {
            background: var(--bg-primary);
            border: none;
            border-radius: var(--radius-xl);
            box-shadow: var(--card-shadow);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            overflow: hidden;
            position: relative;
            height: 100%;
            padding: var(--spacing-xl) var(--spacing-lg);
            text-align: center;
        }

        .metric-card:hover {
            transform: translateY(-5px) scale(1.02);
            box-shadow: var(--card-hover-shadow);
        }

        .metric-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--primary-gradient);
            opacity: 1;
            transition: opacity 0.3s ease;
        }

        .metric-card.success::before {
            background: var(--success-gradient);
        }

        .metric-card.warning::before {
            background: var(--warning-gradient);
        }

        .metric-card.danger::before {
            background: var(--danger-gradient);
        }

        .metric-card.info::before {
            background: var(--info-gradient);
        }

        .metric-card .metric-icon {
            position: absolute;
            top: var(--spacing-lg);
            right: var(--spacing-lg);
            width: 48px;
            height: 48px;
            background: var(--bg-secondary);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            color: var(--text-muted);
            transition: all 0.3s ease;
        }

        .metric-card:hover .metric-icon {
            background: var(--primary-gradient);
            color: white;
            transform: scale(1.1);
        }

        .metric-card .metric-value {
            font-size: 3rem;
            font-weight: 700;
            margin-bottom: var(--spacing-sm);
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            line-height: 1;
        }

        .metric-card.success .metric-value {
            background: var(--success-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .metric-card.warning .metric-value {
            background: var(--warning-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .metric-card.danger .metric-value {
            background: var(--danger-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .metric-card.info .metric-value {
            background: var(--info-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .metric-card .metric-label {
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 0.95rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: var(--spacing-sm);
        }

        .metric-card .metric-trend {
            position: absolute;
            bottom: var(--spacing-lg);
            left: var(--spacing-lg);
            font-size: 0.85rem;
            color: var(--text-muted);
            font-weight: 500;
        }

        /* 主卡片系统 - 参照巡检报告中心，更专业 */
        .main-card {
            background: var(--bg-primary);
            border: none;
            border-radius: var(--radius-xl);
            box-shadow: var(--card-shadow);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            overflow: hidden;
            height: 100%;
            margin-bottom: var(--spacing-xl);
        }

        .main-card:hover {
            box-shadow: var(--card-hover-shadow);
            transform: translateY(-3px);
        }

        .main-card .card-header {
            background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-tertiary) 100%);
            border-bottom: 1px solid rgba(0, 0, 0, 0.05);
            border-radius: var(--radius-xl) var(--radius-xl) 0 0 !important;
            padding: var(--spacing-lg);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: var(--spacing-sm);
        }

        .main-card .card-header h5 {
            font-weight: 600;
            color: var(--text-primary);
            margin: 0;
            font-size: 1.2rem;
            display: flex;
            align-items: center;
            gap: var(--spacing-sm);
        }

        .main-card .card-header .header-actions {
            display: flex;
            gap: var(--spacing-sm);
            align-items: center;
        }

        .main-card .card-body {
            padding: var(--spacing-xl);
        }

        /* 按钮系统 - 参照巡检报告中心，更精致 */
        .btn {
            border-radius: 25px;
            font-weight: 600;
            padding: var(--spacing-md) var(--spacing-xl);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            border: none;
            position: relative;
            overflow: hidden;
            font-size: 0.95rem;
        }

        .btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: left 0.5s;
        }

        .btn:hover::before {
            left: 100%;
        }

        .btn-primary {
            background: var(--primary-gradient);
            color: white;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }

        .btn-outline-primary {
            border: 2px solid #667eea;
            color: #667eea;
            background: transparent;
        }

        .btn-outline-primary:hover {
            background: var(--primary-gradient);
            color: white;
            border-color: transparent;
            transform: translateY(-2px);
        }

        .btn-export {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);
        }

        .btn-export:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(40, 167, 69, 0.4);
            color: white;
        }

        /* 表格优化 - 参照巡检报告中心，更专业 */
        .table {
            border-radius: 15px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
            border: none;
        }

        .table thead th {
            background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-tertiary) 100%);
            border: none;
            padding: 1rem;
            font-weight: 600;
            color: var(--text-primary);
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            text-align: center;
        }

        .table tbody tr {
            transition: all 0.3s ease;
            border: none;
        }

        .table tbody tr:hover {
            background-color: var(--bg-secondary);
            transform: scale(1.01);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        }

        .table tbody td {
            padding: 1rem;
            border: none;
            vertical-align: middle;
            text-align: center;
        }

        /* 徽章系统 - 参照巡检报告中心，更精致 */
        .badge {
            border-radius: 20px;
            padding: 0.5rem 1rem;
            font-weight: 500;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }

        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            border-radius: 25px;
            font-weight: 500;
            font-size: 0.85rem;
        }

        .status-badge.ok {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
        }

        .status-badge.alert {
            background: linear-gradient(135deg, #ffc107 0%, #fd7e14 100%);
            color: white;
        }

        .status-badge.error {
            background: linear-gradient(135deg, #dc3545 0%, #e83e8c 100%);
            color: white;
        }

        .status-badge.critical {
            background: linear-gradient(135deg, #6f42c1 0%, #e83e8c 100%);
            color: white;
        }

        /* 加载动画 - 参照巡检报告中心，更精致 */
        .loading-spinner {
            display: inline-block;
            width: 2rem;
            height: 2rem;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* 动画系统 - 参照巡检报告中心，更丰富 */
        .fade-in {
            animation: fadeIn 0.5s ease-in;
        }

        @keyframes fadeIn {
            from { 
                opacity: 0; 
                transform: translateY(20px); 
            }
            to { 
                opacity: 1; 
                transform: translateY(0); 
            }
        }

        .slide-in-left {
            animation: slideInLeft 0.5s ease-out;
        }

        @keyframes slideInLeft {
            from { 
                opacity: 0; 
                transform: translateX(-20px); 
            }
            to { 
                opacity: 1; 
                transform: translateX(0); 
            }
        }

        .slide-in {
            animation: slideIn 0.5s ease-out;
        }

        @keyframes slideIn {
            from { 
                opacity: 0; 
                transform: translateX(-20px); 
            }
            to { 
                opacity: 1; 
                transform: translateX(0); 
            }
        }

        .bounce-in {
            animation: bounceIn 0.8s cubic-bezier(0.68, -0.55, 0.265, 1.55);
        }

        @keyframes bounceIn {
            0% { 
                opacity: 0; 
                transform: scale(0.3); 
            }
            50% { 
                opacity: 1; 
                transform: scale(1.05); 
            }
            70% { 
                transform: scale(0.9); 
            }
            100% { 
                opacity: 1; 
                transform: scale(1); 
            }
        }

        .scale-in {
            animation: scaleIn 0.4s ease-out;
        }

        @keyframes scaleIn {
            from { 
                opacity: 0; 
                transform: scale(0.8); 
            }
            to { 
                opacity: 1; 
                transform: scale(1); 
            }
        }

        /* 图表容器 - 参照巡检报告中心，更专业 */
        .chart-container {
            position: relative;
            height: 400px;
            margin: 1rem 0;
            border-radius: var(--radius-md);
            overflow: hidden;
        }

        .chart-container.small {
            height: 300px;
        }

        /* 告警项目 - 参照巡检报告中心，更精致 */
        .alert-item {
            background: linear-gradient(135deg, #fff5f5 0%, #fed7d7 100%);
            border: 1px solid #feb2b2;
            border-radius: var(--radius-lg);
            padding: var(--spacing-lg);
            margin-bottom: var(--spacing-md);
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }

        .alert-item::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--danger-gradient);
        }

        .alert-item:hover {
            transform: translateX(4px);
            box-shadow: var(--card-hover-shadow);
        }

        /* 服务器资源卡片 - 参照巡检报告中心，更精致 */
        .server-resource-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: var(--radius-xl);
            padding: var(--spacing-lg);
            margin-bottom: var(--spacing-md);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
        }

        .server-resource-card::before {
            content: '';
            position: absolute;
            top: -50%;
            right: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
            transform: rotate(45deg);
            transition: all 0.4s ease;
        }

        .server-resource-card:hover::before {
            transform: rotate(45deg) scale(1.1);
        }

        .server-resource-card:hover {
            transform: translateY(-5px) scale(1.02);
            box-shadow: var(--card-hover-shadow);
        }

        .server-resource-card .progress {
            height: 25px;
            border-radius: 15px;
            background: rgba(255, 255, 255, 0.2);
            overflow: hidden;
            margin: var(--spacing-sm) 0;
            box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.1);
        }

        .server-resource-card .progress-bar {
            border-radius: 15px;
            transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            font-weight: 600;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .server-resource-card .progress-bar::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
            animation: shimmer 2s infinite;
        }

        @keyframes shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }

        /* 刷新按钮 - 参照巡检报告中心，更精致 */
        .refresh-btn {
            background: var(--primary-gradient);
            border: none;
            border-radius: 25px;
            color: white;
            padding: var(--spacing-md) var(--spacing-xl);
            font-weight: 600;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
            position: relative;
            overflow: hidden;
            font-size: 0.95rem;
        }

        .refresh-btn:hover {
            transform: translateY(-2px) rotate(3deg);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }

        .refresh-btn:active {
            transform: translateY(-1px) rotate(1deg);
        }
        
        /* 巡检按钮样式 */
        .inspection-btn {
            background: var(--success-gradient);
            border: none;
            border-radius: 25px;
            color: white;
            padding: var(--spacing-md) var(--spacing-xl);
            font-weight: 600;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 4px 15px rgba(79, 172, 254, 0.3);
            position: relative;
            overflow: hidden;
        }
        .inspection-btn:hover {
            transform: translateY(-2px) rotate(-3deg);
            box-shadow: 0 6px 20px rgba(79, 172, 254, 0.4);
            color: white;
        }
        .inspection-btn:active {
            transform: translateY(-1px) rotate(-1deg);
        }

        /* 响应式设计 - 参照巡检报告中心 */
        @media (max-width: 1200px) {
            .page-header h1 {
                font-size: 2rem;
            }
            
            .metric-card .metric-value {
                font-size: 2.5rem;
            }
        }

        @media (max-width: 768px) {
            .page-header {
                padding: var(--spacing-lg);
                text-align: center;
            }
            
            .page-header .header-icon {
                margin: 0 auto var(--spacing-sm) auto;
            }
            
            .page-header h1 {
                font-size: 2rem;
            }
            
            .metric-card {
                padding: var(--spacing-lg);
            }
            
            .metric-card .metric-value {
                font-size: 2.5rem;
            }
            
            .main-card .card-body {
                padding: var(--spacing-lg);
            }
            
            .chart-container {
                height: 300px;
            }
            
            .btn {
                padding: var(--spacing-sm) var(--spacing-lg);
                font-size: 0.9rem;
            }
        }

        @media (max-width: 576px) {
            .page-header {
                padding: var(--spacing-md);
            }
            
            .page-header h1 {
                font-size: 1.75rem;
            }
            
            .metric-card .metric-value {
                font-size: 2rem;
            }
            
            .btn {
                padding: var(--spacing-sm) var(--spacing-md);
                font-size: 0.85rem;
            }
        }

        /* 深色模式支持 - 参照巡检报告中心 */
        @media (prefers-color-scheme: dark) {
            :root {
                --text-primary: #f7fafc;
                --text-secondary: #e2e8f0;
                --text-muted: #a0aec0;
                --bg-primary: #1a202c;
                --bg-secondary: #2d3748;
                --bg-tertiary: #4a5568;
            }
            
            body {
                background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%);
            }
            
            .navbar {
                background: rgba(26, 32, 44, 0.95) !important;
            }
            
            .page-header {
                background: var(--bg-secondary);
                border-color: rgba(255, 255, 255, 0.1);
            }
            
            .main-card {
                background: var(--bg-secondary);
            }
            
            .main-card .card-header {
                background: linear-gradient(135deg, var(--bg-tertiary) 0%, var(--bg-secondary) 100%);
            }
        }

        /* 打印样式 - 参照巡检报告中心 */
        @media print {
            .navbar, .btn, .refresh-btn {
                display: none !important;
            }
            
            .metric-card, .main-card {
                box-shadow: none !important;
                border: 1px solid #ddd !important;
                break-inside: avoid;
            }
            
            .page-header {
                background: white !important;
                color: black !important;
            }
            
            .chart-container {
                height: 300px !important;
            }
        }

        /* 工具提示样式 - 参照巡检报告中心 */
        .tooltip-inner {
            background: #495057;
            border-radius: 8px;
            padding: 0.5rem 0.75rem;
            font-size: 0.85rem;
        }

        /* 自定义滚动条 - 参照巡检报告中心 */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 4px;
        }

        ::-webkit-scrollbar-thumb {
            background: #c1c1c1;
            border-radius: 4px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: #a8a8a8;
        }
    </style>
</head>
<body>
    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg navbar-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">
                <i class="bi bi-speedometer2 me-2"></i>AI-Ops 智能运维系统
            </a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link active" href="/">
                    <i class="bi bi-house-door me-1"></i>仪表板
                </a>
                
                <a class="nav-link" href="/log-types">
                    <i class="bi bi-file-text me-1"></i>日志类型
                </a>
                
                <a class="nav-link" href="/reports">
                    <i class="bi bi-file-earmark-text me-1"></i>报告
                </a>
            </div>
        </div>
    </nav>

    <div class="container-fluid py-3">
        <!-- 页面标题 -->
        <div class="page-header">
            <div class="row align-items-center">
                <div class="col-lg-8">
                    <div class="d-flex align-items-center">
                        <div class="header-icon">
                            <i class="bi bi-speedometer2"></i>
                        </div>
                        <div>
                            <h1>AI-Ops 智能运维系统</h1>
                            <p>🚀 实时监控 · 🎯 智能告警 · ⚡ 自动化运维 · 📊 数据分析</p>
                        </div>
                    </div>
                </div>
                <div class="col-lg-4 text-lg-end">
                    <button class="btn btn-primary refresh-btn me-2" id="refreshBtn">
                        <i class="bi bi-arrow-clockwise me-2"></i>刷新数据
                    </button>
                    <button class="btn btn-success inspection-btn" id="inspectionBtn">
                        <i class="bi bi-play-circle me-2"></i>开始巡检
                    </button>
                </div>
            </div>
        </div>

        <!-- 状态卡片 -->
        <div class="row mb-3" id="status-cards">
            <div class="col-lg-3 col-md-6 mb-2">
                <div class="metric-card success">
                    <div class="card-body">
                        <div class="metric-icon">
                            <i class="bi bi-heart-pulse"></i>
                        </div>
                        <div class="metric-value" id="healthScore">--</div>
                        <div class="metric-label">健康评分</div>
                        <div class="metric-trend">
                            <i class="bi bi-arrow-up-circle text-success"></i> 良好
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-lg-3 col-md-6 mb-2">
                <div class="metric-card info">
                    <div class="card-body">
                        <div class="metric-icon">
                            <i class="bi bi-clipboard-check"></i>
                        </div>
                        <div class="metric-value" id="total-checks">--</div>
                        <div class="metric-label">总检查数</div>
                        <div class="metric-trend">
                            <i class="bi bi-activity"></i> 活跃
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-lg-3 col-md-6 mb-2">
                <div class="metric-card warning">
                    <div class="card-body">
                        <div class="metric-icon">
                            <i class="bi bi-exclamation-triangle"></i>
                        </div>
                        <div class="metric-value" id="alert-count">--</div>
                        <div class="metric-label">告警数量</div>
                        <div class="metric-trend">
                            <i class="bi bi-eye"></i> 监控中
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-lg-3 col-md-6 mb-2">
                <div class="metric-card danger">
                    <div class="card-body">
                        <div class="metric-icon">
                            <i class="bi bi-x-circle"></i>
                        </div>
                        <div class="metric-value" id="error-count">--</div>
                        <div class="metric-label">错误数量</div>
                        <div class="metric-trend">
                            <i class="bi bi-shield-exclamation"></i> 需关注
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 日志分析卡片 -->
        <div class="row mb-3">
            <div class="col-lg-6 mb-3">
                <div class="main-card">
                    <div class="card-header">
                        <h5><i class="bi bi-graph-up-arrow text-warning"></i> 日志趋势（每分钟）</h5>
                        <div class="header-actions"><small class="text-muted">最近 60 分钟</small></div>
                    </div>
                    <div class="card-body">
                        <div class="chart-container small"><canvas id="log-trend-chart"></canvas></div>
                    </div>
                </div>
            </div>
            <div class="col-lg-6 mb-3">
                <div class="main-card">
                    <div class="card-header">
                        <h5><i class="bi bi-exclamation-octagon text-danger"></i> 日志阈值告警</h5>
                        <div class="header-actions"><small class="text-muted">最近1小时</small></div>
                    </div>
                    <div class="card-body" id="log-alerts">
                        <div class="text-center text-muted py-3">正在加载...</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 图表区域 -->
        <div class="row mb-3">
            <div class="col-lg-6 mb-2">
                <div class="main-card">
                    <div class="card-header">
                        <h5 class="card-title">
                            <i class="bi bi-graph-up-arrow me-2" style="color: #667eea;"></i>健康趋势分析
                        </h5>
                        <div class="header-actions">
                            <small class="text-muted">最近7天健康状态变化趋势</small>
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="chart-container">
                            <canvas id="healthTrendChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-lg-6 mb-2">
                <div class="main-card">
                    <div class="card-header">
                        <h5 class="card-title">
                            <i class="bi bi-pie-chart-fill me-2" style="color: #764ba2;"></i>状态分布分析
                        </h5>
                        <div class="header-actions">
                            <small class="text-muted">各项检查的状态统计</small>
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="chart-container">
                            <canvas id="statusChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 预测性预警分析 与 当前告警监控（同一行并排） -->
        <div class="row mb-3">
          <div class="col-lg-6 mb-3">
            <div class="main-card">
              <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="card-title mb-0">
                  <i class="bi bi-lightning-charge me-2" style="color: #fa709a;"></i> 预测性预警分析
                </h5>
                <div class="header-actions">
                  <small class="text-muted d-block">基于最近5次服务器资源数据，评估未来是否可能触发预警阈值</small>
                  <span class="badge bg-warning text-dark">AI预测</span>
                </div>
              </div>
              <div class="card-body" id="predictive-trend">
                <div class="text-center text-muted py-3">
                  <div class="loading-spinner"></div>
                  <p class="mt-2">正在分析服务器走势...</p>
                </div>
              </div>
            </div>
          </div>
          <div class="col-lg-6 mb-3">
            <div class="main-card">
              <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="card-title mb-0">
                  <i class="bi bi-exclamation-triangle-fill me-2" style="color: #fa709a;"></i>当前告警监控
                </h5>
                <div class="header-actions">
                  <span class="badge bg-danger me-2" id="alert-badge" style="display:none;">0</span>
                  <small class="text-muted">实时监控系统状态</small>
                </div>
              </div>
              <div class="card-body" id="alerts-container">
                <div class="text-center text-muted py-3">
                  <i class="bi bi-check-circle" style="font-size: 2.5rem; color: #28a745;"></i>
                  <p class="mt-2">暂无告警，系统运行正常</p>
                </div>
              </div>
              <div class="d-flex justify-content-between align-items-center mt-2 px-3 pb-3" id="alerts-pagination"></div>
            </div>
          </div>
        </div>

        <!-- 服务器资源信息 -->
        <div class="row mb-3">
            <div class="col-12">
                <div class="main-card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="card-title">
                            <i class="bi bi-hdd-network me-2" style="color: #667eea;"></i>服务器资源监控
                        </h5>
                        <div class="header-actions">
                            <small class="text-muted me-3">实时监控服务器性能</small>
                            <a href="/server-resources" class="btn btn-outline-primary btn-sm">
                                <i class="bi bi-arrow-right me-1"></i>查看详细
                            </a>
                        </div>
                    </div>
                    <div class="card-body">
                        <div id="server-resources">
                            <div class="text-center py-3">
                                <div class="loading-spinner"></div>
                                <p class="mt-2 text-muted">正在加载服务器资源信息...</p>
                            </div>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mt-2" id="server-resources-pagination"></div>
                    </div>
                </div>
            </div>
        </div>


        <!-- 详细数据 -->
        <div class="row">
            <div class="col-12">
                <div class="main-card">
                    <div class="card-header">
                        <h5 class="card-title">
                            <i class="bi bi-clock-history me-2" style="color: #764ba2;"></i>巡检记录分析
                        </h5>
                        <div class="header-actions">
                            <small class="text-muted">最近24小时的系统巡检历史</small>
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-hover" id="inspection-table">
                                <thead>
                                    <tr>
                                        <th>时间</th>
                                        <th>检查项</th>
                                        <th>状态</th>
                                        <th>类别</th>
                                        <th>严重程度</th>
                                        <th>详情</th>
                                    </tr>
                                </thead>
                                <tbody id="inspection-tbody">
                                    <tr>
                                        <td colspan="6" class="text-center py-4">
                                            <div class="loading-spinner"></div>
                                            <p class="mt-2 text-muted">加载中...</p>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mt-2" id="inspection-pagination"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let healthTrendChart, statusChart;
        // 当前告警分页状态
        let alertsPage = 1;
        const alertsPageSize = 10;
        let alertsAllItems = [];
        // 服务器资源分页状态
        let serverResourcesPage = 1;
        const serverResourcesPageSize = 10;
        let serverResourcesItems = [];

        // 告警标题（中文）映射与解析
        function getAlertTitle(alert) {
            if (alert && alert.description) return alert.description;
            const name = (alert && (alert.rule_name || alert.check_name)) ? String(alert.rule_name || alert.check_name) : '';
            const mapping = {
                'cpu_usage_high': 'CPU使用率过高',
                'memory_usage_high': '内存使用率过高',
                'disk_usage_high': '磁盘使用率过高',
                'service_down': '服务不可用',
                'http_4xx_errors': 'HTTP 4xx错误率过高',
                'http_5xx_errors': 'HTTP 5xx错误率过高',
                'network_errors': '网络错误率过高',
                'mysql_connections_high': 'MySQL连接数过高',
                'cpu_usage_over_60': 'CPU使用率超过60%',
                'memory_usage_over_90': '内存使用率超过90%',
                'disk_usage_over_85': '磁盘使用率超过85%'
            };
            return mapping[name] || name || '告警';
        }

        // 告警等级（中文）映射
        function getSeverityText(severity) {
            const key = String(severity || '').toLowerCase();
            const mapping = {
                'critical': '严重',
                'warning': '警告',
                'error': '错误',
                'info': '提示',
                'ok': '正常'
            };
            return mapping[key] || (severity || '');
        }

        // 状态文本（中文）映射
        function getStatusText(status) {
            const key = String(status || '').toLowerCase();
            const mapping = {
                'ok': '正常',
                'alert': '告警',
                'error': '错误'
            };
            return mapping[key] || (status || '');
        }
        
        // 初始化图表
        function initCharts() {
            // 健康趋势图表
            const healthCtx = document.getElementById('healthTrendChart').getContext('2d');
            healthTrendChart = new Chart(healthCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: '健康评分',
                        data: [],
                        borderColor: '#667eea',
                        backgroundColor: 'rgba(102, 126, 234, 0.1)',
                        tension: 0.4,
                        borderWidth: 3,
                        pointBackgroundColor: '#667eea',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        pointRadius: 6,
                        pointHoverRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100,
                            grid: {
                                color: 'rgba(0,0,0,0.1)'
                            }
                        },
                        x: {
                            grid: {
                                color: 'rgba(0,0,0,0.1)'
                            }
                        }
                    }
                }
            });

            // 状态分布图表
            const statusCtx = document.getElementById('statusChart').getContext('2d');
            statusChart = new Chart(statusCtx, {
                type: 'doughnut',
                data: {
                    labels: ['正常', '告警', '错误'],
                    datasets: [{
                        data: [0, 0, 0],
                        backgroundColor: ['#28a745', '#ffc107', '#dc3545'],
                        borderWidth: 0,
                        hoverOffset: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                padding: 20,
                                usePointStyle: true
                            }
                        }
                    }
                }
            });
        }

        // 渲染当前告警（分页）
        function renderAlerts(alerts) {
            const container = document.getElementById('alerts-container');
            const badge = document.getElementById('alert-badge');
            const pager = document.getElementById('alerts-pagination');
            
            if (!container || !badge || !pager) {
                console.warn('告警容器元素未找到');
                return;
            }
            
            const items = Array.isArray(alerts) ? alerts : [];

            // 缓存完整列表用于分页切换
            alertsAllItems = items;

            if (items.length === 0) {
                container.innerHTML = `
                    <div class="text-center text-muted py-4">
                        <i class="bi bi-check-circle" style="font-size: 3rem; color: #28a745;"></i>
                        <p class="mt-2">暂无告警，系统运行正常</p>
                    </div>
                `;
                badge.style.display = 'none';
                pager.innerHTML = '';
                return;
            }

            const total = items.length;
            const totalPages = Math.max(1, Math.ceil(total / alertsPageSize));
            if (alertsPage > totalPages) alertsPage = totalPages;
            const start = (alertsPage - 1) * alertsPageSize;
            const pageItems = items.slice(start, start + alertsPageSize);

            badge.textContent = total;
            badge.style.display = 'inline-block';

            let html = '<div class="row">';
            pageItems.forEach(a => {
                const sev = a.severity === 'critical' ? 'danger' : 'warning';
                const title = getAlertTitle(a);
                html += `
                    <div class="col-md-6 mb-3">
                        <div class="alert-item">
                            <div class="d-flex align-items-center mb-2">
                                <span class="badge bg-${sev} me-2">${getSeverityText(a.severity)}</span>
                                <small class="text-muted">${formatTimeForDisplay(a.timestamp)}</small>
                            </div>
                            <h6 class="mb-1">${title}</h6>
                            <p class="mb-1 small">实例: ${a.instance || '未知'} · 类别: ${a.category || '无'}</p>
                            <div class="d-flex justify-content-between align-items-center">
                                <span class="small">当前值: ${a.current_value !== null && a.current_value !== undefined ? a.current_value.toString() : '未知'}</span>
                                <span class="small">阈值: ${a.threshold !== null && a.threshold !== undefined ? a.threshold.toString() : '未知'}</span>
                            </div>
                        </div>
                    </div>
                `;
            });
            html += '</div>';

            container.innerHTML = html;

            // 分页控件
            const hasPrev = alertsPage > 1;
            const hasNext = alertsPage < totalPages;
            pager.innerHTML = `
                <div>
                    <small class="text-muted">每页 ${alertsPageSize} 条，共 ${total} 条</small>
                </div>
                <div>
                    <button class="btn btn-sm btn-outline-secondary me-2 ${hasPrev ? '' : 'disabled'}" ${hasPrev ? '' : 'disabled'} onclick="setAlertsPage(${alertsPage - 1})">上一页</button>
                    <span class="text-muted">第 ${alertsPage} / ${totalPages} 页</span>
                    <button class="btn btn-sm btn-outline-secondary ms-2 ${hasNext ? '' : 'disabled'}" ${hasNext ? '' : 'disabled'} onclick="setAlertsPage(${alertsPage + 1})">下一页</button>
                </div>
            `;
        }

        function setAlertsPage(p) {
            const totalPages = Math.max(1, Math.ceil((alertsAllItems?.length || 0) / alertsPageSize));
            const nextPage = Math.min(Math.max(1, p), totalPages);
            if (nextPage === alertsPage) return;
            alertsPage = nextPage;
            renderAlerts(alertsAllItems || []);
        }

        function setServerResourcesPage(p) {
            const totalPages = Math.max(1, Math.ceil((serverResourcesItems?.length || 0) / serverResourcesPageSize));
            const nextPage = Math.min(Math.max(1, p), totalPages);
            if (nextPage === serverResourcesPage) return;
            serverResourcesPage = nextPage;
            renderServerResources();
        }

        function renderServerResources() {
            const container = document.getElementById('server-resources');
            if (!container) {
                console.warn('服务器资源容器未找到');
                return;
            }
            
            if (!serverResourcesItems || serverResourcesItems.length === 0) {
                container.innerHTML = '<div class="text-center text-muted py-4">暂无服务器资源信息</div>';
                return;
            }

            const sp = new URLSearchParams(location.search);
            const metricParam = (sp.get('metric') || 'max').toLowerCase();
            const page = serverResourcesPage;
            const pageSize = serverResourcesPageSize;

            // 排序
            const itemsSorted = serverResourcesItems.slice().sort((a, b) => {
                const cpuA = Number(a?.cpu?.usage_percent || 0);
                const memA = Number(a?.memory?.usage_percent || 0);
                const diskA = a?.disk?.partitions && a.disk.partitions.length > 0 ? 
                    Math.max(...a.disk.partitions.map(p => Number(p.usage_percent || 0))) : 0;
                const cpuB = Number(b?.cpu?.usage_percent || 0);
                const memB = Number(b?.memory?.usage_percent || 0);
                const diskB = b?.disk?.partitions && b.disk.partitions.length > 0 ? 
                    Math.max(...b.disk.partitions.map(p => Number(p.usage_percent || 0))) : 0;
                
                let keyA, keyB;
                if (metricParam === 'cpu') {
                    keyA = cpuA;
                    keyB = cpuB;
                } else if (metricParam === 'mem') {
                    keyA = memA;
                    keyB = memB;
                } else if (metricParam === 'disk') {
                    keyA = diskA;
                    keyB = diskB;
                } else {
                    // 默认按最大值排序
                    keyA = Math.max(cpuA, memA, diskA);
                    keyB = Math.max(cpuB, memB, diskB);
                }
                return keyB - keyA;
            });

            const start = (page - 1) * pageSize;
            const pageItems = itemsSorted.slice(start, start + pageSize);

            let html = '<div class="table-responsive"><table class="table table-hover"><thead><tr>'+
                       '<th>实例</th><th>主机</th><th>CPU</th><th>内存</th><th>磁盘(最大分区)</th><th>操作</th></tr></thead><tbody>';
            pageItems.forEach(sv => {
                const instance = sv.instance || 'unknown';
                const hostname = (sv.system && sv.system.hostname) || instance.split(':')[0] || '';
                const cpu = Number(sv?.cpu?.usage_percent ?? sv?.cpu?.usage ?? 0);
                const mem = Number(sv?.memory?.usage_percent || 0);
                
                // 计算最大分区使用率
                let maxDiskUsage = 0;
                if (sv.disk?.partitions && sv.disk.partitions.length > 0) {
                    // 优先选择根挂载点'/'，若无则使用最大分区
                    const root = sv.disk.partitions.find(p => (p.mountpoint === '/' || p.mountpoint === 'root' || p.mountpoint === '/root'));
                    if (root && root.usage_percent != null) {
                        maxDiskUsage = Number(root.usage_percent);
                    } else {
                        maxDiskUsage = Math.max(...sv.disk.partitions.map(p => Number(p.usage_percent || 0)));
                    }
                }

                html += `
                <tr>
                    <td><strong>${instance}</strong></td>
                    <td><strong>${hostname || '无'}</strong></td>
                    <td>
                        <span class="badge bg-${cpu>80?'danger':cpu>60?'warning':'success'}">${cpu.toFixed(1)}%</span>
                    </td>
                    <td>
                        <span class="badge bg-${mem>80?'danger':mem>60?'warning':'success'}">${mem.toFixed(1)}%</span>
                    </td>
                    <td>
                        <span class="badge bg-${maxDiskUsage>80?'danger':maxDiskUsage>60?'warning':'success'}">${maxDiskUsage.toFixed(1)}%</span>
                    </td>
                    <td>
                        <a class="btn btn-outline-primary btn-sm" href="/server-detail?instance=${encodeURIComponent(instance)}">查看</a>
                    </td>
                </tr>`;
            });
            html += '</tbody></table></div>';

            // 分页控件
            const hasPrev = page > 1;
            const hasNext = start + pageSize < itemsSorted.length;
            html += `<div class="d-flex justify-content-between align-items-center mt-2">
                <small class="text-muted">每页 10 条，共 ${itemsSorted.length} 条${metricParam!=='max' ? `（按 ${metricParam==='cpu'?'CPU':metricParam==='mem'?'内存':'磁盘'} 排序）` : '（按 CPU/内存/磁盘最大值排序）'}</small>
                <div>
                    <button class="btn btn-sm btn-outline-secondary me-2 ${hasPrev?'':'disabled'}" ${hasPrev?'':'disabled'} onclick="setServerResourcesPage(${page - 1})">上一页</button>
                    <span class="text-muted">第 ${page} 页</span>
                    <button class="btn btn-sm btn-outline-secondary ms-2 ${hasNext?'':'disabled'}" ${hasNext?'':'disabled'} onclick="setServerResourcesPage(${page + 1})">下一页</button>
                </div>
            </div>`;
            
            document.getElementById('server-resources').innerHTML = html;
        }

        // 格式化时间显示 - 处理时区问题
        function formatTimeForDisplay(timestamp) {
            if (!timestamp) return '无';
            
            const date = new Date(timestamp);
            
            // 检查是否是有效日期
            if (isNaN(date.getTime())) {
                return '无效时间';
            }
            
            // 如果时间戳是UTC时间（包含Z后缀），转换为中国时区
            if (typeof timestamp === 'string' && timestamp.endsWith('Z')) {
                const chinaTime = new Date(date.getTime() + (8 * 60 * 60 * 1000));
                return chinaTime.toLocaleString('zh-CN', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
            } else {
                // 已经是本地时间或数据库中的中国时区时间，直接格式化
                return date.toLocaleString('zh-CN', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
            }
        }

        // 更新状态卡片
        function updateStatusCards(data) {
            const healthScoreEl = document.getElementById('healthScore');
            const totalChecksEl = document.getElementById('total-checks');
            const alertCountEl = document.getElementById('alert-count');
            const errorCountEl = document.getElementById('error-count');
            const statusCardsEl = document.getElementById('status-cards');
            
            if (healthScoreEl) healthScoreEl.textContent = data.health_score;
            if (totalChecksEl) totalChecksEl.textContent = data.total_checks;
            if (alertCountEl) alertCountEl.textContent = data.alert_count;
            if (errorCountEl) errorCountEl.textContent = data.error_count;
            
            // 添加动画效果 - 参照巡检报告中心
            if (statusCardsEl) {
                statusCardsEl.classList.add('fade-in');
                // 为每个卡片添加延迟动画
                const cards = statusCardsEl.querySelectorAll('.metric-card');
                cards.forEach((card, index) => {
                    setTimeout(() => {
                        card.classList.add('scale-in');
                    }, index * 100);
                });
            }
        }

        // 更新健康趋势图表 - 时间从左到右递增
        function updateHealthTrendChart(data) {
            if (!healthTrendChart || !data || !data.trends) {
                console.warn('健康趋势图表数据无效或图表未初始化');
                return;
            }
            
            // 按时间排序，确保从左到右递增
            const sortedData = data.trends.sort((a, b) => new Date(a.date) - new Date(b.date));
            const labels = sortedData.map(item => item.date);
            const scores = sortedData.map(item => item.health_score);
            
            healthTrendChart.data.labels = labels;
            healthTrendChart.data.datasets[0].data = scores;
            healthTrendChart.update('active');
        }

        // 更新状态分布图表
        function updateStatusChart(data) {
            if (!statusChart || !data) {
                console.warn('状态分布图表未初始化或数据无效');
                return;
            }
            
            const okCount = data.ok_count || 0;
            const alertCount = data.alert_count || 0;
            const errorCount = data.error_count || 0;
            
            statusChart.data.datasets[0].data = [okCount, alertCount, errorCount];
            statusChart.update('active');
        }

        // 更新巡检记录表格
        function updateInspectionTable(data) {
            const tbody = document.getElementById('inspection-tbody');
            const pager = document.getElementById('inspection-pagination');
            
            if (!tbody || !pager) {
                console.warn('巡检表格元素未找到');
                return;
            }
            
            tbody.innerHTML = '';

            const items = Array.isArray(data) ? data : (data && data.items) ? data.items : [];
            const page = (data && data.page) ? data.page : 1;
            const pageSize = (data && data.page_size) ? data.page_size : 10;
            const hasMore = !!(data && data.has_more);

            if (items.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center py-4">
                            <i class="bi bi-inbox" style="font-size: 2rem; color: #6c757d;"></i>
                            <p class="mt-2 text-muted">暂无数据</p>
                        </td>
                    </tr>
                `;
                pager.innerHTML = '';
                return;
            }

            items.forEach(item => {
                const row = document.createElement('tr');
                const statusClass = item.status === 'ok' ? 'text-success' : 
                                  item.status === 'alert' ? 'text-warning' : 'text-danger';
                const statusIcon = item.status === 'ok' ? 'bi-check-circle' : 
                                 item.status === 'alert' ? 'bi-exclamation-triangle' : 'bi-x-circle';
                row.innerHTML = `
                    <td><small>${formatTimeForDisplay(item.ts)}</small></td>
                    <td><strong>${item.check_name}</strong></td>
                    <td>
                        <i class="bi ${statusIcon} ${statusClass} status-icon"></i>
                        <span class="badge bg-${item.status === 'ok' ? 'success' : item.status === 'alert' ? 'warning' : 'danger'}">${getStatusText(item.status)}</span>
                    </td>
                    <td><span class="badge bg-secondary">${item.category || '无'}</span></td>
                    <td>
                        <span class="badge bg-${item.severity === 'critical' ? 'danger' : item.severity === 'warning' ? 'warning' : 'info'}">${getSeverityText(item.severity)}</span>
                    </td>
                    <td><small>${item.detail || '无'}</small></td>
                `;
                tbody.appendChild(row);
            });

            // 分页控件
            const total = data.total || items.length;
            const prevDisabled = page <= 1 ? 'disabled' : '';
            const nextDisabled = hasMore ? '' : 'disabled';
            pager.innerHTML = `
                <div>
                    <small class="text-muted">共 ${total} 条记录，每页 ${pageSize} 条</small>
                </div>
                <div>
                    <button class="btn btn-sm btn-outline-secondary me-2" ${prevDisabled} onclick="loadInspections(${page-1}, ${pageSize})">上一页</button>
                    <span class="text-muted">第 ${page} 页</span>
                    <button class="btn btn-sm btn-outline-secondary ms-2" ${nextDisabled} onclick="loadInspections(${page+1}, ${pageSize})">下一页</button>
                </div>
            `;
        }

        // 加载巡检（分页）
        async function loadInspections(page=1, pageSize=10) {
            const inspectionsResponse = await axios.get(`/api/inspections?hours=24&page=${page}&page_size=${pageSize}`);
            updateInspectionTable(inspectionsResponse.data);
        }

        // 更新服务器资源信息
        function updateServerResources(response) {
            const container = document.getElementById('server-resources');
            
            let data = response;
            let cacheInfo = null;
            
            if (response && response.data) {
                data = response.data;
                cacheInfo = response.cache;
            }
            
            if (!data || data.length === 0) {
                container.innerHTML = `
                    <div class="text-center text-muted py-4">
                        <i class="bi bi-server" style="font-size: 3rem; color: #6c757d;"></i>
                        <p class="mt-2">暂无服务器资源信息</p>
                    </div>
                `;
                return;
            }
            
            let cacheStatusHtml = '';
            if (cacheInfo) {
                const cacheStatus = cacheInfo.connected ? 
                    `<span class="badge bg-success">Redis已连接</span>` : 
                    `<span class="badge bg-warning">Redis未连接</span>`;
                cacheStatusHtml = `
                    <div class="mb-3 p-3 bg-light rounded">
                        <small class="text-muted">缓存状态: ${cacheStatus}</small>
                        ${cacheInfo.connected ? `<small class="text-muted ms-2">缓存大小: ${cacheInfo.size}</small>` : ''}
                    </div>
                `;
            }
            
            let html = cacheStatusHtml + '<div class="row">';
            data.forEach(server => {
                const cpuUsage = Number(server.cpu?.usage_percent ?? server.cpu?.usage ?? 0);
                const memoryUsage = server.memory?.usage_percent || 0;
                const cpuCores = server.cpu?.cores || 0;
                const totalMemory = server.memory?.total_gb || 0;
                const uptime = server.system?.uptime_days || 0;
                
                // 计算最大分区使用率
                let maxDiskUsage = 0;
                if (server.disk?.partitions && server.disk.partitions.length > 0) {
                    const root = server.disk.partitions.find(p => (p.mountpoint === '/' || p.mountpoint === 'root' || p.mountpoint === '/root'));
                    if (root && root.usage_percent != null) {
                        maxDiskUsage = Number(root.usage_percent);
                    } else {
                        maxDiskUsage = Math.max(...server.disk.partitions.map(p => Number(p.usage_percent || 0)));
                    }
                }
                
                html += `
                    <div class="col-lg-6 mb-3">
                        <div class="server-resource-card">
                            <div class="d-flex justify-content-between align-items-start mb-3">
                                <h6 class="mb-0">
                                    <i class="bi bi-hdd-network me-2"></i>${server.instance}
                                </h6>
                                <small class="opacity-75">运行 ${uptime.toFixed(1)} 天</small>
                            </div>
                            <div class="row">
                                <div class="col-6">
                                    <div class="mb-3">
                                        <small class="opacity-75">CPU使用率</small>
                                        <div class="progress mt-1">
                                            <div class="progress-bar ${cpuUsage > 80 ? 'bg-danger' : cpuUsage > 60 ? 'bg-warning' : 'bg-success'}" 
                                                 style="width: ${cpuUsage}%">${cpuUsage.toFixed(1)}%</div>
                                        </div>
                                    </div>
                                    <div class="mb-3">
                                        <small class="opacity-75">内存使用率</small>
                                        <div class="progress mt-1">
                                            <div class="progress-bar ${memoryUsage > 80 ? 'bg-danger' : memoryUsage > 60 ? 'bg-warning' : 'bg-success'}" 
                                                 style="width: ${memoryUsage}%">${memoryUsage.toFixed(1)}%</div>
                                        </div>
                                    </div>
                                    <div class="mb-3">
                                        <small class="opacity-75">磁盘使用率(最大分区)</small>
                                        <div class="progress mt-1">
                                            <div class="progress-bar ${maxDiskUsage > 80 ? 'bg-danger' : maxDiskUsage > 60 ? 'bg-warning' : 'bg-success'}" 
                                                 style="width: ${maxDiskUsage}%">${maxDiskUsage.toFixed(1)}%</div>
                                        </div>
                                    </div>
                                </div>
                                <div class="col-6">
                                    <div class="mb-2">
                                        <small class="opacity-75">CPU核心数</small>
                                        <div class="fw-bold">${cpuCores}</div>
                                    </div>
                                    <div class="mb-2">
                                        <small class="opacity-75">总内存</small>
                                        <div class="fw-bold">${totalMemory} GB</div>
                                    </div>
                                    <div class="mb-2">
                                        <small class="opacity-75">磁盘分区数</small>
                                        <div class="fw-bold">${server.disk?.partitions?.length || 0}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            container.innerHTML = html;
        }

        // 刷新所有数据
        async function refreshAll() {
            try {
                const refreshBtn = document.getElementById('refreshBtn');
                if (refreshBtn) {
                    refreshBtn.innerHTML = '<div class="loading-spinner"></div> 刷新中...';
                    refreshBtn.disabled = true;
                }
                
                // 获取当前状态
                const statusResponse = await axios.get('/api/current-status');
                updateStatusCards(statusResponse.data);
                
                // 获取健康趋势
                const trendsResponse = await axios.get('/api/health-trends?days=7');
                updateHealthTrendChart(trendsResponse.data);
                
                // 获取巡检记录
                const inspectionsResponse = await axios.get('/api/inspections?hours=24&page=1&page_size=10');
                updateInspectionTable(inspectionsResponse.data);
                updateStatusChart(statusResponse.data);
                
                // 首页服务器资源信息：快速获取 + 软轮询回填（每页10条）
                try {
                    const quick = await axios.get('/api/server-resources?quick=true&prefetch=true&t=' + Date.now());
                    let items = (quick.data && quick.data.data) || [];
                    if (!items.length) {
                        // 进行2次软轮询，每次间隔2秒
                        let attempts = 2;
                        while (attempts-- > 0) {
                            await new Promise(r => setTimeout(r, 2000));
                            try {
                                const fresh = await axios.get('/api/server-resources?quick=true&t=' + Date.now());
                                items = (fresh.data && fresh.data.data) || [];
                                if (items.length) break;
                            } catch (_) {}
                        }
                    }
                    if (!items.length) {
                        document.getElementById('server-resources').innerHTML = '<div class="text-center text-muted py-4">暂无服务器资源信息</div>';
                    } else {
                        const totalPagesBefore = Math.max(1, Math.ceil((serverResourcesItems?.length || 0) / serverResourcesPageSize));
                        const currentPageBefore = serverResourcesPage;
                        serverResourcesItems = items;
                        const totalPagesAfter = Math.max(1, Math.ceil(items.length / serverResourcesPageSize));
                        if (currentPageBefore > totalPagesAfter) {
                            serverResourcesPage = totalPagesAfter;
                        }
                        renderServerResources();
                    }
                } catch (e) {
                    console.error('加载服务器资源失败:', e);
                }

                // 预测性预警趋势（最近5次）
                try {
                  const trendEl = document.getElementById('predictive-trend');
                  const t5 = await axios.get('/api/resource-trend-alerts');
                  const rows = t5.data?.items || [];
                  if (!rows.length){
                    trendEl.innerHTML = '<div class="text-center text-muted py-3">暂无即将触发预警的服务器</div>';
                  } else {
                    let html = '<div class="table-responsive"><table class="table table-hover"><thead><tr>'+
                               '<th>实例</th><th>指标</th><th>最近值序列</th><th>预测</th><th>阈值</th><th>趋势</th></tr></thead><tbody>';
                    rows.forEach(r=>{
                      const seq = (r.series||[]).map(v=>Number(v).toFixed(1)).join(' → ');
                      const sevBadge = r.metric==='cpu'? 'warning' : 'danger';
                      html += `<tr>
                        <td><strong>${r.instance}</strong></td>
                        <td><span class="badge bg-${sevBadge}">${r.metric.toUpperCase()}</span></td>
                        <td><small>${seq}</small></td>
                        <td><span class="badge bg-${sevBadge}">${Number(r.prediction||0).toFixed(1)}%</span></td>
                        <td><span class="badge bg-secondary">${Number(r.threshold||0).toFixed(0)}%</span></td>
                        <td><span class="badge ${r.trend==='rising'?'bg-danger': r.trend==='stable'?'bg-secondary':'bg-success'}">${r.trend||'-'}</span></td>
                      </tr>`;
                    });
                    html += '</tbody></table></div>';
                    trendEl.innerHTML = html;
                  }
                } catch(e){
                  console.error('预测趋势分析失败:', e);
                }

                // 获取当前告警（分页渲染，每页10条）
                const alertsResp = await axios.get('/api/alerts');
                const allAlerts = alertsResp.data.alerts || [];
                // 刷新后保持当前页尽量不变
                const totalPagesBefore = Math.max(1, Math.ceil((alertsAllItems?.length || 0) / alertsPageSize));
                const currentPageBefore = alertsPage;
                alertsAllItems = allAlerts;
                const totalPagesAfter = Math.max(1, Math.ceil(allAlerts.length / alertsPageSize));
                if (currentPageBefore > totalPagesAfter) {
                    alertsPage = totalPagesAfter;
                }
                renderAlerts(allAlerts);

                // 获取日志统计（仍用于其他部件需要时）
                try {
                  const logStatsResp = await axios.get(`/api/log-stats?hours=1`);
                  window.__logStats = logStatsResp.data || {};
                  renderLogWidgets(window.__logStats);
                } catch(e){ console.warn('获取日志统计失败:', e); }

                // 获取日志阈值告警
                try {
                  const logAlertResp = await axios.get('/api/log-threshold-alerts');
                  const logAlerts = (logAlertResp.data && logAlertResp.data.alerts) ? logAlertResp.data.alerts : [];
                  renderLogAlerts(logAlerts);
                } catch(e){ console.warn('获取日志阈值告警失败:', e); }
                
            } catch (error) {
                console.error('刷新数据失败:', error);
                alert('刷新数据失败: ' + error.message);
            } finally {
                const refreshBtn = document.getElementById('refreshBtn');
                if (refreshBtn) {
                    refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise me-2"></i>刷新数据';
                    refreshBtn.disabled = false;
                }
            }
        }
        
        // 开始巡检功能
        async function startInspection() {
            try {
                const inspectionBtn = document.getElementById('inspectionBtn');
                if (inspectionBtn) {
                    inspectionBtn.innerHTML = '<div class="loading-spinner"></div> 巡检中...';
                    inspectionBtn.disabled = true;
                }
                
                // 调用巡检API
                const response = await axios.post('/api/start-inspection');
                
                if (response.data && response.data.success) {
                    // 巡检成功，显示消息
                    alert('巡检已成功启动！结果已保存到系统中。');
                    
                    // 刷新页面数据以显示最新的巡检结果
                    await refreshAll();
                } else {
                    alert('巡检启动失败: ' + (response.data.message || '未知错误'));
                }
                
            } catch (error) {
                console.error('启动巡检失败:', error);
                alert('启动巡检失败: ' + error.message);
            } finally {
                const inspectionBtn = document.getElementById('inspectionBtn');
                if (inspectionBtn) {
                    inspectionBtn.innerHTML = '<i class="bi bi-play-circle me-2"></i>开始巡检';
                    inspectionBtn.disabled = false;
                }
            }
        }

        // 页面加载完成后初始化
        document.addEventListener('DOMContentLoaded', function() {
            // 添加页面加载动画
            document.body.classList.add('fade-in');
            
            // 绑定刷新按钮点击事件
            const refreshBtn = document.getElementById('refreshBtn');
            if (refreshBtn) {
                refreshBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    refreshAll();
                });
            }
            
            // 绑定巡检按钮点击事件
            const inspectionBtn = document.getElementById('inspectionBtn');
            if (inspectionBtn) {
                inspectionBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    startInspection();
                });
            }
            
            // 检查Chart.js和axios是否加载完成
            function waitForLibraries() {
                let attempts = 0;
                const maxAttempts = 10;
                
                function checkLibraries() {
                    attempts++;
                    
                    if (typeof Chart !== 'undefined' && typeof axios !== 'undefined') {
                        console.log('Chart.js和axios已成功加载');
                        initCharts();
                        refreshAll();
                        return;
                    }
                    
                    if (attempts < maxAttempts) {
                        console.log(`等待库加载... (${attempts}/${maxAttempts})`);
                        setTimeout(checkLibraries, 500);
                    } else {
                        console.error('Chart.js或axios加载超时，请检查网络连接');
                        // 显示错误提示
                        const healthChart = document.getElementById('healthTrendChart');
                        if (healthChart) {
                            healthChart.parentElement.innerHTML = '<div class="text-center text-danger py-4"><i class="bi bi-exclamation-triangle"></i><br>图表加载失败，请刷新页面重试</div>';
                        }
                    }
                }
                
                checkLibraries();
            }
            
            waitForLibraries();

            // 移除日志小时选择切换（不再使用按小时分类视图）
            
            // 为页面元素添加动画效果 - 参照巡检报告中心
            setTimeout(() => {
                const mainCards = document.querySelectorAll('.main-card');
                mainCards.forEach((card, index) => {
                    setTimeout(() => {
                        card.classList.add('slide-in');
                    }, index * 150);
                });
            }, 500);
            
            // 每5分钟自动刷新整页数据
            setInterval(refreshAll, 300000);
            // 每分钟单独刷新日志趋势（轻量，不阻塞整页）
            setInterval(() => { try { refreshLogTrend(); } catch(e){} }, 60000);
        });

        // 日志图表实例
        let logTrendChart = null;

        async function renderLogWidgets(data){
            try{
                const trend = data.time_distribution || {};

                // 日志趋势折线图（按分钟）
                try {
                    const selMin = 60; // 默认最近60分钟
                    const minTrend = await axios.get(`/api/log-trend-minutely?minutes=${selMin}`);
                    const rawLabels = (minTrend.data && minTrend.data.labels) ? minTrend.data.labels : [];
                    const values = (minTrend.data && minTrend.data.values) ? minTrend.data.values : [];

                    // 友好时间标签 HH:mm
                    const displayLabels = rawLabels.map(ts => {
                        try { return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }); }
                        catch(_) { return ts; }
                    });

                    const canvas = document.getElementById('log-trend-chart');
                    if (!canvas) return;
                    const trendCtx = canvas.getContext('2d');

                    // 渐变填充
                    const gradient = trendCtx.createLinearGradient(0, 0, 0, canvas.height || 300);
                    gradient.addColorStop(0, 'rgba(250, 112, 154, 0.25)');
                    gradient.addColorStop(1, 'rgba(250, 112, 154, 0.02)');

                    // 投影插件（提升立体感）
                    const shadowPlugin = {
                        id: 'lineShadow',
                        beforeDatasetsDraw(chart) {
                            const { ctx } = chart;
                            ctx.save();
                            ctx.shadowColor = 'rgba(250, 112, 154, 0.35)';
                            ctx.shadowBlur = 8;
                            ctx.shadowOffsetX = 0;
                            ctx.shadowOffsetY = 4;
                        },
                        afterDatasetsDraw(chart) { chart.ctx.restore(); }
                    };

                    if (!logTrendChart) {
                        logTrendChart = new Chart(trendCtx, {
                            type: 'line',
                            data: {
                                labels: displayLabels,
                                datasets: [{
                                    label: '每分钟日志数',
                                    data: values,
                                    borderColor: '#fa709a',
                                    backgroundColor: gradient,
                                    borderWidth: 2,
                                    fill: true,
                                    tension: 0.35,
                                    pointRadius: 0,
                                    pointHoverRadius: 5,
                                    pointHitRadius: 10,
                                    pointBackgroundColor: '#fa709a',
                                    pointBorderColor: '#fff',
                                    pointBorderWidth: 2,
                                    segment: { borderJoinStyle: 'round' }
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                animation: {
                                    duration: 600,
                                    easing: 'cubicBezier(0.4, 0, 0.2, 1)'
                                },
                                interaction: {
                                    mode: 'index',
                                    intersect: false
                                },
                                plugins: {
                                    legend: { display: false },
                                    tooltip: {
                                        backgroundColor: 'rgba(0,0,0,0.85)',
                                        padding: 10,
                                        displayColors: false,
                                        callbacks: {
                                            title: (items) => {
                                                const i = items[0].dataIndex;
                                                return (rawLabels[i] || '').replace('T', ' ').replace('Z',' UTC');
                                            },
                                            label: (item) => `数量：${item.parsed.y} 条`
                                        }
                                    },
                                    decimation: { enabled: true, algorithm: 'lttb' }
                                },
                                scales: {
                                    x: {
                                        grid: { display: false },
                                        ticks: { maxTicksLimit: 12 }
                                    },
                                    y: {
                                        beginAtZero: true,
                                        grid: { color: 'rgba(0,0,0,0.08)', borderDash: [4, 4] },
                                        ticks: {
                                            precision: 0,
                                            callback: (v) => (v >= 1000 ? (v/1000).toFixed(1)+'k' : v)
                                        }
                                    }
                                }
                            },
                            plugins: [shadowPlugin]
                        });
                    } else {
                        // 仅更新数据，避免销毁重建带来的延迟
                        logTrendChart.data.labels = displayLabels;
                        if (logTrendChart.data.datasets && logTrendChart.data.datasets[0]) {
                            logTrendChart.data.datasets[0].data = values;
                        }
                        logTrendChart.update('active');
                    }
                } catch (e) { console.warn('获取分钟趋势失败:', e); }
            }catch(e){ console.warn('渲染日志图表失败:', e); }
        }

        // 仅刷新日志趋势（轻量方法，按分钟触发）
        async function refreshLogTrend(){
            try{
                const selMin = 60;
                const minTrend = await axios.get(`/api/log-trend-minutely?minutes=${selMin}&nocache=true&t=` + Date.now());
                const rawLabels = (minTrend.data && minTrend.data.labels) ? minTrend.data.labels : [];
                const values = (minTrend.data && minTrend.data.values) ? minTrend.data.values : [];
                const displayLabels = rawLabels.map(ts => { try { return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }); } catch(_) { return ts; } });
                if (logTrendChart){
                    logTrendChart.data.labels = displayLabels;
                    if (logTrendChart.data.datasets && logTrendChart.data.datasets[0]) {
                        logTrendChart.data.datasets[0].data = values;
                    }
                    logTrendChart.update('active');
                } else {
                    // 若首次尚未创建，走完整渲染流程
                    renderLogWidgets({});
                }
            }catch(e){ console.warn('分钟趋势刷新失败:', e); }
        }

        function renderLogAlerts(alerts){
            const box = document.getElementById('log-alerts');
            if (!box) return;
            if (!alerts || !alerts.length){
                box.innerHTML = '<div class="text-center text-muted py-3">暂无日志阈值告警</div>';
                return;
            }
            let html = '';
            alerts.forEach(a=>{
                const type = a.type || '-';
                const cat = a.category || '-';
                const msg = a.message || '';
                const ts = a.timestamp || '';
                const sevBadge = (a.severity === 'critical') ? 'bg-danger' : 'bg-warning';
                html += `<div class="alert-item"><div class="d-flex justify-content-between align-items-center"><div><div><span class="badge ${sevBadge} me-2">${type}</span><strong>${cat}</strong></div><div class="text-muted mt-1">${msg}</div></div><div class="text-muted small">${ts}</div></div></div>`;
            });
            box.innerHTML = html;
        }
    </script>
    
    <!-- 在页面底部加载外部脚本 -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js" crossorigin="anonymous"></script>
    <script src="https://cdn.jsdelivr.net/npm/axios@1.6.0/dist/axios.min.js" crossorigin="anonymous"></script>
</body>
</html>
        """

    @app.get("/reports", response_class=HTMLResponse)
    def reports():
        """重定向到新前端巡检报告页面"""
        return FileResponse("frontend_new/pages/reports.html")

    @app.get("/server-resources", response_class=HTMLResponse)
    def server_resources_page() -> str:
        """重定向到新前端服务器资源页面"""
        return FileResponse("frontend_new/pages/server-resources.html")

    @app.get("/server-detail", response_class=HTMLResponse)
    def server_detail_page() -> str:
        """重定向到新前端服务器详情页面"""
        return FileResponse("frontend_new/pages/server-detail.html")

    @app.get("/api/log-messages")
    def get_log_messages(
        hours: int = Query(1, ge=1, le=24, description="查询最近N小时的日志"),
        category: Optional[str] = Query(None, description="按错误类别过滤"),
        severity: Optional[str] = Query(None, description="按严重程度过滤: critical, warning, info"),
        instance: Optional[str] = Query(None, description="按实例名过滤"),
        host: Optional[str] = Query(None, description="按主机名过滤"),
        search: Optional[str] = Query(None, description="在message中搜索关键词"),
        limit: int = Query(100, ge=1, le=1000, description="返回记录数量限制"),
        page: int = Query(1, ge=1, description="分页页码，从1开始"),
        page_size: int = Query(20, ge=1, le=100, description="分页大小")
    ) -> Dict[str, Any]:
        """获取详细的日志message信息，支持分类过滤和搜索。"""
        try:
            analyzer = LogAnalyzer()
            if not analyzer.es_client:
                raise HTTPException(status_code=503, detail="Elasticsearch 不可用")
            
            # 构建ES查询
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"range": {"@timestamp": {"gte": f"now-{hours}h"}}},
                            {"exists": {"field": analyzer.es_field}}
                        ],
                        "should": [
                            {"match": {analyzer.es_field: "error"}},
                            {"match": {analyzer.es_field: "exception"}},
                            {"match": {analyzer.es_field: "failed"}},
                            {"match": {analyzer.es_field: "failure"}}
                        ],
                        "minimum_should_match": 1
                    }
                },
                "sort": [{"@timestamp": {"order": "desc"}}],
                "size": limit
            }
            
            # 添加过滤条件
            if category or severity or instance or host or search:
                filter_conditions = []
                
                if category:
                    filter_conditions.append({"match": {analyzer.es_field: category}})
                
                if instance:
                    filter_conditions.append({"term": {"instance.keyword": instance}})
                
                if host:
                    filter_conditions.append({"term": {"host.keyword": host}})
                
                if search:
                    filter_conditions.append({"match": {analyzer.es_field: search}})
                
                if filter_conditions:
                    query["query"]["bool"]["filter"] = filter_conditions
            
            # 执行ES查询
            response = analyzer.es_client.search(
                index=analyzer.es_index_pattern,
                body=query,
                request_timeout=30
            )
            
            # 处理结果
            logs = []
            total_hits = response.get("hits", {}).get("total", {}).get("value", 0)
            
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                message = source.get(analyzer.es_field, "")
                
                # 对每条日志进行分类
                category_result, severity_result = analyzer.classify_error(message)
                
                # 如果指定了严重程度过滤，进行过滤
                if severity and severity_result != severity:
                    continue
                
                log_entry = {
                    "id": hit.get("_id"),
                    "timestamp": source.get("@timestamp"),
                    "message": message,
                    "category": category_result,
                    "severity": severity_result,
                    "level": source.get("level", "error"),
                    "logger": source.get("logger", ""),
                    "thread": source.get("thread", ""),
                    "host": source.get("host", ""),
                    "instance": source.get("instance", ""),
                    "tags": source.get("tags", []),
                    "score": hit.get("_score", 0)
                }
                logs.append(log_entry)
            
            # 分页处理
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_logs = logs[start_idx:end_idx]
            
            # 统计信息
            category_stats = {}
            severity_stats = {}
            instance_stats = {}
            
            for log in logs:
                # 分类统计
                cat = log["category"]
                category_stats[cat] = category_stats.get(cat, 0) + 1
                
                # 严重程度统计
                sev = log["severity"]
                severity_stats[sev] = severity_stats.get(sev, 0) + 1
                
                # 实例统计
                inst = log["instance"]
                instance_stats[inst] = instance_stats.get(inst, 0) + 1
            
            return {
                "logs": paginated_logs,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": len(logs),
                    "total_hits": total_hits,
                    "pages": (len(logs) + page_size - 1) // page_size
                },
                "statistics": {
                    "category_distribution": category_stats,
                    "severity_distribution": severity_stats,
                    "instance_distribution": instance_stats
                },
                "filters": {
                    "hours": hours,
                    "category": category,
                    "severity": severity,
                    "instance": instance,
                    "host": host,
                    "search": search
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取日志message详情失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取日志message详情失败: {e}")

    @app.get("/api/log-categories")
    def get_log_categories(
        hours: int = Query(24, ge=1, le=168, description="分析最近N小时的日志分类"),
        include_details: bool = Query(False, description="是否包含每个分类的详细示例")
    ) -> Dict[str, Any]:
        """获取日志分类统计和详细信息。"""
        try:
            analyzer = LogAnalyzer()
            if not analyzer.es_client:
                raise HTTPException(status_code=503, detail="Elasticsearch 不可用")
            
            # 收集日志
            logs = analyzer.collect_logs(hours=hours)
            classified = analyzer.classify_errors(logs)
            
            # 分类统计
            category_stats = {}
            for log in classified:
                category = log["category"]
                if category not in category_stats:
                    category_stats[category] = {
                        "count": 0,
                        "severity_breakdown": {},
                        "instances": set(),
                        "examples": []
                    }
                
                stats = category_stats[category]
                stats["count"] += 1
                
                # 严重程度分布
                severity = log["severity"]
                stats["severity_breakdown"][severity] = stats["severity_breakdown"].get(severity, 0) + 1
                
                # 实例分布
                stats["instances"].add(log["instance"])
                
                # 示例消息（最多保留5个）
                if include_details and len(stats["examples"]) < 5:
                    stats["examples"].append({
                        "message": log["message"][:200] + "..." if len(log["message"]) > 200 else log["message"],
                        "timestamp": log["timestamp"],
                        "instance": log["instance"],
                        "severity": log["severity"]
                    })
            
            # 转换为可序列化的格式
            result = {}
            for category, stats in category_stats.items():
                result[category] = {
                    "count": stats["count"],
                    "percentage": round(stats["count"] / len(classified) * 100, 2) if classified else 0,
                    "severity_breakdown": stats["severity_breakdown"],
                    "instance_count": len(stats["instances"]),
                    "instances": list(stats["instances"])[:10],  # 最多显示10个实例
                    "examples": stats["examples"] if include_details else []
                }
            
            # 按数量排序
            sorted_categories = sorted(result.items(), key=lambda x: x[1]["count"], reverse=True)
            
            return {
                "total_logs": len(classified),
                "time_range": f"最近{hours}小时",
                "categories": dict(sorted_categories),
                "summary": {
                    "total_categories": len(result),
                    "most_common_category": sorted_categories[0][0] if sorted_categories else None,
                    "critical_count": sum(1 for log in classified if log["severity"] == "critical"),
                    "warning_count": sum(1 for log in classified if log["severity"] == "warning"),
                    "info_count": sum(1 for log in classified if log["severity"] == "info")
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取日志分类统计失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取日志分类统计失败: {e}")

    @app.get("/api/log-search")
    def search_logs(
        q: str = Query(..., description="搜索关键词"),
        hours: int = Query(24, ge=1, le=168, description="搜索最近N小时的日志"),
        highlight: bool = Query(True, description="是否高亮显示匹配内容"),
        limit: int = Query(50, ge=1, le=200, description="返回记录数量限制")
    ) -> Dict[str, Any]:
        """全文搜索日志message内容。"""
        try:
            analyzer = LogAnalyzer()
            if not analyzer.es_client:
                raise HTTPException(status_code=503, detail="Elasticsearch 不可用")
            
            # 构建搜索查询
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"range": {"@timestamp": {"gte": f"now-{hours}h"}}},
                            {
                                "multi_match": {
                                    "query": q,
                                    "fields": [analyzer.es_field, "logger", "host", "instance"],
                                    "type": "best_fields",
                                    "fuzziness": "AUTO"
                                }
                            }
                        ]
                    }
                },
                "sort": [{"_score": {"order": "desc"}}, {"@timestamp": {"order": "desc"}}],
                "size": limit
            }
            
            # 添加高亮
            if highlight:
                query["highlight"] = {
                    "fields": {
                        analyzer.es_field: {
                            "pre_tags": ["<mark>"],
                            "post_tags": ["</mark>"],
                            "fragment_size": 200,
                            "number_of_fragments": 3
                        }
                    }
                }
            
            # 执行搜索
            response = analyzer.es_client.search(
                index=analyzer.es_index_pattern,
                body=query,
                request_timeout=30
            )
            
            # 处理结果
            results = []
            total_hits = response.get("hits", {}).get("total", {}).get("value", 0)
            
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                message = source.get(analyzer.es_field, "")
                
                # 分类
                category, severity = analyzer.classify_error(message)
                
                result = {
                    "id": hit.get("_id"),
                    "score": hit.get("_score", 0),
                    "timestamp": source.get("@timestamp"),
                    "message": message,
                    "category": category,
                    "severity": severity,
                    "level": source.get("level", "error"),
                    "logger": source.get("logger", ""),
                    "host": source.get("host", ""),
                    "instance": source.get("instance", ""),
                    "highlight": hit.get("highlight", {}) if highlight else {}
                }
                results.append(result)
            
            return {
                "query": q,
                "results": results,
                "total_hits": total_hits,
                "time_range": f"最近{hours}小时",
                "search_stats": {
                    "query_time_ms": response.get("took", 0),
                    "max_score": response.get("hits", {}).get("max_score", 0)
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"搜索日志失败: {e}")
            raise HTTPException(status_code=500, detail=f"搜索日志失败: {e}")

    @app.get("/api/log-analysis-detail")
    def get_log_analysis_detail(
        hours: int = Query(1, ge=1, le=24, description="分析最近N小时的日志"),
        category: Optional[str] = Query(None, description="按错误类别过滤"),
        severity: Optional[str] = Query(None, description="按严重程度过滤"),
        include_suggestions: bool = Query(True, description="是否包含处理建议"),
        limit: int = Query(100, ge=1, le=500, description="返回记录数量限制")
    ) -> Dict[str, Any]:
        """获取详细的日志分析结果，包含智能分类和处理建议。"""
        try:
            analyzer = LogAnalyzer()
            if not analyzer.es_client:
                raise HTTPException(status_code=503, detail="Elasticsearch 不可用")
            
            # 收集日志
            logs = analyzer.collect_logs(hours=hours)
            
            # 详细分类分析
            detailed_analysis = []
            category_summary = {}
            severity_summary = {}
            
            for log in logs:
                # 使用高级分类
                context = {
                    "logger": log.get("logger", ""),
                    "host": log.get("host", ""),
                    "instance": log.get("instance", ""),
                    "level": log.get("level", "error")
                }
                
                classification = analyzer.classify_error_with_context(log.get("message", ""), context)
                
                # 应用过滤条件
                if category and classification["category"] != category:
                    continue
                if severity and classification["severity"] != severity:
                    continue
                
                # 构建详细分析结果
                analysis_item = {
                    "id": log.get("id"),
                    "timestamp": log.get("timestamp"),
                    "message": log.get("message", ""),
                    "classification": classification,
                    "context": {
                        "logger": log.get("logger", ""),
                        "host": log.get("host", ""),
                        "instance": log.get("instance", ""),
                        "level": log.get("level", "error"),
                        "thread": log.get("thread", ""),
                        "tags": log.get("tags", [])
                    }
                }
                
                detailed_analysis.append(analysis_item)
                
                # 统计分类信息
                cat = classification["category"]
                sev = classification["severity"]
                
                if cat not in category_summary:
                    category_summary[cat] = {
                        "count": 0,
                        "severity_breakdown": {},
                        "instances": set(),
                        "hosts": set(),
                        "confidence_avg": 0.0
                    }
                
                if sev not in severity_summary:
                    severity_summary[sev] = {
                        "count": 0,
                        "categories": set(),
                        "instances": set()
                    }
                
                # 更新统计
                category_summary[cat]["count"] += 1
                category_summary[cat]["severity_breakdown"][sev] = category_summary[cat]["severity_breakdown"].get(sev, 0) + 1
                category_summary[cat]["instances"].add(log.get("instance", "unknown"))
                category_summary[cat]["hosts"].add(log.get("host", "unknown"))
                category_summary[cat]["confidence_avg"] = (
                    (category_summary[cat]["confidence_avg"] * (category_summary[cat]["count"] - 1) + classification["confidence"]) 
                    / category_summary[cat]["count"]
                )
                
                severity_summary[sev]["count"] += 1
                severity_summary[sev]["categories"].add(cat)
                severity_summary[sev]["instances"].add(log.get("instance", "unknown"))
            
            # 限制返回数量
            detailed_analysis = detailed_analysis[:limit]
            
            # 处理建议汇总
            suggestions_summary = {}
            if include_suggestions:
                for item in detailed_analysis:
                    category = item["classification"]["category"]
                    severity = item["classification"]["severity"]
                    suggestions = item["classification"].get("suggested_actions", [])
                    
                    key = f"{category}_{severity}"
                    if key not in suggestions_summary:
                        suggestions_summary[key] = {
                            "category": category,
                            "severity": severity,
                            "suggestions": suggestions,
                            "count": 0
                        }
                    suggestions_summary[key]["count"] += 1
            
            # 转换为可序列化的格式
            for cat, summary in category_summary.items():
                summary["instances"] = list(summary["instances"])
                summary["hosts"] = list(summary["hosts"])
                summary["confidence_avg"] = round(summary["confidence_avg"], 2)
            
            for sev, summary in severity_summary.items():
                summary["categories"] = list(summary["categories"])
                summary["instances"] = list(summary["instances"])
            
            return {
                "analysis": {
                    "total_logs": len(logs),
                    "filtered_logs": len(detailed_analysis),
                    "time_range": f"最近{hours}小时",
                    "analysis_timestamp": datetime.now(timezone.utc).isoformat()
                },
                "detailed_results": detailed_analysis,
                "category_summary": category_summary,
                "severity_summary": severity_summary,
                "suggestions_summary": suggestions_summary,
                "filters": {
                    "hours": hours,
                    "category": category,
                    "severity": severity,
                    "include_suggestions": include_suggestions
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取详细日志分析失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取详细日志分析失败: {e}")

    @app.get("/api/log-patterns")
    def get_log_patterns(
        hours: int = Query(24, ge=1, le=168, description="分析最近N小时的日志模式"),
        min_frequency: int = Query(3, ge=1, description="最小出现频率")
    ) -> Dict[str, Any]:
        """分析日志中的重复模式，帮助发现系统性问题。"""
        try:
            analyzer = LogAnalyzer()
            if not analyzer.es_client:
                raise HTTPException(status_code=503, detail="Elasticsearch 不可用")
            
            # 收集日志
            logs = analyzer.collect_logs(hours=hours)
            
            # 提取消息模式
            message_patterns = {}
            for log in logs:
                message = log.get("message", "")
                if not message:
                    continue
                
                # 简单的模式提取（可以进一步优化）
                # 移除时间戳、数字等变量部分
                pattern = re.sub(r'\d+', 'N', message)
                pattern = re.sub(r'[0-9a-fA-F]{8,}', 'UUID', pattern)  # UUID
                pattern = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', 'IP', pattern)  # IP地址
                pattern = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 'EMAIL', pattern)  # 邮箱
                
                if pattern not in message_patterns:
                    message_patterns[pattern] = {
                        "count": 0,
                        "examples": [],
                        "instances": set(),
                        "hosts": set(),
                        "categories": set(),
                        "severities": set()
                    }
                
                pattern_info = message_patterns[pattern]
                pattern_info["count"] += 1
                pattern_info["instances"].add(log.get("instance", "unknown"))
                pattern_info["hosts"].add(log.get("host", "unknown"))
                
                # 分类
                category, severity = analyzer.classify_error(message)
                pattern_info["categories"].add(category)
                pattern_info["severities"].add(severity)
                
                # 保存示例（最多5个）
                if len(pattern_info["examples"]) < 5:
                    pattern_info["examples"].append({
                        "message": message[:200] + "..." if len(message) > 200 else message,
                        "timestamp": log.get("timestamp"),
                        "instance": log.get("instance", ""),
                        "category": category,
                        "severity": severity
                    })
            
            # 过滤低频模式
            frequent_patterns = {
                pattern: info for pattern, info in message_patterns.items()
                if info["count"] >= min_frequency
            }
            
            # 转换为可序列化的格式
            for pattern, info in frequent_patterns.items():
                info["instances"] = list(info["instances"])
                info["hosts"] = list(info["hosts"])
                info["categories"] = list(info["categories"])
                info["severities"] = list(info["severities"])
            
            # 按频率排序
            sorted_patterns = sorted(frequent_patterns.items(), key=lambda x: x[1]["count"], reverse=True)
            
            return {
                "patterns": dict(sorted_patterns),
                "summary": {
                    "total_patterns": len(frequent_patterns),
                    "total_logs": len(logs),
                    "min_frequency": min_frequency,
                    "time_range": f"最近{hours}小时"
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"分析日志模式失败: {e}")
            raise HTTPException(status_code=500, detail=f"分析日志模式失败: {e}")

    @app.get("/api/log-recent-analysis")
    def get_log_recent_analysis(
        minutes: int = Query(1, ge=1, le=60, description="分析最近N分钟的日志，默认1分钟"),
        include_details: bool = Query(True, description="是否包含详细错误信息"),
        refresh: bool = Query(False, description="是否绕过缓存强制刷新")
    ) -> Dict[str, Any]:
        """获取最近N分钟的日志分析结果，包含中文业务类别提取和错误分析。"""
        try:
            analyzer = LogAnalyzer()
            if not analyzer.es_client:
                raise HTTPException(status_code=503, detail="Elasticsearch 不可用")

            cache_key = f"log_recent_analysis:{minutes}:{include_details}"
            if not refresh:
                cached = REDIS_CACHE.get(cache_key)
                if cached is not None:
                    return cached

            # 分析最近日志
            analysis_result = analyzer.analyze_recent_logs(minutes)

            # 如果不包含详细信息，移除recent_errors
            if not include_details:
                analysis_result.pop("recent_errors", None)

            # 空结果短TTL，避免长时间缓存空集；非空结果较长TTL
            ttl_seconds = 5 if (analysis_result.get("total_logs", 0) == 0) else (min(30, minutes * 30) if minutes <= 10 else 300)
            try:
                REDIS_CACHE.set_with_ttl(cache_key, analysis_result, ttl_seconds)
            except Exception:
                REDIS_CACHE.set(cache_key, analysis_result)

            return analysis_result

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取最近日志分析失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取最近日志分析失败: {e}")

    @app.get("/api/log-search-by-type")
    def search_logs_by_error_type(
        type: str = Query(..., min_length=1, description="中文错误类型，支持关键字匹配"),
        minutes: int = Query(10, ge=1, le=60, description="检索最近N分钟的日志"),
        limit: int = Query(200, ge=1, le=1000, description="返回结果上限")
    ) -> Dict[str, Any]:
        """按中文错误类型检索最近N分钟内的清洗后错误日志。"""
        try:
            analyzer = LogAnalyzer()
            if not analyzer.es_client:
                raise HTTPException(status_code=503, detail="Elasticsearch 不可用")

            # 收集并清洗日志（不截断为recent_errors）
            raw_logs = analyzer.collect_recent_logs(minutes)
            cleaned_logs = analyzer.clean_log_data(raw_logs)

            keyword = (type or "").strip()
            if not keyword:
                return {"query": {"type": type, "minutes": minutes, "limit": limit}, "total": 0, "logs": []}

            def match(log: Dict[str, Any]) -> bool:
                ea = log.get("error_analysis", {}) or {}
                et = str(ea.get("error_type", "")).strip()
                cet = str(log.get("chinese_error_type", "")).strip()
                # 关键字子串匹配，优先中文错误类型
                source = cet or et
                return keyword in source

            matched = [
                {
                    "id": log.get("id"),
                    "timestamp": log.get("timestamp"),
                    "instance": log.get("instance"),
                    "host": log.get("host"),
                    "logger": log.get("logger"),
                    "business_analysis": log.get("business_analysis", {}),
                    "error_analysis": log.get("error_analysis", {}),
                    "core_message": log.get("core_message"),
                    "message": log.get("message")
                }
                for log in cleaned_logs if match(log)
            ]

            return {
                "query": {"type": type, "minutes": minutes, "limit": limit},
                "total": len(matched),
                "logs": matched[:limit]
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"错误类型检索失败: {e}")
            raise HTTPException(status_code=500, detail=f"检索失败: {e}")

    @app.get("/api/log-classification-test")
    def get_log_classification_test(
        minutes: int = Query(1, ge=1, le=60, description="测试时间范围，默认1分钟")
    ) -> Dict[str, Any]:
        """测试日志归类功能，返回详细的归类统计结果。"""
        try:
            analyzer = LogAnalyzer()
            
            # 使用新的归类统计功能
            try:
                # 获取归类统计
                classification_stats = analyzer.get_classification_stats(hours=minutes)
                if not classification_stats:
                    return {
                        "status": "warning",
                        "message": "未获取到归类统计数据",
                        "data": {}
                    }
                
                # 获取格式化报告
                formatted_report = analyzer.get_formatted_classification_report(hours=minutes)
                if "error" in formatted_report:
                    return {
                        "status": "warning",
                        "message": formatted_report["error"],
                        "data": classification_stats
                    }
                
                return {
                    "status": "success",
                    "message": "日志归类功能测试成功",
                    "data": {
                        "raw_stats": classification_stats,
                        "formatted_report": formatted_report,
                        "summary": {
                            "total_logs": sum(classification_stats.get("level_distribution", {}).values()),
                            "total_errors": sum(classification_stats.get("error_categories", {}).values()),
                            "business_modules_count": len(classification_stats.get("business_modules", {})),
                            "instances_count": len(classification_stats.get("instance_distribution", {})),
                            "generated_at": classification_stats.get("generated_at", ""),
                            "time_range": classification_stats.get("time_range", "")
                        }
                    }
                }
                
            except Exception as e:
                logger.error(f"日志归类功能测试失败: {e}")
                return {
                    "status": "error",
                    "message": f"日志归类功能测试失败: {str(e)}",
                    "data": {}
                }
                
        except Exception as e:
            logger.error(f"日志归类测试接口异常: {e}")
            raise HTTPException(status_code=500, detail=f"日志归类测试失败: {str(e)}")

    @app.get("/api/log-dashboard-data")
    def get_log_dashboard_data(
        hours: int = Query(24, ge=1, le=168, description="获取时间范围，默认24小时")
    ) -> Dict[str, Any]:
        """获取日志仪表板数据，包含完整的归类统计和图表数据。"""
        try:
            analyzer = LogAnalyzer()
            
            # 获取仪表板摘要数据
            dashboard_data = analyzer.get_dashboard_summary_data(hours=hours)
            
            if "error" in dashboard_data:
                return {
                    "status": "error",
                    "message": dashboard_data["error"],
                    "data": {}
                }
            
            return {
                "status": "success",
                "message": "获取仪表板数据成功",
                "data": dashboard_data
            }
            
        except Exception as e:
            logger.error(f"获取仪表板数据失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取仪表板数据失败: {str(e)}")

    @app.get("/log-types", response_class=HTMLResponse)
    def log_types_page():
        """重定向到新前端日志类型页面"""
        return FileResponse("frontend_new/pages/log-types.html")
    
    # 新前端页面路由
    @app.get("/new", response_class=HTMLResponse)
    def new_index_page():
        """新前端主仪表板页面"""
        return FileResponse("frontend_new/pages/index.html")
    
    @app.get("/new/reports", response_class=HTMLResponse)
    def new_reports_page():
        """新前端巡检报告页面"""
        return FileResponse("frontend_new/pages/reports.html")
    
    @app.get("/new/server-resources", response_class=HTMLResponse)
    def new_server_resources_page():
        """新前端服务器资源页面"""
        return FileResponse("frontend_new/pages/server-resources.html")
    
    @app.get("/new/server-detail", response_class=HTMLResponse)
    def new_server_detail_page():
        """新前端服务器详情页面"""
        return FileResponse("frontend_new/pages/server-detail.html")
    
    @app.get("/new/log-types", response_class=HTMLResponse)
    def new_log_types_page():
        """新前端日志类型分析页面"""
        return FileResponse("frontend_new/pages/log-types.html")
    
    @app.get("/test", response_class=HTMLResponse)
    def test_page():
        """API测试页面"""
        return FileResponse("test_page.html")
    
    @app.post("/api/start-inspection")
    def start_inspection() -> Dict[str, Any]:
        """启动巡检功能，执行检查并将结果存储到Redis"""
        try:
            from app.services.inspection import InspectionEngine
            import json
            from datetime import datetime
            
            # 创建巡检引擎实例
            engine = InspectionEngine()
            
            # 执行巡检
            logger.info("开始执行手动巡检...")
            inspection_result = engine.run_comprehensive_inspection()
            results = inspection_result.get('results', [])
            
            if not results:
                logger.warning("巡检未返回任何结果")
                return {"success": False, "message": "巡检未返回任何结果"}
            
            # 准备存储到Redis的数据
            inspection_data = {
                "timestamp": datetime.now().isoformat(),
                "total_checks": len(results),
                "results": []
            }
            
            # 处理巡检结果并统计
            success_count = 0
            warning_count = 0
            error_count = 0
            
            for result in results:
                # 如果是InspectionResult对象，转换为字典
                if hasattr(result, 'check_name'):
                    result_data = {
                        "check_name": result.check_name,
                        "status": result.status,
                        "detail": result.detail,
                        "severity": result.severity,
                        "category": result.category,
                        "timestamp": result.timestamp,
                        "score": result.score,
                        "instance": result.instance or "",
                        "value": result.value or "",
                        "labels": result.labels or {}
                    }
                    status = result.status
                else:
                    # 如果是字典格式
                    result_data = {
                        "check_name": result.get("check_name", "未知检查"),
                        "status": result.get("status", "unknown"),
                        "detail": result.get("detail", ""),
                        "severity": result.get("severity", "info"),
                        "category": result.get("category", "system"),
                        "timestamp": result.get("ts", datetime.now().isoformat()),
                        "score": result.get("score", 0),
                        "instance": result.get("instance", ""),
                        "value": result.get("value", ""),
                        "labels": result.get("labels", {})
                    }
                    status = result.get("status", "unknown")
                
                inspection_data["results"].append(result_data)
                
                # 统计结果
                if status == "ok":
                    success_count += 1
                elif status == "warning":
                    warning_count += 1
                elif status == "error" or status == "alert":
                    error_count += 1
            
            inspection_data.update({
                "success_count": success_count,
                "warning_count": warning_count, 
                "error_count": error_count,
                "summary": f"成功: {success_count}, 警告: {warning_count}, 错误: {error_count}"
            })
            
            # 存储到Redis
            try:
                # 存储最新的巡检结果
                REDIS_CACHE.set_with_ttl("latest_inspection_result", inspection_data, 86400)  # 保存24小时
                
                # 存储到历史记录（使用时间戳作为key）
                history_key = f"inspection_history:{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                REDIS_CACHE.set_with_ttl(history_key, inspection_data, 604800)  # 保存7天
                
                logger.info(f"巡检结果已存储到Redis，共检查{len(results)}项")
                
            except Exception as e:
                logger.error(f"存储巡检结果到Redis失败: {e}")
                return {"success": False, "message": f"存储结果失败: {str(e)}"}
            
            return {
                "success": True,
                "message": "巡检完成并已保存结果",
                "data": {
                    "total_checks": len(results),
                    "success_count": success_count,
                    "warning_count": warning_count,
                    "error_count": error_count,
                    "timestamp": inspection_data["timestamp"]
                }
            }
            
        except Exception as e:
            logger.error(f"启动巡检失败: {e}")
            return {"success": False, "message": f"巡检执行失败: {str(e)}"}
    
    return app
