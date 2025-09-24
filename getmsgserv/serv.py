
import hashlib
import hmac
import logging
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import json
import os
import re
import sqlite3
import time
from threading import Lock
from contextlib import contextmanager
import fcntl
from logging.handlers import RotatingFileHandler
from collections import deque
from urllib.parse import urlparse, parse_qs

# 创建自定义的日志格式化器
class CustomFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # 自定义时间格式
        ct = self.converter(record.created)
        if datefmt:
            s = datetime.fromtimestamp(record.created).strftime(datefmt)
        else:
            s = datetime.fromtimestamp(record.created).strftime("[%H:%M:%S %d/%b]")
        return s

# 配置日志
logger = logging.getLogger('OQQWallServer')
log_level = logging.DEBUG if os.getenv('OQQ_DEBUG') not in (None, '', '0', 'false', 'False') else logging.INFO
logger.setLevel(log_level)

# 创建格式化器
formatter = CustomFormatter('%(asctime)s %(message)s')

# 日志处理器
file_handler = RotatingFileHandler('OQQWallmsgserv.log', maxBytes=10 * 1024 * 1024, backupCount=5)
file_handler.setFormatter(formatter)
file_handler.setLevel(log_level)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.setLevel(log_level)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# 定义存储路径
RAWPOST_DIR = './getmsgserv/rawpost'
ALLPOST_DIR = './getmsgserv/all'
ALL_POSTS_FILE = os.path.join(ALLPOST_DIR, 'all_posts.jsonl')
PRIV_POST_FILE = os.path.join(ALLPOST_DIR, 'priv_post.jsonl')
LEGACY_ALL_POSTS_FILE = os.path.join(ALLPOST_DIR, 'all_posts.json')
LEGACY_PRIV_POST_FILE = os.path.join(ALLPOST_DIR, 'priv_post.json')

os.makedirs(RAWPOST_DIR, exist_ok=True)
os.makedirs(ALLPOST_DIR, exist_ok=True)

# 添加文件锁
file_lock = Lock()

# ---- Windows for suppression (seconds) ----
FRIEND_REQ_WINDOW_SEC = 120          # 同一用户 2 分钟内重复好友申请只处理一次
PRIVATE_SUPPRESSION_WINDOW_SEC = 120 # 好友通过后，2 分钟内相同内容的私聊忽略

MAX_PAYLOAD_BYTES = 10 * 1024 * 1024
MAX_CHUNK_BYTES = 2 * 1024 * 1024
MAX_HEADER_LINE = 8192
REPLY_LOOKBACK_LINES = 5000

# ---- Friend-request de-dup cache ----
friend_req_lock = Lock()
friend_req_cache = {}  # { user_id: expire_ts }

def should_process_friend_request(user_id: str, window: int = FRIEND_REQ_WINDOW_SEC) -> bool:
    """Return True if we should handle this friend request now; False if it is a duplicate within window."""
    if not user_id:
        return True
    now = int(time.time())
    with friend_req_lock:
        expired = [uid for uid, exp in friend_req_cache.items() if exp <= now]
        for uid in expired:
            friend_req_cache.pop(uid, None)
        exp = friend_req_cache.get(user_id, 0)
        if exp > now:
            return False
        friend_req_cache[user_id] = now + window
        return True

# === Friend-request suppression (2-minute window) ===
suppression_lock = Lock()
suppression_cache = {}  # { user_id: [{"comment_norm": str, "expire_ts": int}] }

def normalize_text(s):
    """Normalize text to compare user messages with friend-request comments."""
    if s is None:
        return ""
    s = str(s)
    remove_chars = "　“”‘’《》〈〉【】。，：；？！（）、「」『』—［］＂＇\"'`~!@#$%^&*()_+-={}[]|:;<>?,./"
    for ch in remove_chars:
        s = s.replace(ch, "")
    # remove all whitespace (including tabs/newlines)
    s = "".join(s.split())
    return s

def add_suppression(user_id, comment, duration_sec=300):
    expire_ts = int(time.time()) + duration_sec
    entry = {"comment_norm": normalize_text(comment), "expire_ts": expire_ts}
    with suppression_lock:
        lst = suppression_cache.get(user_id, [])
        lst.append(entry)
        now = int(time.time())
        lst = [e for e in lst if e.get("expire_ts", 0) > now]
        suppression_cache[user_id] = lst

def should_suppress(user_id, text):
    norm = normalize_text(text)
    now = int(time.time())
    with suppression_lock:
        lst = suppression_cache.get(user_id, [])
        kept = []
        suppressed = False
        for e in lst:
            if e.get("expire_ts", 0) > now:
                kept.append(e)
                if norm and norm == e.get("comment_norm"):
                    suppressed = True
        suppression_cache[user_id] = kept
        return suppressed

# 数据库连接管理
def init_db():
    os.makedirs('cache', exist_ok=True)
    with sqlite3.connect('cache/OQQWall.db') as conn:
        cursor = conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA synchronous=NORMAL;')
        cursor.execute('PRAGMA busy_timeout=5000;')
        conn.commit()


@contextmanager
def get_db_connection():
    conn = sqlite3.connect('cache/OQQWall.db', timeout=10, isolation_level=None)
    try:
        conn.execute('PRAGMA busy_timeout=5000;')
        yield conn
    finally:
        conn.close()


def read_config(file_path):
    config = {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.partition('#')[0].strip()
                if not line or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip().strip('"')
    except FileNotFoundError:
        logger.warning('Configuration file %s not found; using defaults.', file_path)
    return config


config = read_config('oqqwall.config')
NAPCAT_ACCESS_TOKEN = config.get('napcat_access_token') or os.getenv('NAPCAT_ACCESS_TOKEN', '')
if not NAPCAT_ACCESS_TOKEN:
    raise RuntimeError('napcat_access_token 未配置，请更新 oqqwall.config。')
EXPECTED_AUTH_HEADER = f'Bearer {NAPCAT_ACCESS_TOKEN}'


def _digits(value, max_len=20):
    return isinstance(value, str) and value.isdigit() and 0 < len(value) <= max_len


def append_jsonl_threadsafe(file_path, obj):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    with open(file_path, 'a', encoding='utf-8') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line + '\n')
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def migrate_json_to_jsonl_if_needed(src_path):
    if not os.path.exists(src_path) or os.path.getsize(src_path) == 0:
        return
    with file_lock:
        try:
            with open(src_path, 'r', encoding='utf-8') as f:
                first_char = f.read(1)
                if first_char != '[':
                    return
                f.seek(0)
                data = json.load(f)
        except Exception as exc:
            logger.error('Failed to read legacy JSON file %s: %s', src_path, exc)
            return
        try:
            with open(src_path, 'w', encoding='utf-8') as f:
                for idx, item in enumerate(data):
                    json.dump(item, f, ensure_ascii=False)
                    if idx != len(data) - 1:
                        f.write('\n')
        except Exception as exc:
            logger.error('Failed to migrate %s to JSONL: %s', src_path, exc)


def read_recent_messages(file_path, max_lines=2000):
    if not os.path.exists(file_path):
        return []
    items = deque(maxlen=max_lines)
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    except Exception as exc:
        logger.error('Failed to read %s: %s', file_path, exc)
    return list(items)


def find_raw_message_by_id(message_id, max_lines=2000):
    try:
        target = int(message_id)
    except (TypeError, ValueError):
        return None
    entries = read_recent_messages(ALL_POSTS_FILE, max_lines=max_lines)
    for entry in reversed(entries):
        if entry.get('message_id') == target:
            return entry.get('raw_message')
    return None


def migrate_legacy_files():
    for legacy, target in (
        (LEGACY_ALL_POSTS_FILE, ALL_POSTS_FILE),
        (LEGACY_PRIV_POST_FILE, PRIV_POST_FILE),
    ):
        if not os.path.exists(legacy):
            continue
        migrate_json_to_jsonl_if_needed(legacy)
        if os.path.exists(target):
            logger.info('Target file %s already exists; skipping migration of %s', target, legacy)
            continue
        try:
            os.replace(legacy, target)
            logger.info('Migrated legacy file %s to %s', legacy, target)
        except OSError as exc:
            logger.error('Failed to migrate %s to %s: %s', legacy, target, exc)

ACCOUNT_CFG_PATH = './AcountGroupcfg.json'
_account_cfg_mtime = 0
account_group_cfg = {}
self_id_to_acgroup = {}
_managed_group_ids = set()


def _normalize_qq_id(value):
    if value is None:
        return None
    qq_str = str(value).strip()
    return qq_str or None


def _reload_account_group_cfg(force=False):
    global account_group_cfg, self_id_to_acgroup, _managed_group_ids, _account_cfg_mtime
    try:
        stat_info = os.stat(ACCOUNT_CFG_PATH)
    except FileNotFoundError:
        if force or _account_cfg_mtime:
            account_group_cfg = {}
            self_id_to_acgroup = {}
            _managed_group_ids = set()
            _account_cfg_mtime = 0
        return

    if not force and stat_info.st_mtime == _account_cfg_mtime:
        return

    try:
        with open(ACCOUNT_CFG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error('Failed to parse %s: %s', ACCOUNT_CFG_PATH, exc)
        return
    except FileNotFoundError:
        return

    mapping = {}
    managed_groups = set()
    for group_name, group_info in data.items():
        if not isinstance(group_info, dict):
            continue
        mainqqid = _normalize_qq_id(group_info.get('mainqqid'))
        if mainqqid:
            mapping[mainqqid] = group_name
        for qqid in group_info.get('minorqqid', []) or []:
            normalized_id = _normalize_qq_id(qqid)
            if normalized_id:
                mapping[normalized_id] = group_name
        mangroupid = group_info.get('mangroupid')
        if mangroupid:
            managed_groups.add(str(mangroupid))

    account_group_cfg = data
    self_id_to_acgroup = mapping
    _managed_group_ids = managed_groups
    _account_cfg_mtime = stat_info.st_mtime


_reload_account_group_cfg(force=True)

class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        """重写默认的日志方法，禁用默认的访问日志"""
        pass

    def handle(self):
        """重写 handle 方法来捕获连接错误"""
        try:
            super().handle()
        except ConnectionResetError as e:
            logger.error(f"连接错误 {str(e)}")
        except Exception as e:
            logger.error(f"处理请求时发生错误: {str(e)}")

    def send_json_response(self, status_code, data):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _verify_webhook(self, body: bytes):
        auth_header = self.headers.get('Authorization', '')
        if auth_header == EXPECTED_AUTH_HEADER:
            return True

        parsed = urlparse(self.path)
        access_token = parse_qs(parsed.query or '').get('access_token', [''])[0]
        if access_token == NAPCAT_ACCESS_TOKEN:
            return True

        signature = self.headers.get('X-Signature', '')
        if signature:
            scheme, _, provided = signature.partition('=')
            if scheme.lower() == 'sha1' and provided and NAPCAT_ACCESS_TOKEN:
                expected = hmac.new(
                    NAPCAT_ACCESS_TOKEN.encode('utf-8'),
                    body or b'',
                    hashlib.sha1
                ).hexdigest()
                if hmac.compare_digest(provided, expected):
                    return True

        logger.warning('Rejected request with invalid access token from %s', self.client_address)
        self.send_json_response(401, {"error": "unauthorized"})
        return False

    def _read_request_body(self):
        transfer_encoding = self.headers.get('Transfer-Encoding', '').lower()
        if 'chunked' in transfer_encoding:
            return self.read_chunked()

        content_length = self.headers.get('Content-Length')
        if content_length is not None:
            try:
                content_length = int(content_length)
            except ValueError:
                self.send_json_response(400, {"error": "Invalid Content-Length"})
                return None
            if content_length > MAX_PAYLOAD_BYTES:
                self.send_json_response(413, {"error": "Payload Too Large"})
                return None
            post_data = self.rfile.read(content_length)
            if len(post_data) != content_length:
                self.send_json_response(400, {"error": "Incomplete body"})
                return None
            return post_data

        post_data = bytearray()
        while True:
            chunk = self.rfile.read(1024)
            if not chunk:
                break
            post_data.extend(chunk)
            if len(post_data) > MAX_PAYLOAD_BYTES:
                self.send_json_response(413, {"error": "Payload Too Large"})
                return None
        return bytes(post_data)

    def do_POST(self):
        try:
            post_data = self._read_request_body()
            if post_data is None:
                return

            if not self._verify_webhook(post_data):
                return

            _reload_account_group_cfg()

            try:
                data = json.loads(post_data.decode('utf-8'))
            except json.JSONDecodeError:
                self.send_json_response(400, {"error": "Invalid JSON"})
                return

            user_id = data.get('user_id')
            self_id = data.get('self_id')
            acgroup = self_id_to_acgroup.get(str(self_id), 'Unknown')
            logger.info(f"来自{user_id}到{self_id},组{acgroup}")

            # 忽略自动回复消息和好友请求消息
            if data.get('message_type') == 'private' and 'raw_message' in data:
                raw_message = data['raw_message']
                if '自动回复' in raw_message:
                    logger.info("Received auto-reply message, ignored.")
                    self.send_json_response(200, {"status": "ok", "message": "Auto-reply message ignored"})
                    return
                if '请求添加你为好友' in raw_message:
                    logger.info("Received friend-add request message, ignored.")
                    self.send_json_response(200, {"status": "ok", "message": "Friend-add request ignored"})
                    return
                if '我们已成功添加为好友，' in raw_message:
                    logger.info("Received friend-add request message, ignored.")
                    self.send_json_response(200, {"status": "ok", "message": "Friend-add request ignored"})
                    return

            # === 好友请求：自动同意 + 2 分钟内屏蔽相同内容私聊 ===
            if data.get('post_type') == 'request' and data.get('request_type') == 'friend':
                self.handle_friend_request(data)
                self.send_json_response(200, {"status": "ok", "message": "Friend request handled"})
                return

            # === 私聊消息：如命中 2 分钟屏蔽规则则直接忽略 ===
            if data.get('message_type') == 'private':
                if self.is_suppressed_private_message(data):
                    logger.info("Private message suppressed due to recent friend-request duplicate.")
                    self.send_json_response(200, {"status": "ok", "message": "Suppressed duplicate private message"})
                    return

            # 处理不同类型的通知
            if data.get('notice_type') == 'friend_recall':
                self.handle_friend_recall(data)
            else:
                self.handle_default(data)

            # 发送响应
            self.send_json_response(200, {"status": "ok", "message": "Post received and saved"})

        except ConnectionResetError as e:
            logger.error('连接错误 %s', e)
        except Exception as e:
            logger.error(f"处理POST请求时发生错误: {str(e)}")
            self.send_json_response(500, {"error": f"Internal Server Error: {str(e)}"})

    def read_chunked(self):
        payload = bytearray()
        total = 0
        while True:
            line = self.rfile.readline(MAX_HEADER_LINE)
            if not line:
                self.send_json_response(400, {"error": "Malformed chunked encoding"})
                return None
            size_token = line.split(b';', 1)[0].strip()
            if not size_token:
                continue
            try:
                chunk_size = int(size_token, 16)
            except ValueError:
                self.send_json_response(400, {"error": "Invalid chunk size"})
                return None

            if chunk_size == 0:
                while True:
                    trailer = self.rfile.readline(MAX_HEADER_LINE)
                    if not trailer or trailer == b'\r\n':
                        break
                break

            if chunk_size > MAX_CHUNK_BYTES:
                self.send_json_response(413, {"error": "Chunk Too Large"})
                return None

            chunk = self.rfile.read(chunk_size + 2)
            if len(chunk) < chunk_size + 2:
                self.send_json_response(400, {"error": "Incomplete chunked data"})
                return None

            payload.extend(chunk[:-2])
            total += chunk_size
            if total > MAX_PAYLOAD_BYTES:
                self.send_json_response(413, {"error": "Payload Too Large"})
                return None

        return bytes(payload)

    def handle_friend_recall(self, data):
        user_id = str(data.get('user_id'))
        self_id = str(data.get('self_id'))
        message_id = data.get('message_id')

        if user_id and message_id:
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT rawmsg FROM sender WHERE senderid=? AND receiver=?', (user_id, self_id))
                    row = cursor.fetchone()
                    if row:
                        rawmsg_json = row[0]
                        try:
                            message_list = json.loads(rawmsg_json)
                        except json.JSONDecodeError as exc:
                            logger.error('Error decoding rawmsg JSON: %s', exc)
                            message_list = []
                        message_list = [msg for msg in message_list if msg.get('message_id') != message_id]
                        updated_rawmsg = json.dumps(message_list, ensure_ascii=False)
                        cursor.execute('UPDATE sender SET rawmsg=? WHERE senderid=? AND receiver=?', (updated_rawmsg, user_id, self_id))
                        conn.commit()
                        logger.info('Message deleted from rawmsg in database')
                    else:
                        logger.info('No existing messages found for this user and receiver.')
            except Exception as e:
                logger.error(f'Error deleting message from database: {e}')

    def handle_friend_request(self, data):
        """自动同意好友请求，并将该请求的 comment 记录为几分钟的抑制关键词。"""
        user_id = str(data.get('user_id') or '')
        flag = str(data.get('flag') or '')
        self_id = str(data.get('self_id') or '')
        comment = data.get('comment') or ''

        if not (_digits(user_id) and _digits(flag) and _digits(self_id)):
            logger.warning('Friend request carries invalid identifiers; request ignored.')
            return

        # 2 分钟内重复的同一 user_id 好友申请只处理一次
        if not should_process_friend_request(user_id, FRIEND_REQ_WINDOW_SEC):
            logger.info(f"Duplicate friend request from {user_id} within some minutes; ignored.")
            return

        if user_id and comment:
            add_suppression(user_id, comment, duration_sec=PRIVATE_SUPPRESSION_WINDOW_SEC)
            logger.info(f"Added suppression for user {user_id} with comment='{comment}' for some minutes.")
        else:
            logger.warning("Friend request missing user_id or comment; suppression not added.")

        try:
            subprocess.run(['bash', './qqBot/approve_friend_add.sh', flag, user_id, self_id], check=True)
            logger.info('Approved friend request: user=%s flag=%s', user_id, flag)
        except subprocess.CalledProcessError as exc:
            logger.error('approve_friend_add.sh failed: %s', exc)

    def is_suppressed_private_message(self, data) -> bool:
        user_id = str(data.get('user_id') or '')
        # 优先使用 raw_message；若是 array 格式，可拼接 text 字段兜底
        raw = data.get('raw_message')
        if not raw and isinstance(data.get('message'), list):
            try:
                parts = []
                for seg in data['message']:
                    if isinstance(seg, dict) and seg.get('type') == 'text':
                        parts.append(str(seg.get('data', {}).get('text', '')))
                raw = ''.join(parts) if parts else ''
            except Exception:
                raw = ''
        return should_suppress(user_id, raw or '')
    def handle_default(self, data):
        try:
            append_jsonl_threadsafe(ALL_POSTS_FILE, data)
        except Exception as exc:
            logger.error('Error writing to %s: %s', ALL_POSTS_FILE, exc)

        # Record group commands and private messages
        self.record_group_command(data)
        self.record_private_message(data)

    def record_group_command(self, data):
        if data.get('message_type') != 'group':
            return

        group_id = str(data.get('group_id') or '')
        sender = data.get('sender', {})
        raw_message = data.get('raw_message', '')
        self_id = str(data.get('self_id') or '')

        if not group_id or group_id not in _managed_group_ids:
            return

        is_admin = sender.get('role') in ('admin', 'owner')
        if not is_admin:
            return

        command_script_path = './getmsgserv/command.sh'

        if raw_message.startswith(f"[CQ:at,qq={self_id}"):
            command_text = re.sub(r'\[.*?\]', '', raw_message).strip()
            if command_text:
                try:
                    subprocess.run([command_script_path, command_text, self_id], check=True)
                except subprocess.CalledProcessError as exc:
                    logger.error('Command execution failed: %s', exc)
            return

        if raw_message.startswith('[CQ:reply,id=') and f"[CQ:at,qq={self_id}]" in raw_message:
            match_reply = re.search(r"\[CQ:reply,id=(\d+)\]", raw_message)
            if not match_reply:
                return
            reply_id = match_reply.group(1)
            raw_reply_message = find_raw_message_by_id(reply_id, max_lines=REPLY_LOOKBACK_LINES)
            if not raw_reply_message:
                logger.warning('Reply message %s not found within last %d lines.', reply_id, REPLY_LOOKBACK_LINES)
                return

            match_tag = re.search(r"内部编号(\d+)", raw_reply_message or '')
            gottedtag = match_tag.group(1) if match_tag else None
            match_after_at = re.search(r"\[CQ:at,qq=\d+\]\s*(.+)", raw_message)
            after_at_text = match_after_at.group(1).strip() if match_after_at else ''
            command_text = f"{gottedtag} {after_at_text}".strip() if gottedtag and after_at_text else None
            if not command_text:
                logger.warning('Reply command missing内部编号或命令文本，忽略。')
                return
            try:
                subprocess.run([command_script_path, command_text, self_id], check=True)
            except subprocess.CalledProcessError as exc:
                logger.error('Command execution failed: %s', exc)


    def record_private_message(self, data):
        message_type = data.get('message_type')
        post_type = data.get('post_type')
        user_id = str(data.get('user_id'))
        self_id = str(data.get('self_id'))
        nickname = data.get('sender', {}).get('nickname')
        timestamp = data.get('time')

        if message_type == 'private' and post_type != 'message_sent' and user_id and timestamp is not None:
            simplified_data = {
                "message_id": data.get("message_id"),
                "message": data.get("message"),
                "time": data.get("time")
            }
            logger.debug('Recording private message for %s -> %s', user_id, self_id)
            ACgroup = self_id_to_acgroup.get(self_id, 'Unknown')

            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    try:
                        cursor.execute('SELECT rawmsg FROM sender WHERE senderid=? AND receiver=?', (user_id, self_id))
                        row = cursor.fetchone()
                        if row:
                            rawmsg_json = row[0]
                            try:
                                message_list = json.loads(rawmsg_json)
                                if not isinstance(message_list, list):
                                    message_list = []
                            except json.JSONDecodeError:
                                message_list = []
                        else:
                            message_list = []

                        message_list.append(simplified_data)
                        message_list = [m for m in message_list if isinstance(m, dict)]
                        message_list.sort(key=lambda x: x.get('time', 0))

                        deduped = []
                        seen_ids = set()
                        for item in message_list:
                            message_id = item.get('message_id')
                            if message_id is not None:
                                if message_id in seen_ids:
                                    continue
                                seen_ids.add(message_id)
                            deduped.append(item)

                        message_list = deduped[-500:]
                        updated_rawmsg = json.dumps(message_list, ensure_ascii=False)

                        if row:
                            cursor.execute('''
                                UPDATE sender 
                                SET rawmsg=?, modtime=CURRENT_TIMESTAMP 
                                WHERE senderid=? AND receiver=?
                            ''', (updated_rawmsg, user_id, self_id))
                        else:
                            cursor.execute('''
                                INSERT INTO sender (senderid, receiver, ACgroup, rawmsg, modtime) 
                                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                            ''', (user_id, self_id, ACgroup, updated_rawmsg))

                            cursor.execute('SELECT MAX(tag) FROM preprocess')
                            max_tag = cursor.fetchone()[0] or 0
                            new_tag = max_tag + 1
                            cursor.execute('''
                                INSERT INTO preprocess (tag, senderid, nickname, receiver, ACgroup) 
                                VALUES (?, ?, ?, ?, ?)
                            ''', (new_tag, user_id, nickname, self_id, ACgroup))

                            conn.commit()
                            preprocess_script_path = './getmsgserv/preprocess.sh'
                            try:
                                subprocess.run([preprocess_script_path, str(new_tag)], check=True)
                            except subprocess.CalledProcessError as e:
                                logger.error(f"Preprocess script execution failed: {e}")

                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        logger.error(f'Database error: {e}')
                        raise

                try:
                    append_jsonl_threadsafe(PRIV_POST_FILE, data)
                except Exception as exc:
                    logger.error('Error recording to %s: %s', PRIV_POST_FILE, exc)

            except Exception as e:
                logger.error(f'Error recording private message to database: {e}')

def run(server_class=ThreadingHTTPServer, handler_class=RequestHandler):
    init_db()
    migrate_legacy_files()
    _reload_account_group_cfg(force=True)

    server_class.allow_reuse_address = True
    if hasattr(server_class, 'daemon_threads'):
        server_class.daemon_threads = True

    port = int(config.get('http-serv-port', 8000))
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    httpd.daemon_threads = True
    httpd.allow_reuse_address = True
    logger.info(f'Starting HTTP server on port {port}...')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info('Server is shutting down...')
        httpd.server_close()

if __name__ == '__main__':
    run()


# The following lines are ignored as per the request
# - They were marked as IGNORE in the original code comments.
# - They are not part of the recent edits and should not be included in the final code
# - They are not relevant to the current context of the code.
