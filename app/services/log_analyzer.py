from __future__ import annotations

import logging
import json
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError, NotFoundError

from app.core.config import SETTINGS, REDIS_CACHE
from app.services.notifiers import notify_workwechat
# 已移除对 Dify 的直接调用以避免发送原始日志到外部服务

logger = logging.getLogger(__name__)


class LogAnalyzer:
    """日志智能分析器"""
    
    def __init__(self):
        # ELK连接配置
        self.es_host = SETTINGS.es_host
        self.es_port = SETTINGS.es_port
        self.es_index_pattern = SETTINGS.es_index_pattern
        self.es_field = SETTINGS.es_log_field
        
        # 中文业务类别提取规则
        self.business_patterns = {
            "业务模块": r"【([^】]+)】",  # 匹配【】中的内容
            "功能模块": r"([A-Z_]+模块)",  # 匹配大写下划线模块
            "服务名称": r"([A-Za-z]+Service)",  # 匹配Service结尾的类
            "控制器": r"([A-Za-z]+Controller)",  # 匹配Controller结尾的类
        }
        
        # 数据清洗和汇总配置
        self.data_cleaning_config = {
            "max_message_length": 500,  # 消息最大长度
            "min_confidence_threshold": 0.7,  # 最小置信度阈值
            "batch_size_for_dify": 100,  # 发送给Dify的批次大小
            "cache_ttl": 3600,  # 缓存过期时间（秒）
            "aggregation_window": 24  # 聚合时间窗口（小时）
        }
        
        # 中文错误类型映射
        self.chinese_error_mapping = {
            "获取失败": "数据获取异常",
            "保存失败": "数据保存异常", 
            "更新失败": "数据更新异常",
            "删除失败": "数据删除异常",
            "查询失败": "数据查询异常",
            "校验失败": "校验异常",
            "校验异常": "校验异常",
            "验证失败": "校验异常",
            "参数错误": "校验异常",
            "连接失败": "连接异常",
            "调用失败": "服务调用异常",
            "处理失败": "业务处理异常",
            "验证失败": "数据验证异常",
            "解析失败": "数据解析异常",
            "转换失败": "数据转换异常",
            "上传失败": "文件上传异常",
            "下载失败": "文件下载异常",
            "发送失败": "消息发送异常",
            "接收失败": "消息接收异常",
            "同步失败": "数据同步异常",
            "异步失败": "异步处理异常",
            "缓存失败": "缓存操作异常",
            "锁失败": "并发锁异常",
            "事务失败": "事务处理异常"
        }
        
        # 错误分类规则
        self.error_patterns = {
            "网络超时": [
                r"timeout",
                r"connection.*timed out",
                r"read.*timeout",
                r"write.*timeout",
                r"connect.*timeout",
                r"request.*timeout",
                r"operation.*timeout"
            ],
            "DNS解析失败": [
                r"dns.*resolve.*fail",
                r"dns.*not.*found",
                r"unknown.*host",
                r"could not resolve host"
            ],
            "SSL证书错误": [
                r"ssl.*error",
                r"certificate.*verify.*failed",
                r"ssl.*handshake.*failed",
                r"tls.*error"
            ],
            "连接被重置": [
                r"connection.*reset",
                r"connection.*aborted",
                r"connection.*closed.*by.*remote"
            ],
            "端口不可达": [
                r"port.*unreachable",
                r"connection.*refused",
                r"no.*route.*to.*host"
            ],
            "数据库连接失败": [
                r"database.*connection.*failed",
                r"db.*connection.*error",
                r"mysql.*connection.*failed",
                r"postgresql.*connection.*failed",
                r"mongodb.*connection.*failed",
                r"redis.*connection.*failed",
                r"connection.*refused",
                r"connection.*reset",
                r"connection.*closed"
            ],
            "SQL语法错误": [
                r"syntax.*error.*at",
                r"sql.*parse.*error",
                r"you.*have.*an.*error.*in.*your.*sql.*syntax"
            ],
            "主从同步异常": [
                r"replication.*error",
                r"slave.*io.*error",
                r"master.*has.*sent.*all.*binlog",
                r"replication.*stopped"
            ],
            "数据库死锁": [
                r"deadlock.*found",
                r"lock.*wait.*timeout",
                r"could not obtain lock"
            ],
            "唯一约束冲突": [
                r"duplicate.*entry",
                r"unique.*constraint.*failed",
                r"violates.*unique.*constraint"
            ],
            "NullPointerException": [
                r"nullpointerexception",
                r"null.*pointer",
                r"null.*reference",
                r"attempt.*null",
                r"cannot.*null"
            ],
            "类型转换错误": [
                r"type.*cast.*error",
                r"cannot.*convert",
                r"invalid.*type.*conversion"
            ],
            "数组越界": [
                r"index.*out.*of.*range",
                r"array.*index.*out.*of.*bounds",
                r"list.*index.*out.*of.*range"
            ],
            "断言失败": [
                r"assertion.*failed",
                r"assert.*error"
            ],
            "API限流": [
                r"rate.*limit.*exceeded",
                r"too.*many.*requests",
                r"quota.*exceeded"
            ],
            "第三方认证失败": [
                r"authentication.*failed",
                r"invalid.*token",
                r"unauthorized",
                r"forbidden"
            ],
            "第三方超时": [
                r"external.*service.*timeout",
                r"upstream.*timeout",
                r"dependency.*timeout"
            ],
            "SQL注入": [
                r"sql.*injection",
                r"detected.*sql.*injection"
            ],
            "XSS攻击": [
                r"cross.*site.*scripting",
                r"xss.*attack"
            ],
            "CSRF攻击": [
                r"csrf.*attack",
                r"cross.*site.*request.*forgery"
            ],
            "CPU过载": [
                r"cpu.*overload",
                r"cpu.*usage.*high",
                r"cpu.*limit.*exceeded"
            ],
            "线程池耗尽": [
                r"thread.*pool.*exhausted",
                r"no.*available.*threads"
            ],
            "句柄泄漏": [
                r"handle.*leak",
                r"too.*many.*open.*files"
            ],
            "文件不存在": [
                r"file.*not.*found",
                r"no.*such.*file",
                r"cannot.*find.*file"
            ],
            "文件权限错误": [
                r"permission.*denied",
                r"access.*denied",
                r"read.*only.*file"
            ],
            "文件损坏": [
                r"file.*corrupt",
                r"file.*damaged"
            ],
            "内存不足": [
                r"out.*of.*memory",
                r"memory.*full",
                r"heap.*space",
                r"gc.*overhead",
                r"memory.*leak"
            ],
            "磁盘空间不足": [
                r"disk.*full",
                r"no.*space.*left",
                r"disk.*space.*exhausted",
                r"storage.*full"
            ],
            "权限拒绝": [
                r"permission.*denied",
                r"access.*denied",
                r"unauthorized",
                r"forbidden",
                r"insufficient.*privileges"
            ],
            "服务不可用": [
                r"service.*unavailable",
                r"service.*down",
                r"service.*not.*found",
                r"endpoint.*not.*found",
                r"503.*service.*unavailable"
            ],
            # 新增：微服务相关错误
            "微服务调用失败": [
                r"microservice.*call.*failed",
                r"service.*invocation.*failed",
                r"rpc.*call.*failed",
                r"grpc.*error",
                r"service.*mesh.*error"
            ],
            "服务发现失败": [
                r"service.*discovery.*failed",
                r"consul.*error",
                r"etcd.*error",
                r"service.*registry.*error"
            ],
            "负载均衡错误": [
                r"load.*balancer.*error",
                r"upstream.*unavailable",
                r"backend.*unhealthy",
                r"health.*check.*failed"
            ],
            "熔断器触发": [
                r"circuit.*breaker.*open",
                r"circuit.*breaker.*triggered",
                r"fallback.*triggered"
            ],
            # 新增：容器和Kubernetes相关错误
            "容器启动失败": [
                r"container.*start.*failed",
                r"docker.*error",
                r"container.*exited.*with.*code",
                r"pod.*failed.*to.*start"
            ],
            "镜像拉取失败": [
                r"image.*pull.*failed",
                r"docker.*pull.*error",
                r"registry.*error"
            ],
            "Kubernetes资源不足": [
                r"insufficient.*cpu",
                r"insufficient.*memory",
                r"resource.*quota.*exceeded",
                r"node.*pressure"
            ],
            "Pod调度失败": [
                r"pod.*scheduling.*failed",
                r"no.*nodes.*available",
                r"taint.*tolerations"
            ],
            "存储卷挂载失败": [
                r"volume.*mount.*failed",
                r"persistent.*volume.*error",
                r"storage.*class.*not.*found"
            ],
            # 新增：云原生和DevOps相关错误
            "CI/CD流水线失败": [
                r"pipeline.*failed",
                r"build.*failed",
                r"deployment.*failed",
                r"jenkins.*error",
                r"gitlab.*ci.*error"
            ],
            "配置管理错误": [
                r"config.*not.*found",
                r"configuration.*error",
                r"env.*var.*missing",
                r"secret.*not.*found"
            ],
            "监控告警": [
                r"alert.*triggered",
                r"metric.*threshold.*exceeded",
                r"prometheus.*error",
                r"grafana.*error"
            ],
            "日志聚合错误": [
                r"log.*aggregation.*failed",
                r"fluentd.*error",
                r"logstash.*error",
                r"elasticsearch.*error"
            ],
            # 新增：安全相关错误
            "认证失败": [
                r"authentication.*failed",
                r"login.*failed",
                r"invalid.*credentials",
                r"user.*not.*found"
            ],
            "授权失败": [
                r"authorization.*failed",
                r"access.*denied",
                r"insufficient.*permissions",
                r"role.*not.*found"
            ],
            "证书过期": [
                r"certificate.*expired",
                r"ssl.*cert.*expired",
                r"tls.*cert.*expired"
            ],
            "安全扫描失败": [
                r"security.*scan.*failed",
                r"vulnerability.*detected",
                r"security.*violation"
            ],
            # 新增：性能相关错误
            "响应时间过长": [
                r"response.*time.*exceeded",
                r"slow.*query",
                r"performance.*degradation",
                r"latency.*high"
            ],
            "并发处理错误": [
                r"concurrent.*modification",
                r"race.*condition",
                r"deadlock.*detected",
                r"thread.*safety.*violation"
            ],
            "缓存失效": [
                r"cache.*miss",
                r"cache.*invalidation",
                r"cache.*expired",
                r"cache.*corruption"
            ],
            "队列积压": [
                r"queue.*overflow",
                r"message.*queue.*full",
                r"backlog.*exceeded",
                r"consumer.*lag"
            ]
        }
        
        # 预编译常用清洗正则
        self._ansi_escape_re = re.compile(r"\x1b\[[0-9;]*m")
        self._leading_brackets_re = re.compile(r"^(?:【[^】]*】\s*)+")
        self._kv_split_re = re.compile(r"\s+[A-Za-z_][A-Za-z0-9_]*=")

        # 监控阈值配置
        self.thresholds = {
            "error_count_5min": 50,  # 5分钟内同类错误超过50条
            "error_growth_1hour": 0.5,  # 1小时内错误数量相比上小时增长50%以上
            "critical_error_count": 100,  # 严重错误数量阈值
            "error_duration": 300,  # 错误持续时间阈值（秒）
            "minute_total_count": 1000  # 上一分钟日志总数阈值
        }
        
        # 初始化Elasticsearch客户端
        self.es_client = None
        self._init_es_client()
        
        # 错误统计缓存
        self.error_stats = defaultdict(lambda: {
            "count": 0,
            "recent_count": 0,  # 最近5分钟的错误数量
            "last_seen": None,
            "first_seen": None,
            "instances": set(),
            "severity": "info",
            "category": "未知",
            "last_alert_time": None
        })
        
        # 监控线程
        self.monitoring_thread = None
        self.stop_monitoring = False
        
        # 线程池
        self.executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="log_analyzer")
        
        # 告警历史记录
        self.alert_history = {}
        
        # 时间窗口统计
        self.time_windows = {
            "5min": [],
            "1hour": [],
            "24hour": []
        }
        # 上一分钟总量告警去抖
        self._last_minute_total_alert_ts: Optional[datetime] = None
        
        # 数据清洗和汇总缓存
        self.cleaned_data_cache = {}
        self.aggregated_stats_cache = {}
        self.dify_analysis_cache = {}
    
    def _parse_timestamp(self, ts: Any, fallback: Optional[datetime] = None) -> datetime:
        """将多种时间格式解析为 datetime 对象。
        支持 ISO 字符串（含/不含 Z），datetime 对象，或时间戳（秒）。
        """
        if isinstance(ts, datetime):
            dt = ts
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        if ts is None:
            return (fallback.astimezone(timezone.utc) if (fallback and fallback.tzinfo) else (fallback or datetime.now(timezone.utc)))
        try:
            # ISO 格式，兼容 Z 结尾
            if isinstance(ts, str):
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            # 数字型时间戳（秒）
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except Exception:
            pass
        return (fallback.astimezone(timezone.utc) if (fallback and fallback.tzinfo) else (fallback or datetime.now(timezone.utc)))
    
    def _init_es_client(self):
        """初始化Elasticsearch客户端"""
        try:
            es_url = f"http://{self.es_host}:{self.es_port}"
            
            # 使用认证信息创建Elasticsearch客户端
            auth = (SETTINGS.es_username, SETTINGS.es_password) if SETTINGS.es_username and SETTINGS.es_password else None
            self.es_client = Elasticsearch(
                [es_url], 
                request_timeout=SETTINGS.es_connection_timeout, 
                max_retries=SETTINGS.es_max_retries,
                basic_auth=auth
            )
            
            # 测试连接
            if self.es_client.ping():
                logger.info(f"Elasticsearch connected to {es_url} with user: {SETTINGS.es_username}")
            else:
                logger.error(f"Elasticsearch connection failed to {es_url}")
                self.es_client = None
        except Exception as e:
            logger.error(f"Failed to initialize Elasticsearch client: {e}")
            self.es_client = None
    
    def classify_error(self, message: str) -> Tuple[str, str]:
        """
        对错误日志进行分类
        
        Args:
            message: 错误日志消息
            
        Returns:
            Tuple[错误类别, 严重程度]
        """
        if not message:
            return "未知错误", "info"
        
        message_lower = message.lower()
        
        # 按优先级匹配错误模式
        for category, patterns in self.error_patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    # 确定严重程度
                    severity = self._determine_severity(message_lower, category)
                    return category, severity
        
        # 如果没有匹配到预定义模式，尝试智能分类
        return self._smart_classify(message), "warning"
    
    def _determine_severity(self, message: str, category: str) -> str:
        """确定错误严重程度"""
        # 严重错误关键词
        critical_keywords = [
            "fatal", "critical", "emergency", "panic", "crash", "abort",
            "out of memory", "disk full", "connection refused", "service down"
        ]
        
        # 警告级别关键词
        warning_keywords = [
            "warning", "warn", "deprecated", "deprecation", "legacy"
        ]
        
        # 检查严重程度
        if any(keyword in message for keyword in critical_keywords):
            return "critical"
        elif any(keyword in message for keyword in warning_keywords):
            return "warning"
        elif category in ["NullPointerException", "内存不足", "磁盘空间不足"]:
            return "critical"
        elif category in ["网络超时", "数据库连接失败", "服务不可用"]:
            return "warning"
        else:
            return "info"
    
    def _smart_classify(self, message: str) -> str:
        """智能分类未知错误"""
        message_lower = message.lower()
        
        # 基于关键词的智能分类
        if any(word in message_lower for word in ["error", "exception", "failed", "failure"]):
            if any(word in message_lower for word in ["http", "api", "rest"]):
                return "API调用异常"
            elif any(word in message_lower for word in ["file", "io", "stream"]):
                return "文件IO异常"
            elif any(word in message_lower for word in ["thread", "concurrent", "lock"]):
                return "并发处理异常"
            elif any(word in message_lower for word in ["cache", "redis", "memory"]):
                return "缓存异常"
            else:
                return "通用异常"
        
        return "未知错误"
    
    def _advanced_classify(self, message: str, context: Dict[str, Any] = None) -> Tuple[str, str, Dict[str, Any]]:
        """
        高级智能分类，基于上下文和模式识别
        
        Args:
            message: 错误消息
            context: 上下文信息（logger, host, instance等）
            
        Returns:
            Tuple[错误类别, 严重程度, 额外信息]
        """
        message_lower = message.lower()
        context = context or {}
        
        # 提取关键信息
        extra_info = {
            "confidence": 0.0,
            "matched_patterns": [],
            "context_hints": [],
            "suggested_actions": []
        }
        
        # 基于上下文的分类增强
        logger_name = context.get("logger", "").lower()
        host = context.get("host", "").lower()
        instance = context.get("instance", "").lower()
        
        # 数据库相关错误检测
        if any(db_hint in message_lower for db_hint in ["mysql", "postgresql", "mongodb", "redis", "oracle", "sqlite"]):
            if "connection" in message_lower:
                return "数据库连接失败", "warning", extra_info
            elif "syntax" in message_lower or "sql" in message_lower:
                return "SQL语法错误", "warning", extra_info
            elif "deadlock" in message_lower:
                return "数据库死锁", "critical", extra_info
            else:
                return "数据库异常", "warning", extra_info
        
        # 网络相关错误检测
        if any(net_hint in message_lower for net_hint in ["connection", "network", "socket", "http", "tcp", "udp"]):
            if "timeout" in message_lower:
                return "网络超时", "warning", extra_info
            elif "refused" in message_lower:
                return "连接被拒绝", "warning", extra_info
            elif "reset" in message_lower:
                return "连接被重置", "warning", extra_info
            else:
                return "网络异常", "warning", extra_info
        
        # 容器/K8s相关错误检测
        if any(k8s_hint in message_lower for k8s_hint in ["pod", "container", "kubernetes", "docker", "namespace"]):
            if "start" in message_lower and "failed" in message_lower:
                return "容器启动失败", "critical", extra_info
            elif "pull" in message_lower and "failed" in message_lower:
                return "镜像拉取失败", "warning", extra_info
            elif "scheduling" in message_lower:
                return "Pod调度失败", "critical", extra_info
            else:
                return "容器编排异常", "warning", extra_info
        
        # 微服务相关错误检测
        if any(ms_hint in message_lower for ms_hint in ["service", "microservice", "rpc", "grpc", "consul", "etcd"]):
            if "discovery" in message_lower:
                return "服务发现失败", "critical", extra_info
            elif "circuit" in message_lower and "breaker" in message_lower:
                return "熔断器触发", "warning", extra_info
            else:
                return "微服务异常", "warning", extra_info
        
        # 性能相关错误检测
        if any(perf_hint in message_lower for perf_hint in ["slow", "timeout", "latency", "performance", "memory", "cpu"]):
            if "memory" in message_lower and ("full" in message_lower or "out" in message_lower):
                return "内存不足", "critical", extra_info
            elif "cpu" in message_lower and ("high" in message_lower or "overload" in message_lower):
                return "CPU过载", "warning", extra_info
            elif "timeout" in message_lower:
                return "响应时间过长", "warning", extra_info
            else:
                return "性能异常", "warning", extra_info
        
        # 安全相关错误检测
        if any(sec_hint in message_lower for sec_hint in ["authentication", "authorization", "permission", "security", "certificate"]):
            if "certificate" in message_lower and "expired" in message_lower:
                return "证书过期", "critical", extra_info
            elif "authentication" in message_lower:
                return "认证失败", "warning", extra_info
            elif "authorization" in message_lower:
                return "授权失败", "warning", extra_info
            else:
                return "安全异常", "warning", extra_info
        
        # 基于logger名称的分类
        if logger_name:
            if "db" in logger_name or "database" in logger_name:
                return "数据库异常", "warning", extra_info
            elif "http" in logger_name or "web" in logger_name:
                return "Web服务异常", "warning", extra_info
            elif "cache" in logger_name or "redis" in logger_name:
                return "缓存异常", "warning", extra_info
            elif "queue" in logger_name or "kafka" in logger_name:
                return "消息队列异常", "warning", extra_info
        
        # 基于实例名称的分类
        if instance:
            if "db" in instance or "mysql" in instance or "redis" in instance:
                return "数据库异常", "warning", extra_info
            elif "api" in instance or "service" in instance:
                return "API服务异常", "warning", extra_info
            elif "cache" in instance:
                return "缓存异常", "warning", extra_info
        
        # 默认分类
        return "未知错误", "info", extra_info
    
    def classify_error_with_context(self, message: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        带上下文的错误分类，返回详细信息
        
        Args:
            message: 错误消息
            context: 上下文信息
            
        Returns:
            分类结果字典
        """
        # 首先尝试模式匹配
        category, severity = self.classify_error(message)
        
        # 如果匹配到预定义模式，使用高级分类增强信息
        if category != "未知错误":
            _, _, extra_info = self._advanced_classify(message, context)
            return {
                "category": category,
                "severity": severity,
                "confidence": 0.9,
                "method": "pattern_match",
                "context_hints": extra_info.get("context_hints", []),
                "suggested_actions": self._get_suggested_actions(category, severity)
            }
        
        # 否则使用高级分类
        category, severity, extra_info = self._advanced_classify(message, context)
        return {
            "category": category,
            "severity": severity,
            "confidence": extra_info.get("confidence", 0.7),
            "method": "smart_classify",
            "context_hints": extra_info.get("context_hints", []),
            "suggested_actions": self._get_suggested_actions(category, severity)
        }
    
    def _get_suggested_actions(self, category: str, severity: str) -> List[str]:
        """根据错误类别和严重程度提供建议操作"""
        actions = []
        
        if category == "数据库连接失败":
            actions.extend([
                "检查数据库服务状态",
                "验证连接配置",
                "检查网络连通性",
                "查看数据库日志"
            ])
        elif category == "内存不足":
            actions.extend([
                "检查内存使用情况",
                "分析内存泄漏",
                "考虑增加内存或优化代码",
                "重启相关服务"
            ])
        elif category == "网络超时":
            actions.extend([
                "检查网络连通性",
                "验证目标服务状态",
                "调整超时配置",
                "检查防火墙设置"
            ])
        elif category == "容器启动失败":
            actions.extend([
                "检查容器镜像",
                "验证资源配置",
                "查看容器日志",
                "检查存储卷挂载"
            ])
        elif category == "微服务调用失败":
            actions.extend([
                "检查服务注册状态",
                "验证服务发现配置",
                "检查负载均衡器",
                "查看服务间网络"
            ])
        
        # 根据严重程度添加通用建议
        if severity == "critical":
            actions.insert(0, "立即处理 - 影响系统稳定性")
        elif severity == "warning":
            actions.insert(0, "及时处理 - 可能影响用户体验")
        
        return actions
    
    def analyze_chinese_error(self, message: str) -> Dict[str, Any]:
        """
        分析中文错误信息
        
        Args:
            message: 日志消息
            
        Returns:
            错误分析结果
        """
        result = {
            "error_type": "未知错误",
            "error_category": "未知类别",
            "severity": "info",
            "business_context": "",
            "technical_details": {},
            "suggested_actions": []
        }
        
        try:
            # 提取业务上下文
            business_info = self.extract_business_category(message)
            result["business_context"] = business_info["business_module"]
            
            # 分析错误类型
            message_lower = message.lower()
            
            # 检查NullPointerException
            if "nullpointerexception" in message_lower or "空指针" in message:
                result["error_type"] = "空指针异常"
                result["error_category"] = "应用异常"
                result["severity"] = "critical"
                result["technical_details"]["异常类型"] = "NullPointerException"
                result["suggested_actions"] = [
                    "检查对象是否为空",
                    "添加空值检查",
                    "查看调用链中的空值传递"
                ]
            
            # 检查中文错误描述
            for chinese_error, mapped_category in self.chinese_error_mapping.items():
                if chinese_error in message:
                    result["error_type"] = mapped_category
                    result["error_category"] = "业务异常"
                    result["severity"] = "warning"
                    result["technical_details"]["错误描述"] = chinese_error
                    break
            
            # 检查数据库相关错误
            if any(db_hint in message_lower for db_hint in ["dataaccessexception", "sqlexception", "数据库"]):
                result["error_category"] = "数据库异常"
                result["severity"] = "warning"
                result["suggested_actions"].extend([
                    "检查数据库连接状态",
                    "验证SQL语句语法",
                    "查看数据库日志"
                ])
            
            # 检查网络相关错误
            if any(net_hint in message_lower for net_hint in ["connection", "timeout", "网络"]):
                result["error_category"] = "网络异常"
                result["severity"] = "warning"
                result["suggested_actions"].extend([
                    "检查网络连通性",
                    "验证服务地址",
                    "调整超时配置"
                ])
            
            # 添加业务上下文相关的建议
            if business_info["business_module"]:
                result["suggested_actions"].insert(0, f"检查{business_info['business_module']}相关配置")
            
            # 合并提取的详细信息
            result["technical_details"].update(business_info["extracted_info"])
            
        except Exception as e:
            logger.error(f"分析中文错误失败: {e}")
        
        return result
    
    def collect_recent_logs(self, minutes: int = 1) -> List[Dict[str, Any]]:
        """
        收集最近N分钟的日志
        
        Args:
            minutes: 最近N分钟
            
        Returns:
            日志列表
        """
        if not self.es_client:
            logger.error("Elasticsearch client not available")
            return []
        
        try:
            logger.info(f"开始查询最近 {minutes} 分钟的日志，索引模式: {self.es_index_pattern}")
            if SETTINGS.ai_assist_enabled:
                if SETTINGS.dify_enabled and SETTINGS.dify_api_key:
                    logger.info("AI分析已启用，将使用Dify进行日志分类")
                else:
                    logger.info("AI分析已启用，将使用Xinference进行日志分类")
            else:
                logger.info("AI分析未启用，仅使用规则分类")

            # 候选时间与消息字段，最大化兼容不同索引结构
            time_fields = ["@timestamp", "timestamp", "ts", "time"]
            candidate_message_fields = [
                self.es_field,
                "message",
                "log",
                "log.original",
                "msg",
                "error.message",
                "message_text",
            ]

            # 使用 should+minimum_should_match 以匹配任意一个可用消息字段
            exists_should = [{"exists": {"field": f}} for f in candidate_message_fields]
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"range": {time_fields[0]: {"gte": f"now-{minutes}m"}}}
                        ],
                        "should": exists_should,
                        "minimum_should_match": 1
                    }
                },
                "sort": [{time_fields[0]: {"order": "desc"}}],
                "size": getattr(SETTINGS, "es_max_results_per_query", 500)
            }
            
            logger.info(f"查询超时设置: {SETTINGS.es_query_timeout}秒")
            logger.info(f"查询条件: {json.dumps(query, ensure_ascii=False)}")
            
            response = self.es_client.search(
                index=self.es_index_pattern,
                body={**query, **({"track_total_hits": SETTINGS.es_track_total_hits} if hasattr(SETTINGS, "es_track_total_hits") else {})},
                request_timeout=SETTINGS.es_query_timeout
            )
            
            total_hits = response.get("hits", {}).get("total", {}).get("value", 0)
            logger.info(f"ELK查询结果: 总命中数={total_hits}, 索引={self.es_index_pattern}")
            
            logs: List[Dict[str, Any]] = []
            ai_used = 0
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})

                # 选择时间字段
                ts_val = None
                for tf in time_fields:
                    if tf in source:
                        ts_val = source.get(tf)
                        break

                # 选择消息字段（按候选顺序取第一个非空）
                message = None
                for field_name in candidate_message_fields:
                    val = source.get(field_name)
                    if isinstance(val, str) and val.strip():
                        message = val
                        break

                # 跳过无消息的文档
                if not message:
                    continue

                log_entry = {
                    "id": hit.get("_id"),
                    "timestamp": ts_val,
                    "message": message,
                    "level": source.get("level", "error"),
                    "logger": source.get("logger", ""),
                    "thread": source.get("thread", ""),
                    "host": source.get("host", ""),
                    "instance": source.get("instance", ""),
                    "tags": source.get("tags", [])
                }
                
                # 添加中文业务分析
                business_info = self.extract_business_category(message)
                error_analysis = self.analyze_chinese_error(message)
                
                # 明确禁用将日志发送给 Dify 的路径；仅使用本地规则完成分类与提取
                
                log_entry.update({
                    "business_analysis": business_info,
                    "error_analysis": error_analysis
                })
                
                logs.append(log_entry)
            
            logger.info(f"成功收集 {len(logs)} 条日志记录")
            return logs
            
        except Exception as e:
            logger.error(f"收集最近日志失败: {e}")
            logger.error(f"错误详情: {type(e).__name__}: {str(e)}")
            return []
    
    def analyze_recent_logs(self, minutes: int = 1) -> Dict[str, Any]:
        """
        分析最近N分钟的日志，先进行数据清洗和存储，再用于页面渲染
        
        Args:
            minutes: 最近N分钟
            
        Returns:
            分析结果
        """
        # 1. 从ELK收集原始日志
        raw_logs = self.collect_recent_logs(minutes)
        
        if not raw_logs:
            return {
                "total_logs": 0,
                "time_range": f"最近{minutes}分钟",
                "business_modules": {},
                "error_categories": {},
                "error_types": {},
                "severity_distribution": {},
                "recent_errors": [],
                "cleaned_logs_count": 0,
                "processing_status": "no_logs_found"
            }
        
        # 2. 进行数据清洗和归类
        cleaned_logs = self.clean_log_data(raw_logs)
        
        # 3. 存储清洗后的数据
        self._store_cleaned_logs(cleaned_logs, minutes)
        
        # 4. 生成统计信息（基于清洗后的数据）
        local_stats = self.aggregate_log_statistics(cleaned_logs)
        
        # 5. 读取累计错误类型统计（不在此更新，避免与调度器重复累计）
        try:
            cumulative_error_types = self._get_cumulative_error_types()
        except Exception as e:
            logger.warning(f"读取累计错误类型统计失败: {e}")
            cumulative_error_types = {}
        
        # 6. 格式化业务模块信息
        business_modules = {}
        for module, count in local_stats.get("business_modules", {}).items():
            business_modules[module] = {
                "count": count,
                "errors": [],
                "instances": set()
            }
            
            # 添加错误示例
            for log in cleaned_logs:
                if log.get("business_analysis", {}).get("business_module") == module:
                    business_modules[module]["instances"].add(log.get("instance", "unknown"))
                    if len(business_modules[module]["errors"]) < 3:
                        business_modules[module]["errors"].append({
                            "message": log["message"][:100] + "..." if len(log["message"]) > 100 else log["message"],
                            "timestamp": log["timestamp"],
                            "error_type": log.get("error_analysis", {}).get("error_type", "未知"),
                            "severity": log.get("error_analysis", {}).get("severity", "unknown")
                        })
        
        # 转换为可序列化的格式
        for module, info in business_modules.items():
            info["instances"] = list(info["instances"])
        
        # 7. 构建结果（不包含Dify分析）
        result = {
            "total_logs": len(raw_logs),
            "cleaned_logs_count": len(cleaned_logs),
            "time_range": f"最近{minutes}分钟",
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            "processing_status": "cleaned_and_stored",
            "business_modules": business_modules,
            "error_categories": local_stats.get("error_patterns", {}),
            # 类型分布返回累计统计（按需由调度器每分钟累加）
            "error_types": cumulative_error_types,
            # 同时附带窗口统计供参考
            "error_types_window": local_stats.get("error_types", {}),
            # 兼容字段
            "error_types_cumulative": cumulative_error_types,
            "severity_distribution": local_stats.get("level_distribution", {}),
            "recent_errors": cleaned_logs[:10],  # 最近10条清洗后的错误详情
            "cleaning_summary": {
                "raw_logs_count": len(raw_logs),
                "cleaned_logs_count": len(cleaned_logs),
                "duplicates_removed": len(raw_logs) - len(cleaned_logs),
                "business_modules_found": len(business_modules),
                "error_categories_found": len(local_stats.get("error_patterns", {})),
                "cleaning_timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        
        # 8. 缓存结果
        cache_key = f"recent_analysis_{minutes}m_{datetime.now(timezone.utc).strftime('%Y%m%d_%H')}"
        self.cache_analysis_results([result], cache_key)
        
        logger.info(f"日志分析完成: 原始日志{len(raw_logs)}条, 清洗后{len(cleaned_logs)}条, 业务模块{len(business_modules)}个")
        
        return result

    def _get_cumulative_error_types(self, scope: str = "global") -> Dict[str, int]:
        """读取累计错误类型统计（Redis Hash为权威来源）。"""
        date_key = datetime.now(timezone.utc).strftime("%Y%m%d") if scope == "daily" else "global"
        hash_key = f"log:cumulative:error_types:{date_key}:hash"
        try:
            # 优先从Redis哈希读取，避免JSON竞争覆盖
            hash_map = REDIS_CACHE.hgetall(hash_key)
            if isinstance(hash_map, dict) and hash_map:
                # 转为int
                return {k: int(v) for k, v in hash_map.items() if v is not None}
        except Exception:
            pass
        # 兼容旧JSON键
        legacy_key = f"log:cumulative:error_types:{date_key}"
        try:
            data = REDIS_CACHE.get(legacy_key)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        mem = self.aggregated_stats_cache.get(legacy_key)
        return mem if isinstance(mem, dict) else {}

    def _update_cumulative_error_types(self, new_counts: Dict[str, int], scope: str = "global") -> Dict[str, int]:
        """原子地将本次统计的错误类型计数累加到Redis哈希中并返回累计结果。
        使用哈希字段自增，避免多进程/多服务器并发覆盖。
        """
        if not isinstance(new_counts, dict) or not new_counts:
            return self._get_cumulative_error_types(scope)

        date_key = datetime.now(timezone.utc).strftime("%Y%m%d") if scope == "daily" else "global"
        hash_key = f"log:cumulative:error_types:{date_key}:hash"

        # 使用pipeline原子自增；daily 设置较长TTL，global 不设置TTL
        try:
            ttl_seconds = (3 * 24 * 3600) if scope == "daily" else None
            REDIS_CACHE.hincrby_mapping(
                hash_key,
                {str(k): int(v) for k, v in new_counts.items()},
                ttl_seconds=ttl_seconds,
            )
        except Exception:
            pass

        # 读取最新结果
        cumulative = {}
        try:
            m = REDIS_CACHE.hgetall(hash_key)
            if isinstance(m, dict):
                cumulative = {k: int(v) for k, v in m.items() if v is not None}
        except Exception:
            cumulative = {}

        # 内存也保存一份便于本进程快速访问
        legacy_key = f"log:cumulative:error_types:{date_key}"
        self.aggregated_stats_cache[legacy_key] = dict(cumulative)
        return cumulative

    def _store_cleaned_logs(self, cleaned_logs: List[Dict[str, Any]], minutes: int) -> None:
        """
        存储清洗后的日志数据
        
        Args:
            cleaned_logs: 清洗后的日志列表
            minutes: 时间范围
        """
        try:
            # 生成存储键
            storage_key = f"cleaned_logs_{minutes}m_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"
            
            # 存储到内存缓存
            self.cleaned_data_cache[storage_key] = {
                "logs": cleaned_logs,
                "count": len(cleaned_logs),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "time_range": f"最近{minutes}分钟"
            }
            
            # 存储到Redis（如果可用）
            try:
                if hasattr(self, 'redis_client') and self.redis_client:
                    redis_key = f"cleaned_logs:{storage_key}"
                    self.redis_client.setex(
                        redis_key,
                        3600,  # 1小时过期
                        json.dumps({
                            "logs": cleaned_logs,
                            "count": len(cleaned_logs),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "time_range": f"最近{minutes}分钟"
                        }, ensure_ascii=False, default=str)
                    )
                    logger.info(f"清洗后的日志已存储到Redis: {redis_key}")
            except Exception as e:
                logger.warning(f"存储到Redis失败: {e}")
            
            # 存储统计摘要
            stats_key = f"cleaned_stats_{minutes}m_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"
            self.cleaned_data_cache[stats_key] = {
                "total_logs": len(cleaned_logs),
                "level_distribution": {},
                "instance_distribution": {},
                "business_modules": {},
                "error_categories": {},
                "severity_distribution": {},
                "critical_errors": [],
                "recent_errors": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "time_range": f"最近{minutes}分钟"
            }
            
            # 计算统计信息
            for log in cleaned_logs:
                # 级别分布
                level = log.get("level", "unknown")
                self.cleaned_data_cache[stats_key]["level_distribution"][level] = \
                    self.cleaned_data_cache[stats_key]["level_distribution"].get(level, 0) + 1
                
                # 实例分布
                instance = log.get("instance", "unknown")
                self.cleaned_data_cache[stats_key]["instance_distribution"][instance] = \
                    self.cleaned_data_cache[stats_key]["instance_distribution"].get(instance, 0) + 1
                
                # 业务模块
                business_module = log.get("business_analysis", {}).get("business_module", "未知模块")
                self.cleaned_data_cache[stats_key]["business_modules"][business_module] = \
                    self.cleaned_data_cache[stats_key]["business_modules"].get(business_module, 0) + 1
                
                # 错误类别
                error_category = log.get("error_analysis", {}).get("error_category", "未知类别")
                self.cleaned_data_cache[stats_key]["error_categories"][error_category] = \
                    self.cleaned_data_cache[stats_key]["error_categories"].get(error_category, 0) + 1
                
                # 严重程度
                severity = log.get("error_analysis", {}).get("severity", "unknown")
                self.cleaned_data_cache[stats_key]["severity_distribution"][severity] = \
                    self.cleaned_data_cache[stats_key]["severity_distribution"].get(severity, 0) + 1
                
                # 严重错误
                if severity in ["critical", "high"]:
                    self.cleaned_data_cache[stats_key]["critical_errors"].append({
                        "message": log.get("message", "")[:200],
                        "timestamp": log.get("timestamp", ""),
                        "instance": log.get("instance", ""),
                        "category": error_category,
                        "business_module": business_module
                    })
                
                # 最近错误
                if len(self.cleaned_data_cache[stats_key]["recent_errors"]) < 10:
                    self.cleaned_data_cache[stats_key]["recent_errors"].append({
                        "message": log.get("message", "")[:200],
                        "timestamp": log.get("timestamp", ""),
                        "instance": log.get("instance", ""),
                        "category": error_category,
                        "severity": severity,
                        "business_module": business_module
                    })
            
            logger.info(f"清洗后的日志统计已存储: {stats_key}")
            
        except Exception as e:
            logger.error(f"存储清洗后的日志失败: {e}")
            import traceback
            traceback.print_exc()
    
    def collect_logs(self, hours: int = 1) -> List[Dict[str, Any]]:
        """
        从ELK收集错误日志
        
        Args:
            hours: 查询最近几小时的日志
            
        Returns:
            日志列表
        """
        if not self.es_client:
            logger.error("Elasticsearch client not available")
            return []
        try:
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"range": {"@timestamp": {"gte": f"now-{hours}h"}}},
                            {"exists": {"field": self.es_field}}
                        ],
                        "should": [
                            {"match": {self.es_field: "error"}},
                            {"match": {self.es_field: "exception"}},
                            {"match": {self.es_field: "failed"}},
                            {"match": {self.es_field: "failure"}}
                        ],
                        "minimum_should_match": 1
                    }
                },
                "sort": [{"@timestamp": {"order": "desc"}}],
                "size": 1000
            }
            response = self.es_client.search(
                index=self.es_index_pattern,
                body=query,
                request_timeout=30
            )
            logs: List[Dict[str, Any]] = []
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                logs.append({
                    "timestamp": source.get("@timestamp"),
                    "message": source.get(self.es_field, ""),
                    "level": source.get("level", "error"),
                    "logger": source.get("logger", ""),
                    "thread": source.get("thread", ""),
                    "host": source.get("host", ""),
                    "instance": source.get("instance", ""),
                    "tags": source.get("tags", [])
                })
            logger.info(f"Collected {len(logs)} error logs from ELK in last {hours}h")
            return logs
        except Exception as e:
            logger.error(f"Failed to collect logs from ELK: {e}")
            return []
        
    def collect_logs_range(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        """按时间范围从ELK收集错误日志（UTC时间）。"""
        if not self.es_client:
            logger.error("Elasticsearch client not available")
            return []
        try:
            start_utc = self._parse_timestamp(start).isoformat()
            end_utc = self._parse_timestamp(end).isoformat()
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"range": {"@timestamp": {"gte": start_utc, "lt": end_utc}}},
                            {"exists": {"field": self.es_field}}
                        ],
                        "should": [
                            {"match": {self.es_field: "error"}},
                            {"match": {self.es_field: "exception"}},
                            {"match": {self.es_field: "failed"}},
                            {"match": {self.es_field: "failure"}}
                        ],
                        "minimum_should_match": 1
                    }
                },
                "sort": [{"@timestamp": {"order": "asc"}}],
                "size": getattr(SETTINGS, "es_max_results_per_query", 500)
            }
            response = self.es_client.search(index=self.es_index_pattern, body={**query, **({"track_total_hits": SETTINGS.es_track_total_hits} if hasattr(SETTINGS, "es_track_total_hits") else {})}, request_timeout=SETTINGS.es_query_timeout)
            logs = []
            for hit in response.get("hits", {}).get("hits", []):
                source = hit["_source"]
                logs.append({
                    "timestamp": source.get("@timestamp"),
                    "message": source.get(self.es_field, ""),
                    "level": source.get("level", "error"),
                    "logger": source.get("logger", ""),
                    "thread": source.get("thread", ""),
                    "host": source.get("host", ""),
                    "instance": source.get("instance", ""),
                    "tags": source.get("tags", [])
                })
            return logs
        except Exception as e:
            logger.error(f"Failed to collect logs in range: {e}")
            return []

    def count_logs_range(self, start: datetime, end: datetime) -> int:
        """按时间范围统计日志总条数（UTC时间）。"""
        if not self.es_client:
            logger.error("Elasticsearch client not available")
            return 0
        try:
            start_utc = self._parse_timestamp(start).isoformat()
            end_utc = self._parse_timestamp(end).isoformat()
            query = {
                "query": {
                    "range": {
                        "@timestamp": {"gte": start_utc, "lt": end_utc}
                    }
                }
            }
            resp = self.es_client.count(index=self.es_index_pattern, body=query, request_timeout=SETTINGS.es_query_timeout)
            return int(resp.get("count", 0))
        except Exception as e:
            logger.error(f"Failed to count logs in range: {e}")
            return 0

    def get_previous_minute_window(self, now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
        """获取上一分钟的UTC窗口 [start, end)。"""
        now_utc = self._parse_timestamp(now or datetime.now(timezone.utc))
        current_minute = now_utc.replace(second=0, microsecond=0)
        end = current_minute
        start = end - timedelta(minutes=1)
        return start, end

    def analyze_last_minute(self) -> Dict[str, Any]:
        """拉取上一分钟日志，分类并返回分钟统计。"""
        start, end = self.get_previous_minute_window()
        logs = self.collect_logs_range(start, end)
        classified = self.classify_errors(logs)
        # 不在此清空历史窗口，直接增量写入
        self.update_error_stats(classified)
        # 基础分钟统计
        category_counts: Dict[str, int] = defaultdict(int)
        severity_counts: Dict[str, int] = defaultdict(int)
        for c in classified:
            category_counts[c["category"]] += 1
            severity_counts[c["severity"]] += 1
        stats = {
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "total": len(classified),
            "category_counts": dict(category_counts),
            "severity_counts": dict(severity_counts),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        return stats

    def count_last_minute_total(self) -> Dict[str, Any]:
        """统计上一分钟日志总条数并返回窗口与计数。"""
        start, end = self.get_previous_minute_window()
        total = self.count_logs_range(start, end)
        info = {
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "count": total,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        try:
            # 缓存便于前端/其他任务快速读取（60s过期）
            REDIS_CACHE.set_with_ttl("log:last_minute:total", info, 60)
        except Exception as e:
            logger.error(f"缓存上一分钟日志总数失败: {e}")
        # 阈值判断并告警
        try:
            if total > self.thresholds.get("minute_total_count", 1000):
                # 5分钟内不重复提醒
                now_ts = datetime.now(timezone.utc)
                if not self._last_minute_total_alert_ts or (now_ts - self._last_minute_total_alert_ts).total_seconds() >= 300:
                    msg = (
                        f"🚨 日志阈值告警\n"
                        f"上一分钟日志总数: {total} 条，超过阈值 {self.thresholds.get('minute_total_count', 1000)}\n"
                        f"窗口: {info['window']['start']} ~ {info['window']['end']} (UTC)"
                    )
                    notify_workwechat(msg)
                    self._last_minute_total_alert_ts = now_ts
        except Exception as e:
            logger.error(f"发送上一分钟总量阈值告警失败: {e}")
        return info

    def run_last_minute_cycle(self) -> Dict[str, Any]:
        """执行上一分钟日志的采集-分类-更新-阈值检测，并缓存结果。"""
        stats = self.analyze_last_minute()
        alerts = self.check_thresholds()
        try:
            REDIS_CACHE.set_with_ttl("log:last_minute:stats", stats, 60)
            REDIS_CACHE.set_with_ttl("log:threshold_alerts", {"alerts": alerts, "ts": datetime.now(timezone.utc).isoformat()}, 60)
        except Exception as e:
            logger.error(f"缓存日志分钟统计/告警失败: {e}")
        return {"stats": stats, "alerts": alerts}
    
    def classify_errors(self, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        对日志进行错误分类
        
        Args:
            logs: 日志列表
            
        Returns:
            分类后的错误列表
        """
        classified_errors = []
        
        for log in logs:
            message = log.get("message", "")
            category, severity = self.classify_error(message)
            
            # 确保 instance 是字符串类型
            instance = log.get("instance", "unknown")
            if isinstance(instance, dict):
                instance = str(instance)
            elif not isinstance(instance, str):
                instance = str(instance)
            
            classified_error = {
                "timestamp": log.get("timestamp"),
                "message": message,
                "category": category,
                "severity": severity,
                "instance": instance,
                "host": log.get("host", ""),
                "logger": log.get("logger", ""),
                "level": log.get("level", "error")
            }
            
            classified_errors.append(classified_error)
        
        return classified_errors
    
    def update_error_stats(self, classified_errors: List[Dict[str, Any]]) -> None:
        """
        更新错误统计信息
        
        Args:
            classified_errors: 分类后的错误列表
        """
        current_time = datetime.now(timezone.utc)
        
        # 清理过期的时间窗口数据
        self._cleanup_time_windows(current_time)
        
        for error in classified_errors:
            category = error["category"]
            instance = error["instance"]
            severity = error["severity"]
            timestamp = error.get("timestamp")
            ts_dt = self._parse_timestamp(timestamp, fallback=current_time)
            
            # 更新错误统计
            if category not in self.error_stats:
                self.error_stats[category]["first_seen"] = ts_dt
                self.error_stats[category]["category"] = category
                self.error_stats[category]["severity"] = severity
            
            self.error_stats[category]["count"] += 1
            self.error_stats[category]["last_seen"] = ts_dt
            self.error_stats[category]["instances"].add(instance)
            self.error_stats[category]["severity"] = severity
            
            # 添加到时间窗口
            self._add_to_time_window(category, ts_dt)
    
    def _cleanup_time_windows(self, current_time: datetime) -> None:
        """清理过期的时间窗口数据"""
        # 清理5分钟窗口
        cutoff_5min = current_time - timedelta(minutes=5)
        self.time_windows["5min"] = [
            (cat, ts) for cat, ts in self.time_windows["5min"] 
            if (self._parse_timestamp(ts, fallback=current_time) > cutoff_5min)
        ]
        
        # 清理1小时窗口
        cutoff_1hour = current_time - timedelta(hours=1)
        self.time_windows["1hour"] = [
            (cat, ts) for cat, ts in self.time_windows["1hour"] 
            if (self._parse_timestamp(ts, fallback=current_time) > cutoff_1hour)
        ]
        
        # 清理24小时窗口
        cutoff_24hour = current_time - timedelta(hours=24)
        self.time_windows["24hour"] = [
            (cat, ts) for cat, ts in self.time_windows["24hour"] 
            if (self._parse_timestamp(ts, fallback=current_time) > cutoff_24hour)
        ]
    
    def _add_to_time_window(self, category: str, timestamp: datetime) -> None:
        """添加错误到时间窗口"""
        self.time_windows["5min"].append((category, timestamp))
        self.time_windows["1hour"].append((category, timestamp))
        self.time_windows["24hour"].append((category, timestamp))
    
    def analyze_logs(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析日志，进行错误分类和统计
        
        Args:
            logs: 日志列表
            
        Returns:
            分析结果
        """
        if not logs:
            return {}
        
        analysis_result = {
            "total_logs": len(logs),
            "error_categories": defaultdict(int),
            "severity_distribution": defaultdict(int),
            "instance_distribution": defaultdict(int),
            "time_distribution": defaultdict(int),
            "category_details": defaultdict(list),
            "critical_errors": [],
            "trends": {}
        }
        
        current_time = datetime.now()
        
        for log in logs:
            message = log.get("message", "")
            timestamp = log.get("timestamp")
            instance = log.get("instance", "unknown")
            
            # 分类错误
            category, severity = self.classify_error(message)
            
            # 统计分类
            analysis_result["error_categories"][category] += 1
            analysis_result["severity_distribution"][severity] += 1
            analysis_result["instance_distribution"][instance] += 1
            
            # 时间分布（按小时）
            if timestamp:
                try:
                    if isinstance(timestamp, str):
                        log_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    else:
                        log_time = timestamp
                    
                    hour_key = log_time.strftime("%Y-%m-%d %H:00")
                    analysis_result["time_distribution"][hour_key] += 1
                except Exception:
                    pass
            
            # 分类详情
            analysis_result["category_details"][category].append({
                "message": message[:200] + "..." if len(message) > 200 else message,
                "timestamp": timestamp,
                "instance": instance,
                "severity": severity,
                "level": log.get("level", "error")
            })
            
            # 严重错误
            if severity == "critical":
                analysis_result["critical_errors"].append({
                    "message": message[:200] + "..." if len(message) > 200 else message,
                    "timestamp": timestamp,
                    "instance": instance,
                    "category": category
                })
        
        # 计算趋势
        analysis_result["trends"] = self._calculate_trends(analysis_result["time_distribution"])
        
        return dict(analysis_result)
    
    def _calculate_trends(self, time_distribution: Dict[str, int]) -> Dict[str, Any]:
        """计算错误趋势"""
        if len(time_distribution) < 2:
            return {"growth_rate": 0, "trend": "stable"}
        
        # 按时间排序
        sorted_times = sorted(time_distribution.items())
        
        # 计算最近两小时的增长率
        if len(sorted_times) >= 2:
            current_hour = sorted_times[-1][1]
            previous_hour = sorted_times[-2][1]
            
            if previous_hour > 0:
                growth_rate = (current_hour - previous_hour) / previous_hour
                trend = "increasing" if growth_rate > 0 else "decreasing" if growth_rate < 0 else "stable"
            else:
                growth_rate = 0
                trend = "stable"
        else:
            growth_rate = 0
            trend = "stable"
        
        return {
            "growth_rate": growth_rate,
            "trend": trend,
            "current_hour_count": sorted_times[-1][1] if sorted_times else 0,
            "previous_hour_count": sorted_times[-2][1] if len(sorted_times) >= 2 else 0
        }
    
    def check_thresholds(self) -> List[Dict[str, Any]]:
        """
        检查是否超过阈值，生成告警
        
        Returns:
            告警列表
        """
        alerts = []
        current_time = datetime.now(timezone.utc)
        
        # 检查5分钟内各类错误数量阈值（基于时间过滤）
        cutoff_5min = current_time - timedelta(minutes=5)
        for category in self.error_stats:
            recent_count = len([
                (cat, ts) for cat, ts in self.time_windows["5min"] 
                if cat == category and self._parse_timestamp(ts, fallback=current_time) >= cutoff_5min
            ])
            
            if recent_count > self.thresholds["error_count_5min"]:
                # 检查是否已经发送过告警（避免重复告警）
                last_alert = self.error_stats[category].get("last_alert_time")
                if not last_alert or (current_time - last_alert).total_seconds() > 300:  # 5分钟内不重复告警
                    alert = {
                        "type": "error_count_threshold",
                        "category": category,
                        "count": recent_count,
                        "threshold": self.thresholds["error_count_5min"],
                        "message": f"错误类别 '{category}' 在5分钟内出现 {recent_count} 次，超过阈值 {self.thresholds['error_count_5min']}",
                        "severity": "warning",
                        "timestamp": current_time.isoformat(),
                        "details": {
                            "category": category,
                            "current_count": recent_count,
                            "threshold": self.thresholds["error_count_5min"],
                            "time_window": "5分钟"
                        }
                    }
                    alerts.append(alert)
                    
                    # 更新最后告警时间
                    self.error_stats[category]["last_alert_time"] = current_time
        
        # 检查1小时内各类别错误增长趋势（与前一小时相比）
        if len(self.time_windows["1hour"]) > 0:
            recent_1hour_start = current_time - timedelta(hours=1)
            previous_1hour_start = recent_1hour_start - timedelta(hours=1)
            previous_1hour_end = recent_1hour_start

            # 统计最近一小时与前一小时各类别计数
            recent_counts: Counter = Counter()
            previous_counts: Counter = Counter()
            for cat, ts in self.time_windows["1hour"]:
                ts_dt = self._parse_timestamp(ts, fallback=current_time)
                if ts_dt >= recent_1hour_start:
                    recent_counts[cat] += 1
                elif previous_1hour_start <= ts_dt < previous_1hour_end:
                    previous_counts[cat] += 1

            for category in set(list(recent_counts.keys()) + list(previous_counts.keys())):
                cur_cnt = recent_counts.get(category, 0)
                prev_cnt = previous_counts.get(category, 0)
                if prev_cnt <= 0:
                    continue  # 无法计算增长率
                growth_rate = (cur_cnt - prev_cnt) / prev_cnt
                if growth_rate > self.thresholds["error_growth_1hour"]:
                    alert = {
                        "type": "error_growth_threshold",
                        "category": category,
                        "current_count": cur_cnt,
                        "previous_count": prev_cnt,
                        "growth_rate": round(growth_rate, 4),
                        "threshold": self.thresholds["error_growth_1hour"],
                        "message": (
                            f"错误类别 '{category}' 过去1小时 {cur_cnt} 条，较前一小时 {prev_cnt} 条，增长率 {growth_rate:.1%} 超过阈值 {self.thresholds['error_growth_1hour']:.0%}"
                        ),
                        "severity": "warning",
                        "timestamp": current_time.isoformat(),
                        "details": {
                            "category": category,
                            "current_count": cur_cnt,
                            "previous_count": prev_cnt,
                            "growth_rate": growth_rate,
                            "time_window": "1小时"
                        }
                    }
                    alerts.append(alert)

        return alerts

    def notify_threshold_alerts(self, alerts: List[Dict[str, Any]]) -> bool:
        """将阈值告警通过企业微信发送。"""
        if not alerts:
            return False
        try:
            lines = [f"🚨 日志阈值告警 - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"]
            # 分组展示
            count_alerts = [a for a in alerts if a.get("type") == "error_count_threshold"]
            growth_alerts = [a for a in alerts if a.get("type") == "error_growth_threshold"]
            if count_alerts:
                lines.append("\n⚠️ 5分钟同类错误超阈：")
                for a in count_alerts:
                    lines.append(
                        f"  - {a.get('category')}: {a.get('count')} 次 (> {a.get('threshold')})"
                    )
            if growth_alerts:
                lines.append("\n📈 1小时增长率超阈：")
                for a in growth_alerts:
                    lines.append(
                        f"  - {a.get('category')}: {a.get('current_count')} / {a.get('previous_count')} (增长 {a.get('growth_rate', 0):.1%} > {a.get('threshold', 0):.0%})"
                    )
            text = "\n".join(lines)
            notify_workwechat(text)
            return True
        except Exception as e:
            logger.error(f"发送企业微信阈值告警失败: {e}")
            return False

    def run_log_alert_cycle(self, hours: int = 1) -> List[Dict[str, Any]]:
        """执行一次日志采集-分析-阈值检测-通知的完整流程。
        返回触发的告警列表。
        """
        logs = self.collect_logs(hours=hours)
        if not logs:
            return []
        classified = self.classify_errors(logs)
        self.update_error_stats(classified)
        alerts = self.check_thresholds()
        if alerts:
            self.notify_threshold_alerts(alerts)
        return alerts

    def clean_log_data(self, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        数据清洗：过滤、去重、标准化日志数据，并进行初步归类
        
        Args:
            logs: 原始日志列表
            
        Returns:
            清洗后的日志列表
        """
        cleaned_logs = []
        seen_messages = set()
        
        # 初始化归类统计
        classification_stats = {
            "level_distribution": defaultdict(int),      # 级别分布
            "instance_distribution": defaultdict(int),  # 实例分布
            "host_distribution": defaultdict(int),      # 主机分布
            "logger_distribution": defaultdict(int),    # 日志器分布
            "business_modules": defaultdict(int),       # 业务模块分布
            "error_categories": defaultdict(int),       # 错误类别分布
            "severity_distribution": defaultdict(int),  # 严重程度分布
            "time_distribution": defaultdict(int),      # 时间分布
            "critical_errors": [],                      # 严重错误详情
            "recent_errors": []                         # 最近错误详情
        }
        
        def _safe_str(val: Any) -> str:
            try:
                if val is None:
                    return ""
                if isinstance(val, (str, int, float)):
                    return str(val)
                if isinstance(val, (dict, list, tuple, set)):
                    return json.dumps(val, ensure_ascii=False, sort_keys=True)
                return str(val)
            except Exception:
                return ""

        for log in logs:
            message = log.get("message", "")
            if not message or not isinstance(message, str):
                continue
                
            # 消息长度限制
            if len(message) > self.data_cleaning_config["max_message_length"]:
                message = message[:self.data_cleaning_config["max_message_length"]] + "..."
                log["message"] = message
            
            # 去重（基于消息内容的简单哈希）
            message_hash = hash(message[:100])  # 取前100字符作为哈希
            if message_hash in seen_messages:
                continue
            seen_messages.add(message_hash)
            
            # 标准化字段
            cleaned_log = {
                "id": log.get("id", ""),
                "timestamp": log.get("timestamp"),
                "message": message,
                "level": _safe_str(log.get("level", "error")),
                "logger": _safe_str(log.get("logger", "")),
                "thread": _safe_str(log.get("thread", "")),
                "host": _safe_str(log.get("host", "")),
                "instance": _safe_str(log.get("instance", "")),
                "tags": log.get("tags", []),
                "cleaned_at": datetime.now(timezone.utc).isoformat()
            }
            
            # 进行错误分类和业务分析（仅本地规则，不调用外部AI）
            category, severity = self.classify_error(message)
            business_info = self.extract_business_category(message)
            core_message = self._extract_core_message(message)
            
            # 添加到归类统计
            classification_stats["level_distribution"][cleaned_log["level"]] += 1
            classification_stats["instance_distribution"][cleaned_log["instance"]] += 1
            classification_stats["host_distribution"][cleaned_log["host"]] += 1
            classification_stats["logger_distribution"][cleaned_log["logger"]] += 1
            classification_stats["error_categories"][category] += 1
            classification_stats["severity_distribution"][severity] += 1
            
            # 业务模块统计
            if business_info.get("business_module"):
                classification_stats["business_modules"][business_info["business_module"]] += 1
            
            # 时间分布统计（按小时）
            timestamp = cleaned_log.get("timestamp")
            if timestamp:
                try:
                    ts_dt = self._parse_timestamp(timestamp)
                    hour_key = ts_dt.strftime("%Y-%m-%d %H:00")
                    classification_stats["time_distribution"][hour_key] += 1
                except Exception:
                    pass
            
            # 严重错误和最近错误记录
            if severity == "critical":
                classification_stats["critical_errors"].append({
                    "message": message[:100] + "..." if len(message) > 100 else message,
                    "timestamp": timestamp,
                    "instance": cleaned_log["instance"],
                    "category": category,
                    "business_module": business_info.get("business_module", "")
                })
            
            # 记录最近错误（限制数量）
            if len(classification_stats["recent_errors"]) < 50:
                classification_stats["recent_errors"].append({
                    "message": message[:100] + "..." if len(message) > 100 else message,
                    "timestamp": timestamp,
                    "instance": cleaned_log["instance"],
                    "category": category,
                    "severity": severity,
                    "business_module": business_info.get("business_module", "")
                })
            
            # 添加分析结果到清洗后的日志，结构对齐前端字段
            # 计算中文错误类型标识
            chinese_error_type = self._extract_chinese_error_type(message) or category

            cleaned_log.update({
                "business_analysis": {
                    "business_module": business_info.get("business_module", ""),
                    "business_function": business_info.get("business_function", ""),
                    "extracted_info": business_info.get("extracted_info", {})
                },
                "error_analysis": {
                    # 使用中文错误类型标识作为 error_type 展示
                    "error_type": chinese_error_type,
                    "error_category": category,       # 保留类别信息
                    "category": category,             # 向后兼容
                    "severity": severity,
                    "suggested_actions": []
                },
                "core_message": core_message,
                "chinese_error_type": chinese_error_type
            })
            
            cleaned_logs.append(cleaned_log)
        
        # 转换为可序列化格式
        for key in classification_stats:
            if isinstance(classification_stats[key], defaultdict):
                classification_stats[key] = dict(classification_stats[key])
        
        # 存储归类统计结果
        self._store_classification_stats(classification_stats)
        
        logger.info(f"数据清洗完成: {len(logs)} -> {len(cleaned_logs)} 条")
        logger.info(f"归类统计: 级别分布={len(classification_stats['level_distribution'])}种, "
                   f"实例分布={len(classification_stats['instance_distribution'])}个, "
                   f"业务模块={len(classification_stats['business_modules'])}个, "
                   f"错误类别={len(classification_stats['error_categories'])}种")
        
        return cleaned_logs
    
    def _store_classification_stats(self, stats: Dict[str, Any]) -> None:
        """
        存储归类统计结果到内存缓存和Redis
        
        Args:
            stats: 归类统计结果
        """
        try:
            # 存储到内存缓存
            cache_key = f"classification_stats_{datetime.now(timezone.utc).strftime('%Y%m%d_%H')}"
            self.cleaned_data_cache[cache_key] = stats
            
            # 存储到Redis缓存
            cache_data = {
                "stats": stats,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "cache_ttl": self.data_cleaning_config["cache_ttl"]
            }
            
            REDIS_CACHE.set_with_ttl(
                f"log:classification:{cache_key}", 
                cache_data, 
                self.data_cleaning_config["cache_ttl"]
            )
            
            logger.info(f"归类统计结果已缓存: {cache_key}")
            
        except Exception as e:
            logger.error(f"存储归类统计结果失败: {e}")
    
    def get_classification_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取指定时间范围内的归类统计结果
        
        Args:
            hours: 时间范围（小时）
            
        Returns:
            归类统计结果
        """
        try:
            # 尝试从缓存获取
            cache_key = f"classification_stats_{datetime.now(timezone.utc).strftime('%Y%m%d_%H')}"
            cached_data = self.get_cached_analysis(f"classification:{cache_key}")
            
            if cached_data and cached_data.get("stats"):
                return cached_data["stats"]
            
            # 如果缓存中没有，执行实时分析
            logger.info(f"缓存中未找到归类统计，开始实时分析最近{hours}小时数据")
            return self._generate_realtime_classification_stats(hours)
            
        except Exception as e:
            logger.error(f"获取归类统计失败: {e}")
            return {}
    
    def _generate_realtime_classification_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        实时生成归类统计结果
        
        Args:
            hours: 时间范围（小时）
            
        Returns:
            实时归类统计结果
        """
        try:
            # 收集日志
            logs = self.collect_logs(hours=hours)
            if not logs:
                return {}
            
            # 初始化统计
            stats = {
                "level_distribution": defaultdict(int),      # 级别分布
                "instance_distribution": defaultdict(int),  # 实例分布
                "host_distribution": defaultdict(int),      # 主机分布
                "logger_distribution": defaultdict(int),    # 日志器分布
                "business_modules": defaultdict(int),       # 业务模块分布
                "error_categories": defaultdict(int),       # 错误类别分布
                "severity_distribution": defaultdict(int),  # 严重程度分布
                "time_distribution": defaultdict(int),      # 时间分布
                "critical_errors": [],                      # 严重错误详情
                "recent_errors": [],                        # 最近错误详情
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "time_range": f"最近{hours}小时"
            }
            
            for log in logs:
                message = log.get("message", "")
                if not message:
                    continue
                
                # 错误分类和业务分析
                category, severity = self.classify_error(message)
                business_info = self.extract_business_category(message)
                
                # 统计分布
                stats["level_distribution"][log.get("level", "error")] += 1
                stats["instance_distribution"][log.get("instance", "unknown")] += 1
                stats["host_distribution"][log.get("host", "unknown")] += 1
                stats["logger_distribution"][log.get("logger", "unknown")] += 1
                stats["error_categories"][category] += 1
                stats["severity_distribution"][severity] += 1
                
                # 业务模块统计
                if business_info.get("business_module"):
                    stats["business_modules"][business_info["business_module"]] += 1
                
                # 时间分布
                timestamp = log.get("timestamp")
                if timestamp:
                    try:
                        ts_dt = self._parse_timestamp(timestamp)
                        hour_key = ts_dt.strftime("%Y-%m-%d %H:00")
                        stats["time_distribution"][hour_key] += 1
                    except Exception:
                        pass
                
                # 严重错误记录
                if severity == "critical":
                    stats["critical_errors"].append({
                        "message": message[:100] + "..." if len(message) > 100 else message,
                        "timestamp": timestamp,
                        "instance": log.get("instance", "unknown"),
                        "category": category,
                        "business_module": business_info.get("business_module", "")
                    })
                
                # 最近错误记录
                if len(stats["recent_errors"]) < 50:
                    stats["recent_errors"].append({
                        "message": message[:100] + "..." if len(message) > 100 else message,
                        "timestamp": timestamp,
                        "instance": log.get("instance", "unknown"),
                        "category": category,
                        "severity": severity,
                        "business_module": business_info.get("business_module", "")
                    })
            
            # 转换为可序列化格式
            for key in stats:
                if isinstance(stats[key], defaultdict):
                    stats[key] = dict(stats[key])
            
            # 缓存结果
            self._store_classification_stats(stats)
            
            return stats
            
        except Exception as e:
            logger.error(f"生成实时归类统计失败: {e}")
            return {}
    
    def get_dashboard_summary_data(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取仪表板摘要数据，包含所有归类统计
        
        Args:
            hours: 时间范围（小时）
            
        Returns:
            仪表板摘要数据
        """
        try:
            # 获取归类统计
            classification_stats = self.get_classification_stats(hours)
            
            if not classification_stats:
                return {"error": "无法获取归类统计数据"}
            
            # 格式化仪表板数据
            dashboard_data = {
                "summary": {
                    "total_logs": sum(classification_stats.get("level_distribution", {}).values()),
                    "total_errors": sum(classification_stats.get("error_categories", {}).values()),
                    "critical_errors": len(classification_stats.get("critical_errors", [])),
                    "business_modules_count": len(classification_stats.get("business_modules", {})),
                    "instances_count": len(classification_stats.get("instance_distribution", {})),
                    "last_updated": classification_stats.get("generated_at", ""),
                    "time_range": classification_stats.get("time_range", "")
                },
                "distributions": {
                    "level_distribution": classification_stats.get("level_distribution", {}),
                    "instance_distribution": classification_stats.get("instance_distribution", {}),
                    "host_distribution": classification_stats.get("host_distribution", {}),
                    "logger_distribution": classification_stats.get("logger_distribution", {}),
                    "business_modules": classification_stats.get("business_modules", {}),
                    "error_categories": classification_stats.get("error_categories", {}),
                    "severity_distribution": classification_stats.get("severity_distribution", {}),
                    "time_distribution": classification_stats.get("time_distribution", {})
                },
                "details": {
                    "critical_errors": classification_stats.get("critical_errors", []),
                    "recent_errors": classification_stats.get("recent_errors", [])
                },
                "charts_data": {
                    "level_chart": self._format_chart_data(classification_stats.get("level_distribution", {}), "级别分布"),
                    "instance_chart": self._format_chart_data(classification_stats.get("instance_distribution", {}), "实例分布"),
                    "business_chart": self._format_chart_data(classification_stats.get("business_modules", {}), "业务模块"),
                    "error_chart": self._format_chart_data(classification_stats.get("error_categories", {}), "错误类别")
                }
            }
            
            return dashboard_data
            
        except Exception as e:
            logger.error(f"获取仪表板摘要数据失败: {e}")
            return {"error": f"获取仪表板数据失败: {str(e)}"}
    
    def _format_chart_data(self, data: Dict[str, int], title: str) -> Dict[str, Any]:
        """
        格式化图表数据
        
        Args:
            data: 原始数据字典
            title: 图表标题
            
        Returns:
            格式化后的图表数据
        """
        if not data:
            return {"title": title, "labels": [], "data": [], "total": 0}
        
        # 按数量排序，取前10个
        sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]
        
        labels = [item[0] for item in sorted_items]
        values = [item[1] for item in sorted_items]
        total = sum(values)
        
        return {
            "title": title,
            "labels": labels,
            "data": values,
            "total": total,
            "top_items": sorted_items[:5]  # 前5个最大值的项目
        }
    
    def aggregate_log_statistics(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        汇总日志统计信息
        
        Args:
            logs: 清洗后的日志列表
            
        Returns:
            汇总统计信息
        """
        if not logs:
            return {}
        
        # 基础统计
        total_logs = len(logs)
        level_counts = Counter()
        instance_counts = Counter()
        host_counts = Counter()
        logger_counts = Counter()
        
        # 时间分布统计
        time_distribution = defaultdict(int)
        business_modules = defaultdict(int)
        error_patterns = defaultdict(int)
        error_types = defaultdict(int)
        
        for log in logs:
            # 级别统计
            level_counts[log.get("level", "unknown")] += 1
            
            # 实例统计
            instance_counts[log.get("instance", "unknown")] += 1
            
            # 主机统计
            host_counts[log.get("host", "unknown")] += 1
            
            # 日志器统计
            logger_counts[log.get("logger", "unknown")] += 1
            
            # 时间分布（按小时）
            timestamp = log.get("timestamp")
            if timestamp:
                try:
                    ts_dt = self._parse_timestamp(timestamp)
                    hour_key = ts_dt.strftime("%Y-%m-%d %H:00")
                    time_distribution[hour_key] += 1
                except Exception:
                    pass
            
            # 业务模块提取
            message = log.get("message", "")
            business_info = self.extract_business_category(message)
            if business_info.get("business_module"):
                business_modules[business_info["business_module"]] += 1
            
            # 错误模式识别（类别）
            category, severity = self.classify_error(message)
            error_patterns[category] += 1

            # 错误类型统计（基于清洗出的中文类型）
            try:
                etype = (
                    (log.get("error_analysis") or {}).get("error_type")
                    or log.get("chinese_error_type")
                )
                if isinstance(etype, str) and etype.strip():
                    error_types[etype.strip()] += 1
            except Exception:
                pass
        
        # 转换为可序列化格式
        stats = {
            "total_logs": total_logs,
            "level_distribution": dict(level_counts),
            "instance_distribution": dict(instance_counts),
            "host_distribution": dict(host_counts),
            "logger_distribution": dict(logger_counts),
            "time_distribution": dict(time_distribution),
            "business_modules": dict(business_modules),
            "error_patterns": dict(error_patterns),
            "error_types": dict(error_types),
            "aggregated_at": datetime.now(timezone.utc).isoformat(),
            "time_range": f"最近{self.data_cleaning_config['aggregation_window']}小时"
        }
        
        return stats
    
    def prepare_dify_batch_data(self, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        准备发送给Dify的批次数据
        
        Args:
            logs: 清洗后的日志列表
            
        Returns:
            适合Dify处理的批次数据
        """
        if not logs:
            return []
        
        # 按批次大小分组
        batch_size = self.data_cleaning_config["batch_size_for_dify"]
        batches = []
        
        for i in range(0, len(logs), batch_size):
            batch_logs = logs[i:i + batch_size]
            
            # 为每个批次准备摘要信息
            batch_summary = {
                "batch_id": f"batch_{i//batch_size + 1}",
                "total_logs": len(batch_logs),
                "time_range": {
                    "start": batch_logs[0].get("timestamp"),
                    "end": batch_logs[-1].get("timestamp")
                },
                "level_summary": Counter(log.get("level", "unknown") for log in batch_logs),
                "instance_summary": Counter(log.get("instance", "unknown") for log in batch_logs),
                "business_modules": set(),
                "error_categories": set()
            }
            
            # 提取业务模块和错误类别
            for log in batch_logs:
                message = log.get("message", "")
                business_info = self.extract_business_category(message)
                if business_info.get("business_module"):
                    batch_summary["business_modules"].add(business_info["business_module"])
                
                category, _ = self.classify_error(message)
                batch_summary["error_categories"].add(category)
            
            # 转换为可序列化格式
            batch_summary["business_modules"] = list(batch_summary["business_modules"])
            batch_summary["error_categories"] = list(batch_summary["error_categories"])
            batch_summary["level_summary"] = dict(batch_summary["level_summary"])
            batch_summary["instance_summary"] = dict(batch_summary["instance_summary"])
            
            batches.append({
                "summary": batch_summary,
                "logs": batch_logs
            })
        
        return batches
    
    def batch_analyze_with_dify(self, batches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量使用Dify分析日志数据
        
        Args:
            batches: 准备好的批次数据
            
        Returns:
            Dify分析结果列表
        """
        if not SETTINGS.ai_assist_enabled or not SETTINGS.dify_enabled:
            logger.warning("Dify分析未启用，跳过AI分析")
            return []
        
        analysis_results = []
        
        for batch in batches:
            try:
                batch_summary = batch["summary"]
                batch_logs = batch["logs"]
                
                logger.info(f"开始使用Dify分析批次 {batch_summary['batch_id']}: {len(batch_logs)} 条日志")
                
                # 准备发送给Dify的摘要信息
                summary_text = self._format_batch_summary_for_dify(batch_summary)
                
                # 调用Dify进行分析
                dify_result = self._call_dify_analysis(summary_text, batch_logs)
                
                if dify_result:
                    analysis_result = {
                        "batch_id": batch_summary["batch_id"],
                        "dify_analysis": dify_result,
                        "local_analysis": self._analyze_batch_locally(batch_logs),
                        "analyzed_at": datetime.now(timezone.utc).isoformat()
                    }
                    analysis_results.append(analysis_result)
                    
                    logger.info(f"批次 {batch_summary['batch_id']} Dify分析完成")
                else:
                    logger.warning(f"批次 {batch_summary['batch_id']} Dify分析失败")
                    
            except Exception as e:
                logger.error(f"批次 {batch.get('summary', {}).get('batch_id', 'unknown')} Dify分析异常: {e}")
                continue
        
        return analysis_results
    
    def _format_batch_summary_for_dify(self, batch_summary: Dict[str, Any]) -> str:
        """格式化批次摘要信息，适合发送给Dify"""
        lines = [
            f"日志批次摘要 - {batch_summary['batch_id']}",
            f"总日志数: {batch_summary['total_logs']}",
            f"时间范围: {batch_summary['time_range']['start']} ~ {batch_summary['time_range']['end']}",
            "",
            "级别分布:",
        ]
        
        for level, count in batch_summary["level_summary"].items():
            lines.append(f"  - {level}: {count}")
        
        lines.extend([
            "",
            "实例分布:",
        ])
        
        for instance, count in batch_summary["instance_summary"].items():
            lines.append(f"  - {instance}: {count}")
        
        lines.extend([
            "",
            "业务模块:",
        ])
        
        for module in batch_summary["business_modules"]:
            lines.append(f"  - {module}")
        
        lines.extend([
            "",
            "错误类别:",
        ])
        
        for category in batch_summary["error_categories"]:
            lines.append(f"  - {category}")
        
        return "\n".join(lines)
    
    def _call_dify_analysis(self, summary_text: str, logs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """调用Dify进行日志分析"""
        try:
            if not SETTINGS.dify_enabled or not SETTINGS.dify_api_key:
                logger.warning("Dify未启用或API密钥未配置")
                return None
            
            logger.info(f"调用Dify分析，摘要长度: {len(summary_text)} 字符，日志数量: {len(logs)}")
            
            # 构建Dify分析请求
            analysis_prompt = f"""
请分析以下日志批次数据，并提供结构化的分析结果。

日志批次摘要：
{summary_text}

请从以下角度进行分析：
1. 错误模式识别：识别主要的错误类型和模式
2. 业务影响评估：评估对业务的影响程度
3. 系统健康度：评估系统整体健康状态
4. 建议措施：提供具体的改进建议

请以JSON格式返回分析结果，包含以下字段：
- analysis_type: 分析类型
- confidence_score: 置信度 (0-1)
- key_insights: 关键洞察 (数组)
- recommendations: 建议措施 (数组)
- risk_assessment: 风险评估 (low/medium/high)
- business_impact: 业务影响 (low/medium/high)
- error_patterns: 错误模式分析 (对象)
- system_health: 系统健康度评估 (对象)
"""
            
            # 调用Dify API
            from ai_client import chat_completion_dify
            
            response = chat_completion_dify(
                query=analysis_prompt,
                user=SETTINGS.dify_default_user
            )
            
            if not response:
                logger.error("Dify API调用失败，返回空响应")
                return None
            
            # 解析Dify响应
            try:
                # 首先尝试直接解析为JSON
                try:
                    dify_result = json.loads(response)
                    logger.info("成功直接解析Dify响应为JSON")
                except json.JSONDecodeError:
                    # 如果直接解析失败，尝试从响应中提取JSON
                    import re
                    json_match = re.search(r'\{.*\}', response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                        dify_result = json.loads(json_str)
                        logger.info("成功从响应中提取并解析JSON")
                    else:
                        # 如果无法提取JSON，构建默认结果
                        logger.warning("无法从Dify响应中提取JSON，使用默认分析结果")
                        dify_result = {
                            "analysis_type": "batch_log_analysis",
                            "confidence_score": 0.7,
                            "key_insights": [
                                "基于日志分析，检测到系统异常",
                                "建议进一步分析错误模式"
                            ],
                            "recommendations": [
                                "增加错误监控告警",
                                "优化高频错误模块"
                            ],
                            "risk_assessment": "medium",
                            "business_impact": "moderate",
                            "error_patterns": {},
                            "system_health": {
                                "overall_status": "warning",
                                "details": "检测到异常需要关注"
                            }
                        }
                
                # 验证和标准化结果
                dify_result.setdefault("analysis_type", "batch_log_analysis")
                dify_result.setdefault("confidence_score", 0.7)
                dify_result.setdefault("key_insights", [])
                dify_result.setdefault("recommendations", [])
                dify_result.setdefault("risk_assessment", "medium")
                dify_result.setdefault("business_impact", "moderate")
                
                logger.info(f"Dify分析完成，置信度: {dify_result.get('confidence_score', 0)}")
                return dify_result
                
            except Exception as e:
                logger.error(f"解析Dify响应失败: {e}")
                logger.error(f"原始响应: {response}")
                # 返回默认结果而不是None，确保流程可以继续
                return {
                    "analysis_type": "batch_log_analysis",
                    "confidence_score": 0.5,
                    "key_insights": [
                        "Dify分析响应解析失败，使用默认分析",
                        "建议检查Dify API配置和响应格式"
                    ],
                    "recommendations": [
                        "检查Dify API连接状态",
                        "验证API密钥和端点配置"
                    ],
                    "risk_assessment": "unknown",
                    "business_impact": "unknown",
                    "error_patterns": {},
                    "system_health": {
                        "overall_status": "unknown",
                        "details": "Dify分析失败，需要人工检查"
                    }
                }
            
        except Exception as e:
            logger.error(f"Dify分析调用失败: {e}")
            return None
    
    def _analyze_batch_locally(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """本地分析批次日志"""
        if not logs:
            return {}
        
        # 使用现有的本地分析逻辑
        analysis_result = {
            "total_logs": len(logs),
            "error_categories": defaultdict(int),
            "severity_distribution": defaultdict(int),
            "business_modules": defaultdict(int),
            "critical_errors": []
        }
        
        for log in logs:
            message = log.get("message", "")
            
            # 错误分类
            category, severity = self.classify_error(message)
            analysis_result["error_categories"][category] += 1
            analysis_result["severity_distribution"][severity] += 1
            
            # 业务模块
            business_info = self.extract_business_category(message)
            if business_info.get("business_module"):
                analysis_result["business_modules"][business_info["business_module"]] += 1
            
            # 严重错误
            if severity == "critical":
                analysis_result["critical_errors"].append({
                    "message": message[:100] + "..." if len(message) > 100 else message,
                    "timestamp": log.get("timestamp"),
                    "instance": log.get("instance", "unknown")
                })
        
        # 转换为可序列化格式
        analysis_result["error_categories"] = dict(analysis_result["error_categories"])
        analysis_result["severity_distribution"] = dict(analysis_result["severity_distribution"])
        analysis_result["business_modules"] = dict(analysis_result["business_modules"])
        
        return analysis_result
    
    def cache_analysis_results(self, results: List[Dict[str, Any]], cache_key: str) -> bool:
        """缓存分析结果到Redis"""
        try:
            cache_data = {
                "results": results,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "total_batches": len(results),
                "cache_ttl": self.data_cleaning_config["cache_ttl"]
            }
            
            REDIS_CACHE.set_with_ttl(
                f"log:analysis:{cache_key}", 
                cache_data, 
                self.data_cleaning_config["cache_ttl"]
            )
            
            logger.info(f"分析结果已缓存: {cache_key}, TTL: {self.data_cleaning_config['cache_ttl']}秒")
            return True
            
        except Exception as e:
            logger.error(f"缓存分析结果失败: {e}")
            return False
    
    def get_cached_analysis(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """从Redis获取缓存的分析结果"""
        try:
            cache_data = REDIS_CACHE.get(f"log:analysis:{cache_key}")
            if cache_data:
                logger.info(f"从缓存获取分析结果: {cache_key}")
                return cache_data
            return None
            
        except Exception as e:
            logger.error(f"获取缓存分析结果失败: {e}")
            return None
    
    def run_daily_log_analysis_pipeline(self, hours: int = 24) -> Dict[str, Any]:
        """
        执行完整的日志分析流水线：收集 -> 清洗 -> 汇总 -> Dify分析 -> 缓存
        
        Args:
            hours: 分析最近几小时的日志
            
        Returns:
            完整的分析结果
        """
        try:
            logger.info(f"开始执行日志分析流水线，时间范围: 最近{hours}小时")
            
            # 1. 收集原始日志
            raw_logs = self.collect_logs(hours=hours)
            if not raw_logs:
                logger.warning("未收集到日志数据")
                return {"error": "未收集到日志数据"}
            
            logger.info(f"收集到 {len(raw_logs)} 条原始日志")
            
            # 2. 数据清洗
            cleaned_logs = self.clean_log_data(raw_logs)
            if not cleaned_logs:
                logger.warning("数据清洗后无有效日志")
                return {"error": "数据清洗后无有效日志"}
            
            # 3. 本地统计汇总
            local_stats = self.aggregate_log_statistics(cleaned_logs)
            logger.info("本地统计汇总完成")
            
            # 4. 准备Dify批次数据
            batches = self.prepare_dify_batch_data(cleaned_logs)
            logger.info(f"准备 {len(batches)} 个批次数据")
            
            # 5. Dify批量分析
            dify_results = []
            if batches and SETTINGS.ai_assist_enabled:
                dify_results = self.batch_analyze_with_dify(batches)
                logger.info(f"Dify分析完成，共 {len(dify_results)} 个批次")
            else:
                logger.info("跳过Dify分析")
            
            # 6. 整合分析结果
            final_result = {
                "pipeline_info": {
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                    "time_range": f"最近{hours}小时",
                    "total_raw_logs": len(raw_logs),
                    "total_cleaned_logs": len(cleaned_logs),
                    "total_batches": len(batches),
                    "dify_analysis_enabled": SETTINGS.ai_assist_enabled and SETTINGS.dify_enabled
                },
                "local_statistics": local_stats,
                "dify_analysis_results": dify_results,
                "summary": {
                    "total_logs": len(cleaned_logs),
                    "business_modules_count": len(local_stats.get("business_modules", {})),
                    "error_categories_count": len(local_stats.get("error_patterns", {})),
                    "critical_errors_count": sum(1 for level, count in local_stats.get("level_distribution", {}).items() if level == "critical"),
                    "analysis_confidence": "high" if dify_results else "medium"
                }
            }
            
            # 7. 缓存结果
            cache_key = f"daily_analysis_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            self.cache_analysis_results([final_result], cache_key)
            
            # 8. 更新内存缓存
            self.cleaned_data_cache[cache_key] = cleaned_logs
            self.aggregated_stats_cache[cache_key] = local_stats
            self.dify_analysis_cache[cache_key] = dify_results
            
            logger.info("日志分析流水线执行完成")
            return final_result
            
        except Exception as e:
            logger.error(f"日志分析流水线执行失败: {e}")
            return {"error": f"流水线执行失败: {str(e)}"}
    
    def get_daily_analysis_summary(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        获取指定日期的日志分析摘要
        
        Args:
            date: 日期字符串 (YYYYMMDD)，默认为今天
            
        Returns:
            分析摘要
        """
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y%m%d")
        
        cache_key = f"daily_analysis_{date}"
        
        # 尝试从缓存获取
        cached_result = self.get_cached_analysis(cache_key)
        if cached_result:
            return cached_result
        
        # 如果缓存中没有，执行分析
        logger.info(f"缓存中未找到 {date} 的分析结果，开始执行分析")
        return self.run_daily_log_analysis_pipeline(hours=24)
    
    def get_frontend_display_data(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取前端展示所需的数据，使用新的归类统计功能
        
        Args:
            hours: 时间范围
            
        Returns:
            前端展示数据
        """
        try:
            # 尝试从缓存获取
            cache_key = f"frontend_data_{hours}h_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            cached_data = self.get_cached_analysis(cache_key)
            
            if cached_data:
                return cached_data
            
            # 使用新的归类统计功能
            dashboard_data = self.get_dashboard_summary_data(hours)
            
            if "error" in dashboard_data:
                return dashboard_data
            
            # 格式化前端数据
            frontend_data = {
                "dashboard_data": {
                    "total_logs": dashboard_data["summary"]["total_logs"],
                    "total_errors": dashboard_data["summary"]["total_errors"],
                    "critical_errors": dashboard_data["summary"]["critical_errors"],
                    "business_modules_count": dashboard_data["summary"]["business_modules_count"],
                    "instances_count": dashboard_data["summary"]["instances_count"],
                    "last_updated": dashboard_data["summary"]["last_updated"],
                    "time_range": dashboard_data["summary"]["time_range"]
                },
                "distributions": dashboard_data["distributions"],
                "charts_data": dashboard_data["charts_data"],
                "details": dashboard_data["details"],
                "ai_insights": {
                    "enabled": SETTINGS.ai_assist_enabled and SETTINGS.dify_enabled,
                    "key_insights": [],
                    "recommendations": [],
                    "risk_assessment": "unknown"
                },
                "last_updated": dashboard_data["summary"]["last_updated"]
            }
            
            # 尝试获取AI分析结果（如果启用）
            if SETTINGS.ai_assist_enabled and SETTINGS.dify_enabled:
                try:
                    # 执行AI分析流水线获取AI洞察
                    analysis_result = self.run_daily_log_analysis_pipeline(hours=hours)
                    if "error" not in analysis_result and analysis_result.get("dify_analysis_results"):
                        for batch_result in analysis_result["dify_analysis_results"]:
                            dify_analysis = batch_result.get("dify_analysis", {})
                            if dify_analysis.get("key_insights"):
                                frontend_data["ai_insights"]["key_insights"].extend(dify_analysis["key_insights"])
                            if dify_analysis.get("recommendations"):
                                frontend_data["ai_insights"]["recommendations"].extend(dify_analysis["recommendations"])
                            if dify_analysis.get("risk_assessment"):
                                frontend_data["ai_insights"]["risk_assessment"] = dify_analysis["risk_assessment"]
                except Exception as e:
                    logger.warning(f"获取AI洞察失败: {e}")
            
            # 缓存前端数据
            self.cache_analysis_results([frontend_data], cache_key)
            
            return frontend_data
            
        except Exception as e:
            logger.error(f"获取前端展示数据失败: {e}")
            return {"error": f"获取前端数据失败: {str(e)}"}

    def extract_business_category(self, message: str) -> Dict[str, Any]:
        """
        提取中文业务类别信息
        
        Args:
            message: 日志消息
            
        Returns:
            业务类别信息字典
        """
        result = {
            "business_module": "",  # 业务模块（如：APP_首页版块）
            "business_function": "",  # 业务功能（如：获取用户信息）
            "error_detail": "",  # 详细错误信息
            "extracted_info": {}  # 提取的详细信息
        }
        
        try:
            # 提取【】中的业务模块
            business_match = re.search(r"【([^】]+)】", message)
            if business_match:
                result["business_module"] = business_match.group(1).strip()
                result["extracted_info"]["业务模块"] = result["business_module"]
            
            # 提取中文错误描述
            if business_match:
                after_bracket = message[business_match.end():]
                chinese_sentence = re.search(r"([^，。！？\n]+)", after_bracket)
                if chinese_sentence:
                    result["business_function"] = chinese_sentence.group(1).strip()
                    result["extracted_info"]["业务功能"] = result["business_function"]
            
            # 提取Java异常信息
            java_exception = re.search(r"(java\.[\w\.]+Exception[^，。！？\n]*)", message, re.IGNORECASE)
            if java_exception:
                result["error_detail"] = java_exception.group(1).strip()
                result["extracted_info"]["Java异常"] = result["error_detail"]
            
            # 提取堆栈信息
            stack_trace = re.search(r"at\s+([\w\.]+)\.([\w]+)\(([\w\.]+\.java):(\d+)\)", message)
            if stack_trace:
                class_name = stack_trace.group(1)
                method_name = stack_trace.group(2)
                file_name = stack_trace.group(3)
                line_number = stack_trace.group(4)
                result["extracted_info"]["异常位置"] = f"{class_name}.{method_name}({file_name}:{line_number})"
            
        except Exception as e:
            logger.error(f"提取业务类别失败: {e}")
        
        return result

    def _extract_core_message(self, message: str) -> str:
        """提取日志的核心业务文案。
        - 去除ANSI颜色码
        - 保留开头多个【...】段并原样拼接
        - 优先取 " - " 右侧的中文首句
        - 去掉后续的键值对长串（如 key=value）
        - 去除句末标点（如中文句号）
        期望示例：
        输入："【】 【1956264477569716224】 【0000165330001】\x1b[0;39m com.xxx.Controller - 云服务费已过期。"
        输出："【】 【1956264477569716224】 【0000165330001】 云服务费已过期"
        """
        if not message:
            return ""

        # 去掉控制台颜色码
        text = re.sub(r"\x1b\[[0-9;]*m", "", message)

        # 提取并保留开头的【...】段（可能有多个，含空内容）
        brackets_prefix = ""
        m = re.match(r"^(?:\s*(【[^】]*】)\s*)+", text)
        if m:
            brackets_prefix = m.group(0).strip()
            text = text[len(m.group(0)):]  # 去掉已匹配的前缀

        # 优先按 " - " 分隔，取右侧内容
        if " - " in text:
            text = text.split(" - ", 1)[1]

        # 截断到第一个键值串开始处
        kv_match = re.search(r"\s+[A-Za-z_][A-Za-z0-9_]*=", text)
        if kv_match:
            text = text[:kv_match.start()].strip()

        # 取首句（中文句号/英文句号/感叹号/问号等）
        first_sentence = text
        for sep in ["。", ".", "!", "！", "?", "？", "  "]:
            if sep in first_sentence:
                first_sentence = first_sentence.split(sep, 1)[0]
                break

        first_sentence = first_sentence.strip()

        # 组合结果：保留的【...】 + 空格 + 中文首句
        if brackets_prefix:
            result = f"{brackets_prefix} {first_sentence}".strip()
        else:
            result = first_sentence

        # 规范空白
        result = re.sub(r"\s+", " ", result).strip()
        return result

    def _extract_chinese_error_type(self, message: str) -> str:
        """基于ELK message提取中文错误类型标识。
        - 复用核心文案提取
        - 去掉前缀的【...】块，仅保留中文首句
        - 去除中文逗号/英文逗号后的编号等尾随内容
        - 去除句尾的空格+数字串
        - 若为空，回退到业务功能；再为空则回退到通用类别
        """
        try:
            core = self._extract_core_message(message)
            # 去掉前缀【...】
            chinese = self._leading_brackets_re.sub("", core).strip()
            # 去除逗号后的内容（中文/英文逗号）
            chinese = re.split(r"[，,]", chinese, 1)[0].strip()
            # 去除结尾的空格+数字等
            chinese = re.sub(r"\s+\d[\d\s\-_,]*$", "", chinese).strip()
            # 去除控制字符与零宽字符
            chinese = re.sub(r"[\u0000-\u001F\u007F-\u009F\u200B-\u200F\u202A-\u202E\uFEFF]", "", chinese)
            # 仅保留中文与空格（去除标点/特殊符号/英文字母/数字）
            chinese = re.sub(r"[^\u4e00-\u9fff\s]", "", chinese)
            # 规范空白
            chinese = re.sub(r"\s+", " ", chinese).strip()
            # 简单裁剪长度，避免过长
            if len(chinese) > 100:
                chinese = chinese[:100].rstrip() + "..."
            return chinese or ""
        except Exception:
            return ""
    
    def get_formatted_classification_report(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取格式化的归类统计报告，用于页面展示和数据分析
        
        Args:
            hours: 时间范围（小时）
            
        Returns:
            格式化的归类统计报告
        """
        try:
            # 获取归类统计
            classification_stats = self.get_classification_stats(hours)
            
            if not classification_stats:
                return {"error": "无法获取归类统计数据"}
            
            # 格式化报告数据
            report = {
                "report_info": {
                    "generated_at": classification_stats.get("generated_at", ""),
                    "time_range": classification_stats.get("time_range", ""),
                    "total_logs": sum(classification_stats.get("level_distribution", {}).values()),
                    "total_errors": sum(classification_stats.get("error_categories", {}).values())
                },
                "level_distribution": self._format_distribution_report(
                    classification_stats.get("level_distribution", {}), 
                    "级别分布"
                ),
                "instance_distribution": self._format_distribution_report(
                    classification_stats.get("instance_distribution", {}), 
                    "实例分布"
                ),
                "host_distribution": self._format_distribution_report(
                    classification_stats.get("host_distribution", {}), 
                    "主机分布"
                ),
                "logger_distribution": self._format_distribution_report(
                    classification_stats.get("logger_distribution", {}), 
                    "日志器分布"
                ),
                "business_modules": self._format_distribution_report(
                    classification_stats.get("business_modules", {}), 
                    "业务模块"
                ),
                "error_categories": self._format_distribution_report(
                    classification_stats.get("error_categories", {}), 
                    "错误类别"
                ),
                "severity_distribution": self._format_distribution_report(
                    classification_stats.get("severity_distribution", {}), 
                    "严重程度分布"
                ),
                "time_distribution": self._format_time_distribution_report(
                    classification_stats.get("time_distribution", {})
                ),
                "critical_errors_summary": {
                    "count": len(classification_stats.get("critical_errors", [])),
                    "top_categories": self._get_top_categories_by_severity(
                        classification_stats.get("error_categories", {}),
                        classification_stats.get("severity_distribution", {})
                    ),
                    "recent_critical": classification_stats.get("critical_errors", [])[:10]
                },
                "trends": self._calculate_distribution_trends(classification_stats),
                "recommendations": self._generate_recommendations(classification_stats)
            }
            
            return report
            
        except Exception as e:
            logger.error(f"生成格式化归类统计报告失败: {e}")
            return {"error": f"生成报告失败: {str(e)}"}
    
    def _format_distribution_report(self, data: Dict[str, int], title: str) -> Dict[str, Any]:
        """
        格式化分布报告
        
        Args:
            data: 分布数据
            title: 报告标题
            
        Returns:
            格式化的分布报告
        """
        if not data:
            return {
                "title": title,
                "total": 0,
                "items": [],
                "top_items": [],
                "distribution_percentage": {}
            }
        
        # 按数量排序
        sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
        total = sum(data.values())
        
        # 计算百分比
        distribution_percentage = {}
        for key, value in data.items():
            if total > 0:
                distribution_percentage[key] = round((value / total) * 100, 2)
            else:
                distribution_percentage[key] = 0
        
        # 格式化项目列表
        items = []
        for key, value in sorted_items:
            items.append({
                "name": key,
                "count": value,
                "percentage": distribution_percentage.get(key, 0)
            })
        
        return {
            "title": title,
            "total": total,
            "items": items,
            "top_items": items[:5],  # 前5个
            "distribution_percentage": distribution_percentage
        }
    
    def _format_time_distribution_report(self, time_data: Dict[str, int]) -> Dict[str, Any]:
        """
        格式化时间分布报告
        
        Args:
            time_data: 时间分布数据
            
        Returns:
            格式化的时间分布报告
        """
        if not time_data:
            return {
                "title": "时间分布",
                "total": 0,
                "time_periods": [],
                "peak_hours": [],
                "trend": "stable"
            }
        
        # 按时间排序
        sorted_times = sorted(time_data.items())
        total = sum(time_data.values())
        
        # 格式化时间段
        time_periods = []
        for time_key, count in sorted_times:
            time_periods.append({
                "time": time_key,
                "count": count,
                "percentage": round((count / total) * 100, 2) if total > 0 else 0
            })
        
        # 找出峰值时间
        peak_hours = sorted(time_data.items(), key=lambda x: x[1], reverse=True)[:3]
        peak_hours = [{"time": time, "count": count} for time, count in peak_hours]
        
        # 计算趋势
        if len(time_periods) >= 2:
            recent_count = time_periods[-1]["count"]
            previous_count = time_periods[-2]["count"]
            if previous_count > 0:
                growth_rate = (recent_count - previous_count) / previous_count
                if growth_rate > 0.1:
                    trend = "increasing"
                elif growth_rate < -0.1:
                    trend = "decreasing"
                else:
                    trend = "stable"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        return {
            "title": "时间分布",
            "total": total,
            "time_periods": time_periods,
            "peak_hours": peak_hours,
            "trend": trend
        }
    
    def _get_top_categories_by_severity(self, error_categories: Dict[str, int], severity_distribution: Dict[str, int]) -> List[Dict[str, Any]]:
        """
        根据严重程度获取顶级错误类别
        
        Args:
            error_categories: 错误类别分布
            severity_distribution: 严重程度分布
            
        Returns:
            顶级错误类别列表
        """
        if not error_categories:
            return []
        
        # 按数量排序，取前10个
        top_categories = sorted(error_categories.items(), key=lambda x: x[1], reverse=True)[:10]
        
        result = []
        for category, count in top_categories:
            # 确定严重程度（这里简化处理，实际可以根据错误类别名称判断）
            severity = "warning"  # 默认
            if any(critical_word in category.lower() for critical_word in ["nullpointer", "outofmemory", "deadlock", "fatal"]):
                severity = "critical"
            elif any(error_word in category.lower() for error_word in ["timeout", "connection", "database"]):
                severity = "error"
            
            result.append({
                "category": category,
                "count": count,
                "severity": severity,
                "percentage": round((count / sum(error_categories.values())) * 100, 2) if sum(error_categories.values()) > 0 else 0
            })
        
        return result
    
    def _calculate_distribution_trends(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算分布趋势
        
        Args:
            stats: 统计数据
            
        Returns:
            趋势分析结果
        """
        trends = {
            "error_growth": "stable",
            "business_impact": "low",
            "system_health": "good",
            "critical_trend": "stable"
        }
        
        try:
            # 错误增长趋势
            error_categories = stats.get("error_categories", {})
            if error_categories:
                total_errors = sum(error_categories.values())
                if total_errors > 100:
                    trends["error_growth"] = "high"
                elif total_errors > 50:
                    trends["error_growth"] = "medium"
                else:
                    trends["error_growth"] = "low"
            
            # 业务影响评估
            business_modules = stats.get("business_modules", {})
            if business_modules:
                affected_modules = len(business_modules)
                if affected_modules > 5:
                    trends["business_impact"] = "high"
                elif affected_modules > 2:
                    trends["business_impact"] = "medium"
                else:
                    trends["business_impact"] = "low"
            
            # 系统健康度
            critical_errors = len(stats.get("critical_errors", []))
            if critical_errors > 10:
                trends["system_health"] = "poor"
            elif critical_errors > 5:
                trends["system_health"] = "warning"
            else:
                trends["system_health"] = "good"
            
            # 严重错误趋势
            severity_distribution = stats.get("severity_distribution", {})
            critical_count = severity_distribution.get("critical", 0)
            if critical_count > 20:
                trends["critical_trend"] = "increasing"
            elif critical_count > 10:
                trends["critical_trend"] = "warning"
            else:
                trends["critical_trend"] = "stable"
                
        except Exception as e:
            logger.error(f"计算分布趋势失败: {e}")
        
        return trends
    
    def _generate_recommendations(self, stats: Dict[str, Any]) -> List[str]:
        """
        根据统计数据生成建议
        
        Args:
            stats: 统计数据
            
        Returns:
            建议列表
        """
        recommendations = []
        
        try:
            # 基于错误数量的建议
            total_errors = sum(stats.get("error_categories", {}).values())
            if total_errors > 100:
                recommendations.append("错误数量较多，建议检查系统配置和代码质量")
            
            # 基于严重错误的建议
            critical_errors = len(stats.get("critical_errors", []))
            if critical_errors > 10:
                recommendations.append("严重错误较多，建议立即检查系统稳定性")
            
            # 基于业务模块的建议
            business_modules = stats.get("business_modules", {})
            if len(business_modules) > 5:
                recommendations.append("涉及业务模块较多，建议进行业务影响评估")
            
            # 基于实例分布的建议
            instance_distribution = stats.get("instance_distribution", {})
            if len(instance_distribution) > 10:
                recommendations.append("涉及实例较多，建议检查负载均衡和实例健康状态")
            
            # 基于时间分布的建议
            time_distribution = stats.get("time_distribution", {})
            if time_distribution:
                peak_hours = max(time_distribution.values())
                avg_hours = sum(time_distribution.values()) / len(time_distribution)
                if peak_hours > avg_hours * 2:
                    recommendations.append("存在明显的峰值时间，建议优化峰值时段的系统性能")
            
            # 如果没有具体建议，提供通用建议
            if not recommendations:
                recommendations.append("系统运行正常，建议继续监控")
                recommendations.append("定期检查日志模式变化")
                
        except Exception as e:
            logger.error(f"生成建议失败: {e}")
            recommendations.append("无法生成具体建议，请检查系统状态")
        
        return recommendations