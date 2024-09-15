from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import json
import os
import re

# Define storage paths
RAWPOST_DIR = './getmsgserv/rawpost'
ALLPOST_DIR = './getmsgserv/all'
COMMAND_DIR = './qqBot/command'
COMMU_DIR = './getmsgserv/all/'
# Ensure save paths exist
os.makedirs(RAWPOST_DIR, exist_ok=True)
os.makedirs(ALLPOST_DIR, exist_ok=True)

def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                config[key.strip()] = value.strip().strip('"')
    return config

config = read_config('oqqwall.config')

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # Read the content length and data
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            # Decode and parse JSON data
            try:
                data = json.loads(post_data.decode('utf-8'))
            except json.JSONDecodeError:
                self.send_error(400, 'Invalid JSON')
                return

            # Ignore auto-reply messages
            if data.get('message_type') == 'private' and 'raw_message' in data and '自动回复' in data['raw_message']:
                print("Received auto-reply message, ignored.")
            else:
                # Handle different types of notifications
                if data.get('notice_type') == 'friend_recall':
                    self.handle_friend_recall(data)
                else:
                    self.handle_default(data)

            # Send response
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Post received and saved')

        except Exception as e:
            self.send_error(500, f'Internal Server Error: {e}')
            print(f'Error handling request: {e}')

    def handle_friend_recall(self, data):
        user_id = data.get('user_id')
        self_id = data.get('self_id')
        message_id = data.get('message_id')

        if user_id and message_id:
            file_path = os.path.join(RAWPOST_DIR, f'{user_id}-{self_id}.json')
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)

                    updated_data = [msg for msg in existing_data if msg.get('message_id') != message_id]

                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(updated_data, f, ensure_ascii=False, indent=4)

                    print('已删除')
                except Exception as e:
                    print(f'Error updating file {file_path}: {e}')

    def handle_default(self, data):
        # Append to all_posts.json incrementally
        all_file_path = os.path.join(ALLPOST_DIR, 'all_posts.json')
        with open(all_file_path, 'a', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            f.write('\n')  # Add a newline for readability

        # Record group commands and private messages
        self.record_group_command(data)
        self.record_private_message(data)

    def record_group_command(self, data):
        message_type = data.get('message_type')
        if message_type == 'group':
            # Read JSON configuration file
            try:
                with open('./AcountGroupcfg.json', 'r') as file:
                    cfgdata = json.load(file)
            except Exception as e:
                print(f'Error reading configuration file: {e}')
                return

            # Extract all management group IDs
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
        user_id = data.get('user_id')
        self_id = data.get('self_id')
        timestamp = data.get('time')

        if message_type == 'private' and post_type != 'message_sent' and user_id and timestamp is not None:
            simplified_data = {
                "message_id": data.get("message_id"),
                "message": data.get("message"),
                "time": data.get("time")
            }

            file_path = os.path.join(RAWPOST_DIR, f'{user_id}-{self_id}.json')
            try:
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                else:
                    existing_data = []

                if not existing_data:
                    sender_info = {"sender": data.get("sender")}
                    existing_data.append(sender_info)

                existing_data.append(simplified_data)
                sorted_data = sorted(existing_data, key=lambda x: x.get('time', 0))

                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(sorted_data, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f'Error recording private message to {file_path}: {e}')

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
                print(f'Error recording to priv_post.json: {e}')

def run(server_class=ThreadingHTTPServer, handler_class=RequestHandler):
    port = int(config.get('http-serv-port', 8000))
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f'Starting HTTP server on port {port}...')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('Server is shutting down...')
        httpd.server_close()

if __name__ == '__main__':
    run()
