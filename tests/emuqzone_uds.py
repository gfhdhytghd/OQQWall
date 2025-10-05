"""
QZone UDS Service Emulator
基于 Unix Domain Socket 的 qzone-serv-UDS 模拟器，用于联调与开发。

- 监听一个 UDS（默认 ./qzone_uds.sock，可通过环境变量 QZONE_UDS_PATH 或命令行参数 --sock 指定）
- 每个连接接收一段 JSON（EOF 结束），解析后返回 'success' 或 'failed'
- 内置一个简易 Web 页面（默认 http://localhost:8086，可通过 --port 指定）用于预览最近请求

用法示例：
  python3 tests/emuqzone_uds.py --sock ./qzone_uds.sock --port 8086
  printf '%s' '{"text":"hello","image":[],"cookies":{}}' | socat - UNIX-CONNECT:./qzone_uds.sock
"""

import os
import json
import time
import base64
import logging
import threading
import socket
import argparse
from datetime import datetime
from typing import List, Dict, Any
import http.server


logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("emuqzone_uds")


def _process_image(image_str: str) -> str:
    """将输入图片源转为可在网页预览的 data URL 或保留 http(s) 链接。"""
    try:
        if not image_str:
            return ""
        s = image_str.strip()
        if s.startswith('http://') or s.startswith('https://'):
            return s
        if s.startswith('file://'):
            path = s[7:]
            if os.path.isfile(path):
                with open(path, 'rb') as f:
                    b = f.read()
                return f"data:image/jpeg;base64,{base64.b64encode(b).decode()}"
            return ""
        if s.startswith('data:image'):
            return s
        # 原始 base64 或文件路径兜底
        try:
            base64.b64decode(s)
            return f"data:image/jpeg;base64,{s}"
        except Exception:
            if os.path.isfile(s):
                with open(s, 'rb') as f:
                    b = f.read()
                return f"data:image/jpeg;base64,{base64.b64encode(b).decode()}"
            return ""
    except Exception as e:
        logger.warning(f"_process_image error: {e}")
        return ""


class WebHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args):
        logger.info("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), fmt % args)

    def do_GET(self):
        try:
            path = self.path.split('?', 1)[0]
            if path == '/':
                self._serve_main()
            elif path == '/data':
                self._serve_data()
            elif path == '/health':
                self._serve_health()
            else:
                body = b'Not Found'
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except BrokenPipeError:
            self.close_connection = True
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode('utf-8')
            try:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except BrokenPipeError:
                self.close_connection = True

    def _serve_main(self):
        html = """<!doctype html>
<html><head><meta charset='utf-8'><title>QZone UDS Emulator</title>
<style>
body{font-family:Arial,Helvetica,sans-serif;margin:20px}
.post{border:1px solid #ddd;margin:10px 0;padding:12px;border-radius:6px}
.post-images{display:flex;gap:8px;flex-wrap:wrap}
.post-image{max-width:200px;max-height:200px;border-radius:4px}
.btn{padding:6px 10px;background:#0b73ec;color:#fff;border:none;border-radius:4px;cursor:pointer}
</style></head>
<body>
<h2>QZone UDS 服务模拟器</h2>
<p>Socket: %%SOCK%%</p>
<p>Web: http://localhost:%%PORT%%</p>
<button class='btn' onclick='loadData()'>刷新</button>
<div id='posts'></div>
<script>
async function loadData(){
  const r = await fetch('/data');
  const arr = await r.json();
  const root = document.getElementById('posts');
  root.innerHTML = arr.map(p => `
    <div class='post'>
      <div><b>#${p.id}</b> @ ${p.timestamp} &nbsp; <span>状态: ${p.status}</span></div>
      <div>${p.text || ''}</div>
      ${(p.images && p.images.length) ? `<div class='post-images'>${p.images.map(i=>`<img class='post-image' src='${i}'>`).join('')}</div>`:''}
    </div>`
  ).join('');
}
loadData();setInterval(loadData, 5000);
</script>
</body></html>"""
        html = html.replace("%%SOCK%%", self.server.sock_path).replace("%%PORT%%", str(self.server.server_port))
        data = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_health(self):
        data = b'ok'
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_data(self):
        # 从 server.emu 读取快照
        with self.server.data_lock:
            arr = list(self.server.data)
        body = json.dumps(arr, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class UDSHttpServer(http.server.ThreadingHTTPServer):
    # 仅用于挂载共享状态
    daemon_threads = True
    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        self.data: List[Dict[str, Any]] = []
        self.data_lock = threading.Lock()
        self.sock_path = ""


class UDSQzoneEmu:
    def __init__(self, sock_path: str, web_port: int):
        self.sock_path = sock_path
        self.web_port = web_port
        self._stop = threading.Event()
        self.web: UDSHttpServer | None = None
        self.data: List[Dict[str, Any]] = []
        self.data_lock = threading.Lock()

    def start(self):
        # 1) 启动 Web
        self.web = UDSHttpServer(("", self.web_port), WebHandler)
        self.web.data = self.data
        self.web.data_lock = self.data_lock
        self.web.sock_path = self.sock_path
        threading.Thread(target=self.web.serve_forever, daemon=True).start()
        logger.info(f"Web 界面: http://localhost:{self.web_port}")

        # 2) 启动 UDS 监听
        try:
            if os.path.exists(self.sock_path):
                os.unlink(self.sock_path)
        except Exception:
            pass

        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.sock_path)
        self.server.listen(16)
        logger.info(f"UDS 监听: {self.sock_path}")

        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.server.accept()
            except OSError:
                if self._stop.is_set():
                    break
                continue
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn: socket.socket):
        try:
            chunks: List[bytes] = []
            while True:
                buf = conn.recv(4096)
                if not buf:
                    break
                chunks.append(buf)
            raw = b"".join(chunks).decode('utf-8', errors='ignore')
            if not raw.strip():
                try:
                    conn.sendall(b"failed")
                finally:
                    conn.close()
                return
            try:
                payload = json.loads(raw)
            except Exception as e:
                logger.warning(f"JSON 解析失败: {e}")
                try:
                    conn.sendall(b"failed")
                finally:
                    conn.close()
                return

            text = str(payload.get('text') or '')
            images = payload.get('image') or []
            cookies = payload.get('cookies') or {}
            processed = [_process_image(x) for x in images]
            item = {
                'id': len(self.data) + 1,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'text': text,
                'images': [i for i in processed if i],
                'image_count': len([i for i in processed if i]),
                'cookies_keys': list(cookies.keys()),
                'status': 'success',
            }
            with self.data_lock:
                self.data.append(item)
                if len(self.data) > 100:
                    self.data[:] = self.data[-100:]
            try:
                conn.sendall(b"success")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"处理连接异常: {e}")
            try:
                conn.sendall(b"failed")
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        try:
            self.server.close()
        except Exception:
            pass
        if self.web:
            try:
                self.web.shutdown(); self.web.server_close()
            except Exception:
                pass
        try:
            if os.path.exists(self.sock_path):
                os.unlink(self.sock_path)
        except Exception:
            pass
        logger.info("Emulator 停止")


def main():
    parser = argparse.ArgumentParser(description="QZone UDS Emulator")
    parser.add_argument("--sock", default=os.environ.get("QZONE_UDS_PATH", "./qzone_uds.sock"), help="UDS 路径")
    parser.add_argument("--port", type=int, default=8086, help="Web 端口")
    args = parser.parse_args()

    emu = UDSQzoneEmu(args.sock, args.port)
    emu.start()
    logger.info("按 Ctrl+C 退出。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        emu.stop()


if __name__ == "__main__":
    main()
