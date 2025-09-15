#!/usr/bin/env python3
"""
测试 processsend.sh 调用
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def test_processsend_call(tag, cmd, flag=None):
    """测试调用 processsend.sh"""
    print(f"🧪 测试调用: processsend.sh '{tag} {cmd}' {' '.join([flag]) if flag else ''}")
    
    # 构建命令
    args = [tag, cmd]
    if flag:
        args.append(flag)
    
    cmd_str = ' '.join(args)
    cmdline = ['bash', '-lc', f"./getmsgserv/processsend.sh '{cmd_str}'"]
    
    print(f"📋 执行命令: {' '.join(cmdline)}")
    
    try:
        proc = subprocess.run(
            cmdline,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        
        print(f"✅ 命令执行完成")
        print(f"📤 退出码: {proc.returncode}")
        
        if proc.stdout:
            print(f"📤 输出:")
            print(proc.stdout)
        
        if proc.stderr:
            print(f"⚠️  错误:")
            print(proc.stderr)
            
        return proc.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("❌ 命令执行超时")
        return False
    except Exception as e:
        print(f"❌ 命令执行失败: {e}")
        return False

def main():
    print("🧪 processsend.sh 调用测试")
    print("=" * 50)
    
    # 测试不同的命令
    test_cases = [
        ("50", "是"),
        ("50", "否"),
        ("50", "匿"),
        ("50", "刷新"),
        ("50", "重渲染"),
    ]
    
    for tag, cmd in test_cases:
        print(f"\n🔍 测试: {tag} {cmd}")
        success = test_processsend_call(tag, cmd)
        print(f"结果: {'✅ 成功' if success else '❌ 失败'}")
        print("-" * 30)

if __name__ == "__main__":
    main()


