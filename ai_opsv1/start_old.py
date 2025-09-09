#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-Ops 巡检系统 - 跨平台启动脚本
支持 Windows、Linux、macOS
"""

import os
import sys
import subprocess
import platform
import time
from pathlib import Path

# 关键依赖列表，确保这些模块必须安装
REQUIRED_MODULES = [
    "elasticsearch",
    # 可以添加其他必须的模块
]


def print_banner():
    """打印启动横幅"""
    print("=" * 50)
    print("   AI-Ops 智能运维巡检系统")
    print("   跨平台启动脚本")
    print("=" * 50)
    print()


def check_python():
    """检查Python环境"""
    print("[1/6] 检查Python环境...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 7):
        print("❌ Python版本过低，需要Python 3.7+")
        return False
    print(f"✅ Python环境正常 (Python {version.major}.{version.minor}.{version.micro})")
    return True


def check_required_modules():
    """检查关键依赖模块是否已安装"""
    print("[2/6] 检查关键依赖模块...")
    missing = []
    for module in REQUIRED_MODULES:
        try:
            __import__(module)
            print(f"✅ {module} 已安装")
        except ImportError:
            missing.append(module)
            print(f"❌ {module} 未安装")

    if missing:
        print(f"⚠️  发现缺失的关键依赖: {', '.join(missing)}")
        return False
    return True


def install_dependencies():
    """安装依赖包"""
    print("\n[3/6] 安装依赖包...")
    try:
        # 先确保pip是最新版本
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--upgrade", "pip"
        ], check=True, capture_output=True, text=True)

        # 安装requirements.txt中的依赖
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
        ], capture_output=True, text=True)

        # 检查并单独安装可能缺失的关键依赖
        for module in REQUIRED_MODULES:
            try:
                __import__(module)
            except ImportError:
                print(f"⚠️  尝试单独安装 {module}...")
                subprocess.run([
                    sys.executable, "-m", "pip", "install", module
                ], check=True, capture_output=True, text=True)

        print("✅ 依赖包安装完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 依赖安装失败: {e.stderr}")
        return False
    except Exception as e:
        print(f"⚠️  依赖安装出错: {e}")
        return False


def init_database():
    """初始化数据库"""
    print("\n[4/6] 初始化数据库...")
    try:
        result = subprocess.run([
            sys.executable, "main.py", "setup"
        ], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ 数据库初始化完成")
        else:
            print(f"⚠️  数据库初始化失败: {result.stderr}，尝试继续运行...")
        return True
    except Exception as e:
        print(f"⚠️  数据库初始化出错: {e}")
        return False


def run_first_inspection():
    """执行首次巡检"""
    print("\n[5/6] 执行首次巡检...")
    print("🔍 正在执行系统巡检...")
    try:
        result = subprocess.run([
            sys.executable, "main.py", "inspect"
        ], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("✅ 首次巡检完成")
        else:
            print(f"⚠️  首次巡检失败: {result.stderr}，但系统仍可正常运行")
        return True
    except subprocess.TimeoutExpired:
        print("⚠️  首次巡检超时，但系统仍可正常运行")
        return False
    except Exception as e:
        print(f"⚠️  首次巡检出错: {e}")
        return False


def start_services():
    """启动服务"""
    print("\n[6/6] 启动完整服务...")
    print()
    print("🚀 正在启动AI-Ops巡检系统...")
    print("📊 主仪表板: http://localhost:8000/")
    print("📋 巡检报告: http://localhost:8000/reports")
    print("📚 API文档: http://localhost:8000/docs")
    print()
    print("🔄 定时巡检: 每5分钟自动执行")
    print("💡 按 Ctrl+C 停止所有服务")
    print("=" * 50)
    print()

    # 启动定时巡检服务（后台运行）
    if platform.system() == "Windows":
        # Windows使用start命令
        subprocess.Popen([
            "start", "/B", sys.executable, "main.py", "schedule", "--health-interval", "300"
        ], shell=True)
    else:
        # Linux/macOS 直接以后台子进程方式启动，并将输出重定向到日志文件
        try:
            log_path = Path("schedule.log")
            log_file = open(log_path, "ab")
            subprocess.Popen(
                [sys.executable, "main.py", "schedule", "--health-interval", "300"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                close_fds=True
            )
        except Exception:
            pass

    print("定时巡检服务已启动")

    # 启动Web服务器
    try:
        subprocess.run([
            sys.executable, "main.py", "serve", "--host", "0.0.0.0", "--port", "8000"
        ])
    except KeyboardInterrupt:
        print("\n正在停止服务...")
        stop_services()


def stop_services():
    """停止服务"""
    print("🔄 正在停止所有服务...")

    if platform.system() == "Windows":
        # Windows停止Python进程，更精确地只停止相关进程
        try:
            # 先获取所有包含main.py的Python进程ID
            result = subprocess.run(
                ["wmic", "process", "where", "commandline like '%main.py%'", "get", "processid"],
                capture_output=True, text=True, shell=True
            )
            pids = [line.strip() for line in result.stdout.split() if line.strip().isdigit()]
            for pid in pids:
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, shell=True)
        except Exception as e:
            print(f"停止服务时出错: {e}")
    else:
        # Linux/macOS停止相关进程
        subprocess.run(["pkill", "-f", "main.py"], capture_output=True)

    print("✅ 所有服务已停止")


def main():
    """主函数"""
    print_banner()

    # 检查Python环境
    if not check_python():
        sys.exit(1)

    # 先检查关键模块，如果缺失则安装
    if not check_required_modules():
        print("尝试安装缺失的依赖...")
        if not install_dependencies():
            print("❌ 关键依赖安装失败，无法继续运行")
            sys.exit(1)

        # 安装后再次检查
        if not check_required_modules():
            print("❌ 仍然存在缺失的关键依赖，无法继续运行")
            sys.exit(1)

    # 初始化数据库
    init_database()

    # 执行首次巡检
    run_first_inspection()

    # 启动服务
    start_services()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中断，正在退出...")
        stop_services()
    except Exception as e:
        print(f"\n启动失败: {e}")
        sys.exit(1)
