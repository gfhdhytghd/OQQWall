"""
QZone Service Emulator
模拟qzone-serv-pipe服务，用于测试和开发
"""

import os
import json
import time
import logging
import threading
import base64
from datetime import datetime
import http.server
import socketserver
import webbrowser

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class QzoneEmulator:
    def __init__(self, fifo_in_path="qzone_in_fifo", fifo_out_path="qzone_out_fifo"):
        self.fifo_in_path = fifo_in_path
        self.fifo_out_path = fifo_out_path
        self.web_port = 8080
        self.web_data = []
        self.web_lock = threading.Lock()
        self.running = True
        
        # 创建FIFO文件
        self._create_fifos()
        
        # 启动Web服务器
        self._start_web_server()
        
        # 启动FIFO处理线程
        self.fifo_thread = threading.Thread(target=self._fifo_worker, daemon=True)
        self.fifo_thread.start()
        
    def _create_fifos(self):
        """创建FIFO文件"""
        for fifo_path in [self.fifo_in_path, self.fifo_out_path]:
            if not os.path.exists(fifo_path):
                os.mkfifo(fifo_path)
                logger.info(f"创建FIFO文件: {fifo_path}")
            else:
                logger.info(f"FIFO文件已存在: {fifo_path}")
    
    def _start_web_server(self):
        class QzoneHandler(http.server.SimpleHTTPRequestHandler):
            protocol_version = "HTTP/1.1"  # 可选

            def log_message(self, format, *args):
                logger.info("%s - - [%s] %s",
                            self.client_address[0],
                            self.log_date_time_string(),
                            format % args)

            def do_GET(self):
                try:
                    path = self.path.split('?', 1)[0]
                    if path == '/':
                        self._serve_main_page()
                    elif path == '/data':
                        self._serve_data()
                    else:
                        # 明确返回 404（避免 SimpleHTTPRequestHandler 去找磁盘文件）
                        self.send_response(404)
                        self.send_header('Content-Type', 'text/plain; charset=utf-8')
                        self.end_headers()
                        self.wfile.write(b'Not Found')
                except Exception as e:
                    logger.exception("Handler error")
                    body = json.dumps({"error": str(e)}).encode('utf-8')
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def _serve_main_page(self):
                html_content = self._generate_html().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(html_content)))
                self.end_headers()
                self.wfile.write(html_content)

            def _serve_data(self):
                # ✅ 这里改成 server.emulator
                with self.server.emulator.web_lock:
                    data = self.server.emulator.web_data.copy()
                body = json.dumps(data, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _generate_html(self):
                return f"""<!DOCTYPE html>
    <html lang="zh-CN">
    <head>
    <meta charset="UTF-8"><title>QZone服务模拟器</title>
    <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
    .post {{ border: 1px solid #ddd; margin: 10px 0; padding: 15px; border-radius: 5px; }}
    .post-header {{ font-weight: bold; margin-bottom: 10px; }}
    .post-content {{ margin-bottom: 10px; }}
    .post-images {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .post-image {{ max-width: 200px; max-height: 200px; border-radius: 5px; }}
    .refresh-btn {{ padding: 10px 20px; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }}
    </style>
    </head>
    <body>
    <h1>🎯 QZone服务模拟器</h1>
    <p><strong>FIFO输入:</strong> {self.server.emulator.fifo_in_path}</p>
    <p><strong>FIFO输出:</strong> {self.server.emulator.fifo_out_path}</p>
    <p><strong>Web端口:</strong> {self.server.emulator.web_port}</p>

    <button class="refresh-btn" onclick="loadData()">🔄 刷新数据</button>
    <div id="posts"></div>

    <script>
    function loadData() {{
        fetch('/data')
        .then(r => r.json())
        .then(data => {{
            const posts = document.getElementById('posts');
            if (!data.length) {{
            posts.innerHTML = '<p>暂无数据，等待从FIFO接收数据...</p>';
            return;
            }}
            posts.innerHTML = data.map(post => `
            <div class="post">
                <div class="post-header">📝 说说 #${{post.id}} - ${{post.timestamp}}</div>
                <div class="post-content">${{post.text || '无文本内容'}}</div>
                ${{post.images && post.images.length ? `
                <div class="post-images">
                    ${{post.images.map(img => `<img src="${{img}}" alt="图片" class="post-image">`).join('')}}
                </div>` : ''}}
                <div>状态: ${{post.status}} | 图片数量: ${{post.image_count || 0}}</div>
            </div>
            `).join('');
        }})
        .catch(e => {{
            console.error(e);
            document.getElementById('posts').innerHTML = '<p>加载数据失败</p>';
        }});
    }}
    loadData();
    setInterval(loadData, 5000);
    </script>
    </body>
    </html>"""

        
        # 线程版 HTTPServer，并把 emulator 挂到 server 上
        class QzoneHTTPServer(http.server.ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        try:
            self.httpd = QzoneHTTPServer(("", self.web_port), QzoneHandler)
            self.httpd.emulator = self
            logger.info(f"Web服务器启动在端口 {self.web_port}")
            logger.info(f"访问地址: http://localhost:{self.web_port}")
            
            # 在新线程中运行服务器
            server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            server_thread.start()
            
            # 等待服务器启动
            time.sleep(1)
            
            # 尝试打开浏览器
            try:
                webbrowser.open(f'http://localhost:{self.web_port}')
            except:
                pass
                
        except Exception as e:
            logger.error(f"Web服务器启动失败: {e}")
            self.web_port = None
    
    def process_image(self, image_str: str) -> str:
        """处理图片数据，返回可显示的URL或base64数据"""
        try:
            if image_str.startswith('http://') or image_str.startswith('https://'):
                return image_str
            elif image_str.startswith('file://'):
                file_path = image_str[7:]
                if os.path.isfile(file_path):
                    with open(file_path, 'rb') as f:
                        data = f.read()
                    return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
            elif image_str.startswith('data:image'):
                return image_str
            else:
                try:
                    data = base64.b64decode(image_str)
                    return f"data:image/jpeg;base64,{image_str}"
                except:
                    if os.path.isfile(image_str):
                        with open(image_str, 'rb') as f:
                            data = f.read()
                        return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
        except Exception as e:
            logger.error(f"处理图片失败: {e}")
        return ""
    
    def process_submission(self, data: dict) -> dict:
        """处理提交的数据"""
        try:
            text = data.get('text', '')
            images = data.get('image', [])
            cookies = data.get('cookies', {})
            
            # 处理图片
            processed_images = []
            for img in images:
                processed_img = self.process_image(img)
                if processed_img:
                    processed_images.append(processed_img)
            
            # 创建响应数据
            response_data = {
                'id': len(self.web_data) + 1,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'text': text,
                'images': processed_images,
                'image_count': len(processed_images),
                'status': 'success',
                'original_data': {
                    'text_length': len(text),
                    'image_count': len(images),
                    'cookies_keys': list(cookies.keys()) if cookies else []
                }
            }
            
            # 添加到Web数据
            with self.web_lock:
                self.web_data.append(response_data)
                if len(self.web_data) > 50:
                    self.web_data = self.web_data[-50:]
            
            logger.info(f"处理数据成功: ID={response_data['id']}, 文本长度={len(text)}, 图片数量={len(processed_images)}")
            return response_data
            
        except Exception as e:
            logger.error(f"处理数据失败: {e}")
            return {
                'id': len(self.web_data) + 1,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'text': '处理失败',
                'images': [],
                'image_count': 0,
                'status': 'failed',
                'error': str(e)
            }
    
    def _fifo_worker(self):
        """FIFO处理工作线程"""
        logger.info("FIFO处理线程启动")
        logger.info(f"FIFO输入: {self.fifo_in_path}")
        logger.info(f"FIFO输出: {self.fifo_out_path}")
        
        while self.running:
            try:
                logger.info("等待从FIFO读取数据...")
                
                # 使用非阻塞方式读取FIFO，支持优雅退出
                try:
                    # 设置超时读取，这样可以定期检查running状态
                    import select
                    with open(self.fifo_in_path, 'r', encoding='utf-8') as fifo:
                        # 使用select检查是否有数据可读，超时1秒
                        ready, _, _ = select.select([fifo], [], [], 1.0)
                        if not ready:
                            # 超时，检查是否需要退出
                            continue
                        
                        data = ''
                        while self.running:
                            line = fifo.readline()
                            if not line:
                                break
                            data += line
                            
                            # 检查是否读取完整
                            if data.strip() and not data.endswith('\n'):
                                break
                except (OSError, IOError) as e:
                    if not self.running:
                        break
                    logger.error(f"FIFO读取错误: {e}")
                    time.sleep(1)
                    continue
                
                if not data.strip() or not self.running:
                    continue
                
                logger.info(f"接收到数据: {data[:200]}...")
                
                # 解析JSON数据
                try:
                    submission_data = json.loads(data)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON解析失败: {e}")
                    self._write_response('failed')
                    continue
                
                # 处理数据
                result = self.process_submission(submission_data)
                
                # 写入响应
                if result['status'] == 'success':
                    self._write_response('success')
                else:
                    self._write_response('failed')
                
                logger.info("数据处理完成")
                
            except Exception as e:
                if not self.running:
                    break
                logger.error(f"FIFO处理错误: {e}")
                self._write_response('failed')
                time.sleep(1)
        
        logger.info("FIFO处理线程已退出")
    
    def run(self):
        """运行模拟器"""
        logger.info("QZone服务模拟器启动")
        logger.info(f"Web界面: http://localhost:{self.web_port}")
        
        try:
            # 保持主线程运行
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在退出...")
            self.stop()
    
    def stop(self):
        """停止模拟器"""
        logger.info("正在停止模拟器...")
        self.running = False
        
        # 关闭Web服务器
        if hasattr(self, 'httpd') and self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
                logger.info("Web服务器已关闭")
            except Exception as e:
                logger.error(f"关闭Web服务器时出错: {e}")
        
        # 等待FIFO线程结束
        if hasattr(self, 'fifo_thread') and self.fifo_thread.is_alive():
            logger.info("等待FIFO处理线程结束...")
            self.fifo_thread.join(timeout=5)
            if self.fifo_thread.is_alive():
                logger.warning("FIFO处理线程未能及时结束")
            else:
                logger.info("FIFO处理线程已结束")
        
        logger.info("模拟器已完全停止")
    
    def _write_response(self, response: str):
        """写入响应到输出FIFO"""
        try:
            with open(self.fifo_out_path, 'w', encoding='utf-8') as fifo:
                fifo.write(response)
                fifo.flush()
            logger.info(f"写入响应: {response}")
        except Exception as e:
            logger.error(f"写入响应失败: {e}")

def main():
    """主函数"""
    print("🎯 QZone服务模拟器")
    print("=" * 50)
    
    # 创建模拟器实例
    emulator = QzoneEmulator()
    
    try:
        # 运行模拟器
        emulator.run()
    except KeyboardInterrupt:
        print("\n👋 收到中断信号，正在停止模拟器...")
        emulator.stop()
        print("模拟器已完全停止")
    except Exception as e:
        print(f"❌ 运行错误: {e}")
        logger.error(f"主程序错误: {e}")
        emulator.stop()

if __name__ == "__main__":
    main()
