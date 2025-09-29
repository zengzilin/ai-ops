#!/usr/bin/env python3
"""
性能监控和优化模块
用于监控普罗米修斯查询性能，提供优化建议和自动调优
"""

from __future__ import annotations

import time
import logging
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
import statistics
import gc
import psutil
import os

from app.core.config import SETTINGS

logger = logging.getLogger(__name__)


@dataclass
class QueryMetrics:
    """查询性能指标"""
    query: str
    execution_time: float
    timestamp: float
    success: bool
    error_message: Optional[str] = None
    cache_hit: bool = False
    response_size: Optional[int] = None


@dataclass
class PerformanceStats:
    """性能统计信息"""
    total_queries: int
    successful_queries: int
    failed_queries: int
    avg_response_time: float
    median_response_time: float
    p95_response_time: float
    p99_response_time: float
    cache_hit_rate: float
    queries_per_second: float
    memory_usage_mb: float
    cpu_usage_percent: float


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.query_history: deque = deque(maxlen=max_history)
        self.performance_stats: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()
        
        # 性能阈值
        self.thresholds = {
            'slow_query_threshold': 2.0,  # 2秒
            'error_rate_threshold': 0.05,  # 5%
            'memory_threshold': 800,  # 800MB
            'cpu_threshold': 80.0,  # 80%
        }
        
        # 优化建议
        self.optimization_suggestions: List[str] = []
        
    def record_query(self, query: str, execution_time: float, success: bool, 
                    error_message: Optional[str] = None, cache_hit: bool = False,
                    response_size: Optional[int] = None):
        """记录查询性能指标"""
        with self._lock:
            metrics = QueryMetrics(
                query=query,
                execution_time=execution_time,
                timestamp=time.time(),
                success=success,
                error_message=error_message,
                cache_hit=cache_hit,
                response_size=response_size
            )
            self.query_history.append(metrics)
    
    def get_performance_stats(self) -> PerformanceStats:
        """获取性能统计信息"""
        with self._lock:
            if not self.query_history:
                return PerformanceStats(
                    total_queries=0,
                    successful_queries=0,
                    failed_queries=0,
                    avg_response_time=0.0,
                    median_response_time=0.0,
                    p95_response_time=0.0,
                    p99_response_time=0.0,
                    cache_hit_rate=0.0,
                    queries_per_second=0.0,
                    memory_usage_mb=0.0,
                    cpu_usage_percent=0.0
                )
            
            # 计算基本统计
            total_queries = len(self.query_history)
            successful_queries = sum(1 for q in self.query_history if q.success)
            failed_queries = total_queries - successful_queries
            
            # 响应时间统计
            response_times = [q.execution_time for q in self.query_history if q.success]
            if response_times:
                avg_response_time = statistics.mean(response_times)
                median_response_time = statistics.median(response_times)
                p95_response_time = statistics.quantiles(response_times, n=20)[18]  # 95th percentile
                p99_response_time = statistics.quantiles(response_times, n=100)[98]  # 99th percentile
            else:
                avg_response_time = median_response_time = p95_response_time = p99_response_time = 0.0
            
            # 缓存命中率
            cache_hits = sum(1 for q in self.query_history if q.cache_hit)
            cache_hit_rate = (cache_hits / total_queries * 100) if total_queries > 0 else 0.0
            
            # 查询频率
            elapsed_time = time.time() - self._start_time
            queries_per_second = total_queries / elapsed_time if elapsed_time > 0 else 0.0
            
            # 系统资源使用
            memory_usage_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            cpu_usage_percent = psutil.cpu_percent(interval=0.1)
            
            return PerformanceStats(
                total_queries=total_queries,
                successful_queries=successful_queries,
                failed_queries=failed_queries,
                avg_response_time=avg_response_time,
                median_response_time=median_response_time,
                p95_response_time=p95_response_time,
                p99_response_time=p99_response_time,
                cache_hit_rate=cache_hit_rate,
                queries_per_second=queries_per_second,
                memory_usage_mb=memory_usage_mb,
                cpu_usage_percent=cpu_usage_percent
            )
    
    def analyze_performance(self) -> Dict[str, Any]:
        """分析性能并提供优化建议"""
        stats = self.get_performance_stats()
        analysis = {
            'stats': asdict(stats),
            'issues': [],
            'suggestions': [],
            'optimizations': {}
        }
        
        # 检查性能问题
        if stats.avg_response_time > self.thresholds['slow_query_threshold']:
            analysis['issues'].append(f"平均响应时间过高: {stats.avg_response_time:.2f}s")
            analysis['suggestions'].append("考虑增加缓存TTL或优化查询语句")
        
        error_rate = stats.failed_queries / stats.total_queries if stats.total_queries > 0 else 0
        if error_rate > self.thresholds['error_rate_threshold']:
            analysis['issues'].append(f"错误率过高: {error_rate:.2%}")
            analysis['suggestions'].append("检查网络连接和Prometheus服务状态")
        
        if stats.memory_usage_mb > self.thresholds['memory_threshold']:
            analysis['issues'].append(f"内存使用过高: {stats.memory_usage_mb:.1f}MB")
            analysis['suggestions'].append("考虑清理缓存或增加内存限制")
        
        if stats.cpu_usage_percent > self.thresholds['cpu_threshold']:
            analysis['issues'].append(f"CPU使用率过高: {stats.cpu_usage_percent:.1f}%")
            analysis['suggestions'].append("考虑减少并发查询数量或优化查询逻辑")
        
        # 查询优化建议
        if stats.cache_hit_rate < 50:
            analysis['suggestions'].append("缓存命中率较低，考虑增加缓存TTL或优化缓存策略")
        
        if stats.queries_per_second < 1:
            analysis['suggestions'].append("查询频率较低，可能存在性能瓶颈")
        
        # 自动优化建议
        analysis['optimizations'] = self._get_optimization_recommendations(stats)
        
        return analysis
    
    def _get_optimization_recommendations(self, stats: PerformanceStats) -> Dict[str, Any]:
        """获取优化建议"""
        recommendations = {}
        
        # 缓存优化
        if stats.cache_hit_rate < 70:
            recommendations['cache'] = {
                'action': 'increase_cache_ttl',
                'current_ttl': SETTINGS.prom_cache_ttl,
                'suggested_ttl': min(SETTINGS.prom_cache_ttl * 2, 1800),  # 最大30分钟
                'reason': '缓存命中率较低'
            }
        
        # 并发优化
        if stats.avg_response_time > 1.0:
            recommendations['concurrency'] = {
                'action': 'adjust_max_workers',
                'current_workers': SETTINGS.prom_max_workers,
                'suggested_workers': min(SETTINGS.prom_max_workers + 5, 50),
                'reason': '响应时间较长，可能需要增加并发数'
            }
        
        # 查询优化
        if stats.failed_queries > 0:
            recommendations['query_optimization'] = {
                'action': 'enable_query_optimization',
                'current': SETTINGS.prom_enable_query_optimization,
                'suggested': True,
                'reason': '存在查询失败，启用查询优化可能有助于提高成功率'
            }
        
        # 内存优化
        if stats.memory_usage_mb > 500:
            recommendations['memory'] = {
                'action': 'reduce_cache_size',
                'current_max_history': self.max_history,
                'suggested_max_history': max(self.max_history // 2, 500),
                'reason': '内存使用较高，减少历史记录缓存大小'
            }
        
        return recommendations
    
    def get_slow_queries(self, limit: int = 10) -> List[QueryMetrics]:
        """获取最慢的查询"""
        with self._lock:
            slow_queries = sorted(
                [q for q in self.query_history if q.success],
                key=lambda x: x.execution_time,
                reverse=True
            )[:limit]
            return slow_queries
    
    def get_failed_queries(self, limit: int = 10) -> List[QueryMetrics]:
        """获取失败的查询"""
        with self._lock:
            failed_queries = [q for q in self.query_history if not q.success]
            return sorted(failed_queries, key=lambda x: x.timestamp, reverse=True)[:limit]
    
    def get_query_patterns(self) -> Dict[str, Any]:
        """分析查询模式"""
        with self._lock:
            patterns = defaultdict(lambda: {
                'count': 0,
                'total_time': 0.0,
                'avg_time': 0.0,
                'success_count': 0,
                'error_count': 0,
                'cache_hits': 0
            })
            
            for query in self.query_history:
                # 提取查询类型（简化处理）
                query_type = self._categorize_query(query.query)
                
                patterns[query_type]['count'] += 1
                patterns[query_type]['total_time'] += query.execution_time
                patterns[query_type]['avg_time'] = patterns[query_type]['total_time'] / patterns[query_type]['count']
                
                if query.success:
                    patterns[query_type]['success_count'] += 1
                else:
                    patterns[query_type]['error_count'] += 1
                
                if query.cache_hit:
                    patterns[query_type]['cache_hits'] += 1
            
            return dict(patterns)
    
    def _categorize_query(self, query: str) -> str:
        """对查询进行分类"""
        query_lower = query.lower()
        
        if 'cpu' in query_lower:
            return 'cpu_metrics'
        elif 'memory' in query_lower or 'mem' in query_lower:
            return 'memory_metrics'
        elif 'disk' in query_lower or 'filesystem' in query_lower:
            return 'disk_metrics'
        elif 'network' in query_lower:
            return 'network_metrics'
        elif 'up' in query_lower:
            return 'health_check'
        elif 'rate(' in query_lower or 'irate(' in query_lower:
            return 'rate_queries'
        elif 'histogram_quantile' in query_lower:
            return 'histogram_queries'
        else:
            return 'other_queries'
    
    def clear_history(self):
        """清除查询历史"""
        with self._lock:
            self.query_history.clear()
            logger.info("查询历史已清除")
    
    def export_metrics(self, filepath: str):
        """导出性能指标到文件"""
        try:
            import json
            from datetime import datetime
            
            export_data = {
                'export_timestamp': datetime.now().isoformat(),
                'performance_stats': asdict(self.get_performance_stats()),
                'query_patterns': self.get_query_patterns(),
                'slow_queries': [asdict(q) for q in self.get_slow_queries(20)],
                'failed_queries': [asdict(q) for q in self.get_failed_queries(20)],
                'analysis': self.analyze_performance()
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"性能指标已导出到: {filepath}")
            
        except Exception as e:
            logger.error(f"导出性能指标失败: {e}")


class PerformanceOptimizer:
    """性能优化器"""
    
    def __init__(self, monitor: PerformanceMonitor):
        self.monitor = monitor
        self.optimization_history: List[Dict[str, Any]] = []
    
    def auto_optimize(self) -> Dict[str, Any]:
        """自动优化性能"""
        analysis = self.monitor.analyze_performance()
        optimizations = analysis.get('optimizations', {})
        
        results = {
            'applied': [],
            'skipped': [],
            'errors': []
        }
        
        for opt_type, opt_config in optimizations.items():
            try:
                if self._apply_optimization(opt_type, opt_config):
                    results['applied'].append({
                        'type': opt_type,
                        'config': opt_config,
                        'timestamp': time.time()
                    })
                    
                    # 记录优化历史
                    self.optimization_history.append({
                        'type': opt_type,
                        'config': opt_config,
                        'timestamp': time.time(),
                        'success': True
                    })
                else:
                    results['skipped'].append({
                        'type': opt_type,
                        'reason': '优化条件不满足'
                    })
                    
            except Exception as e:
                results['errors'].append({
                    'type': opt_type,
                    'error': str(e)
                })
                
                # 记录失败历史
                self.optimization_history.append({
                    'type': opt_type,
                    'config': opt_config,
                    'timestamp': time.time(),
                    'success': False,
                    'error': str(e)
                })
        
        return results
    
    def _apply_optimization(self, opt_type: str, opt_config: Dict[str, Any]) -> bool:
        """应用具体的优化"""
        if opt_type == 'cache':
            return self._optimize_cache(opt_config)
        elif opt_type == 'concurrency':
            return self._optimize_concurrency(opt_config)
        elif opt_type == 'memory':
            return self._optimize_memory(opt_config)
        else:
            return False
    
    def _optimize_cache(self, config: Dict[str, Any]) -> bool:
        """优化缓存设置"""
        try:
            # 这里可以动态调整缓存设置
            # 由于配置是只读的，我们只能记录建议
            logger.info(f"缓存优化建议: {config}")
            return True
        except Exception as e:
            logger.error(f"缓存优化失败: {e}")
            return False
    
    def _optimize_concurrency(self, config: Dict[str, Any]) -> bool:
        """优化并发设置"""
        try:
            # 这里可以动态调整并发设置
            logger.info(f"并发优化建议: {config}")
            return True
        except Exception as e:
            logger.error(f"并发优化失败: {e}")
            return False
    
    def _optimize_memory(self, config: Dict[str, Any]) -> bool:
        """优化内存使用"""
        try:
            if config['action'] == 'reduce_cache_size':
                self.monitor.clear_history()
                logger.info("已清理查询历史以优化内存使用")
                return True
            return False
        except Exception as e:
            logger.error(f"内存优化失败: {e}")
            return False


# 全局性能监控器实例
_performance_monitor = None
_performance_optimizer = None


def get_performance_monitor() -> PerformanceMonitor:
    """获取全局性能监控器实例"""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor


def get_performance_optimizer() -> PerformanceOptimizer:
    """获取全局性能优化器实例"""
    global _performance_optimizer
    if _performance_optimizer is None:
        monitor = get_performance_monitor()
        _performance_optimizer = PerformanceOptimizer(monitor)
    return _performance_optimizer


def record_query_performance(query: str, execution_time: float, success: bool,
                           error_message: Optional[str] = None, cache_hit: bool = False,
                           response_size: Optional[int] = None):
    """记录查询性能（便捷函数）"""
    monitor = get_performance_monitor()
    monitor.record_query(query, execution_time, success, error_message, cache_hit, response_size)


def get_performance_report() -> Dict[str, Any]:
    """获取性能报告（便捷函数）"""
    monitor = get_performance_monitor()
    optimizer = get_performance_optimizer()
    
    return {
        'monitor': monitor.analyze_performance(),
        'optimizer': optimizer.auto_optimize(),
        'timestamp': time.time()
    }

