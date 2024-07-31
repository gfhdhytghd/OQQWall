from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os

# 定义存储路径
RAWPOST_DIR = './getmsgserv/rawpost'
ALLPOST_DIR = './getmsgserv/all'
COMMAND_DIR = './qqBot/command'

# 确保保存路径存在
os.makedirs(RAWPOST_DIR, exist_ok=True)
os.makedirs(ALLPOST_DIR, exist_ok=True)

def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            key, value = line.strip().split('=')
            config[key.strip()] = value.strip().strip('"')
    return config

config = read_config('oqqwall.config')

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 解析请求头和请求体
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        # 解析 JSON 数据
        try:
            data = json.loads(post_data.decode('utf-8'))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Invalid JSON')
            return

        # 记录到 ./all 文件夹
        all_file_path = os.path.join(ALLPOST_DIR, 'all_posts.json')
        if os.path.exists(all_file_path):
            with open(all_file_path, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
        else:
            all_data = []

        all_data.append(data)
        with open(all_file_path, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
        
        #记录群中命令
        message_type = data.get('message_type')
        if message_type == 'group':
            print ("serv:有群组消息")
            groupid = config.get('management-group-id')
            qqid = config.get('mainqq-id')
            group_id = data.get('group_id')
            sender = data.get('sender', {})
            raw_message = data.get('raw_message', '')
            group_id=int(group_id)
            groupid=int(groupid)
            if (group_id == groupid and sender.get('role') == 'admin' and 
                raw_message.startswith(f"[CQ:at,qq={qqid}]")):
                print ("serv:有指令消息")
                # Extract and save the relevant part of raw_message
                command_text = raw_message[len(f"[CQ:at,qq={qqid}]"):]
                command_file_path = os.path.join(COMMAND_DIR, 'commands.txt')
                with open(command_file_path, 'a', encoding='utf-8') as f:
                    f.write(command_text + '\n')

        # 获取 message_type、user_id 和 time 字段
        message_type = data.get('message_type')
        user_id = data.get('user_id')
        timestamp = data.get('time')
        if not user_id or timestamp is None:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Missing user_id or time')
            return

        # 仅处理 message_type 为 "private" 的数据
        if message_type == 'private':
            # 只保留 "message" 和 "time" 字段
            simplified_data = {
                "message": data.get("message"),
                "time": data.get("time")
            }

            # 记录到 ./rawpost 文件夹
            file_path = os.path.join(RAWPOST_DIR, f'{user_id}.json')
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            else:
                existing_data = []

            # 检查并更新 "sender" 只记录一次
            if not existing_data:
                sender_info = {
                    "sender": data.get("sender")
                }
                existing_data.append(sender_info)

            # 添加新的数据并按时间戳排序
            existing_data.append(simplified_data)
            sorted_data = sorted(existing_data, key=lambda x: x.get('time', 0))

            # 写入排序后的数据
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(sorted_data, f, ensure_ascii=False, indent=4)
        
            priv_post_path = os.path.join(ALLPOST_DIR, 'priv_post.json')
            if os.path.exists(priv_post_path):
                with open(priv_post_path, 'r', encoding='utf-8') as f:
                    priv_post_data = json.load(f)
            else:
                priv_post_data = []

            priv_post_data.append(data)
            with open(priv_post_path, 'w', encoding='utf-8') as f:
                json.dump(priv_post_data, f, ensure_ascii=False, indent=4)

        # 返回响应
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Post received and saved')

def run(server_class=HTTPServer, handler_class=RequestHandler, port=8082):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f'Starting httpd server on port {port}...')
    httpd.serve_forever()

if __name__ == '__main__':
    run()

