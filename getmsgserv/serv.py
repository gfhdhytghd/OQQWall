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
logger.setLevel(logging.INFO)

# 创建格式化器
formatter = CustomFormatter('%(asctime)s %(message)s')

# 文件处理器
file_handler = logging.FileHandler('OQQWallmsgserv.log')
file_handler.setFormatter(formatter)

# 控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

# 添加处理器
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# 定义存储路径
RAWPOST_DIR = './getmsgserv/rawpost'
ALLPOST_DIR = './getmsgserv/all'
COMMAND_DIR = './qqBot/command'
COMMU_DIR = './getmsgserv/all/'
# 确保保存路径存在
os.makedirs(RAWPOST_DIR, exist_ok=True)
os.makedirs(ALLPOST_DIR, exist_ok=True)

# 添加文件锁
file_lock = Lock()

# 数据库连接管理
@contextmanager
def get_db_connection():
    conn = sqlite3.connect('cache/OQQWall.db', timeout=10)
    try:
        yield conn
    finally:
        conn.close()

# 文件操作安全化
def safe_write_json(file_path, data):
    with file_lock:
        with open(file_path, 'w', encoding='utf-8') as f:
            # 添加文件锁
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, ensure_ascii=False, indent=4)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                config[key.strip()] = value.strip().strip('"')
    return config

config = read_config('oqqwall.config')

# 读取 AcountGroupcfg.json 以映射 self_id 到 ACgroup
with open('./AcountGroupcfg.json', 'r', encoding='utf-8') as f:
    account_group_cfg = json.load(f)

self_id_to_acgroup = {}
for group_name, group_info in account_group_cfg.items():
    mainqqid = group_info.get('mainqqid')
    if mainqqid:
        self_id_to_acgroup[mainqqid] = group_name
    minorqqid_list = group_info.get('minorqqid', [])
    for qqid in minorqqid_list:
        self_id_to_acgroup[qqid] = group_name

class RequestHandler(BaseHTTPRequestHandler):
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

    def do_POST(self):
        try:
            logger.info("newmsg comes")

            # 检查是否使用了 Transfer-Encoding: chunked
            transfer_encoding = self.headers.get('Transfer-Encoding', '').lower()
            if 'chunked' in transfer_encoding:
                post_data = self.read_chunked()
            else:
                content_length = self.headers.get('Content-Length')
                if content_length is not None:
                    try:
                        content_length = int(content_length)
                        post_data = self.rfile.read(content_length)
                    except ValueError:
                        self.send_error(400, 'Invalid Content-Length')
                        return
                else:
                    max_length = 10 * 1024  # 10 KB
                    post_data = b''
                    while True:
                        chunk = self.rfile.read(1024)
                        if not chunk:
                            break
                        post_data += chunk
                        if len(post_data) > max_length:
                            self.send_error(413, 'Payload Too Large')
                            return

            try:
                data = json.loads(post_data.decode('utf-8'))
            except json.JSONDecodeError:
                self.send_error(400, 'Invalid JSON')
                return

            # 记录消息日志
            user_id = data.get('user_id')
            self_id = data.get('self_id')
            acgroup = self_id_to_acgroup.get(str(self_id), 'Unknown')
            logger.info(f"来自{user_id}到{self_id},组{acgroup}")

            # 忽略自动回复消息和好友请求消息
            if data.get('message_type') == 'private' and 'raw_message' in data:
                raw_message = data['raw_message']
                if '自动回复' in raw_message:
                    logger.info("Received auto-reply message, ignored.")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'Auto-reply message ignored')
                    return
                if '请求添加你为好友' in raw_message:
                    logger.info("Received friend-add request message, ignored.")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'Friend-add request ignored')
                    return

            # 处理不同类型的通知
            if data.get('notice_type') == 'friend_recall':
                self.handle_friend_recall(data)
            else:
                self.handle_default(data)

            # 发送响应
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Post received and saved')

        except ConnectionResetError as e:
            logging.error(f"[{time.strftime('%H:%M:%S %d/%b')}] 连接错误 {e}")
        except Exception as e:
            logger.error(f"处理POST请求时发生错误: {str(e)}")
            self.send_error(500, f'Internal Server Error: {e}')

    def read_chunked(self):
        """
        读取分块编码的请求体
        """
        data = b''
        while True:
            # 读取每个块的大小行
            line = self.rfile.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                # 解析块大小（十六进制）
                chunk_size = int(line, 16)
            except ValueError:
                self.send_error(400, 'Invalid chunk size')
                return b''

            if chunk_size == 0:
                # 最后的块，读取并忽略 trailer 头
                while True:
                    trailer = self.rfile.readline()
                    if not trailer or trailer == b'\r\n':
                        break
                break

            # 读取指定大小的块数据加上末尾的 CRLF
            chunk = self.rfile.read(chunk_size + 2)
            if len(chunk) < chunk_size + 2:
                self.send_error(400, 'Incomplete chunked data')
                return data
            data += chunk[:-2]  # 去除末尾的 CRLF

        # 可选：限制最大读取大小以防止资源耗尽
        max_length = 10 * 1024 * 1024  # 10 MB
        if len(data) > max_length:
            self.send_error(413, 'Payload Too Large')
            return b''

        return data

    def handle_friend_recall(self, data):
        user_id = str(data.get('user_id'))
        self_id = str(data.get('self_id'))
        message_id = data.get('message_id')

        if user_id and message_id:
            try:
                conn = sqlite3.connect('cache/OQQWall.db', timeout=10)
                cursor = conn.cursor()

                # Fetch the existing rawmsg
                cursor.execute('SELECT rawmsg FROM sender WHERE senderid=? AND receiver=?', (user_id, self_id))
                row = cursor.fetchone()
                if row:
                    rawmsg_json = row[0]
                    try:
                        message_list = json.loads(rawmsg_json)
                        # Remove the message with the matching message_id
                        message_list = [msg for msg in message_list if msg.get('message_id') != message_id]
                        # Update the rawmsg field
                        updated_rawmsg = json.dumps(message_list, ensure_ascii=False)
                        cursor.execute('UPDATE sender SET rawmsg=? WHERE senderid=? AND receiver=?', (updated_rawmsg, user_id, self_id))
                        conn.commit()
                        logger.info('Message deleted from rawmsg in database')
                    except json.JSONDecodeError as e:
                        logger.error(f'Error decoding rawmsg JSON: {e}')
                else:
                    logger.info('No existing messages found for this user and receiver.')
                conn.close()
            except Exception as e:
                logger.error(f'Error deleting message from database: {e}')

    def handle_default(self, data):
        # Append to all_posts.json incrementally
        all_file_path = os.path.join(ALLPOST_DIR, 'all_posts.json')
        try:
            with open(all_file_path, 'a', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
                f.write('\n')  # Add a newline for readability
        except Exception as e:
            logger.error(f'Error writing to all_posts.json: {e}')

        # Record group commands and private messages
        self.record_group_command(data)
        self.record_private_message(data)

    def record_group_command(self, data):
        message_type = data.get('message_type')
        if message_type == 'group':
            # 读取 JSON 配置文件
            try:
                with open('./AcountGroupcfg.json', 'r', encoding='utf-8') as file:
                    cfgdata = json.load(file)
            except Exception as e:
                logger.error(f'Error reading configuration file: {e}')
                return

            # 提取所有管理组 ID
            mangroupid_list = [group['mangroupid'] for group in cfgdata.values()]
            group_id = str(data.get('group_id'))
            sender = data.get('sender', {})
            raw_message = data.get('raw_message', '')
            self_id = str(data.get('self_id'))

            if (group_id in mangroupid_list and sender.get('role') == 'admin' and raw_message.startswith(f"[CQ:at,qq={self_id}")):
                print("serv:有指令消息")
                command_text = re.sub(r'\[.*?\]', '', raw_message).strip()
                print("指令:", command_text)
                command_script_path = './getmsgserv/command.sh'
                try:
                    subprocess.run([command_script_path, command_text] + [self_id], check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Command execution failed: {e}")

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
            logger.info(data.get("message"))
            ACgroup = self_id_to_acgroup.get(self_id, 'Unknown')

            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    try:
                        # 检查是否已存在该发送者和接收者的记录
                        cursor.execute('SELECT rawmsg FROM sender WHERE senderid=? AND receiver=?', (user_id, self_id))
                        row = cursor.fetchone()
                        if row:
                            # 如果存在，加载现有的 rawmsg 并追加新消息
                            rawmsg_json = row[0]
                            try:
                                message_list = json.loads(rawmsg_json)
                                if not isinstance(message_list, list):
                                    message_list = []
                            except json.JSONDecodeError:
                                message_list = []

                            message_list.append(simplified_data)
                            # 按时间排序消息
                            message_list = sorted(message_list, key=lambda x: x.get('time', 0))

                            updated_rawmsg = json.dumps(message_list, ensure_ascii=False)
                            cursor.execute('''
                                UPDATE sender 
                                SET rawmsg=?, modtime=CURRENT_TIMESTAMP 
                                WHERE senderid=? AND receiver=?
                            ''', (updated_rawmsg, user_id, self_id))
                        else:
                            # 如果不存在，插入新记录
                            message_list = [simplified_data]
                            rawmsg_json = json.dumps(message_list, ensure_ascii=False)
                            cursor.execute('''
                                INSERT INTO sender (senderid, receiver, ACgroup, rawmsg, modtime) 
                                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                            ''', (user_id, self_id, ACgroup, rawmsg_json))

                            # 检查 preprocess 表中的最大 tag
                            cursor.execute('SELECT MAX(tag) FROM preprocess')
                            max_tag = cursor.fetchone()[0] or 0
                            new_tag = max_tag + 1

                            # 插入 preprocess 表
                            cursor.execute('''
                                INSERT INTO preprocess (tag, senderid, nickname, receiver, ACgroup) 
                                VALUES (?, ?, ?, ?, ?)
                            ''', (new_tag, user_id, nickname, self_id, ACgroup))

                            # 提交更改
                            conn.commit()

                            # 调用 preprocess.sh 脚本
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

                # 持续写入 priv_post.json
                priv_post_path = os.path.join(ALLPOST_DIR, 'priv_post.json')
                try:
                    if os.path.exists(priv_post_path):
                        with open(priv_post_path, 'r', encoding='utf-8') as f:
                            priv_post_data = json.load(f)
                    else:
                        priv_post_data = []

                    priv_post_data.append(data)
                    with open(priv_post_path, 'w', encoding='utf-8') as f:
                        json.dump(priv_post_data, f, ensure_ascii=False, indent=4)
                except Exception as e:
                    logger.error(f'Error recording to priv_post.json: {e}')

            except Exception as e:
                logger.error(f'Error recording private message to database: {e}')

def run(server_class=ThreadingHTTPServer, handler_class=RequestHandler):
    port = int(config.get('http-serv-port', 8000))
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    logger.info(f'Starting HTTP server on port {port}...')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info('Server is shutting down...')
        httpd.server_close()

if __name__ == '__main__':
    run()