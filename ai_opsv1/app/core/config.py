from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Optional
import time
from datetime import datetime
import urllib3
# 禁用SSL警告（当使用自签名证书时）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
@dataclass(frozen=True)
class Settings:
    # Prometheus
    prom_url: str = os.getenv("PROM_URL", "https://prometheus-dev-tiqmo.wallyt.net/")
    verify_ssl: bool = os.getenv("VERIFY_SSL", "False").lower() == "true"  # 规范定义：支持环境变量覆盖，默认False
    # ... 其他字段不变
    # Database (MySQL)
    db_host: str = os.getenv("DB_HOST", "192.168.4.99")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_user: str = os.getenv("DB_USER", "testwft")
    db_password: str = os.getenv("DB_PASSWORD", "Wft_2025")
    db_name: str = os.getenv("DB_NAME", "bigdata")

    # Redis Cache
    redis_host: str = os.getenv("REDIS_HOST", "192.168.4.108")
    redis_port: int = int(os.getenv("REDIS_PORT", "30593"))
    redis_password: str = os.getenv("REDIS_PASSWORD", "tiqmo")
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_cache_ttl: int = int(os.getenv("REDIS_CACHE_TTL", "300"))  # 5 minutes

    # Notifiers
    dingtalk_webhook: str = os.getenv("DINGTALK_WEBHOOK", "")
    feishu_webhook: str = os.getenv("FEISHU_WEBHOOK", "")
    slack_webhook: str = os.getenv("SLACK_WEBHOOK", "")
    
    # Enterprise WeChat (企业微信)
    workwechat_url: str = os.getenv("WORKWECHAT_URL", "http://tessst.foreign.wallyt.com/foreign/workWechatPlus/sendText")
    workwechat_channel: str = os.getenv("WORKWECHAT_CHANNEL", "devops")

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_format: str = os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Error handling
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_delay: float = float(os.getenv("RETRY_DELAY", "1.0"))

    # Performance optimizations
    cache_ttl: int = int(os.getenv("CACHE_TTL", "300"))  # 5 minutes
    batch_size: int = int(os.getenv("BATCH_SIZE", "100"))
    max_concurrent_requests: int = int(os.getenv("MAX_CONCURRENT_REQUESTS", "20"))
    
    # Prometheus specific optimizations
    prom_query_timeout: int = int(os.getenv("PROM_QUERY_TIMEOUT", "15"))
    prom_max_workers: int = int(os.getenv("PROM_MAX_WORKERS", "20"))
    prom_batch_size: int = int(os.getenv("PROM_BATCH_SIZE", "50"))
    prom_cache_ttl: int = int(os.getenv("PROM_CACHE_TTL", "300"))  # 5 minutes
    prom_enable_query_optimization: bool = os.getenv("PROM_ENABLE_QUERY_OPTIMIZATION", "true").lower() == "true"
    
    # Elasticsearch specific optimizations
    es_query_timeout: int = int(os.getenv("ES_QUERY_TIMEOUT", "120"))  # 120 seconds for log analysis (increased from 60)
    es_connection_timeout: int = int(os.getenv("ES_CONNECTION_TIMEOUT", "60"))  # 60 seconds for connection (increased from 30)
    es_max_retries: int = int(os.getenv("ES_MAX_RETRIES", "5"))  # 5 retries for failed requests (increased from 3)
    es_max_results_per_query: int = int(os.getenv("ES_MAX_RESULTS_PER_QUERY", "500"))  # cap per search to avoid bloated result sets
    es_track_total_hits: bool = os.getenv("ES_TRACK_TOTAL_HITS", "false").lower() == "true"  # default false for performance
    
    # Elasticsearch connection settings
    es_host: str = os.getenv("ES_HOST", "192.168.4.137")
    es_port: int = int(os.getenv("ES_PORT", "9200"))
    es_username: str = os.getenv("ES_USERNAME", "elastic")
    es_password: str = os.getenv("ES_PASSWORD", "changeme")
    es_index_pattern: str = os.getenv("ES_INDEX_PATTERN", "prod_error_logs*")
    es_log_field: str = os.getenv("ES_LOG_FIELD", "message")

    # AI Assist (Xinference / OpenAI-compatible)
    ai_assist_enabled: bool = os.getenv("AI_ASSIST_ENABLED", "true").lower() == "true"
    xinference_base_url: str = os.getenv("XINFERENCE_BASE_URL", "http://192.168.123.29:9997")
    xinference_model: str = os.getenv("XINFERENCE_MODEL", "deepseek-r1-distill-qwen")
    ai_request_timeout: int = int(os.getenv("AI_REQUEST_TIMEOUT", "60"))
    ai_max_assisted_per_batch: int = int(os.getenv("AI_MAX_ASSISTED_PER_BATCH", "50"))
    ai_use_for_all: bool = os.getenv("AI_USE_FOR_ALL", "true").lower() == "true"
    ai_cache_ttl: int = int(os.getenv("AI_CACHE_TTL", "1800"))
    ai_disable_concurrency: bool = os.getenv("AI_DISABLE_CONCURRENCY", "true").lower() == "true"
    ai_min_interval_ms: int = int(os.getenv("AI_MIN_INTERVAL_MS", "2000"))
    ai_max_tokens: int = int(os.getenv("AI_MAX_TOKENS", "10000"))
    # Dify settings
    dify_enabled: bool = os.getenv("DIFY_ENABLED", "true").lower() == "true"
    dify_base_url: str = os.getenv("DIFY_BASE_URL", "https://deepseek.itlong.com.cn")
    dify_api_key: str = os.getenv("DIFY_API_KEY", "app-z35roLyYe97ayYJeumCAnFrr")
    dify_default_user: str = os.getenv("DIFY_DEFAULT_USER", "ai-ops")
    
    # Database optimizations
    db_connection_pool_size: int = int(os.getenv("DB_CONNECTION_POOL_SIZE", "10"))
    db_batch_insert_size: int = int(os.getenv("DB_BATCH_INSERT_SIZE", "100"))
    db_enable_connection_pooling: bool = os.getenv("DB_ENABLE_CONNECTION_POOLING", "true").lower() == "true"
    
    # Memory management
    max_memory_usage: int = int(os.getenv("MAX_MEMORY_USAGE", "1024"))  # MB
    gc_threshold: int = int(os.getenv("GC_THRESHOLD", "100"))
    
    # Monitoring
    enable_metrics: bool = os.getenv("ENABLE_METRICS", "true").lower() == "true"
    metrics_port: int = int(os.getenv("METRICS_PORT", "9091"))


SETTINGS = Settings()


def setup_logging() -> None:
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, SETTINGS.log_level.upper()),
        format=SETTINGS.log_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("ai_ops.log", encoding="utf-8")
        ]
    )


class Cache:
    """Simple in-memory cache with TTL"""
    
    def __init__(self, ttl: int = 300):
        self._cache = {}
        self._ttl = ttl
    
    def get(self, key: str) -> Optional[any]:
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return value
            else:
                del self._cache[key]
        return None
    
    def set(self, key: str, value: any) -> None:
        self._cache[key] = (value, time.time())
    
    def clear(self) -> None:
        self._cache.clear()
    
    def size(self) -> int:
        return len(self._cache)


class RedisCache:
    """Redis cache with TTL support"""
    
    def __init__(self, host: str = "192.168.4.108", port: int = 30593, password: str = "tiqmo", db: int = 0, ttl: int = 300):
        self.host = host
        self.port = port
        self.password = password
        self.db = db
        self.ttl = ttl
        self._redis = None
        self._connected = False
    
    def _get_redis(self):
        """Get Redis connection"""
        if self._redis is None:
            try:
                import redis
                self._redis = redis.Redis(
                    host=self.host,
                    port=self.port,
                    password=self.password if self.password else None,
                    db=self.db,
                    decode_responses=True,
                    socket_connect_timeout=30,  # Increased from 5 to 30 seconds
                    socket_timeout=30,  # Increased from 5 to 30 seconds
                    retry_on_timeout=True,  # Enable retry on timeout
                    health_check_interval=30  # Health check every 30 seconds
                )
                # Test connection
                self._redis.ping()
                self._connected = True
                print(f"Redis connected to {self.host}:{self.port}")
            except Exception as e:
                print(f"Redis connection failed: {e}")
                self._connected = False
                self._redis = None
        return self._redis
    
    def get(self, key: str) -> Optional[any]:
        """Get value from Redis cache"""
        try:
            redis_client = self._get_redis()
            if redis_client:
                import json
                value = redis_client.get(key)
                if value:
                    return json.loads(value)
        except Exception as e:
            print(f"Redis get error: {e}")
        return None
    
    def set(self, key: str, value: any) -> None:
        """Set value in Redis cache with TTL"""
        try:
            redis_client = self._get_redis()
            if redis_client:
                import json
                from decimal import Decimal
                
                def json_serializer(obj):
                    """Custom JSON serializer for objects not serializable by default json code"""
                    if isinstance(obj, Decimal):
                        return float(obj)
                    elif isinstance(obj, datetime):
                        return obj.isoformat()
                    elif hasattr(obj, 'isoformat'):  # 处理其他日期时间类型
                        return obj.isoformat()
                    elif hasattr(obj, '__dict__'):  # 处理自定义对象
                        return obj.__dict__
                    else:
                        return str(obj)
                
                redis_client.setex(key, self.ttl, json.dumps(value, default=json_serializer))
        except Exception as e:
            print(f"Redis set error: {e}")

    def set_with_ttl(self, key: str, value: any, ttl_seconds: int) -> None:
        """Set value with a custom TTL overriding the default."""
        try:
            redis_client = self._get_redis()
            if redis_client:
                import json
                from decimal import Decimal

                def json_serializer(obj):
                    if isinstance(obj, Decimal):
                        return float(obj)
                    elif isinstance(obj, datetime):
                        return obj.isoformat()
                    elif hasattr(obj, 'isoformat'):
                        return obj.isoformat()
                    elif hasattr(obj, '__dict__'):
                        return obj.__dict__
                    else:
                        return str(obj)

                redis_client.setex(key, int(ttl_seconds), json.dumps(value, default=json_serializer))
        except Exception as e:
            print(f"Redis set_with_ttl error: {e}")
    
    # ---- Hash helpers for atomic counters ----
    def hgetall(self, key: str) -> dict:
        """Return all fields and values of a hash; returns {} on error or missing."""
        try:
            redis_client = self._get_redis()
            if not redis_client:
                return {}
            data = redis_client.hgetall(key)
            return data or {}
        except Exception as e:
            print(f"Redis hgetall error: {e}")
            return {}

    def hincrby(self, key: str, field: str, amount: int = 1) -> int | None:
        """Atomically increment a hash field by amount. Returns new value or None on error."""
        try:
            redis_client = self._get_redis()
            if not redis_client:
                return None
            return int(redis_client.hincrby(key, field, int(amount)))
        except Exception as e:
            print(f"Redis hincrby error: {e}")
            return None

    def hincrby_mapping(self, key: str, mapping: dict[str, int], ttl_seconds: int | None = None) -> None:
        """Atomically increment multiple hash fields using a pipeline. Optionally set TTL/expire."""
        try:
            redis_client = self._get_redis()
            if not redis_client or not isinstance(mapping, dict) or not mapping:
                return
            pipe = redis_client.pipeline(transaction=True)
            for field, amount in mapping.items():
                try:
                    pipe.hincrby(key, str(field), int(amount))
                except Exception:
                    pass
            if ttl_seconds and int(ttl_seconds) > 0:
                try:
                    pipe.expire(key, int(ttl_seconds))
                except Exception:
                    pass
            pipe.execute()
        except Exception as e:
            print(f"Redis hincrby_mapping error: {e}")

    def expire(self, key: str, ttl_seconds: int) -> bool:
        """Set a key's time to live in seconds. Returns True on success."""
        try:
            redis_client = self._get_redis()
            if not redis_client:
                return False
            return bool(redis_client.expire(key, int(ttl_seconds)))
        except Exception as e:
            print(f"Redis expire error: {e}")
            return False

    def try_acquire_lock(self, key: str, ttl_seconds: int = 60) -> bool:
        """Try acquire a simple distributed lock using SET NX EX. Returns True if acquired."""
        try:
            redis_client = self._get_redis()
            if not redis_client:
                return False
            # Redis-py set supports nx/ex flags
            return bool(redis_client.set(key, "1", nx=True, ex=int(ttl_seconds)))
        except Exception as e:
            print(f"Redis try_acquire_lock error: {e}")
            return False
    
    def clear(self) -> None:
        """Clear all cached data"""
        try:
            redis_client = self._get_redis()
            if redis_client:
                redis_client.flushdb()
        except Exception as e:
            print(f"Redis clear error: {e}")
    
    def size(self) -> int:
        """Get cache size"""
        try:
            redis_client = self._get_redis()
            if redis_client:
                return redis_client.dbsize()
        except Exception as e:
            print(f"Redis size error: {e}")
        return 0
    
    def is_connected(self) -> bool:
        """Check if Redis is connected"""
        # ensure at least one connection attempt
        self._get_redis()
        return self._connected

    def get_key_ttl(self, key: str) -> int | None:
        """Get TTL of a key in seconds; returns None if key has no TTL or on error"""
        try:
            redis_client = self._get_redis()
            if not redis_client:
                return None
            ttl_val = redis_client.ttl(key)
            if ttl_val is None:
                return None
            return int(ttl_val) if ttl_val >= 0 else None
        except Exception as e:
            print(f"Redis ttl error: {e}")
            return None


# Global cache instance
CACHE = Cache(SETTINGS.cache_ttl)

# Global Redis cache instance
REDIS_CACHE = RedisCache(
    host=SETTINGS.redis_host,
    port=SETTINGS.redis_port,
    password=SETTINGS.redis_password,
    db=SETTINGS.redis_db,
    ttl=SETTINGS.redis_cache_ttl
)


