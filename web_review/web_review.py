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
import socket
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
import secrets
import hashlib
from http import cookies

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

# 登录页模板（可选外置）
try:
    with open(SCRIPT_DIR / 'login_template.html', 'r', encoding='utf-8') as f:
        LOGIN_HTML_TEMPLATE = f.read()
except FileNotFoundError:
    LOGIN_HTML_TEMPLATE = """
<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>登录</title>
<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,\"PingFang SC\",\"Microsoft Yahei\",sans-serif;background:#F7F2FA;margin:0;display:flex;align-items:center;justify-content:center;height:100vh} .card{background:#fff;border-radius:16px;box-shadow:0 2px 12px rgba(0,0,0,.08);padding:24px;min-width:320px;max-width:360px;width:90%} h1{font-size:20px;margin:.2rem 0 1rem} .row{display:flex;flex-direction:column;gap:6px;margin-bottom:10px} input{padding:10px 12px;border:1px solid #ccc;border-radius:10px} .btn{width:100%;padding:10px 12px;border:none;border-radius:999px;background:#6750A4;color:#fff;font-weight:600;cursor:pointer} .msg{color:#B3261E;margin-bottom:8px;font-size:13px}</style>
</head><body>
<form class=\"card\" method=\"post\" action=\"/login\"> 
  <h1>OQQWall 审核登录</h1>
  {msg}
  <div class=\"row\"><label>用户名</label><input name=\"username\" required></div>
  <div class=\"row\"><label>密码</label><input type=\"password\" name=\"password\" required></div>
  <button class=\"btn\">登录</button>
</form>
</body></html>
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

# 简易会话存储：token -> {username, group}
SESSION_STORE: dict[str, dict] = {}

def load_admins():
    """从 AcountGroupcfg.json 读取管理员账号。
    支持两种密码形式：
      - 明文: "password": "pwd"
      - sha256: "password": "sha256:<hex>"
    结构示例：
      {
        "GroupA": { ..., "admins": [{"username": "alice", "password": "sha256:..."}] }
      }
    返回: dict username -> {"group": group_key, "password": stored}
    """
    try:
        with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        admins = {}
        for group_key, obj in (data or {}).items():
            for adm in obj.get('admins', []) or []:
                u = str(adm.get('username', '')).strip()
                p = str(adm.get('password', '')).strip()
                if u:
                    admins[u] = { 'group': group_key, 'password': p }
        return admins
    except Exception as e:
        print(f"[web-review] 读取管理员配置失败: {e}")
        return {}

def verify_password(stored: str, provided: str) -> bool:
    if stored.startswith('sha256:'):
        h = hashlib.sha256(provided.encode('utf-8')).hexdigest()
        return h == stored.split(':', 1)[1]
    return secrets.compare_digest(stored, provided)

def parse_cookies(header: str | None) -> dict:
    jar = cookies.SimpleCookie()
    if header:
        try:
            jar.load(header)
        except Exception:
            return {}
    return {k: morsel.value for k, morsel in jar.items()}


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

def list_pending(search: str | None = None, group_filter: str | None = None):
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
        # 组过滤
        if group_filter and str(r.get('ACgroup')) != str(group_filter):
            continue
        
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

def list_staged(group_filter: str | None = None):
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
            if (not group_filter) or (group == group_filter):
                staged_items[group] = group_items
            
    return staged_items

def list_groups():
    """读取账户组配置，返回可用于 command.sh 的账号选项。"""
    try:
        with open(ROOT_DIR / 'AcountGroupcfg.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        result = []
        for key, val in (data or {}).items():
            result.append({
                'key': key,
                'mainqqid': str(val.get('mainqqid', '')),
                'minorqqids': [str(x) for x in (val.get('minorqqid') or [])],
            })
        return result
    except Exception as e:
        print(f"[web-review] 读取 AcountGroupcfg.json 失败: {e}")
        return []


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
        - /detail?tag=123: 稿件详情页
        - /cache/prepost/*, /cache/picture/*: 图片文件服务
        - 其他: 渲染审核页面
        """
        parsed_path = urllib.parse.urlparse(self.path)
        
        # 获取当前用户
        user = self._get_user()
        # 登录页
        if parsed_path.path == '/login':
            self._render_login()
            return
        if parsed_path.path == '/logout':
            self._logout()
            return

        # 未登录则跳转
        if not user:
            self.send_response(303)
            self.send_header('Location', '/login')
            self.end_headers()
            return

        # API 端点：获取暂存项目
        if parsed_path.path == '/api/staged':
            try:
                staged_data = list_staged(group_filter=user['group'])
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
                    # 额外权限检查：根据 tag 限制组访问
                    parts = fs_path.parts
                    # expect: ROOT/.../cache/<dir>/<tag>/file
                    tag = None
                    for i, p in enumerate(parts):
                        if p == 'cache' and i + 2 < len(parts):
                            maybe_tag = parts[i + 2]
                            if maybe_tag.isdigit():
                                tag = maybe_tag
                            break
                    if tag:
                        row = db_query("SELECT ACgroup FROM preprocess WHERE tag = ?", (tag,))
                        if not row or str(row[0].get('ACgroup')) != str(user['group']):
                            self.send_error(403, "Forbidden")
                            return
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
        
        # 详情页
        if parsed_path.path == '/detail':
            self.render_detail_page(parsed_path, user)
            return
        
        # 默认：渲染审核页面
        self.render_review_page(parsed_path, user)

    def do_POST(self):
        """
        处理 POST 请求
        
        处理审核操作，如通过、拒绝、删除等；以及全局 command.sh 操作
        """
        content_length = int(self.headers.get('Content-Length', '0') or '0')
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = urllib.parse.parse_qs(post_data)
        path = urllib.parse.urlparse(self.path).path

        # 登录提交
        if path == '/login':
            username = (params.get('username') or [''])[0]
            password = (params.get('password') or [''])[0]
            admins = load_admins()
            rec = admins.get(username)
            if rec and verify_password(rec['password'], password):
                token = secrets.token_urlsafe(32)
                SESSION_STORE[token] = {'username': username, 'group': rec['group'], 'created': time.time()}
                self.send_response(303)
                self.send_header('Set-Cookie', f'session={token}; HttpOnly; Path=/')
                self.send_header('Location', '/')
                self.end_headers()
                return
            else:
                self._render_login("<div class='msg'>用户名或密码错误</div>")
                return

        if path == '/api/cmd':
            # 全局命令 -> command.sh
            user = self._get_user()
            if not user:
                self.send_response(303)
                self.send_header('Location', '/login')
                self.end_headers()
                return
            object_str = params.get('object', [''])[0]
            self_id = params.get('self_id', [''])[0]
            numb = params.get('numb', [''])[0]
            senderid = params.get('senderid', [''])[0]

            if object_str == '设定编号' and numb:
                object_str = f"设定编号 {numb}"
            elif object_str == '取消拉黑' and senderid:
                object_str = f"取消拉黑 {senderid}"

            # 强制 self_id 属于当前组
            if not self_id:
                # fallback 使用当前组主账号
                for g in list_groups():
                    if g['key'] == user['group']:
                        self_id = g['mainqqid']
                        break
            else:
                # 验证所选账号属于当前组
                ok = False
                for g in list_groups():
                    if g['key'] == user['group']:
                        if self_id == g['mainqqid'] or self_id in g['minorqqids']:
                            ok = True
                        break
                if not ok:
                    self.send_error(403, 'Forbidden: invalid self_id for this group')
                    return

            self._run_command_sh(object_str, self_id)
            self.send_response(303)
            self.send_header('Location', '/')
            self.end_headers()
            return
        else:
            # 审核操作 -> processsend.sh
            user = self._get_user()
            if not user:
                self.send_response(303)
                self.send_header('Location', '/login')
                self.end_headers()
                return
            tag = params.get('tag', [''])[0]
            cmd = params.get('cmd', [''])[0]
            flag = params.get('flag', [''])[0]
            redirect_to = params.get('redirect', ['/'])[0] or '/'
            if tag and cmd:
                # 组权限校验
                row = db_query("SELECT ACgroup FROM preprocess WHERE tag = ?", (tag,))
                if not row or str(row[0].get('ACgroup')) != str(user['group']):
                    self.send_error(403, 'Forbidden')
                    return
                print(f"[web-review] 执行审核操作: tag={tag}, cmd={cmd}, flag={flag}")
                run_audit_command(tag, cmd, flag)
            self.send_response(303)
            self.send_header('Location', redirect_to)
            self.end_headers()
            return

    def render_review_page(self, parsed_path, user):
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
        items = list_pending(search=search_term, group_filter=user['group'])
        
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
        
        # 渲染最终页面（安全转义模板中的花括号，避免与 CSS 冲突）
        template_safe = INDEX_HTML_TEMPLATE.replace('{', '{{').replace('}', '}}')
        for key in ['total_count', 'anonymous_count', 'with_images_count', 'search', 'rows', 'group_options', 'userbar']:
            template_safe = template_safe.replace('{{' + key + '}}', '{' + key + '}')

        # 账户组选项
        group_options_html = ''
        # 仅渲染当前组账号
        for g in list_groups():
            if g['key'] != user['group']:
                continue
            k = html.escape(g['key'])
            main = html.escape(g['mainqqid'])
            if main:
                group_options_html += f'<option value="{main}">{k} - 主账号({main})</option>'
            for i, mid in enumerate(g['minorqqids']):
                ms = html.escape(mid)
                group_options_html += f'<option value="{ms}">{k} - 次要账号{i+1}({ms})</option>'

        userbar = f"<div style='text-align:right;color:#49454F;margin-bottom:8px'>组: {html.escape(user['group'])} | 用户: {html.escape(user['username'])} | <a href='/logout'>退出</a></div>"

        page_content = template_safe.format(
            total_count=total_count,
            anonymous_count=anonymous_count,
            with_images_count=with_images_count,
            search=html.escape(search_term),
            rows=rows_html,
            group_options=group_options_html,
            userbar=userbar
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
        detail_url = f"/detail?tag={urlquote(item['tag'])}"
        card_html = f"""
        <div class="item-card">
            <form method="post" action="/">
                <input type="hidden" name="tag" value="{item['tag']}">
                <input type="hidden" name="redirect" value="/">
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
                        <textarea name="flag" placeholder="输入评论或拒绝/拉黑原因 (可选)"></textarea>
                    </div>
                </div>
                <div class="item-actions">
                    <a href="{detail_url}" class="btn btn-info">📄 详情</a>
                    <button type="submit" name="cmd" value="是" class="btn btn-success">✅ 通过</button>
                    <button type="submit" name="cmd" value="否" class="btn">🙅 否</button>
                    <button type="submit" name="cmd" value="立即" class="btn btn-info">🚀 立即</button>
                    <button type="submit" name="cmd" value="拒" class="btn btn-warning">⚠️ 拒绝</button>
                    <button type="submit" name="cmd" value="删" class="btn btn-danger">❌ 删除</button>
                    <button type="submit" name="cmd" value="拉黑" class="btn btn-danger">🚫 拉黑</button>
                    <button type="submit" name="cmd" value="评论" class="btn">💬 评论</button>
                    <button type="submit" name="cmd" value="刷新" class="btn">🔄 刷新</button>
                    <button type="submit" name="cmd" value="重渲染" class="btn">🎨 重渲染</button>
                    <button type="submit" name="cmd" value="展示" class="btn">🖼️ 展示</button>
                    <button type="submit" name="cmd" value="查" class="btn btn-info">ℹ️ 查成分</button>
                </div>
            </form>
        </div>
        """
        
        return card_html

    def _run_command_sh(self, object_str: str, self_id: str):
        if not object_str:
            return 1, 'empty'
        obj_safe = object_str.replace("'", "'\\''")
        id_safe = (self_id or '').replace("'", "'\\''")
        cmdline = ['bash', '-lc', f"./getmsgserv/command.sh '{obj_safe}' '{id_safe}'"]
        print(f"[web-review] command.sh -> {object_str} (self_id={self_id})")
        proc = subprocess.run(cmdline, cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.stdout:
            print('[web-review] command.sh stdout:\n' + proc.stdout)
        if proc.stderr:
            print('[web-review] command.sh stderr:\n' + proc.stderr)
        return proc.returncode, (proc.stdout or proc.stderr)

    # ------------------------------
    # 详情页渲染
    # ------------------------------
    def render_detail_page(self, parsed_path, user):
        query_params = urllib.parse.parse_qs(parsed_path.query)
        tag = (query_params.get('tag') or [''])[0]
        if not tag or not tag.isdigit():
            self.send_error(400, "Bad Request: missing or invalid tag")
            return

        item = self._get_item(tag)
        if not item:
            self.send_error(404, "Not Found: tag not found")
            return
        # 组权限校验
        if str(item.get('ACgroup')) != str(user['group']):
            self.send_error(403, 'Forbidden')
            return

        # 读取详情模板
        detail_tpl_path = SCRIPT_DIR / 'detail_template.html'
        if detail_tpl_path.exists():
            template = detail_tpl_path.read_text(encoding='utf-8')
        else:
            # 简单降级模板
            template = """
<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>稿件详情 #{tag}</title>
<style>body{font-family:Arial,Helvetica,sans-serif;padding:16px;max-width:900px;margin:0 auto}img{max-width:100%;height:auto;border-radius:8px}pre{white-space:pre-wrap;background:#f6f6f6;padding:12px;border-radius:8px;overflow:auto}</style>
</head><body>
<h1>稿件详情 #{tag}</h1>
<p><a href=\"/\">← 返回列表</a></p>
<h3>投稿信息</h3>
<ul>
<li>投稿人: {nickname} ({senderid})</li>
<li>时间: {submit_time}</li>
<li>目标群: {ACgroup} / {receiver}</li>
<li>匿名: {is_anonymous}</li>
</ul>
<h3>内容</h3>
<div>{comment_html}</div>
<h3>图片</h3>
<div>{images_html}</div>
<h3>AfterLM</h3>
<pre>{afterlm_pretty}</pre>
<form method=\"post\" action=\"/\" style=\"margin-top:16px;display:flex;gap:8px;flex-wrap:wrap\"> 
<input type=\"hidden\" name=\"tag\" value=\"{tag}\"> 
<input type=\"hidden\" name=\"redirect\" value=\"/detail?tag={tag}\"> 
<input type=\"text\" name=\"flag\" placeholder=\"评论或拒绝/拉黑原因(可选)\" style=\"flex:1;min-width:220px;padding:8px\"> 
<button name=\"cmd\" value=\"是\">通过</button>
<button name=\"cmd\" value=\"否\">否</button>
<button name=\"cmd\" value=\"立即\">立即</button>
<button name=\"cmd\" value=\"拒\">拒绝</button>
<button name=\"cmd\" value=\"删\">删除</button>
<button name=\"cmd\" value=\"拉黑\">拉黑</button>
<button name=\"cmd\" value=\"评论\">评论</button>
<button name=\"cmd\" value=\"刷新\">刷新</button>
<button name=\"cmd\" value=\"重渲染\">重渲染</button>
<button name=\"cmd\" value=\"展示\">展示</button>
<button name=\"cmd\" value=\"查\">查成分</button>
</form>
</body></html>
"""

        # 构造图片 HTML
        images_html = ""
        if item['has_images']:
            for img in item['images']:
                img_path = urlquote(f"/cache/{item['img_source_dir']}/{item['tag']}/{img}")
                images_html += f'<img src="{img_path}" alt="投稿图片" loading="lazy" style="max-width:100%;margin:6px 0">'

        comment_html = html.escape(item.get('comment') or '').replace('\n', '<br>')
        afterlm_pretty = html.escape(json.dumps(item.get('afterlm') or {}, ensure_ascii=False, indent=2))

        # 响应
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        page = template
        # 安全替换占位符
        replacements = {
            '{tag}': item['tag'],
            '{nickname}': html.escape(item.get('nickname') or '未知'),
            '{senderid}': html.escape(str(item.get('senderid') or '未知')),
            '{submit_time}': item.get('submit_time') or '未知',
            '{ACgroup}': html.escape(str(item.get('ACgroup') or '')),
            '{receiver}': html.escape(str(item.get('receiver') or '')),
            '{is_anonymous}': '是' if item.get('is_anonymous') else '否',
            '{comment_html}': comment_html,
            '{images_html}': images_html,
            '{afterlm_pretty}': afterlm_pretty,
            '{image_count}': str(item.get('image_count') or 0),
        }
        for k, v in replacements.items():
            page = page.replace(k, v)
        self.wfile.write(page.encode('utf-8'))

    def _get_item(self, tag: str):
        rows = list_pending()
        for r in rows:
            if r.get('tag') == tag:
                return r
        return None

    # 登录/注销与用户获取
    def _render_login(self, msg_html: str = ""):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        page = LOGIN_HTML_TEMPLATE.replace('{msg}', msg_html or '')
        self.wfile.write(page.encode('utf-8'))

    def _logout(self):
        # 清理 cookie（客户端覆盖），删除服务端会话
        jar = parse_cookies(self.headers.get('Cookie'))
        token = jar.get('session')
        if token and token in SESSION_STORE:
            del SESSION_STORE[token]
        self.send_response(303)
        self.send_header('Set-Cookie', 'session=deleted; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/')
        self.send_header('Location', '/login')
        self.end_headers()

    def _get_user(self):
        jar = parse_cookies(self.headers.get('Cookie'))
        token = jar.get('session')
        if not token:
            return None
        rec = SESSION_STORE.get(token)
        return rec

# ============================================================================
# 服务器启动函数
# ============================================================================

class ReuseAddrTCPServer(socketserver.TCPServer):
    allow_reuse_address = True
    def server_bind(self):
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        # 尝试启用 REUSEPORT（如果系统支持）
        try:
            if hasattr(socket, 'SO_REUSEPORT'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass
        return super().server_bind()

def run_server(host='0.0.0.0', port=10923):
    """
    启动 Web 服务器
    
    Args:
        host (str): 监听地址
        port (int): 监听端口
    """
    try:
        server_cls = ReuseAddrTCPServer
        with server_cls((host, port), ReviewServer) as httpd:
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
    except OSError as e:
        if 'Address already in use' in str(e) or getattr(e, 'errno', None) in (98, 48):
            print("❌ 端口被占用 (可能处于 TIME_WAIT)。")
            print("提示: 可换一个端口 (--port)，或稍候重试。")
            print("已启用 SO_REUSEADDR/SO_REUSEPORT，若仍失败说明确有进程占用该端口。")
        else:
            raise


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
        default=10923, 
        help='服务器监听的端口 (默认: 10923)'
    )
    
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
