#!/usr/bin/env python3
"""
测试Prometheus数据获取问题
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SETTINGS
from app.services.prom_client import PrometheusClient, get_server_resources
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_prometheus_connection():
    """测试Prometheus连接"""
    logger.info("测试Prometheus连接...")
    logger.info(f"Prometheus URL: {SETTINGS.prom_url}")
    
    try:
        prom = PrometheusClient()
        
        # 测试基本连接
        if prom.ping():
            logger.info("✅ Prometheus连接成功!")
        else:
            logger.error("❌ Prometheus ping失败")
            return False
        
        # 测试获取up指标
        logger.info("测试获取up指标...")
        up_metrics = prom.get_metrics("up")
        logger.info(f"找到 {len(up_metrics)} 个up指标")
        
        for i, metric in enumerate(up_metrics[:3]):  # 只显示前3个
            logger.info(f"  {i+1}. {metric.get('metric', {})}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Prometheus连接失败: {e}")
        return False

def test_node_metrics():
    """测试node指标"""
    logger.info("测试node指标...")
    
    try:
        prom = PrometheusClient()
        
        # 测试CPU指标
        logger.info("测试node_cpu_seconds_total指标...")
        cpu_metrics = prom.get_metrics("node_cpu_seconds_total")
        logger.info(f"找到 {len(cpu_metrics)} 个CPU指标")
        
        # 测试内存指标
        logger.info("测试node_memory_MemTotal_bytes指标...")
        mem_metrics = prom.get_metrics("node_memory_MemTotal_bytes")
        logger.info(f"找到 {len(mem_metrics)} 个内存指标")
        
        # 测试磁盘指标
        logger.info("测试node_filesystem_size_bytes指标...")
        disk_metrics = prom.get_metrics("node_filesystem_size_bytes")
        logger.info(f"找到 {len(disk_metrics)} 个磁盘指标")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ node指标测试失败: {e}")
        return False

def test_custom_query():
    """测试自定义查询"""
    logger.info("测试自定义查询...")
    
    try:
        prom = PrometheusClient()
        
        # 测试你提到的查询
        query = '100 - ((node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100)'
        logger.info(f"执行查询: {query}")
        
        result = prom.instant(query)
        logger.info(f"查询结果: {result}")
        
        if result.get("data", {}).get("result"):
            logger.info("✅ 自定义查询成功!")
            for i, item in enumerate(result["data"]["result"][:3]):
                logger.info(f"  结果 {i+1}: {item}")
            return True
        else:
            logger.warning("⚠️ 查询返回空结果")
            return False
            
    except Exception as e:
        logger.error(f"❌ 自定义查询失败: {e}")
        return False

def test_server_resources():
    """测试服务器资源获取"""
    logger.info("测试服务器资源获取...")
    
    try:
        prom = PrometheusClient()
        resources = get_server_resources(prom)
        
        logger.info(f"获取到 {len(resources)} 个服务器资源")
        
        if resources:
            logger.info("✅ 服务器资源获取成功!")
            for i, resource in enumerate(resources[:2]):  # 只显示前2个
                logger.info(f"  服务器 {i+1}: {resource.get('instance', 'unknown')}")
                logger.info(f"    CPU: {resource.get('cpu', {})}")
                logger.info(f"    内存: {resource.get('memory', {})}")
                logger.info(f"    磁盘: {resource.get('disk', {})}")
        else:
            logger.warning("⚠️ 没有获取到服务器资源")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 服务器资源获取失败: {e}")
        return False

def main():
    """运行所有测试"""
    logger.info("开始Prometheus数据诊断...")
    
    tests = [
        ("Prometheus连接", test_prometheus_connection),
        ("Node指标", test_node_metrics),
        ("自定义查询", test_custom_query),
        ("服务器资源", test_server_resources),
    ]
    
    results = {}
    for test_name, test_func in tests:
        logger.info(f"\n{'='*50}")
        logger.info(f"测试: {test_name}")
        logger.info('='*50)
        try:
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"测试 {test_name} 出现异常: {e}")
            results[test_name] = False
    
    logger.info(f"\n{'='*50}")
    logger.info("测试结果汇总:")
    logger.info('='*50)
    for test_name, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        logger.info(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    if all_passed:
        logger.info("🎉 所有测试通过!")
    else:
        logger.error("💥 部分测试失败!")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
