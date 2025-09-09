#!/usr/bin/env python3
"""
语法检查脚本
用于验证Python文件的语法是否正确
"""

import ast
import sys
import os

def check_python_syntax(file_path):
    """检查Python文件语法"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 尝试解析AST
        ast.parse(content)
        print(f"✅ {file_path} - 语法正确")
        return True
        
    except SyntaxError as e:
        print(f"❌ {file_path} - 语法错误: {e}")
        print(f"  行号: {e.lineno}")
        print(f"  列号: {e.offset}")
        print(f"  错误: {e.text}")
        return False
        
    except Exception as e:
        print(f"❌ {file_path} - 其他错误: {e}")
        return False

def main():
    """主函数"""
    print("Python语法检查工具")
    print("=" * 50)
    
    # 需要检查的文件列表
    files_to_check = [
        "config.py",
        "log_analyzer.py", 
        "frontend.py",
        "main.py"
    ]
    
    passed = 0
    total = len(files_to_check)
    
    for file_path in files_to_check:
        if os.path.exists(file_path):
            if check_python_syntax(file_path):
                passed += 1
        else:
            print(f"⚠️  {file_path} - 文件不存在")
    
    print("\n" + "=" * 50)
    print(f"检查完成: {passed}/{total} 个文件语法正确")
    
    if passed == total:
        print("✅ 所有文件语法正确，可以启动服务")
        return 0
    else:
        print("❌ 存在语法错误，请修复后重试")
        return 1

if __name__ == "__main__":
    sys.exit(main())

