from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional

import pymysql
from datetime import datetime

from app.core.config import SETTINGS

logger = logging.getLogger(__name__)


def get_connection() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=SETTINGS.db_host,
        port=SETTINGS.db_port,
        user=SETTINGS.db_user,
        password=SETTINGS.db_password,
        database=SETTINGS.db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        # 设置时区为中国东八区
        init_command="SET time_zone = '+08:00'",
    )


def init_schema() -> None:
    sqls = [
        # 巡检结果表（labels 使用 TEXT 存字符串，兼容旧版 MySQL）
        """
        CREATE TABLE IF NOT EXISTS inspection_results (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            check_name VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL,
            detail TEXT,
            severity VARCHAR(32),
            category VARCHAR(64),
            score DOUBLE,
            labels TEXT,
            instance VARCHAR(128),
            value DOUBLE,
            INDEX idx_ts (ts),
            INDEX idx_check_name (check_name),
            INDEX idx_status (status),
            INDEX idx_severity (severity),
            INDEX idx_category (category)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        # 巡检摘要表
        """
        CREATE TABLE IF NOT EXISTS inspection_summaries (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            total_checks INT NOT NULL,
            alert_count INT NOT NULL,
            error_count INT NOT NULL,
            ok_count INT NOT NULL,
            health_score DOUBLE NOT NULL,
            duration DOUBLE NOT NULL,
            targets_status LONGTEXT,
            alerts_status LONGTEXT,
            INDEX idx_ts (ts),
            INDEX idx_health_score (health_score)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        # 参数配置表
        """
        CREATE TABLE IF NOT EXISTS config_parameters (
            cfg_key VARCHAR(64) PRIMARY KEY,
            cfg_value VARCHAR(256) NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        # 巡检配置表
        """
        CREATE TABLE IF NOT EXISTS inspection_configs (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(128) NOT NULL UNIQUE,
            description TEXT,
            query_expr TEXT NOT NULL,
            severity VARCHAR(32) NOT NULL DEFAULT 'warning',
            category VARCHAR(64) NOT NULL DEFAULT 'general',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            threshold DOUBLE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_enabled (enabled),
            INDEX idx_category (category)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        # 服务器资源快照表（每5分钟一条快照）
        """
        CREATE TABLE IF NOT EXISTS server_resource_snapshots (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            instance VARCHAR(128) NOT NULL,
            hostname VARCHAR(255),
            cpu_usage DOUBLE,
            cpu_cores INT,
            mem_usage DOUBLE,
            mem_total_gb DOUBLE,
            disk_usage DOUBLE,
            disk_json TEXT,
            metrics_json TEXT,
            INDEX idx_ts (ts),
            INDEX idx_instance (instance)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
    ]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for s in sqls:
                cur.execute(s)
        logger.info("Database schema ensured")
    finally:
        conn.close()
    
    # 确保所有必需的字段都存在
    ensure_table_columns()


def ensure_table_columns() -> None:
    """确保表中有所有必需的字段"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 检查inspection_results表的字段
            cur.execute("DESCRIBE inspection_results")
            columns = [row['Field'] for row in cur.fetchall()]
            
            # 需要添加的字段
            missing_columns = []
            
            if 'category' not in columns:
                missing_columns.append("ADD COLUMN category VARCHAR(64)")
            if 'score' not in columns:
                missing_columns.append("ADD COLUMN score DOUBLE")
            if 'instance' not in columns:
                missing_columns.append("ADD COLUMN instance VARCHAR(128)")
            if 'value' not in columns:
                missing_columns.append("ADD COLUMN value DOUBLE")
            
            # 添加缺失的字段
            if missing_columns:
                for column_def in missing_columns:
                    try:
                        cur.execute(f"ALTER TABLE inspection_results {column_def}")
                        logger.info(f"Added column to inspection_results: {column_def}")
                    except Exception as e:
                        logger.warning(f"Failed to add column {column_def}: {e}")
                
                # 添加索引
                try:
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_category ON inspection_results (category)")
                except:
                    pass  # 索引可能已存在
                
                logger.info("Table columns updated")
            else:
                logger.info("All required columns exist")
                
    finally:
        conn.close()


def insert_inspections(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    sql = (
        "INSERT INTO inspection_results (ts, check_name, status, detail, severity, category, score, labels, instance, value) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            data = [
                (
                    r.get("@timestamp").replace("T", " ").replace("Z", ""),
                    r.get("check"),
                    r.get("status"),
                    r.get("detail"),
                    r.get("labels", {}).get("severity"),
                    r.get("category", "general"),
                    r.get("score"),
                    str(r.get("labels")),
                    r.get("instance"),
                    r.get("value")
                )
                for r in rows
            ]
            cur.executemany(sql, data)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def insert_server_resource_snapshots(resources: List[Dict[str, Any]]) -> int:
    """将 Prometheus 拉取的服务器资源汇总写入快照表"""
    if not resources:
        return 0
    sql = (
        "INSERT INTO server_resource_snapshots (ts, instance, hostname, cpu_usage, cpu_cores, mem_usage, mem_total_gb, disk_usage, disk_json, metrics_json) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            data = []
            for r in resources:
                instance = r.get("instance")
                hostname = (r.get("system") or {}).get("hostname")
                cpu = (r.get("cpu") or {})
                mem = (r.get("memory") or {})
                disk = (r.get("disk") or {})
                disk_partitions = (disk.get("partitions") or [])
                disk_usage = 0.0
                try:
                    if disk_partitions:
                        disk_usage = max([float(p.get("usage_percent", 0)) for p in disk_partitions])
                except Exception:
                    disk_usage = 0.0
                import json
                data.append(
                    (
                        r.get("timestamp"),
                        instance,
                        hostname,
                        float(cpu.get("usage_percent", 0.0)),
                        int(cpu.get("cores", 0) or 0),
                        float(mem.get("usage_percent", 0.0)),
                        float(mem.get("total_gb", 0.0)),
                        float(disk_usage),
                        json.dumps(disk_partitions, ensure_ascii=False),
                        json.dumps(r, ensure_ascii=False),
                    )
                )
            cur.executemany(sql, data)
        conn.commit()
        return len(resources)
    finally:
        conn.close()


# ---------- 配置读取/写入 ----------

def set_config(key: str, value: str) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO config_parameters (cfg_key, cfg_value) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE cfg_value=VALUES(cfg_value)",
                (key, value),
            )
        conn.commit()
    finally:
        conn.close()


def get_config(key: str, default: Optional[str] = None) -> str:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT cfg_value FROM config_parameters WHERE cfg_key=%s", (key,))
            row = cur.fetchone()
            return row["cfg_value"] if row else (default or "")
    finally:
        conn.close()


def get_health_thresholds() -> Dict[str, float]:
    cpu = float(get_config("health.cpu_threshold", "85"))
    mem = float(get_config("health.mem_threshold", "85"))
    disk_hours = float(get_config("health.disk_predict_hours", "4"))
    return {"cpu": cpu, "mem": mem, "disk_hours": disk_hours}


def set_health_thresholds(cpu: float, mem: float, disk_hours: float) -> None:
    set_config("health.cpu_threshold", str(cpu))
    set_config("health.mem_threshold", str(mem))
    set_config("health.disk_predict_hours", str(disk_hours))


def insert_inspection_summary(summary: Dict[str, Any]) -> int:
    """插入巡检摘要"""
    if not summary:
        return 0
    
    sql = """
        INSERT INTO inspection_summaries 
        (ts, total_checks, alert_count, error_count, ok_count, health_score, duration, targets_status, alerts_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            data = (
                summary.get("timestamp", datetime.now()).replace("T", " ").replace("Z", ""),
                summary.get("total_checks", 0),
                summary.get("alert_count", 0),
                summary.get("error_count", 0),
                summary.get("ok_count", 0),
                summary.get("health_score", 0.0),
                summary.get("duration", 0.0),
                str(summary.get("targets_status", {})),
                str(summary.get("alerts_status", {}))
            )
            cur.execute(sql, data)
        conn.commit()
        return 1
    finally:
        conn.close()


def get_inspection_summaries(hours: int = 24) -> List[Dict[str, Any]]:
    """获取巡检摘要历史"""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ts, total_checks, alert_count, error_count, ok_count, health_score, duration
                FROM inspection_summaries 
                WHERE ts >= DATE_SUB(NOW(), INTERVAL %s HOUR)
                ORDER BY ts DESC
            """, (hours,))
            rows = cur.fetchall()
            return rows
    except Exception as e:
        logger.error(f"获取巡检摘要失败: {e}")
        return []


def get_inspection_stats(days: int = 7) -> Dict[str, Any]:
    """获取巡检统计信息"""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # 总体统计
            cur.execute("""
                SELECT 
                    COUNT(*) as total_inspections,
                    AVG(health_score) as avg_health_score,
                    MIN(health_score) as min_health_score,
                    MAX(health_score) as max_health_score
                FROM inspection_summaries 
                WHERE ts >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """, (days,))
            overall_stats = cur.fetchone()
            
            # 按类别统计
            cur.execute("""
                SELECT 
                    category,
                    COUNT(*) as total_checks,
                    SUM(CASE WHEN status = 'alert' THEN 1 ELSE 0 END) as alert_count,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                    SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as ok_count
                FROM inspection_results 
                WHERE ts >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY category
                ORDER BY alert_count DESC
            """, (days,))
            category_stats = cur.fetchall()
            
            return {
                "overall": overall_stats,
                "by_category": category_stats
            }
    except Exception as e:
        logger.error(f"获取巡检统计失败: {e}")
        return {"overall": {}, "by_category": []}
