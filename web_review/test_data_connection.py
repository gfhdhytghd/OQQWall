#!/usr/bin/env python3
"""
测试数据连接和显示
"""

import sqlite3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'cache' / 'OQQWall.db'

def test_database_connection():
    """测试数据库连接"""
    print("🔍 测试数据库连接...")
    
    if not DB_PATH.exists():
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return False
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 检查表结构
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]
        print(f"✅ 数据库连接成功，找到表: {tables}")
        
        # 检查 preprocess 表
        if 'preprocess' in tables:
            cur.execute("SELECT COUNT(*) FROM preprocess")
            count = cur.fetchone()[0]
            print(f"📊 preprocess 表中有 {count} 条记录")
            
            if count > 0:
                # 显示最新的几条记录
                cur.execute("""
                    SELECT p.tag, p.senderid, p.nickname, p.receiver, p.ACgroup, p.comment, p.AfterLM,
                           s.modtime as submit_time
                    FROM preprocess p
                    LEFT JOIN sender s ON p.senderid = s.senderid AND p.receiver = s.receiver
                    ORDER BY p.tag DESC
                    LIMIT 5
                """)
                rows = cur.fetchall()
                print("\n📋 最新的投稿记录:")
                for row in rows:
                    print(f"  标签: {row['tag']}, 发送者: {row['senderid']}({row['nickname']}), 群组: {row['ACgroup']}")
        
        # 检查 sender 表
        if 'sender' in tables:
            cur.execute("SELECT COUNT(*) FROM sender")
            count = cur.fetchone()[0]
            print(f"📊 sender 表中有 {count} 条记录")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return False

def test_directory_structure():
    """测试目录结构"""
    print("\n🔍 测试目录结构...")
    
    prepost_dir = ROOT / 'cache' / 'prepost'
    picture_dir = ROOT / 'cache' / 'picture'
    
    print(f"📁 prepost 目录: {prepost_dir} - {'存在' if prepost_dir.exists() else '不存在'}")
    print(f"📁 picture 目录: {picture_dir} - {'存在' if picture_dir.exists() else '不存在'}")
    
    if prepost_dir.exists():
        dirs = [d for d in prepost_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        print(f"📊 prepost 中有 {len(dirs)} 个投稿目录")
        for d in sorted(dirs, key=lambda x: int(x.name), reverse=True)[:5]:
            files = [f for f in d.iterdir() if f.is_file()]
            print(f"   {d.name}: {len(files)} 个文件")
    
    if picture_dir.exists():
        dirs = [d for d in picture_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        print(f"📊 picture 中有 {len(dirs)} 个投稿目录")

def test_web_review_function():
    """测试 web_review 的数据获取函数"""
    print("\n🔍 测试 web_review 数据获取...")
    
    try:
        # 导入 web_review 模块
        import sys
        sys.path.append(str(ROOT))
        
        # 模拟 web_review 的数据获取
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        
        query = """
        SELECT p.tag, p.senderid, p.nickname, p.receiver, p.ACgroup, p.comment, p.AfterLM,
               s.modtime as submit_time
        FROM preprocess p
        LEFT JOIN sender s ON p.senderid = s.senderid AND p.receiver = s.receiver
        ORDER BY p.tag DESC
        LIMIT 10
        """
        
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        
        print(f"✅ 成功获取 {len(rows)} 条投稿记录")
        
        for row in rows:
            tag = str(row['tag'])
            print(f"\n📝 投稿 #{tag}:")
            print(f"   发送者: {row['senderid']} ({row['nickname']})")
            print(f"   群组: {row['ACgroup']}")
            print(f"   提交时间: {row['submit_time']}")
            print(f"   评论: {row['comment'] or '无'}")
            
            # 检查图片文件
            prepost_dir = ROOT / 'cache' / 'prepost' / tag
            picture_dir = ROOT / 'cache' / 'picture' / tag
            
            imgs = []
            if prepost_dir.exists():
                files = [f for f in prepost_dir.iterdir() if f.is_file()]
                imgs = [f.name for f in files]
            elif picture_dir.exists():
                files = [f for f in picture_dir.iterdir() if f.is_file()]
                imgs = [f.name for f in files]
            
            print(f"   图片: {len(imgs)} 张 - {imgs[:3]}{'...' if len(imgs) > 3 else ''}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

def main():
    print("🧪 OQQWall 数据连接测试")
    print("=" * 50)
    
    # 测试数据库连接
    db_ok = test_database_connection()
    
    # 测试目录结构
    test_directory_structure()
    
    # 测试数据获取
    if db_ok:
        test_web_review_function()
    
    print("\n" + "=" * 50)
    print("✅ 测试完成")

if __name__ == "__main__":
    main()


