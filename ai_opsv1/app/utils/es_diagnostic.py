#!/usr/bin/env python3
"""
Elasticsearch诊断脚本
用于排查连接、查询和配置问题
"""

import os
import sys
import time
from datetime import datetime, timedelta
import json

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.config import SETTINGS
from app.services.log_analyzer import LogAnalyzer

def test_es_connection():
    """测试Elasticsearch连接"""
    print("=== Elasticsearch连接测试 ===")
    print(f"配置信息:")
    print(f"  - 主机: {SETTINGS.es_host}")
    print(f"  - 端口: {SETTINGS.es_port}")
    print(f"  - 连接超时: {SETTINGS.es_connection_timeout}秒")
    print(f"  - 查询超时: {SETTINGS.es_query_timeout}秒")
    print(f"  - 最大重试: {SETTINGS.es_max_retries}次")
    
    try:
        analyzer = LogAnalyzer()
        if not analyzer.es_client:
            print("❌ Elasticsearch客户端初始化失败")
            return False
        
        # 测试连接
        start_time = time.time()
        if analyzer.es_client.ping():
            connection_time = time.time() - start_time
            print(f"✅ 连接成功 (耗时: {connection_time:.2f}秒)")
        else:
            print("❌ 连接失败")
            return False
            
    except Exception as e:
        print(f"❌ 连接异常: {e}")
        return False
    
    return True

def test_es_cluster_info():
    """测试集群信息"""
    print("\n=== 集群信息测试 ===")
    try:
        analyzer = LogAnalyzer()
        if not analyzer.es_client:
            return False
        
        # 获取集群信息
        info = analyzer.es_client.info()
        print(f"集群名称: {info.get('cluster_name', 'N/A')}")
        print(f"版本: {info.get('version', {}).get('number', 'N/A')}")
        print(f"节点名称: {info.get('name', 'N/A')}")
        
        # 获取健康状态
        health = analyzer.es_client.cluster.health()
        print(f"集群状态: {health.get('status', 'N/A')}")
        print(f"节点数量: {health.get('number_of_nodes', 'N/A')}")
        print(f"数据节点: {health.get('number_of_data_nodes', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"❌ 获取集群信息失败: {e}")
        return False

def test_es_indices():
    """测试索引信息"""
    print("\n=== 索引信息测试 ===")
    try:
        analyzer = LogAnalyzer()
        if not analyzer.es_client:
            return False
        
        # 获取所有索引
        indices = analyzer.es_client.cat.indices(format='json')
        print(f"索引总数: {len(indices)}")
        
        if indices:
            print("\n前10个索引:")
            for idx in indices[:10]:
                print(f"  - {idx.get('index', 'N/A')}: {idx.get('docs.count', '0')} 文档, {idx.get('store.size', '0')}")
        else:
            print("⚠️  没有找到任何索引")
        
        # 检查日志索引模式
        print(f"\n日志索引模式: {analyzer.es_index_pattern}")
        matching_indices = [idx for idx in indices if analyzer.es_index_pattern.replace('*', '') in idx.get('index', '')]
        print(f"匹配的索引数量: {len(matching_indices)}")
        
        if matching_indices:
            print("匹配的索引:")
            for idx in matching_indices[:5]:
                print(f"  - {idx.get('index', 'N/A')}: {idx.get('docs.count', '0')} 文档")
        else:
            print("⚠️  没有找到匹配的日志索引")
        
        return True
        
    except Exception as e:
        print(f"❌ 获取索引信息失败: {e}")
        return False

def test_es_query():
    """测试查询功能"""
    print("\n=== 查询功能测试 ===")
    try:
        analyzer = LogAnalyzer()
        if not analyzer.es_client:
            return False
        
        # 测试简单查询
        print("测试1: 查询最近1分钟的日志...")
        start_time = time.time()
        
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": "now-1m"}}},
                        {"exists": {"field": analyzer.es_field}}
                    ]
                }
            },
            "size": 10
        }
        
        response = analyzer.es_client.search(
            index=analyzer.es_index_pattern,
            body=query,
            request_timeout=SETTINGS.es_query_timeout
        )
        
        query_time = time.time() - start_time
        total_hits = response.get("hits", {}).get("total", {}).get("value", 0)
        
        print(f"✅ 查询成功 (耗时: {query_time:.2f}秒)")
        print(f"总命中数: {total_hits}")
        print(f"返回结果数: {len(response.get('hits', {}).get('hits', []))}")
        
        if total_hits > 0:
            print("前3条结果:")
            for i, hit in enumerate(response.get("hits", {}).get("hits", [])[:3]):
                source = hit.get("_source", {})
                print(f"  {i+1}. {source.get('@timestamp', 'N/A')} - {source.get(analyzer.es_field, 'N/A')[:100]}...")
        else:
            print("⚠️  没有找到最近1分钟的日志数据")
        
        return True
        
    except Exception as e:
        print(f"❌ 查询测试失败: {e}")
        return False

def test_es_field():
    """测试字段配置"""
    print("\n=== 字段配置测试 ===")
    try:
        analyzer = LogAnalyzer()
        if not analyzer.es_client:
            return False
        
        print(f"日志字段: {analyzer.es_field}")
        
        # 检查字段映射
        try:
            mapping = analyzer.es_client.indices.get_mapping(index=analyzer.es_index_pattern)
            print("字段映射获取成功")
            
            # 查找日志字段
            field_found = False
            for index_name, index_mapping in mapping.items():
                properties = index_mapping.get("mappings", {}).get("properties", {})
                if analyzer.es_field in properties:
                    field_found = True
                    field_type = properties[analyzer.es_field].get("type", "unknown")
                    print(f"字段 '{analyzer.es_field}' 在索引 '{index_name}' 中找到，类型: {field_type}")
                    break
            
            if not field_found:
                print(f"⚠️  字段 '{analyzer.es_field}' 在索引中未找到")
                
        except Exception as e:
            print(f"⚠️  获取字段映射失败: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ 字段配置测试失败: {e}")
        return False

def test_recent_data():
    """测试最近数据"""
    print("\n=== 最近数据测试 ===")
    try:
        analyzer = LogAnalyzer()
        if not analyzer.es_client:
            return False
        
        # 测试不同时间范围
        time_ranges = [1, 5, 10, 30]
        
        for minutes in time_ranges:
            print(f"\n测试最近 {minutes} 分钟的数据...")
            start_time = time.time()
            
            try:
                logs = analyzer.collect_recent_logs(minutes)
                query_time = time.time() - start_time
                
                print(f"✅ 查询成功 (耗时: {query_time:.2f}秒)")
                print(f"返回日志数: {len(logs)}")
                
                if logs:
                    print(f"时间范围: {logs[0].get('@timestamp', 'N/A')} 到 {logs[-1].get('@timestamp', 'N/A')}")
                else:
                    print("⚠️  没有数据")
                    
            except Exception as e:
                print(f"❌ 查询失败: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ 最近数据测试失败: {e}")
        return False

def main():
    """主函数"""
    print("Elasticsearch诊断工具")
    print("=" * 50)
    
    # 检查配置
    if not hasattr(SETTINGS, 'es_host'):
        print("❌ 配置文件中缺少Elasticsearch配置")
        return
    
    # 运行测试
    tests = [
        test_es_connection,
        test_es_cluster_info,
        test_es_indices,
        test_es_field,
        test_es_query,
        test_recent_data
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ 测试异常: {e}")
    
    print("\n" + "=" * 50)
    print(f"诊断完成: {passed}/{total} 项测试通过")
    
    if passed == total:
        print("✅ 所有测试通过，Elasticsearch配置正常")
    else:
        print("⚠️  部分测试失败，请检查配置和连接")

if __name__ == "__main__":
    main()

