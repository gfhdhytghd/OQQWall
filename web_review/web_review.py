#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OQQWall 网页审核面板
==================

这是一个基于 Python 的网页审核界面，用于管理校园墙投稿内容。
支持实时审核、图片预览、批量操作等功能。
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
from urllib.parse import quote as urlquote
from datetime import datetime
import html
import socket

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
    with open(SCRIPT_DIR / 'review_template.html', 'r', encoding='utf-8') as f:
        INDEX_HTML_TEMPLATE = f.read()
except FileNotFoundError:
    INDEX_HTML_TEMPLATE = """
    <h1>❌ 错误: review_template.html 未找到</h1>
    <p>请确保模板文件与 web_review.py 在同一目录下。</p>
    """

# ============================================================================
# 数据库和数据处理函数
# ============================================================================

def db_query(sql, params=()):
    """执行数据库查询"""
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

def list_pending(search: str | None = None):
    """获取待审核项目列表"""
    items = []
    if not PREPOST_DIR.exists(): return []
    for p in PREPOST_DIR.iterdir():
        if not p.is_dir() or not p.name.isdigit(): continue
        tag = p.name
        row = db_query("SELECT tag, senderid, nickname, receiver, ACgroup, comment, AfterLM FROM preprocess WHERE tag = ?", (tag,))
        if not row: continue
        r = row[0]
        if search:
            search_lower = search.lower()
            if not any([search_lower in str(r.get(k, '')).lower() for k in ['senderid', 'nickname', 'comment']]) and search_lower not in tag:
                continue
        imgs = [f.name for f in sorted(p.iterdir()) if f.is_file()]
        img_source_dir = 'prepost'
        if not imgs:
            picture_dir_for_tag = PICTURE_DIR / tag
            if picture_dir_for_tag.exists():
                imgs = [f.name for f in sorted(picture_dir_for_tag.iterdir()) if f.is_file()]
                img_source_dir = 'picture'
        afterlm_data = {}
        try:
            if r.get('AfterLM'): afterlm_data = json.loads(r['AfterLM'])
        except: pass
        try:
            mod_time = p.stat().st_mtime
            submit_time = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')
        except: submit_time = '未知'
        items.append({'tag': tag, 'senderid': r.get('senderid'), 'nickname': r.get('nickname'), 'ACgroup': r.get('ACgroup'), 'receiver': r.get('receiver'), 'comment': r.get('comment') or '', 'images': imgs, 'submit_time': submit_time, 'afterlm': afterlm_data, 'is_anonymous': afterlm_data.get('needpriv') == 'true', 'has_images': len(imgs) > 0, 'image_count': len(imgs), 'img_source_dir': img_source_dir})
    items.sort(key=lambda x: int(x['tag']), reverse=True)
    return items

def list_staged():
    """获取所有暂存区中的项目列表（已增加错误处理）"""
    staged_items = {}
    try:
        with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
            account_groups = json.load(f)
        group_names = list(account_groups.keys())
    except Exception as e:
        print(f"[web-review] Error reading AcountGroupcfg.json: {e}")
        return {}
    for group in group_names:
        try:
            staged_tags = db_query(f"SELECT tag FROM sendstorge_{group}")
            if not staged_tags: continue
            group_items = []
            for tag_row in staged_tags:
                tag = tag_row.get('tag')
                if not tag: continue
                item_details = db_query("SELECT tag, senderid, nickname FROM preprocess WHERE tag = ?", (tag,))
                if item_details: group_items.append(item_details[0])
            if group_items: staged_items[group] = group_items
        except sqlite3.OperationalError as e:
            if "no such table" in str(e): print(f"[web-review] Info: Staging table for group '{group}' not found, skipping.")
            else: print(f"[web-review] Database error for group '{group}': {e}")
        except Exception as e: print(f"[web-review] Unexpected error processing group '{group}': {e}")
    return staged_items

def get_image_mime_type(file_path):
    """根据文件头检测图片 MIME 类型"""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(16)
            if header.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
            elif header.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
            elif header.startswith((b'GIF87a', b'GIF89a')): return 'image/gif'
            elif header.startswith(b'BM'): return 'image/bmp'
            elif header.startswith(b'RIFF') and header[8:12] == b'WEBP': return 'image/webp'
    except: pass
    return 'application/octet-stream'

# ============================================================================
# 命令执行函数
# ============================================================================

def run_audit_command(tag: str, cmd: str, flag: str | None = None):
    """执行审核相关的 shell 命令"""
    args = [tag, cmd]
    if flag: args.append(flag)
    safe_joined = ' '.join(arg.replace("'", "'\\''") for arg in args)
    cmdline = ['bash', '-lc', f"./getmsgserv/processsend.sh '{safe_joined}'"]
    preview = safe_joined if len(safe_joined) < 200 else (safe_joined[:200] + ' …')
    print(f"[web-review] 执行命令: ./getmsgserv/processsend.sh '{preview}'", flush=True)
    proc = subprocess.run(cmdline, cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.stdout: print("[web-review] 标准输出:\n" + proc.stdout, flush=True)
    if proc.stderr: print("[web-review] 错误输出:\n" + proc.stderr, flush=True)
    print(f"[web-review] 命令执行完成，退出码: {proc.returncode}", flush=True)

# ============================================================================
# Web 服务器类
# ============================================================================

# ============================================================================
# Web 服务器类
# ============================================================================

class ReviewServer(http.server.SimpleHTTPRequestHandler):
    """OQQWall 审核面板 Web 服务器"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    # NOTE: All 'def' statements below must have the same indentation.
    def do_GET(self):
        """处理 GET 请求"""
        parsed_path = urllib.parse.urlparse(self.path)
        
        # --- Serves the favicon.png file ---
        if parsed_path.path == '/favicon.png':
            icon_path = SCRIPT_DIR / 'favicon.png'
            if icon_path.is_file():
                try:
                    with open(icon_path, 'rb') as f:
                        self.send_response(200)
                        self.send_header('Content-type', 'image/png')
                        self.end_headers()
                        self.wfile.write(f.read())
                except IOError:
                    self.send_error(404, "File Not Found")
            else:
                self.send_error(404, "File Not Found")
            return

        # --- Handles old .ico requests to prevent loops ---
        if parsed_path.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
            
        # --- Handles other requests ---
        if parsed_path.path == '/api/staged':
            self.handle_api_staged()
        elif parsed_path.path.startswith(('/cache/prepost/', '/cache/picture/')):
            self.handle_static_files(parsed_path)
        else:
            self.render_review_page(parsed_path)

    def do_POST(self):
        """处理 POST 请求，用于审核操作并返回带状态的重定向"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = urllib.parse.parse_qs(post_data)
        tag, cmd, flag = params.get('tag', [''])[0], params.get('cmd', [''])[0], params.get('flag', [''])[0]
        
        success = False
        message = ""
        
        if tag and cmd:
            print(f"[web-review] 执行审核操作: tag={tag}, cmd={cmd}, flag={flag}")
            try:
                run_audit_command(tag, cmd, flag)
                success = True
                message = f"操作成功：{cmd} #{tag}"
            except Exception as e:
                success = False
                message = f"操作失败：{str(e)}"
                print(f"[web-review] 操作失败: {e}")
        else:
            message = "参数错误"
        
        # 返回带有操作结果的重定向
        status = "success" if success else "error"
        redirect_url = f"/?status={status}&message={urllib.parse.quote(message)}"
        
        self.send_response(303)
        self.send_header('Location', redirect_url)
        self.end_headers()

    def handle_api_staged(self):
        """处理获取暂存项目的 API 请求"""
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

    def handle_static_files(self, parsed_path):
        """提供静态文件服务，尤其是无后缀的图片"""
        fs_path_str = parsed_path.path.lstrip('/')
        fs_path = Path(self.directory) / fs_path_str
        if fs_path.is_file() and str(fs_path.resolve()).startswith(str(Path(self.directory).resolve())):
            try:
                with open(fs_path, 'rb') as f: content = f.read()
                content_type = get_image_mime_type(fs_path)
                self.send_response(200)
                self.send_header('Content-type', content_type)
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except IOError: self.send_error(404, "File Not Found")
        else: self.send_error(404, "File Not Found")

    def render_review_page(self, parsed_path):
        """渲染审核主页面"""
        query_params = urllib.parse.parse_qs(parsed_path.query)
        search_term = query_params.get('search', [''])[0]
        status = query_params.get('status', [''])[0]
        message = query_params.get('message', [''])[0]
        
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        items = list_pending(search=search_term)
        rows_html = "".join([self._generate_item_card(item) for item in items])
        
        if not items and not search_term:
            rows_html = "<div class='empty-state'><h3>🎉 恭喜！</h3><p>所有投稿都已处理完毕。</p></div>"
        elif not items and search_term:
            rows_html = f"<div class='empty-state'><h3>🤔 未找到结果</h3><p>没有找到与 \"{html.escape(search_term)}\" 相关的投稿。</p></div>"
        
        status_html = ""
        if status and message:
            status_class = "success" if status == "success" else "error"
            status_html = f"""
            <div class="status-message {status_class}" id="status-message">
                <span class="status-text">{html.escape(urllib.parse.unquote(message))}</span>
                <button class="status-close" onclick="document.getElementById('status-message').style.display='none'">×</button>
            </div>
            """
        
        try:
            page_content = INDEX_HTML_TEMPLATE.format(
                total_count=len(items),
                anonymous_count=sum(1 for i in items if i.get('is_anonymous')),
                with_images_count=sum(1 for i in items if i.get('has_images')),
                search=html.escape(search_term),
                rows=rows_html,
                status_message=status_html
            )
            self.wfile.write(page_content.encode('utf-8'))
        except (ValueError, KeyError, IndexError) as e:
            error_message = f"<h1>500 - 模板渲染错误</h1><p>错误: {e}</p><p>请检查 review_template.html 文件中的括号是否正确。</p>"
            self.wfile.write(error_message.encode('utf-8'))
            print(f"--- 模板渲染错误: {e} ---")

    # 注意：这个函数必须在 ReviewServer 类内部，并保持正确的缩进
    def _generate_item_card(self, item):
        """生成单个投稿项目的卡片 HTML"""
        images_html = ""
        if item['has_images']:
            for img in item['images']:
                img_path = urlquote(f"/cache/{item['img_source_dir']}/{item['tag']}/{img}")
                images_html += f'<img src="{img_path}" alt="投稿图片" loading="lazy">'

        badges_html = ""
        if item['is_anonymous']: badges_html += '<span class="badge badge-anonymous">匿名</span>'
        if item['has_images']: badges_html += f'<span class="badge badge-images">{item["image_count"]} 图</span>'
        
        safe_nickname = html.escape(item.get('nickname') or '未知')
        safe_senderid = html.escape(str(item.get('senderid') or '未知'))
        safe_comment = html.escape(item.get('comment') or '').replace('\n', '<br>')
        
        return f"""<div class="item-card">
    <form method="post" action="/">
        <input type="hidden" name="tag" value="{item['tag']}">
        <div class="item-content">
            <div class="item-header">
                <div class="item-meta">
                    <div class="item-tag">#{item['tag']}</div>
                    <div class="info-item"><strong>投稿人:</strong> {safe_nickname} ({safe_senderid})</div>
                    <div class="info-item"><strong>时间:</strong> {item['submit_time']}</div>
                </div>
                <div class="item-badges">{badges_html}</div>
            </div>
            <div class="item-comment">{safe_comment}</div>
            <div class="item-images">{images_html}</div>
            <div class="comment-form">
                <textarea name="flag" placeholder="为“拒”、“拉黑”、“评论”、“回复”提供原因或文本 (可选)"></textarea>
            </div>
        </div>
        <div class="item-actions">
            <button type="submit" name="cmd" value="是" class="btn btn-success">✅ 通过 (是)</button>
            <button type="submit" name="cmd" value="匿" class="btn btn-info">🎭 切换匿名 (匿)</button>
            <button type="submit" name="cmd" value="等" class="btn" style="background-color: #6c757d; color: white;">⏳ 等待 (等)</button>
            <button type="submit" name="cmd" value="拒" class="btn btn-warning">⚠️ 拒绝 (拒)</button>
            <button type="submit" name="cmd" value="删" class="btn btn-danger">❌ 删除 (删)</button>
            <button type="submit" name="cmd" value="拉黑" class="btn btn-danger">🚫 拉黑</button>
            <button type="submit" name="cmd" value="否" class="btn" style="background-color: #545b62; color: white;">✍️ 人工处理 (否)</button>
        </div>
    </form>
</div>"""
# --- ReviewServer 类到此结束 ---
        # --- 修改部分结束 ---
        # --- 修改部分结束 ---
# ============================================================================
# 服务器启动函数
# ============================================================================

def run_server(host='0.0.0.0', port=8090):
    """启动 Web 服务器"""
    with socketserver.TCPServer((host, port), ReviewServer) as httpd:
        print("=" * 50)
        print("🚀 OQQWall 审核面板已启动")
        print("=" * 50)
        display_host = 'localhost' if host in ('0.0.0.0', '::') else host
        print(f"📍 本地访问: http://localhost:{port}")
        if host in ('0.0.0.0', '::'):
            try:
                hostname = socket.gethostname()
                ip_address = socket.gethostbyname(hostname)
                print(f"🌐 外部访问: http://{ip_address}:{port}")
            except:
                 print(f"🌐 外部访问: http://<你的IP地址>:{port}")
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
  python web_review.py                   # 使用默认设置启动
  python web_review.py --host 127.0.0.1  # 仅本地访问
  python web_review.py --port 8080       # 使用自定义端口
        """
    )
    parser.add_argument('--host', type=str, default='0.0.0.0', help='服务器监听的地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8090, help='服务器监听的端口 (默认: 8090)')
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)