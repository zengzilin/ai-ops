#!/usr/bin/env python3
"""
测试前端API数据格式
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from frontend import create_app
import json

def test_server_resources_api():
    """测试服务器资源API返回格式"""
    app = create_app()
    
    with app.test_client() as client:
        # 测试服务器资源API
        response = client.get('/api/server-resources')
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.get_json()
            print("API返回数据结构:")
            print(f"- 包含 'data' 字段: {'data' in data}")
            print(f"- 包含 'count' 字段: {'count' in data}")
            print(f"- 包含 'timestamp' 字段: {'timestamp' in data}")
            print(f"- data 字段类型: {type(data.get('data', None))}")
            print(f"- data 字段长度: {len(data.get('data', []))}")
            
            if data.get('data'):
                print(f"- 第一个服务器数据示例: {json.dumps(data['data'][0], indent=2, ensure_ascii=False)}")
        else:
            print(f"API调用失败: {response.get_data()}")

def test_alerts_api():
    """测试告警API返回格式"""
    app = create_app()
    
    with app.test_client() as client:
        # 测试告警API
        response = client.get('/api/alerts')
        print(f"\n告警API状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.get_json()
            print("告警API返回数据结构:")
            print(f"- 包含 'alerts' 字段: {'alerts' in data}")
            print(f"- 包含 'timestamp' 字段: {'timestamp' in data}")
            print(f"- alerts 字段类型: {type(data.get('alerts', None))}")
            print(f"- alerts 字段长度: {len(data.get('alerts', []))}")
        else:
            print(f"告警API调用失败: {response.get_data()}")

if __name__ == "__main__":
    print("测试前端API数据格式...")
    test_server_resources_api()
    test_alerts_api()
