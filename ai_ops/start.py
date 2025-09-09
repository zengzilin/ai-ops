#!/usr/bin/env python3
"""
新的启动脚本 - 使用重新组织的项目结构
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

if __name__ == "__main__":
    main()
