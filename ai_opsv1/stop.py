#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-Ops 巡检系统 - 跨平台停止脚本
支持 Windows、Linux、macOS
"""

import os
import sys
import subprocess
import platform
import signal

def print_banner():
    """打印停止横幅"""
    print("=" * 50)
    print("    停止 AI-Ops 巡检系统")
    print("=" * 50)
    print()

def stop_services():
    """停止所有服务"""
    print("🔄 正在停止所有Python进程...")
    
    system = platform.system()
    
    if system == "Windows":
        # Windows停止Python进程
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/IM", "python.exe"], 
                capture_output=True, 
                shell=True,
                text=True
            )
            if result.returncode == 0:
                print("✅ 已停止所有Python进程")
            else:
                print("✅ 没有找到运行的Python进程")
        except Exception as e:
            print(f"⚠️  停止进程时出错: {e}")
    else:
        # Linux/macOS停止相关进程
        try:
            # 先尝试优雅停止
            result = subprocess.run(
                ["pkill", "-f", "main.py"], 
                capture_output=True,
                text=True
            )
            
            # 等待2秒
            import time
            time.sleep(2)
            
            # 强制停止仍在运行的进程
            result = subprocess.run(
                ["pkill", "-9", "-f", "main.py"], 
                capture_output=True,
                text=True
            )
            
            print("✅ 已停止所有Python进程")
        except Exception as e:
            print(f"⚠️  停止进程时出错: {e}")

def check_web_server():
    """检查Web服务器状态"""
    print("\n🔄 正在检查Web服务器状态...")
    
    system = platform.system()
    
    if system == "Windows":
        # Windows检查端口
        try:
            result = subprocess.run(
                ["netstat", "-an"], 
                capture_output=True, 
                text=True
            )
            if ":8000" in result.stdout:
                print("⚠️  请手动检查8000端口是否已释放")
            else:
                print("✅ Web服务器已停止")
        except Exception as e:
            print(f"⚠️  检查端口时出错: {e}")
    else:
        # Linux/macOS检查端口
        try:
            result = subprocess.run(
                ["netstat", "-tlnp"], 
                capture_output=True, 
                text=True
            )
            if ":8000" in result.stdout:
                print("⚠️  请手动检查8000端口是否已释放")
            else:
                print("✅ Web服务器已停止")
        except Exception as e:
            print(f"⚠️  检查端口时出错: {e}")

def cleanup_files():
    """清理临时文件"""
    print("\n🔄 清理临时文件...")
    
    temp_files = [
        "schedule.log",
        "nohup.out",
        "ai_ops.log"
    ]
    
    for file in temp_files:
        if os.path.exists(file):
            try:
                os.remove(file)
                print(f"✅ 已删除 {file}")
            except Exception as e:
                print(f"⚠️  删除 {file} 失败: {e}")

def main():
    """主函数"""
    print_banner()
    
    # 停止服务
    stop_services()
    
    # 检查Web服务器
    check_web_server()
    
    # 清理文件
    cleanup_files()
    
    print("\n✅ AI-Ops巡检系统已完全停止")
    print()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中断，正在退出...")
    except Exception as e:
        print(f"\n停止失败: {e}")
        sys.exit(1)
