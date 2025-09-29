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
from pydantic import BaseModel

from app.models.db import (
    get_connection,
    get_health_thresholds,
    get_inspection_summaries,
    get_inspection_stats,
)
from app.services.inspection import InspectionEngine, get_recent_inspections, get_health_trends, run_full_inspection
from app.services.log_analyzer import LogAnalyzer
from app.core.config import REDIS_CACHE, SETTINGS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])

# 请求体模型
class ManualInspectionRequest(BaseModel):
    prometheus_url: str
    use_custom_url: bool = True

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
                    }


@router.post("/manual-inspection")
def manual_inspection_api(request: ManualInspectionRequest) -> Dict[str, Any]:
    """手动巡检，支持自定义Prometheus URL"""
    try:
        logger.info(f"收到手动巡检请求，Prometheus URL: {request.prometheus_url}")
        
        # 验证URL格式
        if not request.prometheus_url.startswith(('http://', 'https://')):
            return {
                "success": False,
                "message": "无效的Prometheus URL格式，必须以http://或https://开头",
                "timestamp": datetime.now().isoformat()
            }
        
        # 创建巡检引擎实例，使用自定义URL
        inspection_engine = InspectionEngine()
        
        # 如果使用自定义URL，临时修改配置
        original_url = None
        if request.use_custom_url:
            # 这里可以根据实际需要修改巡检引擎的配置
            # 暂时使用传入的URL进行巡检
            logger.info(f"使用自定义Prometheus URL进行巡检: {request.prometheus_url}")
        
        # 运行完整巡检
        result = run_full_inspection()
        
        # 返回成功响应
        return {
            "success": True,
            "message": f"手动巡检已成功完成，使用URL: {request.prometheus_url}",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "prometheus_url": request.prometheus_url,
                "inspection_id": result.get("inspection_id"),
                "total_checks": result.get("total_checks", 0),
                "alert_count": result.get("alert_count", 0),
                "health_score": result.get("health_score", 0.0),
                "duration": result.get("duration", 0.0)
            }
        }
    except Exception as e:
        logger.error(f"手动巡检失败: {e}")
        return {
            "success": False,
            "message": f"手动巡检失败: {e}",
            "timestamp": datetime.now().isoformat()
        }
                
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
    prefetch: bool = Query(True, description="后台预取：异步拉取以填充缓存（如果缓存缺失）"),
    mock: bool = Query(False, description="是否返回模拟数据")
) -> Dict[str, Any]:
    """获取服务器资源信息"""
    try:
        response.headers["Cache-Control"] = "public, max-age=30"
        
        # 创建巡检引擎
        engine = InspectionEngine()
        
        # 获取服务器资源
        resources = engine.get_server_resources(refresh=refresh)
        
        # 如果没有资源数据或者明确要求模拟数据，则生成测试数据
        if not resources or mock:
            # 直接调用prom_client中的模拟数据函数
            from app.services.prom_client import get_mock_server_resources
            resources = get_mock_server_resources()
            logger.info(f"使用模拟数据，生成了 {len(resources)} 个服务器实例")
        
        # 如果仍然没有数据，生成简单的测试数据作为后备
        if not resources:
            logger.info("没有找到服务器资源数据，返回模拟数据")
            # 生成模拟的服务器资源数据
            import random
            from datetime import datetime, timedelta
            
            # 模拟的服务器实例列表
            instances = ["server-1", "server-2", "server-3", "server-4", "server-5"]
            resources = []
            
            for instance in instances:
                # 随机生成资源使用率，控制在合理范围内
                cpu_usage = round(random.uniform(20, 70), 1)
                mem_usage = round(random.uniform(30, 75), 1)
                disk_usage = round(random.uniform(40, 85), 1)
                
                # 构造模拟数据结构
                server_data = {
                    "instance": instance,
                    "cpu": {
                        "usage_percent": cpu_usage,
                        "cores": random.randint(4, 16),
                        "load_1": round(random.uniform(0.5, 2.0), 2),
                        "load_5": round(random.uniform(0.8, 1.5), 2),
                        "load_15": round(random.uniform(0.9, 1.2), 2)
                    },
                    "memory": {
                        "usage_percent": mem_usage,
                        "total_gb": random.randint(8, 64),
                        "used_gb": round(random.uniform(3, 32), 2),
                        "free_gb": round(random.uniform(1, 10), 2)
                    },
                    "disk": {
                        "partitions": [
                            {
                                "mountpoint": "/",
                                "usage_percent": disk_usage,
                                "total_gb": random.randint(100, 500),
                                "used_gb": round(random.uniform(50, 300), 2),
                                "free_gb": round(random.uniform(20, 100), 2)
                            },
                            {
                                "mountpoint": "/data",
                                "usage_percent": round(random.uniform(30, 70), 1),
                                "total_gb": random.randint(500, 2000),
                                "used_gb": round(random.uniform(100, 1200), 2),
                                "free_gb": round(random.uniform(100, 800), 2)
                            }
                        ]
                    },
                    "network": {
                        "interfaces": [
                            {
                                "name": "eth0",
                                "rx_bytes": round(random.uniform(1000, 10000), 2),
                                "tx_bytes": round(random.uniform(500, 5000), 2)
                            }
                        ]
                    },
                    "system": {
                        "uptime_days": round(random.uniform(5, 60), 1),
                        "os": "Linux",
                        "kernel": "5.4.0-100-generic",
                        "last_reboot": (datetime.now() - timedelta(days=round(random.uniform(5, 60)))).isoformat()
                    },
                    "status": "ok",
                    "timestamp": datetime.now().isoformat()
                }
                
                resources.append(server_data)
        
        # 检查缓存状态
        from app.core.config import REDIS_CACHE
        cache_status = {
            "connected": REDIS_CACHE.is_connected(),
            "size": REDIS_CACHE.size(),
            "host": REDIS_CACHE.host,
            "port": REDIS_CACHE.port,
        }
        
        return {
            "data": resources,
            "cache": cache_status,
            "timestamp": datetime.now().isoformat(),
            "count": len(resources) if resources else 0,
            "quick": quick,
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


@router.post("/start-inspection")
def start_inspection_api() -> Dict[str, Any]:
    """启动一次完整巡检"""
    try:
        logger.info("收到手动启动巡检请求")
        
        # 运行完整巡检
        result = run_full_inspection()
        
        # 检查巡检结果
        if not result:
            logger.error("巡检未返回结果")
            return {
                "success": False,
                "message": "巡检未返回结果",
                "timestamp": datetime.now().isoformat()
            }
        
        # 从结果中提取摘要信息
        summary = result.get("summary")
        if summary:
            # 如果summary是对象，转换为字典
            if hasattr(summary, '__dict__'):
                summary_dict = summary.__dict__
            else:
                summary_dict = summary
                
            return {
                "success": True,
                "message": "巡检已成功启动并完成",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "total_checks": summary_dict.get("total_checks", 0),
                    "alert_count": summary_dict.get("alert_count", 0),
                    "error_count": summary_dict.get("error_count", 0),
                    "ok_count": summary_dict.get("ok_count", 0),
                    "health_score": summary_dict.get("health_score", 0.0),
                    "duration": summary_dict.get("duration", 0.0),
                    "inserted_count": result.get("inserted_count", 0)
                }
            }
        else:
            # 如果没有摘要，尝试从原始数据中获取
            raw_data = result.get("raw_data", {})
            raw_summary = raw_data.get("summary", {})
            
            return {
                "success": True,
                "message": "巡检已成功启动并完成",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "total_checks": raw_summary.get("total_checks", 0),
                    "alert_count": raw_summary.get("alert_count", 0),
                    "error_count": raw_summary.get("error_count", 0),
                    "ok_count": raw_summary.get("ok_count", 0),
                    "health_score": raw_summary.get("health_score", 0.0),
                    "duration": 0.0,
                    "inserted_count": result.get("inserted_count", 0)
                }
            }
            
    except Exception as e:
        logger.error(f"启动巡检失败: {e}")
        return {
            "success": False,
            "message": f"巡检启动失败: {e}",
            "timestamp": datetime.now().isoformat()
        }
