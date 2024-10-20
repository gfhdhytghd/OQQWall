from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import json
import os
import re
import sqlite3

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

# Read AcountGroupcfg.json to map self_id to ACgroup
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
            elif data.get('message_type') == 'private' and 'raw_message' in data and '请求添加你为好友' in data['raw_message']:
                print("Received friend-add request message, ignored.")
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
                        print('Message deleted from rawmsg in database')
                    except json.JSONDecodeError as e:
                        print(f'Error decoding rawmsg JSON: {e}')
                else:
                    print('No existing messages found for this user and receiver.')
                conn.close()
            except Exception as e:
                print(f'Error deleting message from database: {e}')

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
                with open('./AcountGroupcfg.json', 'r', encoding='utf-8') as file:
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

            ACgroup = self_id_to_acgroup.get(self_id, 'Unknown')

            try:
                conn = sqlite3.connect('cache/OQQWall.db', timeout=10)
                cursor = conn.cursor()

                # Check if a record already exists for this sender and receiver
                cursor.execute('SELECT rawmsg FROM sender WHERE senderid=? AND receiver=?', (user_id, self_id))
                row = cursor.fetchone()
                if row:
                    # If exists, load the existing rawmsg and append the new message
                    rawmsg_json = row[0]
                    try:
                        message_list = json.loads(rawmsg_json)
                        if not isinstance(message_list, list):
                            message_list = []
                    except json.JSONDecodeError:
                        message_list = []

                    message_list.append(simplified_data)
                    # Sort messages by time
                    message_list = sorted(message_list, key=lambda x: x.get('time', 0))

                    updated_rawmsg = json.dumps(message_list, ensure_ascii=False)
                    cursor.execute('''
                        UPDATE sender 
                        SET rawmsg=?, modtime=CURRENT_TIMESTAMP 
                        WHERE senderid=? AND receiver=?
                    ''', (updated_rawmsg, user_id, self_id))
                else:
                    # If not exists, insert a new record with the message
                    message_list = [simplified_data]
                    rawmsg_json = json.dumps(message_list, ensure_ascii=False)
                    cursor.execute('''
                        INSERT INTO sender (senderid, receiver, ACgroup, rawmsg, modtime) 
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (user_id, self_id, ACgroup, rawmsg_json))

                    # Check the max tag from the preprocess table
                    cursor.execute('SELECT MAX(tag) FROM preprocess')
                    max_tag = cursor.fetchone()[0] or 0
                    new_tag = max_tag + 1

                    # Insert into preprocess table
                    cursor.execute('''
                        INSERT INTO preprocess (tag, senderid, nickname, receiver, ACgroup) 
                        VALUES (?, ?, ?, ?, ?)
                    ''', (new_tag, user_id, nickname, self_id, ACgroup))

                    # Commit changes
                    conn.commit()

                    # Call the preprocess.sh script with the new tag
                    preprocess_script_path = './getmsgserv/preprocess.sh'
                    try:
                        subprocess.run([preprocess_script_path, str(new_tag)], check=True)
                    except subprocess.CalledProcessError as e:
                        print(f"Preprocess script execution failed: {e}")

                conn.commit()
                conn.close()
            except Exception as e:
                print(f'Error recording private message to database: {e}')

            # Keep writing to priv_post.json as per original code
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
