#!/usr/bin/env python3
"""
简单的测试HTTP服务器，用于接收重放的请求
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time

class TestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[服务器] {format % args}")
    
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
            
            print(f"[接收] POST {self.path}")
            if body:
                try:
                    data = json.loads(body)
                    print(f"[消息] {data.get('message', '无消息内容')}")
                    print(f"[用户] {data.get('user_id', '未知')}")
                    if 'group_id' in data:
                        print(f"[群组] {data['group_id']}")
                except:
                    print(f"[数据] {body[:100]}...")
            
            # 返回成功响应
            response = {"status": "ok", "received": True}
            response_body = json.dumps(response).encode('utf-8')
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            
        except Exception as e:
            print(f"[错误] {e}")
            self.send_response(500)
            self.end_headers()

def run_test_server(port=8082):
    httpd = HTTPServer(('', port), TestHandler)
    print(f"🎯 测试服务器启动在端口 {port}")
    print(f"   访问地址: http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 测试服务器停止")
        httpd.shutdown()

if __name__ == "__main__":
    run_test_server()
