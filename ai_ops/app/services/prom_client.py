from __future__ import annotations

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging
import asyncio
import concurrent.futures
import time
from functools import lru_cache
import threading
from collections import defaultdict

from app.core.config import SETTINGS
from app.utils.http_client import http_get
from app.models.db import get_health_thresholds

logger = logging.getLogger(__name__)


class PrometheusClient:
    def __init__(self, base_url: str | None = None, timeout: int | None = None, max_workers: int | None = None):
        self.base_url = (base_url or SETTINGS.prom_url).rstrip("/")
        # 使用配置默认值，便于通过环境变量控制
        self.timeout = timeout if timeout is not None else SETTINGS.prom_query_timeout
        self.max_workers = max_workers if max_workers is not None else SETTINGS.prom_max_workers
        self._session_cache = {}
        self._query_cache = {}
        self._cache_lock = threading.Lock()
        
        # 性能统计
        self.stats = {
            'total_queries': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'avg_response_time': 0.0,
            'total_response_time': 0.0
        }
        self._stats_lock = threading.Lock()

    def _update_stats(self, response_time: float, cache_hit: bool = False):
        """更新性能统计"""
        with self._stats_lock:
            self.stats['total_queries'] += 1
            self.stats['total_response_time'] += response_time
            self.stats['avg_response_time'] = self.stats['total_response_time'] / self.stats['total_queries']
            if cache_hit:
                self.stats['cache_hits'] += 1
            else:
                self.stats['cache_misses'] += 1

    def _get_cache_key(self, query: str, params: Dict[str, Any] = None) -> str:
        """生成缓存键"""
        if params:
            # 对参数进行排序以确保一致性
            sorted_params = sorted(params.items())
            param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
            return f"{query}:{param_str}"
        return query

    def _get_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """从缓存获取数据"""
        with self._cache_lock:
            if cache_key in self._query_cache:
                data, timestamp = self._query_cache[cache_key]
                # 缓存5分钟
                if time.time() - timestamp < 300:
                    return data
                else:
                    del self._query_cache[cache_key]
        return None

    def _set_cache(self, cache_key: str, data: Dict[str, Any]):
        """设置缓存"""
        with self._cache_lock:
            self._query_cache[cache_key] = (data, time.time())
            # 限制缓存大小
            if len(self._query_cache) > 1000:
                # 删除最旧的20%的缓存
                oldest_keys = sorted(self._query_cache.keys(), 
                                   key=lambda k: self._query_cache[k][1])[:200]
                for key in oldest_keys:
                    del self._query_cache[key]

    def instant(self, query: str, use_cache: bool = True) -> Dict[str, Any]:
        """执行即时查询（带缓存）"""
        cache_key = self._get_cache_key(query) if use_cache else None
        
        # 尝试从缓存获取
        if cache_key and use_cache:
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                self._update_stats(0.0, cache_hit=True)
                return cached_data

        # 执行查询
        start_time = time.time()
        try:
            status, data = http_get(f"{self.base_url}/api/v1/query", 
                                  params={"query": query}, 
                                  timeout=self.timeout)
            if status >= 300:
                raise RuntimeError(f"prom query failed: {status} {data}")
            
            response_time = time.time() - start_time
            self._update_stats(response_time, cache_hit=False)
            
            # 缓存结果
            if cache_key and use_cache:
                self._set_cache(cache_key, data)
            
            assert isinstance(data, dict)
            return data
            
        except Exception as e:
            response_time = time.time() - start_time
            self._update_stats(response_time, cache_hit=False)
            raise e

    def range_query(self, query: str, start: datetime, end: datetime, step: str = "60s") -> Dict[str, Any]:
        """执行范围查询"""
        params = {
            "query": query,
            "start": int(start.timestamp()),
            "end": int(end.timestamp()),
            "step": step,
        }
        
        cache_key = self._get_cache_key(query, params)
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            self._update_stats(0.0, cache_hit=True)
            return cached_data

        start_time = time.time()
        try:
            status, data = http_get(f"{self.base_url}/api/v1/query_range", 
                                  params=params, 
                                  timeout=self.timeout)
            if status >= 300:
                raise RuntimeError(f"prom range query failed: {status} {data}")
            
            response_time = time.time() - start_time
            self._update_stats(response_time, cache_hit=False)
            
            # 缓存结果
            self._set_cache(cache_key, data)
            
            assert isinstance(data, dict)
            return data
            
        except Exception as e:
            response_time = time.time() - start_time
            self._update_stats(response_time, cache_hit=False)
            raise e

    def batch_instant_queries(self, queries: List[str], use_cache: bool = True) -> List[Dict[str, Any]]:
        """批量执行即时查询（并发处理）"""
        if not queries:
            return []
        
        # 过滤出需要查询的查询（未缓存的）
        uncached_queries = []
        cached_results = []
        
        if use_cache:
            for i, query in enumerate(queries):
                cache_key = self._get_cache_key(query)
                cached_data = self._get_from_cache(cache_key)
                if cached_data:
                    cached_results.append((i, cached_data))
                    self._update_stats(0.0, cache_hit=True)
                else:
                    uncached_queries.append((i, query))
        else:
            uncached_queries = [(i, query) for i, query in enumerate(queries)]

        # 如果没有需要查询的，直接返回缓存结果
        if not uncached_queries:
            return [result for _, result in sorted(cached_results, key=lambda x: x[0])]

        # 并发执行查询
        results = [None] * len(queries)
        
        # 将缓存结果放入结果列表
        for i, result in cached_results:
            results[i] = result

        def execute_query(query_info):
            """执行单个查询"""
            try:
                return query_info[0], self.instant(query_info[1], use_cache=False)
            except Exception as e:
                logger.error(f"Query failed for {query_info[1]}: {e}")
                return query_info[0], {"error": str(e)}

        # 使用线程池并发执行
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_query = {executor.submit(execute_query, query_info): query_info 
                             for query_info in uncached_queries}
            
            for future in concurrent.futures.as_completed(future_to_query):
                try:
                    i, result = future.result()
                    results[i] = result
                except Exception as e:
                    logger.error(f"Query execution failed: {e}")
                    query_info = future_to_query[future]
                    results[query_info[0]] = {"error": str(e)}

        return results

    def get_metrics(self, metric_name: str) -> List[Dict[str, Any]]:
        """获取指定指标的所有实例"""
        query = f"{metric_name}"
        data = self.instant(query)
        return data.get("data", {}).get("result", [])

    def get_targets(self) -> Dict[str, Any]:
        """获取所有监控目标状态"""
        status, data = http_get(f"{self.base_url}/api/v1/targets", timeout=self.timeout)
        if status >= 300:
            raise RuntimeError(f"Failed to get targets: {status} {data}")
        return data

    def get_alerts(self) -> Dict[str, Any]:
        """获取所有告警"""
        status, data = http_get(f"{self.base_url}/api/v1/alerts", timeout=self.timeout)
        if status >= 300:
            raise RuntimeError(f"Failed to get alerts: {status} {data}")
        return data

    def get_metrics_batch(self, metric_names: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """批量获取多个指标"""
        queries = [f"{metric_name}" for metric_name in metric_names]
        results = self.batch_instant_queries(queries)
        
        batch_results = {}
        for i, metric_name in enumerate(metric_names):
            if i < len(results) and results[i] and "error" not in results[i]:
                batch_results[metric_name] = results[i].get("data", {}).get("result", [])
            else:
                batch_results[metric_name] = []
        
        return batch_results

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计信息"""
        with self._stats_lock:
            stats_copy = self.stats.copy()
        
        # 计算缓存命中率
        total_queries = stats_copy['total_queries']
        if total_queries > 0:
            cache_hit_rate = (stats_copy['cache_hits'] / total_queries) * 100
        else:
            cache_hit_rate = 0.0
        
        stats_copy['cache_hit_rate'] = round(cache_hit_rate, 2)
        stats_copy['cache_size'] = len(self._query_cache)
        
        return stats_copy

    def clear_cache(self):
        """清除查询缓存"""
        with self._cache_lock:
            self._query_cache.clear()
        logger.info("Prometheus query cache cleared")

    def optimize_queries(self, queries: List[str]) -> List[str]:
        """优化查询语句，合并相似的查询"""
        # 按指标类型分组
        query_groups = defaultdict(list)
        
        for query in queries:
            # 提取指标名称（简化处理）
            if 'node_cpu_seconds_total' in query:
                query_groups['cpu'].append(query)
            elif 'node_memory' in query:
                query_groups['memory'].append(query)
            elif 'node_filesystem' in query:
                query_groups['filesystem'].append(query)
            elif 'node_network' in query:
                query_groups['network'].append(query)
            else:
                query_groups['other'].append(query)
        
        # 尝试合并相似查询
        optimized_queries = []
        
        # CPU 查询不合并，保持逐实例/逐表达式的查询，以保证后续按查询字符串映射解析
        if 'cpu' in query_groups:
            optimized_queries.extend(query_groups['cpu'])
        
        # 内存相关查询
        if 'memory' in query_groups:
            optimized_queries.extend(query_groups['memory'])
        
        # 文件系统相关查询
        if 'filesystem' in query_groups:
            optimized_queries.extend(query_groups['filesystem'])
        
        # 网络相关查询
        if 'network' in query_groups:
            optimized_queries.extend(query_groups['network'])
        
        # 其他查询
        if 'other' in query_groups:
            optimized_queries.extend(query_groups['other'])
        
        return optimized_queries


def default_health_checks() -> List[Dict[str, Any]]:
    """默认健康检查配置"""
    # 动态阈值
    th = get_health_thresholds()
    cpu_th = th["cpu"]
    mem_th = th["mem"]
    disk_h = th["disk_hours"]

    return [
        # 系统资源监控
        {
            "name": "node_cpu_high",
            "expr": f"100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode=\"idle\"}}[5m])) * 100) > {cpu_th}",
            "severity": "warning",
            "message": f"CPU 使用率高于 {cpu_th}%",
            "category": "system"
        },
        {
            "name": "node_memory_high",
            "expr": f"(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > {mem_th}",
            "severity": "warning",
            "message": f"内存使用率高于 {mem_th}%",
            "category": "system"
        },
        {
            "name": "node_disk_fill_fast",
            "expr": f"predict_linear(node_filesystem_free_bytes{{fstype!~\"tmpfs|fuse\"}}[6h], {int(disk_h)} * 3600) < 0",
            "severity": "critical",
            "message": f"磁盘 {disk_h} 小时内可能写满",
            "category": "system"
        },
        {
            "name": "node_disk_usage_high",
            "expr": "100 - (node_filesystem_free_bytes{fstype!~\"tmpfs|fuse\"} / node_filesystem_size_bytes{fstype!~\"tmpfs|fuse\"} * 100) > 85",
            "severity": "warning",
            "message": "磁盘使用率高于85%",
            "category": "system"
        },
        # 网络监控
        {
            "name": "node_network_errors",
            "expr": "rate(node_network_receive_errs_total[5m]) + rate(node_network_transmit_errs_total[5m]) > 0",
            "severity": "warning",
            "message": "网络接口出现错误",
            "category": "network"
        },
        # 服务监控
        {
            "name": "service_down",
            "expr": "up == 0",
            "severity": "critical",
            "message": "服务不可用",
            "category": "service"
        },
        {
            "name": "service_high_latency",
            "expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 1",
            "severity": "warning",
            "message": "服务响应时间过高",
            "category": "service"
        },
        # 数据库监控
        {
            "name": "mysql_connections_high",
            "expr": "mysql_global_status_threads_connected / mysql_global_variables_max_connections * 100 > 80",
            "severity": "warning",
            "message": "MySQL连接数过高",
            "category": "database"
        },
        # 应用监控
        {
            "name": "http_5xx_errors",
            "expr": "rate(http_requests_total{status=~\"5..\"}[5m]) > 0.1",
            "severity": "critical",
            "message": "HTTP 5xx错误率过高",
            "category": "application"
        },
        {
            "name": "http_4xx_errors",
            "expr": "rate(http_requests_total{status=~\"4..\"}[5m]) > 0.5",
            "severity": "warning",
            "message": "HTTP 4xx错误率过高",
            "category": "application"
        }
    ]


def advanced_health_checks() -> List[Dict[str, Any]]:
    """高级健康检查配置"""
    return [
        # 容器监控
        {
            "name": "container_restarts",
            "expr": "increase(container_start_time_seconds[1h]) > 0",
            "severity": "warning",
            "message": "容器重启次数过多",
            "category": "container"
        },
        {
            "name": "container_memory_limit",
            "expr": "container_memory_usage_bytes / container_spec_memory_limit_bytes * 100 > 90",
            "severity": "warning",
            "message": "容器内存使用接近限制",
            "category": "container"
        },
        # 队列监控
        {
            "name": "queue_size_high",
            "expr": "queue_size > 1000",
            "severity": "warning",
            "message": "队列大小过高",
            "category": "queue"
        },
        # 缓存监控
        {
            "name": "cache_hit_rate_low",
            "expr": "cache_hits_total / (cache_hits_total + cache_misses_total) * 100 < 80",
            "severity": "warning",
            "message": "缓存命中率过低",
            "category": "cache"
        }
    ]


def run_health_checks(prom: PrometheusClient, checks: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """执行健康检查"""
    checks = checks or default_health_checks()
    results: List[Dict[str, Any]] = []
    
    for c in checks:
        status = "ok"
        detail = c["message"]
        labels = {
            "expr": c["expr"], 
            "severity": c.get("severity", "info"),
            "category": c.get("category", "general")
        }
        
        try:
            data = prom.instant(c["expr"])
            series = data.get("data", {}).get("result", [])
            
            if series:
                status = "alert"
                # 添加具体的指标值
                if series and len(series) > 0:
                    value = series[0].get("value", [None, None])[1]
                    if value is not None:
                        detail = f"{c['message']} (当前值: {value})"
                        
        except Exception as e:
            status = "error"
            detail = f"{c['message']} | 查询失败: {e}"
            labels["error"] = str(e)
            logger.error(f"Health check failed for {c['name']}: {e}")
            
        results.append({
            "@timestamp": datetime.now().isoformat(),
            "check": c["name"],
            "status": status,
            "detail": detail,
            "labels": labels,
            "severity": c.get("severity", "info"),
            "category": c.get("category", "general"),
            "score": 1.0 if status == "alert" else 0.0,
        })
    
    return results


def run_comprehensive_inspection(prom: PrometheusClient) -> Dict[str, Any]:
    """执行综合巡检"""
    results = {
        "timestamp": datetime.now().isoformat(),
        "checks": run_health_checks(prom),
        "targets": {},
        "alerts": {},
        "summary": {}
    }
    
    try:
        # 获取监控目标状态
        targets_data = prom.get_targets()
        results["targets"] = targets_data
        
        # 获取告警信息
        alerts_data = prom.get_alerts()
        results["alerts"] = alerts_data
        
        # 生成摘要
        total_checks = len(results["checks"])
        alert_count = len([c for c in results["checks"] if c["status"] == "alert"])
        error_count = len([c for c in results["checks"] if c["status"] == "error"])
        
        results["summary"] = {
            "total_checks": total_checks,
            "alert_count": alert_count,
            "error_count": error_count,
            "ok_count": total_checks - alert_count - error_count,
            "health_score": ((total_checks - alert_count - error_count) / total_checks * 100) if total_checks > 0 else 0
        }
        
    except Exception as e:
        logger.error(f"Comprehensive inspection failed: {e}")
        results["error"] = str(e)
    
    return results


def get_server_resources(prom: PrometheusClient) -> List[Dict[str, Any]]:
    """获取服务器资源信息（优化版本）"""
    resources = []
    
    try:
        start_time = time.time()
        logger.info("开始获取服务器资源信息")
        
        # 获取所有监控目标
        all_instances = prom.get_metrics("up")
        logger.info(f"找到 {len(all_instances)} 个监控实例")
        
        # 过滤出有node指标的实例
        node_instances = []
        for instance in all_instances:
            metric = instance.get("metric", {})
            instance_name = metric.get("instance", "")
            job = metric.get("job", "").lower()
            
            # 检查是否有node相关指标
            if instance_name and ("node" in job or "real" in job or "linux" in job):
                node_instances.append(instance)
        
        logger.info(f"找到 {len(node_instances)} 个node实例")
        
        # 如果没有找到node实例，尝试从CPU指标中获取
        if not node_instances:
            cpu_instances = prom.get_metrics("node_cpu_seconds_total")
            seen_instances = set()
            for instance in cpu_instances:
                metric = instance.get("metric", {})
                instance_name = metric.get("instance", "")
                if instance_name and instance_name not in seen_instances:
                    seen_instances.add(instance_name)
                    node_instances.append({
                        "metric": {
                            "instance": instance_name,
                            "job": metric.get("job", "unknown")
                        }
                    })
        
        logger.info(f"最终处理 {len(node_instances)} 个实例")
        
        if not node_instances:
            logger.warning("没有找到可处理的node实例")
            return []
        
        # 批量获取所有实例的资源信息
        resources = get_resources_batch(prom, node_instances)
        
        duration = time.time() - start_time
        logger.info(f"服务器资源信息获取完成，耗时: {duration:.2f}s，实例数: {len(resources)}")
        
        # 输出性能统计
        stats = prom.get_performance_stats()
        logger.info(f"Prometheus查询统计: {stats}")
        
    except Exception as e:
        logger.error(f"获取服务器资源信息失败: {e}")
    
    return resources


def get_resources_batch(prom: PrometheusClient, instances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量获取多个实例的资源信息"""
    resources = []
    
    # 准备所有需要查询的指标
    all_queries = []
    instance_names = []
    
    for instance in instances:
        instance_name = instance.get("metric", {}).get("instance", "unknown")
        if not instance_name or instance_name == "unknown":
            continue
        
        instance_names.append(instance_name)
        
        # 为每个实例准备查询
        queries = prepare_instance_queries(instance_name)
        all_queries.extend(queries)
    
    if not all_queries:
        return []
    
    # 优化查询（合并相似查询）
    optimized_queries = prom.optimize_queries(all_queries)
    logger.info(f"查询优化: {len(all_queries)} -> {len(optimized_queries)}")
    
    # 批量执行查询
    try:
        query_results = prom.batch_instant_queries(optimized_queries)
        logger.info(f"批量查询完成，共 {len(query_results)} 个结果")
        
        # 解析结果并分配给各个实例
        resources = parse_batch_results(instance_names, query_results, optimized_queries)
        
    except Exception as e:
        logger.error(f"批量查询失败: {e}")
        # 降级到串行处理
        resources = get_resources_sequential(prom, instances)
    
    return resources


def prepare_instance_queries(instance_name: str) -> List[str]:
    """为单个实例准备所有需要的查询"""
    queries = []
    
    # CPU相关查询
    queries.extend([
        f'100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode="idle",instance="{instance_name}"}}[5m])) * 100)',
        f'count by (instance) (node_cpu_seconds_total{{mode="idle",instance="{instance_name}"}})',
        f'node_load1{{instance="{instance_name}"}}',
        f'node_load5{{instance="{instance_name}"}}',
        f'node_load15{{instance="{instance_name}"}}'
    ])
    
    # 内存相关查询
    queries.extend([
        f'node_memory_MemTotal_bytes{{instance="{instance_name}"}}',
        f'node_memory_MemAvailable_bytes{{instance="{instance_name}"}}'
    ])
    
    # 磁盘相关查询（优先根挂载点/，再退回全部）
    queries.extend([
        f'100 - (node_filesystem_free_bytes{{fstype!~"tmpfs|fuse",mountpoint="/",instance="{instance_name}"}} / node_filesystem_size_bytes{{fstype!~"tmpfs|fuse",mountpoint="/",instance="{instance_name}"}} * 100)',
        f'100 - (node_filesystem_free_bytes{{fstype!~"tmpfs|fuse",instance="{instance_name}"}} / node_filesystem_size_bytes{{fstype!~"tmpfs|fuse",instance="{instance_name}"}} * 100)',
        f'rate(node_disk_read_bytes_total{{instance="{instance_name}"}}[5m])',
        f'rate(node_disk_written_bytes_total{{instance="{instance_name}"}}[5m])'
    ])
    
    # 网络相关查询
    queries.extend([
        f'rate(node_network_receive_bytes_total{{instance="{instance_name}"}}[5m])',
        f'rate(node_network_transmit_bytes_total{{instance="{instance_name}"}}[5m])',
        f'node_netstat_Tcp_CurrEstab{{instance="{instance_name}"}}',
        f'node_netstat_Tcp_Tw{{instance="{instance_name}"}}'
    ])
    
    # 系统相关查询
    queries.extend([
        f'node_boot_time_seconds{{instance="{instance_name}"}}',
        f'node_os_info{{instance="{instance_name}"}}',
        f'node_uname_info{{instance="{instance_name}"}}'
    ])
    
    return queries


def parse_batch_results(instance_names: List[str], query_results: List[Dict[str, Any]], 
                       queries: List[str]) -> List[Dict[str, Any]]:
    """解析批量查询结果并分配给各个实例"""
    resources = []
    
    # 创建查询结果映射
    query_map = {}
    for i, query in enumerate(queries):
        if i < len(query_results) and query_results[i]:
            query_map[query] = query_results[i]
    
    # 为每个实例构建资源信息
    for instance_name in instance_names:
        try:
            resource_data = {
                "instance": instance_name,
                "timestamp": datetime.now().isoformat(),
                "cpu": parse_cpu_info_batch(instance_name, query_map),
                "memory": parse_memory_info_batch(instance_name, query_map),
                "disk": parse_disk_info_batch(instance_name, query_map),
                "network": parse_network_info_batch(instance_name, query_map),
                "system": parse_system_info_batch(instance_name, query_map)
            }
            resources.append(resource_data)
            
        except Exception as e:
            logger.error(f"解析实例 {instance_name} 的资源信息失败: {e}")
            # 添加错误信息
            resources.append({
                "instance": instance_name,
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            })
    
    return resources


def get_resources_sequential(prom: PrometheusClient, instances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """串行获取资源信息（降级方案）"""
    resources = []
    
    for instance in instances:
        instance_name = instance.get("metric", {}).get("instance", "unknown")
        if not instance_name or instance_name == "unknown":
            continue
            
        logger.info(f"串行处理实例: {instance_name}")
        
        try:
            # 获取CPU信息
            cpu_info = get_cpu_info(prom, instance_name)
            
            # 获取内存信息
            memory_info = get_memory_info(prom, instance_name)
            
            # 获取磁盘信息
            disk_info = get_disk_info(prom, instance_name)
            
            # 获取网络信息
            network_info = get_network_info(prom, instance_name)
            
            # 获取系统信息
            system_info = get_system_info(prom, instance_name)
            
            # 合并所有信息
            resource_data = {
                "instance": instance_name,
                "timestamp": datetime.now().isoformat(),
                "cpu": cpu_info,
                "memory": memory_info,
                "disk": disk_info,
                "network": network_info,
                "system": system_info
            }
            
            resources.append(resource_data)
            
        except Exception as e:
            logger.error(f"处理实例 {instance_name} 失败: {e}")
            resources.append({
                "instance": instance_name,
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            })
    
    return resources


def get_cpu_info(prom: PrometheusClient, instance: str) -> Dict[str, Any]:
    """获取CPU信息"""
    cpu_info = {}
    
    try:
        # CPU使用率
        cpu_usage_query = f'100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode="idle",instance="{instance}"}}[5m])) * 100)'
        cpu_usage_data = prom.instant(cpu_usage_query)
        if cpu_usage_data.get("data", {}).get("result"):
            cpu_info["usage_percent"] = float(cpu_usage_data["data"]["result"][0]["value"][1])
        
        # CPU核心数
        cpu_cores_query = f'count by (instance) (node_cpu_seconds_total{{mode="idle",instance="{instance}"}})'
        cpu_cores_data = prom.instant(cpu_cores_query)
        if cpu_cores_data.get("data", {}).get("result"):
            cpu_info["cores"] = int(cpu_cores_data["data"]["result"][0]["value"][1])
        
        # CPU负载
        load1_query = f'node_load1{{instance="{instance}"}}'
        load1_data = prom.instant(load1_query)
        if load1_data.get("data", {}).get("result"):
            cpu_info["load_1m"] = float(load1_data["data"]["result"][0]["value"][1])
        
        load5_query = f'node_load5{{instance="{instance}"}}'
        load5_data = prom.instant(load5_query)
        if load5_data.get("data", {}).get("result"):
            cpu_info["load_5m"] = float(load5_data["data"]["result"][0]["value"][1])
        
        load15_query = f'node_load15{{instance="{instance}"}}'
        load15_data = prom.instant(load15_query)
        if load15_data.get("data", {}).get("result"):
            cpu_info["load_15m"] = float(load15_data["data"]["result"][0]["value"][1])
            
    except Exception as e:
        logger.error(f"获取CPU信息失败: {e}")
    
    return cpu_info


def parse_cpu_info_batch(instance: str, query_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """从批量查询结果中解析CPU信息"""
    cpu_info = {}
    
    try:
        # CPU使用率
        cpu_usage_query = f'100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode="idle",instance="{instance}"}}[5m])) * 100)'
        if cpu_usage_query in query_map:
            data = query_map[cpu_usage_query]
            if data.get("data", {}).get("result"):
                cpu_info["usage_percent"] = float(data["data"]["result"][0]["value"][1])
        
        # CPU核心数
        cpu_cores_query = f'count by (instance) (node_cpu_seconds_total{{mode="idle",instance="{instance}"}})'
        if cpu_cores_query in query_map:
            data = query_map[cpu_cores_query]
            if data.get("data", {}).get("result"):
                cpu_info["cores"] = int(data["data"]["result"][0]["value"][1])
        
        # CPU负载
        load1_query = f'node_load1{{instance="{instance}"}}'
        if load1_query in query_map:
            data = query_map[load1_query]
            if data.get("data", {}).get("result"):
                cpu_info["load_1m"] = float(data["data"]["result"][0]["value"][1])
        
        load5_query = f'node_load5{{instance="{instance}"}}'
        if load5_query in query_map:
            data = query_map[load5_query]
            if data.get("data", {}).get("result"):
                cpu_info["load_5m"] = float(data["data"]["result"][0]["value"][1])
        
        load15_query = f'node_load15{{instance="{instance}"}}'
        if load15_query in query_map:
            data = query_map[load15_query]
            if data.get("data", {}).get("result"):
                cpu_info["load_15m"] = float(data["data"]["result"][0]["value"][1])
                
    except Exception as e:
        logger.error(f"解析CPU信息失败: {e}")
    
    return cpu_info


def get_memory_info(prom: PrometheusClient, instance: str) -> Dict[str, Any]:
    """获取内存信息"""
    memory_info = {}
    
    try:
        # 总内存
        total_memory_query = f'node_memory_MemTotal_bytes{{instance="{instance}"}}'
        total_memory_data = prom.instant(total_memory_query)
        if total_memory_data.get("data", {}).get("result"):
            total_bytes = float(total_memory_data["data"]["result"][0]["value"][1])
            memory_info["total_gb"] = round(total_bytes / (1024**3), 2)
        
        # 可用内存
        available_memory_query = f'node_memory_MemAvailable_bytes{{instance="{instance}"}}'
        available_memory_data = prom.instant(available_memory_query)
        if available_memory_data.get("data", {}).get("result"):
            available_bytes = float(available_memory_data["data"]["result"][0]["value"][1])
            memory_info["available_gb"] = round(available_bytes / (1024**3), 2)
        
        # 内存使用率
        if memory_info.get("total_gb") and memory_info.get("available_gb"):
            used_gb = memory_info["total_gb"] - memory_info["available_gb"]
            memory_info["used_gb"] = round(used_gb, 2)
            memory_info["usage_percent"] = round((used_gb / memory_info["total_gb"]) * 100, 2)
            
    except Exception as e:
        logger.error(f"获取内存信息失败: {e}")
    
    return memory_info


def parse_memory_info_batch(instance: str, query_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """从批量查询结果中解析内存信息"""
    memory_info = {}
    
    try:
        # 总内存
        total_memory_query = f'node_memory_MemTotal_bytes{{instance="{instance}"}}'
        if total_memory_query in query_map:
            data = query_map[total_memory_query]
            if data.get("data", {}).get("result"):
                total_bytes = float(data["data"]["result"][0]["value"][1])
                memory_info["total_gb"] = round(total_bytes / (1024**3), 2)
        
        # 可用内存
        available_memory_query = f'node_memory_MemAvailable_bytes{{instance="{instance}"}}'
        if available_memory_query in query_map:
            data = query_map[available_memory_query]
            if data.get("data", {}).get("result"):
                available_bytes = float(data["data"]["result"][0]["value"][1])
                memory_info["available_gb"] = round(available_bytes / (1024**3), 2)
        
        # 内存使用率
        if memory_info.get("total_gb") and memory_info.get("available_gb"):
            used_gb = memory_info["total_gb"] - memory_info["available_gb"]
            memory_info["used_gb"] = round(used_gb, 2)
            memory_info["usage_percent"] = round((used_gb / memory_info["total_gb"]) * 100, 2)
            
    except Exception as e:
        logger.error(f"解析内存信息失败: {e}")
    
    return memory_info


def get_disk_info(prom: PrometheusClient, instance: str) -> Dict[str, Any]:
    """获取磁盘信息"""
    disk_info = {}
    
    try:
        # 磁盘使用情况：优先根挂载点，其次所有分区
        disk_usage_root_query = f'100 - (node_filesystem_free_bytes{{fstype!~"tmpfs|fuse",mountpoint="/",instance="{instance}"}} / node_filesystem_size_bytes{{fstype!~"tmpfs|fuse",mountpoint="/",instance="{instance}"}} * 100)'
        disk_usage_all_query = f'100 - (node_filesystem_free_bytes{{fstype!~"tmpfs|fuse",instance="{instance}"}} / node_filesystem_size_bytes{{fstype!~"tmpfs|fuse",instance="{instance}"}} * 100)'
        root_data = prom.instant(disk_usage_root_query)
        all_data = prom.instant(disk_usage_all_query)

        disk_usage_list = []
        # 优先使用全分区结果；若无则退回根分区
        if all_data.get("data", {}).get("result"):
            for result in all_data["data"]["result"]:
                metric_labels = result.get("metric", {})
                mountpoint = metric_labels.get("mountpoint", "unknown")
                device = metric_labels.get("device")
                fstype = metric_labels.get("fstype")
                usage_percent = float(result["value"][1])
                disk_usage_list.append({
                    "mountpoint": mountpoint,
                    "device": device,
                    "fs_type": fstype,
                    "usage_percent": round(usage_percent, 2)
                })
        elif root_data.get("data", {}).get("result"):
            for result in root_data["data"]["result"]:
                metric_labels = result.get("metric", {})
                mountpoint = metric_labels.get("mountpoint", "/")
                device = metric_labels.get("device")
                fstype = metric_labels.get("fstype")
                usage_percent = float(result["value"][1])
                disk_usage_list.append({
                    "mountpoint": mountpoint,
                    "device": device,
                    "fs_type": fstype,
                    "usage_percent": round(usage_percent, 2)
                })
        
        disk_info["partitions"] = disk_usage_list
        
        # 磁盘IO - 读取速度
        disk_read_query = f'rate(node_disk_read_bytes_total{{instance="{instance}"}}[5m])'
        disk_read_data = prom.instant(disk_read_query)
        if disk_read_data.get("data", {}).get("result"):
            total_read = sum(float(result["value"][1]) for result in disk_read_data["data"]["result"])
            disk_info["read_bytes_per_sec"] = round(total_read, 2)
        
        # 磁盘IO - 写入速度
        disk_write_query = f'rate(node_disk_written_bytes_total{{instance="{instance}"}}[5m])'
        disk_write_data = prom.instant(disk_write_query)
        if disk_write_data.get("data", {}).get("result"):
            total_write = sum(float(result["value"][1]) for result in disk_write_data["data"]["result"])
            disk_info["write_bytes_per_sec"] = round(total_write, 2)
            
    except Exception as e:
        logger.error(f"获取磁盘信息失败: {e}")
    
    return disk_info


def parse_disk_info_batch(instance: str, query_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """从批量查询结果中解析磁盘信息"""
    disk_info = {}
    
    try:
        # 磁盘使用情况（批量）：优先根挂载点，再退回全部
        disk_usage_root_query = f'100 - (node_filesystem_free_bytes{{fstype!~"tmpfs|fuse",mountpoint="/",instance="{instance}"}} / node_filesystem_size_bytes{{fstype!~"tmpfs|fuse",mountpoint="/",instance="{instance}"}} * 100)'
        disk_usage_all_query = f'100 - (node_filesystem_free_bytes{{fstype!~"tmpfs|fuse",instance="{instance}"}} / node_filesystem_size_bytes{{fstype!~"tmpfs|fuse",instance="{instance}"}} * 100)'
        disk_usage_list = []
        # 优先使用全分区结果；若无则退回根分区
        if disk_usage_all_query in query_map:
            data = query_map[disk_usage_all_query]
            if data.get("data", {}).get("result"):
                for result in data["data"]["result"]:
                    metric_labels = result.get("metric", {})
                    mountpoint = metric_labels.get("mountpoint", "unknown")
                    device = metric_labels.get("device")
                    fstype = metric_labels.get("fstype")
                    usage_percent = float(result["value"][1])
                    disk_usage_list.append({
                        "mountpoint": mountpoint,
                        "device": device,
                        "fs_type": fstype,
                        "usage_percent": round(usage_percent, 2)
                    })
        elif disk_usage_root_query in query_map:
            data = query_map[disk_usage_root_query]
            if data.get("data", {}).get("result"):
                for result in data["data"]["result"]:
                    metric_labels = result.get("metric", {})
                    mountpoint = metric_labels.get("mountpoint", "/")
                    device = metric_labels.get("device")
                    fstype = metric_labels.get("fstype")
                    usage_percent = float(result["value"][1])
                    disk_usage_list.append({
                        "mountpoint": mountpoint,
                        "device": device,
                        "fs_type": fstype,
                        "usage_percent": round(usage_percent, 2)
                    })
        disk_info["partitions"] = disk_usage_list
        
        # 磁盘IO - 读取速度
        disk_read_query = f'rate(node_disk_read_bytes_total{{instance="{instance}"}}[5m])'
        if disk_read_query in query_map:
            data = query_map[disk_read_query]
            if data.get("data", {}).get("result"):
                total_read = sum(float(result["value"][1]) for result in data["data"]["result"])
                disk_info["read_bytes_per_sec"] = round(total_read, 2)
        
        # 磁盘IO - 写入速度
        disk_write_query = f'rate(node_disk_written_bytes_total{{instance="{instance}"}}[5m])'
        if disk_write_query in query_map:
            data = query_map[disk_write_query]
            if data.get("data", {}).get("result"):
                total_write = sum(float(result["value"][1]) for result in data["data"]["result"])
                disk_info["write_bytes_per_sec"] = round(total_write, 2)
            
    except Exception as e:
        logger.error(f"解析磁盘信息失败: {e}")
    
    return disk_info


def get_network_info(prom: PrometheusClient, instance: str) -> Dict[str, Any]:
    """获取网络信息"""
    network_info = {}
    
    try:
        # 网络接收
        network_receive_query = f'rate(node_network_receive_bytes_total{{instance="{instance}"}}[5m])'
        network_receive_data = prom.instant(network_receive_query)
        if network_receive_data.get("data", {}).get("result"):
            total_receive = sum(float(result["value"][1]) for result in network_receive_data["data"]["result"])
            network_info["receive_bytes_per_sec"] = round(total_receive, 2)
        
        # 网络发送
        network_transmit_query = f'rate(node_network_transmit_bytes_total{{instance="{instance}"}}[5m])'
        network_transmit_data = prom.instant(network_transmit_query)
        if network_transmit_data.get("data", {}).get("result"):
            total_transmit = sum(float(result["value"][1]) for result in network_transmit_data["data"]["result"])
            network_info["transmit_bytes_per_sec"] = round(total_transmit, 2)
        
        # TCP连接数
        tcp_connections_query = f'node_netstat_Tcp_CurrEstab{{instance="{instance}"}}'
        tcp_connections_data = prom.instant(tcp_connections_query)
        if tcp_connections_data.get("data", {}).get("result"):
            network_info["tcp_connections"] = int(tcp_connections_data["data"]["result"][0]["value"][1])
        
        # TCP TIME_WAIT连接数
        tcp_tw_query = f'node_netstat_Tcp_Tw{{instance="{instance}"}}'
        tcp_tw_data = prom.instant(tcp_tw_query)
        if tcp_tw_data.get("data", {}).get("result"):
            network_info["tcp_tw"] = int(tcp_tw_data["data"]["result"][0]["value"][1])
            
    except Exception as e:
        logger.error(f"获取网络信息失败: {e}")
    
    return network_info


def parse_network_info_batch(instance: str, query_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """从批量查询结果中解析网络信息"""
    network_info = {}
    
    try:
        # 网络接收
        network_receive_query = f'rate(node_network_receive_bytes_total{{instance="{instance}"}}[5m])'
        if network_receive_query in query_map:
            data = query_map[network_receive_query]
            if data.get("data", {}).get("result"):
                total_receive = sum(float(result["value"][1]) for result in data["data"]["result"])
                network_info["receive_bytes_per_sec"] = round(total_receive, 2)
        
        # 网络发送
        network_transmit_query = f'rate(node_network_transmit_bytes_total{{instance="{instance}"}}[5m])'
        if network_transmit_query in query_map:
            data = query_map[network_transmit_query]
            if data.get("data", {}).get("result"):
                total_transmit = sum(float(result["value"][1]) for result in data["data"]["result"])
                network_info["transmit_bytes_per_sec"] = round(total_transmit, 2)
        
        # TCP连接数
        tcp_connections_query = f'node_netstat_Tcp_CurrEstab{{instance="{instance}"}}'
        if tcp_connections_query in query_map:
            data = query_map[tcp_connections_query]
            if data.get("data", {}).get("result"):
                network_info["tcp_connections"] = int(data["data"]["result"][0]["value"][1])
        
        # TCP TIME_WAIT连接数
        tcp_tw_query = f'node_netstat_Tcp_Tw{{instance="{instance}"}}'
        if tcp_tw_query in query_map:
            data = query_map[tcp_tw_query]
            if data.get("data", {}).get("result"):
                network_info["tcp_tw"] = int(data["data"]["result"][0]["value"][1])
            
    except Exception as e:
        logger.error(f"解析网络信息失败: {e}")
    
    return network_info


def get_system_info(prom: PrometheusClient, instance: str) -> Dict[str, Any]:
    """获取系统信息"""
    system_info = {}
    
    try:
        # 系统启动时间
        uptime_query = f'node_boot_time_seconds{{instance="{instance}"}}'
        uptime_data = prom.instant(uptime_query)
        if uptime_data.get("data", {}).get("result"):
            boot_time = float(uptime_data["data"]["result"][0]["value"][1])
            current_time = datetime.now().timestamp()
            uptime_seconds = current_time - boot_time
            uptime_days = uptime_seconds / (24 * 3600)
            system_info["uptime_days"] = round(uptime_days, 2)
        
        # 操作系统信息
        os_info_query = f'node_os_info{{instance="{instance}"}}'
        os_info_data = prom.instant(os_info_query)
        if os_info_data.get("data", {}).get("result"):
            os_info = os_info_data["data"]["result"][0]["metric"]
            system_info["os"] = os_info.get("os", "unknown")
            system_info["version"] = os_info.get("version", "unknown")
        
        # 主机名
        hostname_query = f'node_uname_info{{instance="{instance}"}}'
        hostname_data = prom.instant(hostname_query)
        if hostname_data.get("data", {}).get("result"):
            hostname_info = hostname_data["data"]["result"][0]["metric"]
            system_info["hostname"] = hostname_info.get("nodename", "unknown")
            
    except Exception as e:
        logger.error(f"获取系统信息失败: {e}")
    
    return system_info


def parse_system_info_batch(instance: str, query_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """从批量查询结果中解析系统信息"""
    system_info = {}
    
    try:
        # 系统启动时间
        uptime_query = f'node_boot_time_seconds{{instance="{instance}"}}'
        if uptime_query in query_map:
            data = query_map[uptime_query]
            if data.get("data", {}).get("result"):
                boot_time = float(data["data"]["result"][0]["value"][1])
                current_time = datetime.now().timestamp()
                uptime_seconds = current_time - boot_time
                uptime_days = uptime_seconds / (24 * 3600)
                system_info["uptime_days"] = round(uptime_days, 2)
        
        # 操作系统信息
        os_info_query = f'node_os_info{{instance="{instance}"}}'
        if os_info_query in query_map:
            data = query_map[os_info_query]
            if data.get("data", {}).get("result"):
                os_info = data["data"]["result"][0]["metric"]
                system_info["os"] = os_info.get("os", "unknown")
                system_info["version"] = os_info.get("version", "unknown")
        
        # 主机名
        hostname_query = f'node_uname_info{{instance="{instance}"}}'
        if hostname_query in query_map:
            data = query_map[hostname_query]
            if data.get("data", {}).get("result"):
                hostname_info = data["data"]["result"][0]["metric"]
                system_info["hostname"] = hostname_info.get("nodename", "unknown")
            
    except Exception as e:
        logger.error(f"解析系统信息失败: {e}")
    
    return system_info


