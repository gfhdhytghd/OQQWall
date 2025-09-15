#!/usr/bin/env python3
"""
OQQWall 网页端审核系统演示脚本
展示新功能和使用方法
"""

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

def main():
    print("🎉 OQQWall 网页端审核系统 v2.0")
    print("=" * 50)
    
    # 检查依赖
    print("📋 检查系统依赖...")
    
    # 检查 web_review.py 是否存在
    web_review_path = Path("web_review.py")
    if not web_review_path.exists():
        print("❌ 错误：找不到 web_review.py 文件")
        return 1
    
    # 检查数据库文件
    db_path = Path("cache/OQQWall.db")
    if not db_path.exists():
        print("⚠️  警告：数据库文件不存在，将创建空数据库")
        db_path.parent.mkdir(exist_ok=True)
    
    # 检查预处理目录
    prepost_dir = Path("cache/prepost")
    if not prepost_dir.exists():
        print("⚠️  警告：预处理目录不存在，将创建")
        prepost_dir.mkdir(exist_ok=True)
    
    print("✅ 系统检查完成")
    
    # 启动服务
    print("\n🚀 启动网页端审核服务...")
    print("📍 服务地址：http://localhost:8090")
    print("⌨️  按 Ctrl+C 停止服务")
    print("=" * 50)
    
    try:
        # 启动 web_review.py
        process = subprocess.Popen([
            sys.executable, "web_review.py", "--port", "8090"
        ])
        
        # 等待服务启动
        time.sleep(2)
        
        # 自动打开浏览器
        try:
            webbrowser.open("http://localhost:8090")
            print("🌐 已自动打开浏览器")
        except Exception as e:
            print(f"⚠️  无法自动打开浏览器：{e}")
            print("请手动访问：http://localhost:8090")
        
        # 等待用户中断
        process.wait()
        
    except KeyboardInterrupt:
        print("\n🛑 正在停止服务...")
        process.terminate()
        process.wait()
        print("✅ 服务已停止")
    except Exception as e:
        print(f"❌ 启动失败：{e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())


