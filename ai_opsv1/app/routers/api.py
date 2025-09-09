from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json
import logging
import threading
import time
import re

from fastapi import APIRouter, Query, HTTPException, Response
from fastapi.responses import HTMLResponse, FileResponse

from app.models.db import (
    get_connection,
    get_health_thresholds,
    get_inspection_summaries,
    get_inspection_stats,
)
from app.services.inspection import InspectionEngine, get_recent_inspections, get_health_trends
from app.services.log_analyzer import LogAnalyzer
from app.core.config import REDIS_CACHE, SETTINGS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])

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

@router.get("/health")
def health_check() -> Dict[str, Any]:
    """健康检查接口"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }

@router.get("/server-resources")
def get_server_resources_api(
    response: Response,
    refresh: bool = Query(False, description="是否强制刷新，忽略Redis缓存"),
    quick: bool = Query(True, description="快速模式：仅返回缓存，不从Prometheus拉取"),
    prefetch: bool = Query(True, description="后台预取：异步拉取以填充缓存（如果缓存缺失）")
) -> Dict[str, Any]:
    """获取服务器资源信息"""
    try:
        response.headers["Cache-Control"] = "public, max-age=30"
        
        # 创建巡检引擎
        engine = InspectionEngine()
        
        # 获取服务器资源
        resources = engine.get_server_resources(refresh=refresh)
        
        # 检查缓存状态
        cache_status = "hit" if not refresh else "miss"
        
        return {
            "data": resources,
            "cache": cache_status,
            "timestamp": datetime.now().isoformat(),
            "count": len(resources) if resources else 0,
            "quick": False,
        }
    except Exception as e:
        logger.error(f"获取服务器资源失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取服务器资源失败: {e}")

@router.get("/alerts")
def get_alerts_api(response: Response) -> Dict[str, Any]:
    """获取增强监控当前告警（直接从Redis中读取）"""
    try:
        response.headers["Cache-Control"] = "public, max-age=15"
        alerts = get_cached_alerts()  # 已由增强监控模块写入Redis
        return {"alerts": alerts, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"获取告警失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取告警失败: {e}")

@router.get("/inspection-summary")
def get_inspection_summary_api(
    response: Response,
    hours: int = Query(24, description="查询最近几小时的巡检摘要")
) -> Dict[str, Any]:
    """获取巡检摘要"""
    try:
        response.headers["Cache-Control"] = "public, max-age=60"
        
        # 获取巡检摘要
        summaries = get_inspection_summaries(hours=hours)
        
        return {
            "summaries": summaries,
            "timestamp": datetime.now().isoformat(),
            "hours": hours
        }
    except Exception as e:
        logger.error(f"获取巡检摘要失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取巡检摘要失败: {e}")

@router.get("/health-trends")
def get_health_trends_api(
    response: Response,
    hours: int = Query(24, description="查询最近几小时的健康趋势")
) -> Dict[str, Any]:
    """获取健康趋势"""
    try:
        response.headers["Cache-Control"] = "public, max-age=60"
        
        # 获取健康趋势
        trends = get_health_trends(hours=hours)
        
        return {
            "trends": trends,
            "timestamp": datetime.now().isoformat(),
            "hours": hours
        }
    except Exception as e:
        logger.error(f"获取健康趋势失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取健康趋势失败: {e}")

@router.get("/log-stats")
def get_log_stats_api(
    response: Response,
    hours: int = Query(1, description="查询最近几小时的日志统计")
) -> Dict[str, Any]:
    """获取日志统计信息"""
    try:
        response.headers["Cache-Control"] = "public, max-age=30"
        
        # 创建日志分析器
        analyzer = LogAnalyzer()
        
        # 获取日志统计
        stats = analyzer.get_log_statistics(hours=hours)
        
        return {
            "stats": stats,
            "timestamp": datetime.now().isoformat(),
            "hours": hours
        }
    except Exception as e:
        logger.error(f"获取日志统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日志统计失败: {e}")

# ---------------- 日志趋势（每分钟）----------------
@router.get("/log-trend-minutely")
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
        labels: List[str] = []
        values: List[int] = []
        for b in buckets:
            ts = b.get("key_as_string") or b.get("key")
            cnt = int(b.get("doc_count", 0))
            if isinstance(ts, (int, float)):
                from datetime import datetime, timezone
                ts = datetime.fromtimestamp(ts/1000.0, tz=timezone.utc).isoformat()
            labels.append(ts)
            values.append(cnt)
        result = {"labels": labels, "values": values}
        try:
            REDIS_CACHE.set_with_ttl(cache_key, result, 60)
        except Exception:
            pass
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日志分钟趋势失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日志分钟趋势失败: {e}")

# ---------------- 手动指标查询（Pod/Node/Cluster/Disk）----------------
@router.get("/manual/cluster-load")
def manual_cluster_load() -> Dict[str, Any]:
    """集群负载（CPU/内存使用率聚合）。"""
    try:
        from app.services.prom_client import PrometheusClient
        prom = PrometheusClient()
        # CPU 使用率（按实例聚合后再取平均）
        cpu_expr = "avg(100 - (avg by (instance) (irate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100))"
        mem_expr = "avg((1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100)"
        cpu = prom.instant(cpu_expr, use_cache=False)
        mem = prom.instant(mem_expr, use_cache=False)
        def _scalar(d):
            try:
                v = d.get("data", {}).get("result", [])
                if v:
                    return float(v[0]["value"][1])
            except Exception:
                return None
            return None
        return {
            "cpu_percent": _scalar(cpu),
            "mem_percent": _scalar(mem),
            "expr": {"cpu": cpu_expr, "mem": mem_expr},
            "ts": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"手动查询集群负载失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/manual/node-load")
def manual_node_load(node: str) -> Dict[str, Any]:
    """指定节点负载（CPU/LoadAvg/内存）。参数 node 形如 192.168.x.x:9100。"""
    try:
        from app.services.prom_client import PrometheusClient
        prom = PrometheusClient()
        cpu = f"100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode=\"idle\",instance=\"{node}\"}}[5m])) * 100)"
        load1 = f"node_load1{{instance=\"{node}\"}}"
        load5 = f"node_load5{{instance=\"{node}\"}}"
        load15 = f"node_load15{{instance=\"{node}\"}}"
        mem_total = f"node_memory_MemTotal_bytes{{instance=\"{node}\"}}"
        mem_avail = f"node_memory_MemAvailable_bytes{{instance=\"{node}\"}}"
        def _scalar(prom_resp):
            try:
                r = prom_resp.get("data", {}).get("result", [])
                if r:
                    return float(r[0]["value"][1])
            except Exception:
                return None
            return None
        resp = {
            "cpu_percent": _scalar(prom.instant(cpu, use_cache=False)),
            "load1": _scalar(prom.instant(load1, use_cache=False)),
            "load5": _scalar(prom.instant(load5, use_cache=False)),
            "load15": _scalar(prom.instant(load15, use_cache=False)),
        }
        t = _scalar(prom.instant(mem_total, use_cache=False)) or 0.0
        a = _scalar(prom.instant(mem_avail, use_cache=False)) or 0.0
        mem_percent = ((t - a) / t * 100) if t > 0 else None
        resp.update({
            "memory_total_bytes": t,
            "memory_available_bytes": a,
            "memory_percent": mem_percent
        })
        resp["expr"] = {"cpu": cpu, "load1": load1, "load5": load5, "load15": load15}
        return resp
    except Exception as e:
        logger.error(f"手动查询节点负载失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/manual/pod-load")
def manual_pod_load(namespace: str, pod: str) -> Dict[str, Any]:
    """指定Pod负载（CPU/内存）。需要容器指标存在（如 container_cpu_usage_seconds_total）。"""
    try:
        from app.services.prom_client import PrometheusClient
        prom = PrometheusClient()
        cpu_expr = (
            f"sum(rate(container_cpu_usage_seconds_total{{namespace=\"{namespace}\",pod=\"{pod}\",image!=\"\"}}[5m])) * 100"
        )
        mem_expr = (
            f"sum(container_memory_working_set_bytes{{namespace=\"{namespace}\",pod=\"{pod}\",image!=\"\"}})"
        )
        cpu = prom.instant(cpu_expr, use_cache=False)
        mem = prom.instant(mem_expr, use_cache=False)
        def _scalar(d):
            try:
                v = d.get("data", {}).get("result", [])
                if v:
                    return float(v[0]["value"][1])
            except Exception:
                return None
            return None
        return {
            "cpu_percent": _scalar(cpu),
            "memory_bytes": _scalar(mem),
            "expr": {"cpu": cpu_expr, "mem": mem_expr}
        }
    except Exception as e:
        logger.error(f"手动查询Pod负载失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/manual/disk-remaining")
def manual_disk_remaining(node: str, mountpoint: str = "/") -> Dict[str, Any]:
    """指定节点挂载点磁盘剩余（百分比与字节）。node 同上。"""
    try:
        from app.services.prom_client import PrometheusClient
        prom = PrometheusClient()
        avail = f"node_filesystem_avail_bytes{{fstype!~\"tmpfs|fuse\",instance=\"{node}\",mountpoint=\"{mountpoint}\"}}"
        size = f"node_filesystem_size_bytes{{fstype!~\"tmpfs|fuse\",instance=\"{node}\",mountpoint=\"{mountpoint}\"}}"
        pct_expr = (
            f"(node_filesystem_avail_bytes{{fstype!~\"tmpfs|fuse\",instance=\"{node}\",mountpoint=\"{mountpoint}\"}} / "
            f"node_filesystem_size_bytes{{fstype!~\"tmpfs|fuse\",instance=\"{node}\",mountpoint=\"{mountpoint}\"}}) * 100"
        )
        def _scalar(d):
            try:
                v = d.get("data", {}).get("result", [])
                if v:
                    return float(v[0]["value"][1])
            except Exception:
                return None
            return None
        avail_v = _scalar(prom.instant(avail, use_cache=False))
        size_v = _scalar(prom.instant(size, use_cache=False))
        pct_v = _scalar(prom.instant(pct_expr, use_cache=False))
        return {
            "available_bytes": avail_v,
            "size_bytes": size_v,
            "available_percent": pct_v,
            "expr": {"available": avail, "size": size, "percent": pct_expr}
        }
    except Exception as e:
        logger.error(f"手动查询磁盘剩余失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
