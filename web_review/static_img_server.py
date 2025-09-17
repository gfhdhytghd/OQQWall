#!/usr/bin/env python3
import http.server
import socketserver
from pathlib import Path
import sys
import argparse
import mimetypes

ROOT = Path(__file__).resolve().parent.parent  # project root
CACHE_DIR = ROOT / 'cache'

def sniff_mime(p: Path) -> str:
    try:
        with open(p, 'rb') as f:
            header = f.read(16)
            if header.startswith(b'\xff\xd8\xff'):
                return 'image/jpeg'
            if header.startswith(b'\x89PNG\r\n\x1a\n'):
                return 'image/png'
            if header.startswith((b'GIF87a', b'GIF89a')):
                return 'image/gif'
            if header.startswith(b'BM'):
                return 'image/bmp'
            if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
                return 'image/webp'
    except Exception:
        pass
    return mimetypes.guess_type(str(p))[0] or 'application/octet-stream'

class StaticImageHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Expected paths:
        #   /i/prepost/<tag>/<file>
        #   /i/picture/<tag>/<file>
        p = self.path
        if not p.startswith('/i/'):
            self.send_error(404)
            return
        parts = Path(p).parts  # e.g., ('/', 'i', 'prepost', '123', 'file.jpg')
        if len(parts) < 5:
            self.send_error(404)
            return
        _, i, kind, tag, *rest = parts
        if i != 'i' or kind not in ('prepost', 'picture'):
            self.send_error(404)
            return
        if not tag.isdigit() or not rest:
            self.send_error(404)
            return
        rel = Path('cache') / kind / tag / Path(*rest)
        fs_path = (ROOT / rel).resolve()
        # Ensure within project root
        if not str(fs_path).startswith(str(ROOT.resolve())):
            self.send_error(403)
            return
        if not fs_path.is_file():
            self.send_error(404)
            return
        try:
            data = fs_path.read_bytes()
            mime = sniff_mime(fs_path)
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            # Public caching OK for static images; adjust if sensitive
            self.send_header('Cache-Control', 'public, max-age=86400')
            # Allow cross-origin embedding
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_error(500)

def main():
    ap = argparse.ArgumentParser(description='Static image server for OQQWall')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=10924)
    args = ap.parse_args()
    with socketserver.ThreadingTCPServer((args.host, args.port), StaticImageHandler) as httpd:
        sa = httpd.socket.getsockname()
        print(f"[img-server] Serving images at http://{sa[0]}:{sa[1]}/i/<prepost|picture>/<tag>/<file>")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()

if __name__ == '__main__':
    sys.exit(main())

