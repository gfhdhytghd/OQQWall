#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OQQWall 网页审核面板
==================

这是一个基于 Python 的网页审核界面，用于管理校园墙投稿内容。
支持实时审核、图片预览、批量操作等功能。

作者: OQQWall Team
版本: 2.0
"""

# ============================================================================
# 导入模块
# ============================================================================

import http.server
import socketserver
import urllib.parse
import os
import sqlite3
import json
import subprocess
import sys
import argparse
from pathlib import Path
import mimetypes
from urllib.parse import quote as urlquote
import time
import threading
from datetime import datetime, timedelta
import html

# ============================================================================
# 配置和路径设置
# ============================================================================

# 脚本目录：OQQWall/web_review/
SCRIPT_DIR = Path(__file__).resolve().parent 

# 项目根目录：OQQWall/
ROOT_DIR = SCRIPT_DIR.parent

# 数据库和缓存路径
DB_PATH = ROOT_DIR / 'cache' / 'OQQWall.db'
PREPOST_DIR = ROOT_DIR / 'cache' / 'prepost'
PICTURE_DIR = ROOT_DIR / 'cache' / 'picture'

# ============================================================================
# 模板加载
# ============================================================================

try:
    # 从当前目录加载 HTML 模板
    with open(SCRIPT_DIR / 'review_template.html', 'r', encoding='utf-8') as f:
        INDEX_HTML_TEMPLATE = f.read()
except FileNotFoundError:
    INDEX_HTML_TEMPLATE = """
    <h1>❌ 错误: review_template.html 未找到</h1>
    <p>请确保模板文件与 web_review.py 在同一目录下。</p>
    """

# ============================================================================
# 数据库和配置函数
# ============================================================================

def load_config():
    """
    加载 oqqwall.config 配置文件
    
    Returns:
        dict: 配置字典
    """
    cfg = {}
    cfg_file = ROOT_DIR / 'oqqwall.config'
    
    if cfg_file.exists():
        with cfg_file.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    cfg[k.strip()] = v.strip().strip('"')
    return cfg


def db_query(sql, params=()):
    """
    执行数据库查询
    
    Args:
        sql (str): SQL 查询语句
        params (tuple): 查询参数
        
    Returns:
        list: 查询结果列表
    """
    if not DB_PATH.exists():
        return []
        
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    
    try:
        cur = con.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()

# ============================================================================
# 数据处理函数
# ============================================================================

def list_pending(search: str | None = None):
    """
    获取待审核项目列表
    
    Args:
        search (str, optional): 搜索关键词
        
    Returns:
        list: 待审核项目列表
    """
    items = []
    
    if not PREPOST_DIR.exists():
        return []
    
    for p in PREPOST_DIR.iterdir():
        if not p.is_dir() or not p.name.isdigit():
            continue
            
        tag = p.name
        
        # 从数据库获取基本信息
        row = db_query(
            "SELECT tag, senderid, nickname, receiver, ACgroup, comment, AfterLM FROM preprocess WHERE tag = ?", 
            (tag,)
        )
        if not row:
            continue
            
        r = row[0]
        
        # 搜索过滤
        if search:
            search_lower = search.lower()
            searchable_fields = ['senderid', 'nickname', 'comment']
            if not any([search_lower in str(r.get(k, '')).lower() for k in searchable_fields]) and search_lower not in tag:
                continue
        
        # 收集图片文件
        imgs = [f.name for f in sorted(p.iterdir()) if f.is_file()]
        img_source_dir = 'prepost'
        
        # 如果 prepost 目录没有图片，检查 picture 目录
        if not imgs:
            picture_dir_for_tag = PICTURE_DIR / tag
            if picture_dir_for_tag.exists():
                imgs = [f.name for f in sorted(picture_dir_for_tag.iterdir()) if f.is_file()]
                img_source_dir = 'picture'
        
        # 解析 AfterLM JSON 数据
        afterlm_data = {}
        try:
            if r.get('AfterLM'):
                afterlm_data = json.loads(r['AfterLM'])
        except:
            pass
        
        # 获取提交时间
        try:
            mod_time = p.stat().st_mtime
            submit_time = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')
        except:
            submit_time = '未知'
        
        # 构建项目数据
        item = {
            'tag': tag,
            'senderid': r.get('senderid'),
            'nickname': r.get('nickname'),
            'ACgroup': r.get('ACgroup'),
            'receiver': r.get('receiver'),
            'comment': r.get('comment') or '',
            'images': imgs,
            'submit_time': submit_time,
            'afterlm': afterlm_data,
            'is_anonymous': afterlm_data.get('needpriv') == 'true',
            'has_images': len(imgs) > 0,
            'image_count': len(imgs),
            'img_source_dir': img_source_dir
        }
        
        items.append(item)
    
    # 按标签数字排序（最新的在前）
    items.sort(key=lambda x: int(x['tag']), reverse=True)
    return items

def list_staged():
    """
    获取已暂存的项目列表
    
    Returns:
        dict: 按群组分组的暂存项目
    """
    staged_items = {}
    
    try:
        with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
            account_groups = json.load(f)
        group_names = list(account_groups.keys())
    except Exception as e:
        print(f"[web-review] Error reading AcountGroupcfg.json: {e}")
        return {}
    
    for group in group_names:
        staged_tags = db_query(f"SELECT tag FROM sendstorge_{group}")
        if not staged_tags:
            continue
            
        group_items = []
        for tag_row in staged_tags:
            tag = tag_row.get('tag')
            if not tag:
                continue
                
            item_details = db_query(
                "SELECT tag, senderid, nickname FROM preprocess WHERE tag = ?", 
                (tag,)
            )
            if item_details:
                group_items.append(item_details[0])
                
        if group_items:
            staged_items[group] = group_items
            
    return staged_items


def get_image_mime_type(file_path):
    """
    根据文件头检测图片 MIME 类型
    
    Args:
        file_path (str): 图片文件路径
        
    Returns:
        str: MIME 类型
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(16)
            
            if header.startswith(b'\xff\xd8\xff'):
                return 'image/jpeg'
            elif header.startswith(b'\x89PNG\r\n\x1a\n'):
                return 'image/png'
            elif header.startswith((b'GIF87a', b'GIF89a')):
                return 'image/gif'
            elif header.startswith(b'BM'):
                return 'image/bmp'
            elif header.startswith(b'RIFF') and header[8:12] == b'WEBP':
                return 'image/webp'
    except:
        pass
        
    return 'application/octet-stream'

# ============================================================================
# 命令执行函数
# ============================================================================

def run_audit_command(tag: str, cmd: str, flag: str | None = None, background: bool = False):
    """
    执行审核相关的 shell 命令
    
    Args:
        tag (str): 投稿标签
        cmd (str): 审核命令
        flag (str, optional): 附加参数
        background (bool): 是否后台执行
        
    Returns:
        tuple: (退出码, 输出内容)
    """
    args = [tag, cmd]
    if flag:
        args.append(flag)
    
    # 安全地转义参数
    safe_joined = ' '.join(arg.replace("'", "'\\''") for arg in args)
    cmdline = ['bash', '-lc', f"./getmsgserv/processsend.sh '{safe_joined}'"]

    # 记录执行日志
    preview = safe_joined if len(safe_joined) < 200 else (safe_joined[:200] + ' …')
    print(f"[web-review] 执行命令: ./getmsgserv/processsend.sh '{preview}'", flush=True)

    # 在项目根目录执行命令
    proc = subprocess.run(
        cmdline, 
        cwd=str(ROOT_DIR), 
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, 
        text=True,
    )
    
    # 输出执行结果
    if proc.stdout:
        print("[web-review] 标准输出:\n" + proc.stdout, flush=True)
    if proc.stderr:
        print("[web-review] 错误输出:\n" + proc.stderr, flush=True)
        
    print(f"[web-review] 命令执行完成，退出码: {proc.returncode}", flush=True)
    return proc.returncode, (proc.stdout or proc.stderr)

# ============================================================================
# Web 服务器类
# ============================================================================

class ReviewServer(http.server.SimpleHTTPRequestHandler):
    """
    OQQWall 审核面板 Web 服务器
    
    继承自 SimpleHTTPRequestHandler，提供 HTTP 请求处理功能
    """
    
    def __init__(self, *args, **kwargs):
        """
        初始化服务器处理器
        
        设置工作目录为项目根目录
        """
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def do_GET(self):
        """
        处理 GET 请求
        
        支持以下路径：
        - /api/staged: 获取暂存项目 API
        - /cache/prepost/*, /cache/picture/*: 图片文件服务
        - 其他: 渲染审核页面
        """
        parsed_path = urllib.parse.urlparse(self.path)
        
        # API 端点：获取暂存项目
        if parsed_path.path == '/api/staged':
            try:
                staged_data = list_staged()
                response_body = json.dumps(staged_data, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(response_body)
            except Exception as e:
                print(f"[web-review] API 错误: {e}")
                self.send_error(500, "Internal Server Error")
            return
        
        # 图片文件服务
        if parsed_path.path.startswith(('/cache/prepost/', '/cache/picture/')):
            fs_path_str = parsed_path.path.lstrip('/')
            fs_path = Path(self.directory) / fs_path_str
            
            # 安全检查：确保文件在允许的目录内
            if fs_path.is_file() and str(fs_path.resolve()).startswith(str(Path(self.directory).resolve())):
                try:
                    with open(fs_path, 'rb') as f:
                        content = f.read()
                    content_type = get_image_mime_type(fs_path)
                    self.send_response(200)
                    self.send_header('Content-type', content_type)
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except IOError:
                    self.send_error(404, "File Not Found")
            else:
                self.send_error(404, "File Not Found")
            return
        
        # 默认：渲染审核页面
        self.render_review_page(parsed_path)

    def do_POST(self):
        """
        处理 POST 请求
        
        处理审核操作，如通过、拒绝、删除等
        """
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = urllib.parse.parse_qs(post_data)
        
        tag = params.get('tag', [''])[0]
        cmd = params.get('cmd', [''])[0]
        flag = params.get('flag', [''])[0]
        
        if tag and cmd:
            print(f"[web-review] 执行审核操作: tag={tag}, cmd={cmd}, flag={flag}")
            run_audit_command(tag, cmd, flag)
        
        # 重定向回主页
        self.send_response(303)
        self.send_header('Location', '/')
        self.end_headers()

    def render_review_page(self, parsed_path):
        """
        渲染审核页面
        
        Args:
            parsed_path: 解析后的 URL 路径
        """
        query_params = urllib.parse.parse_qs(parsed_path.query)
        search_term = query_params.get('search', [''])[0]
        
        # 设置响应头
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        # 获取待审核项目
        items = list_pending(search=search_term)
        
        # 生成页面内容
        rows_html = ""
        
        if not items and not search_term:
            rows_html = """
            <div class='empty-state'>
                <h3>🎉 恭喜！</h3>
                <p>所有投稿都已处理完毕。</p>
            </div>
            """
        elif not items and search_term:
            rows_html = f"""
            <div class='empty-state'>
                <h3>🤔 未找到结果</h3>
                <p>没有找到与 "{html.escape(search_term)}" 相关的投稿。</p>
            </div>
            """
        else:
            # 生成项目卡片
            for item in items:
                rows_html += self._generate_item_card(item)
        
        # 计算统计信息
        total_count = len(items)
        anonymous_count = sum(1 for i in items if i.get('is_anonymous'))
        with_images_count = sum(1 for i in items if i.get('has_images'))
        
        # 渲染最终页面
        page_content = INDEX_HTML_TEMPLATE.format(
            total_count=total_count,
            anonymous_count=anonymous_count,
            with_images_count=with_images_count,
            search=html.escape(search_term),
            rows=rows_html
        )
        
        self.wfile.write(page_content.encode('utf-8'))
    
    def _generate_item_card(self, item):
        """
        生成单个投稿项目的卡片 HTML
        
        Args:
            item (dict): 投稿项目数据
            
        Returns:
            str: 卡片 HTML
        """
        # 生成图片 HTML
        images_html = ""
        if item['has_images']:
            for img in item['images']:
                img_path = urlquote(f"/cache/{item['img_source_dir']}/{item['tag']}/{img}")
                images_html += f'<img src="{img_path}" alt="投稿图片" loading="lazy">'
        
        # 生成徽章 HTML
        badges_html = ""
        if item['is_anonymous']:
            badges_html += '<span class="badge badge-anonymous">匿名</span>'
        if item['has_images']:
            badges_html += f'<span class="badge badge-images">{item["image_count"]} 图</span>'
        
        # 转义用户输入
        safe_nickname = html.escape(item.get('nickname') or '未知')
        safe_senderid = html.escape(str(item.get('senderid') or '未知'))
        safe_comment = html.escape(item.get('comment') or '').replace('\n', '<br>')
        
        # 生成卡片 HTML
        card_html = f"""
        <div class="item-card">
            <form method="post" action="/">
                <input type="hidden" name="tag" value="{item['tag']}">
                <div class="item-content">
                    <div class="item-header">
                        <div class="item-meta">
                            <div class="item-tag">#{item['tag']}</div>
                            <div class="info-item">
                                <strong>投稿人:</strong> {safe_nickname} ({safe_senderid})
                            </div>
                            <div class="info-item">
                                <strong>时间:</strong> {item['submit_time']}
                            </div>
                        </div>
                        <div class="item-badges">{badges_html}</div>
                    </div>
                    <div class="item-comment">{safe_comment}</div>
                    <div class="item-images">{images_html}</div>
                    <div class="comment-form">
                        <textarea name="flag" placeholder="输入拒绝/拉黑原因 (可选)"></textarea>
                    </div>
                </div>
                <div class="item-actions">
                    <button type="submit" name="cmd" value="是" class="btn btn-success">✅ 通过</button>
                    <button type="submit" name="cmd" value="拒" class="btn btn-warning">⚠️ 拒绝</button>
                    <button type="submit" name="cmd" value="删" class="btn btn-danger">❌ 删除</button>
                    <button type="submit" name="cmd" value="拉黑" class="btn btn-danger">🚫 拉黑</button>
                    <button type="submit" name="cmd" value="查" class="btn btn-info">ℹ️ 查成分</button>
                </div>
            </form>
        </div>
        """
        
        return card_html

# ============================================================================
# 服务器启动函数
# ============================================================================

def run_server(host='0.0.0.0', port=8090):
    """
    启动 Web 服务器
    
    Args:
        host (str): 监听地址
        port (int): 监听端口
    """
    with socketserver.TCPServer((host, port), ReviewServer) as httpd:
        print("=" * 50)
        print("🚀 OQQWall 审核面板已启动")
        print("=" * 50)
        
        display_host = 'localhost' if host == '0.0.0.0' else host
        print(f"📍 本地访问: http://localhost:{port}")
        print(f"🌐 外部访问: http://{display_host}:{port}")
        print("=" * 50)
        print("按 Ctrl+C 停止服务器")
        print("=" * 50)
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n🛑 服务器已停止")


# ============================================================================
# 主程序入口
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OQQWall Web Review Panel - 校园墙投稿审核系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python web_review.py                    # 使用默认设置启动
  python web_review.py --host 127.0.0.1  # 仅本地访问
  python web_review.py --port 8080       # 使用自定义端口
        """
    )
    
    parser.add_argument(
        '--host', 
        type=str, 
        default='0.0.0.0', 
        help='服务器监听的地址 (默认: 0.0.0.0)'
    )
    parser.add_argument(
        '--port', 
        type=int, 
        default=8090, 
        help='服务器监听的端口 (默认: 8090)'
    )
    
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)