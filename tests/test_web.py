#!/usr/bin/env python3
import http.server
import socketserver
import threading
import time

class SimpleHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            html = """
<!DOCTYPE html>
<html>
<head>
    <title>测试页面</title>
</head>
<body>
    <h1>🎯 QZone服务模拟器测试</h1>
    <p>Web服务器运行正常！</p>
    <p>时间: """ + time.strftime('%Y-%m-%d %H:%M:%S') + """</p>
</body>
</html>
            """
            self.wfile.write(html.encode('utf-8'))
        else:
            super().do_GET()

def main():
    port = 8081
    with socketserver.TCPServer(("", port), SimpleHandler) as httpd:
        print(f"服务器启动在端口 {port}")
        print(f"访问: http://localhost:{port}")
        httpd.serve_forever()

if __name__ == "__main__":
    main()
