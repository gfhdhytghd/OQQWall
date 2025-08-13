#!/usr/bin/env python3
"""
NapCat HTTP POST 录制器
用于录制来自napcat的HTTP POST请求，保存为文件供后续重放
"""

import json
import time
import logging
import threading
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import signal
import sys

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class NapCatRecorder:
    def __init__(self, port=8083, recordings_dir="recordings"):
        self.port = port
        self.recordings_dir = recordings_dir
        self.running = True
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.request_count = 0
        
        # 创建录制目录
        if not os.path.exists(self.recordings_dir):
            os.makedirs(self.recordings_dir)
        
        # 会话录制文件
        self.session_file = os.path.join(self.recordings_dir, f"session_{self.session_id}.json")
        self.session_data = {
            "session_id": self.session_id,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "requests": []
        }
        
        logger.info(f"录制器初始化 - 端口: {self.port}, 录制目录: {self.recordings_dir}")
        logger.info(f"会话文件: {self.session_file}")
    
    def save_session(self):
        """保存会话数据到文件"""
        try:
            self.session_data["end_time"] = datetime.now().isoformat()
            with open(self.session_file, 'w', encoding='utf-8') as f:
                json.dump(self.session_data, f, ensure_ascii=False, indent=2)
            logger.info(f"会话数据已保存: {self.session_file}")
        except Exception as e:
            logger.error(f"保存会话数据失败: {e}")
    
    def record_request(self, method, path, headers, body):
        """录制HTTP请求"""
        self.request_count += 1
        
        request_data = {
            "request_id": self.request_count,
            "timestamp": datetime.now().isoformat(),
            "method": method,
            "path": path,
            "headers": dict(headers),
            "body": body,
            "body_parsed": None
        }
        
        # 尝试解析JSON body
        if body:
            try:
                request_data["body_parsed"] = json.loads(body)
            except json.JSONDecodeError:
                logger.warning(f"请求 #{self.request_count} body不是有效JSON")
        
        self.session_data["requests"].append(request_data)
        
        # 实时保存单个请求
        single_request_file = os.path.join(
            self.recordings_dir, 
            f"request_{self.session_id}_{self.request_count:04d}.json"
        )
        try:
            with open(single_request_file, 'w', encoding='utf-8') as f:
                json.dump(request_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存单个请求失败: {e}")
        
        logger.info(f"录制请求 #{self.request_count}: {method} {path}")
        if request_data["body_parsed"]:
            # 打印部分消息内容用于调试
            parsed = request_data["body_parsed"]
            if "message" in parsed:
                msg_preview = str(parsed["message"])[:100]
                logger.info(f"  消息预览: {msg_preview}...")
            if "user_id" in parsed:
                logger.info(f"  用户ID: {parsed['user_id']}")
            if "group_id" in parsed:
                logger.info(f"  群组ID: {parsed['group_id']}")
        
        return request_data

class RecorderHTTPHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""
    
    def log_message(self, format, *args):
        """重写日志方法，使用我们的logger"""
        logger.debug(format % args)
    
    def do_POST(self):
        """处理POST请求"""
        try:
            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
            
            # 录制请求
            request_data = self.server.recorder.record_request(
                method="POST",
                path=self.path,
                headers=self.headers,
                body=body
            )
            
            # 发送响应
            response_data = {
                "status": "recorded",
                "request_id": request_data["request_id"],
                "timestamp": request_data["timestamp"]
            }
            
            response_body = json.dumps(response_data, ensure_ascii=False).encode('utf-8')
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            
        except Exception as e:
            logger.error(f"处理POST请求失败: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            error_response = json.dumps({"error": str(e)}).encode('utf-8')
            self.wfile.write(error_response)
    
    def do_GET(self):
        """处理GET请求 - 显示录制状态"""
        try:
            if self.path == "/status":
                status_data = {
                    "status": "recording",
                    "session_id": self.server.recorder.session_id,
                    "request_count": self.server.recorder.request_count,
                    "start_time": self.server.recorder.session_data["start_time"],
                    "port": self.server.recorder.port
                }
                response_body = json.dumps(status_data, ensure_ascii=False).encode('utf-8')
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)
            else:
                # 显示简单的状态页面
                html = f"""
                <!DOCTYPE html>
                <html>
                <head><title>NapCat录制器</title></head>
                <body>
                    <h1>🎙️ NapCat HTTP POST 录制器</h1>
                    <p><strong>状态:</strong> 正在录制</p>
                    <p><strong>会话ID:</strong> {self.server.recorder.session_id}</p>
                    <p><strong>已录制请求:</strong> {self.server.recorder.request_count}</p>
                    <p><strong>开始时间:</strong> {self.server.recorder.session_data["start_time"]}</p>
                    <p><strong>端口:</strong> {self.server.recorder.port}</p>
                    <hr>
                    <p>请将napcat的HTTP POST目标设置为: <code>http://localhost:{self.server.recorder.port}</code></p>
                </body>
                </html>
                """.encode('utf-8')
                
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                
        except Exception as e:
            logger.error(f"处理GET请求失败: {e}")
            self.send_response(500)
            self.end_headers()

def signal_handler(signum, frame):
    """信号处理器"""
    logger.info("收到退出信号，正在保存数据...")
    sys.exit(0)

def main():
    """主函数"""
    print("🎙️ NapCat HTTP POST 录制器")
    print("=" * 50)
    
    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description='NapCat HTTP POST 录制器')
    parser.add_argument('--port', type=int, default=8083, help='监听端口 (默认: 8083)')
    parser.add_argument('--dir', type=str, default='recordings', help='录制文件目录 (默认: recordings)')
    args = parser.parse_args()
    
    # 创建录制器
    recorder = NapCatRecorder(port=args.port, recordings_dir=args.dir)
    
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # 创建HTTP服务器
        httpd = HTTPServer(('', args.port), RecorderHTTPHandler)
        httpd.recorder = recorder
        
        logger.info(f"HTTP录制服务器启动在端口 {args.port}")
        logger.info(f"Web状态页面: http://localhost:{args.port}")
        logger.info(f"录制文件保存在: {os.path.abspath(args.dir)}")
        logger.info("请将napcat的HTTP POST目标设置为此服务器")
        logger.info("按 Ctrl+C 停止录制")
        print()
        
        # 运行服务器
        httpd.serve_forever()
        
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止录制...")
    except Exception as e:
        logger.error(f"录制器运行错误: {e}")
    finally:
        # 保存会话数据
        recorder.save_session()
        logger.info("录制器已停止")
        print(f"📁 录制数据已保存到: {os.path.abspath(recorder.recordings_dir)}")
        print(f"📄 会话文件: {recorder.session_file}")

if __name__ == "__main__":
    main()
