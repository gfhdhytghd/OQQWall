#!/usr/bin/env python3
"""
NapCat HTTP POST 重放器
用于重放录制的napcat HTTP POST请求
"""

import json
import time
import logging
import requests
import os
import glob
from datetime import datetime
import threading

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class NapCatReplayer:
    def __init__(self, recordings_dir="recordings", target_url=None):
        self.recordings_dir = recordings_dir
        self.target_url = target_url
        self.sessions = []
        self.current_session = None
        self.current_requests = []
        
        logger.info(f"重放器初始化 - 录制目录: {self.recordings_dir}")
        self.load_sessions()
    
    def load_sessions(self):
        """加载所有录制会话"""
        if not os.path.exists(self.recordings_dir):
            logger.warning(f"录制目录不存在: {self.recordings_dir}")
            return
        
        session_files = glob.glob(os.path.join(self.recordings_dir, "session_*.json"))
        self.sessions = []
        
        for session_file in sorted(session_files):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                self.sessions.append({
                    "file": session_file,
                    "data": session_data
                })
            except Exception as e:
                logger.error(f"加载会话文件失败 {session_file}: {e}")
        
        logger.info(f"加载了 {len(self.sessions)} 个录制会话")
    
    def list_sessions(self):
        """列出所有可用会话"""
        if not self.sessions:
            print("❌ 没有找到录制会话")
            return
        
        print("📋 可用的录制会话:")
        print("-" * 80)
        for i, session in enumerate(self.sessions):
            data = session["data"]
            print(f"{i+1:2d}. 会话ID: {data['session_id']}")
            print(f"    开始时间: {data['start_time']}")
            print(f"    请求数量: {len(data.get('requests', []))}")
            print(f"    文件: {os.path.basename(session['file'])}")
            print()
    
    def select_session(self, session_index=None):
        """选择要重放的会话"""
        if not self.sessions:
            logger.error("没有可用的会话")
            return False
        
        if session_index is None:
            self.list_sessions()
            try:
                choice = input("请选择会话编号 (1-{}): ".format(len(self.sessions)))
                session_index = int(choice) - 1
            except (ValueError, KeyboardInterrupt):
                logger.info("取消选择")
                return False
        
        if 0 <= session_index < len(self.sessions):
            self.current_session = self.sessions[session_index]
            self.current_requests = self.current_session["data"].get("requests", [])
            session_id = self.current_session["data"]["session_id"]
            logger.info(f"选择会话: {session_id} ({len(self.current_requests)} 个请求)")
            return True
        else:
            logger.error("无效的会话编号")
            return False
    
    def list_requests(self):
        """列出当前会话的所有请求"""
        if not self.current_requests:
            print("❌ 当前会话没有请求")
            return
        
        print(f"📋 会话 {self.current_session['data']['session_id']} 的请求:")
        print("-" * 100)
        for i, req in enumerate(self.current_requests):
            print(f"{i+1:3d}. [{req['timestamp']}] {req['method']} {req['path']}")
            
            # 显示消息预览
            if req.get('body_parsed'):
                parsed = req['body_parsed']
                preview_items = []
                
                if 'message' in parsed:
                    msg = str(parsed['message'])[:50]
                    preview_items.append(f"消息: {msg}...")
                
                if 'user_id' in parsed:
                    preview_items.append(f"用户: {parsed['user_id']}")
                
                if 'group_id' in parsed:
                    preview_items.append(f"群组: {parsed['group_id']}")
                
                if 'post_type' in parsed:
                    preview_items.append(f"类型: {parsed['post_type']}")
                
                if preview_items:
                    print(f"     {' | '.join(preview_items)}")
            print()
    
    def replay_request(self, request_data, target_url=None):
        """重放单个请求"""
        if target_url is None:
            target_url = self.target_url
        
        if not target_url:
            logger.error("没有指定目标URL")
            return False
        
        try:
            # 准备请求
            method = request_data.get('method', 'POST')
            path = request_data.get('path', '/')
            headers = request_data.get('headers', {})
            body = request_data.get('body', '')
            
            # 构建完整URL
            full_url = target_url.rstrip('/') + path
            
            # 清理headers，移除可能有问题的headers
            clean_headers = {}
            for key, value in headers.items():
                # 跳过一些可能引起问题的headers
                if key.lower() not in ['host', 'content-length', 'connection']:
                    clean_headers[key] = value
            
            # 发送请求
            logger.info(f"重放请求: {method} {full_url}")
            
            if method.upper() == 'POST':
                response = requests.post(
                    full_url, 
                    data=body, 
                    headers=clean_headers,
                    timeout=10
                )
            else:
                response = requests.get(
                    full_url,
                    headers=clean_headers,
                    timeout=10
                )
            
            logger.info(f"响应状态: {response.status_code}")
            if response.text:
                logger.info(f"响应内容: {response.text[:200]}...")
            
            return True
            
        except Exception as e:
            logger.error(f"重放请求失败: {e}")
            return False
    
    def replay_session(self, target_url=None, delay=1.0):
        """重放整个会话"""
        if not self.current_requests:
            logger.error("没有选择会话或会话为空")
            return
        
        if target_url is None:
            target_url = self.target_url
        
        logger.info(f"开始重放会话，共 {len(self.current_requests)} 个请求")
        logger.info(f"目标URL: {target_url}")
        logger.info(f"请求间隔: {delay} 秒")
        
        success_count = 0
        
        for i, request_data in enumerate(self.current_requests):
            print(f"\n[{i+1}/{len(self.current_requests)}] 重放请求...")
            
            if self.replay_request(request_data, target_url):
                success_count += 1
            
            # 延迟
            if i < len(self.current_requests) - 1:  # 最后一个请求不需要延迟
                time.sleep(delay)
        
        logger.info(f"重放完成: {success_count}/{len(self.current_requests)} 成功")
    
    def replay_single_request(self, request_index, target_url=None):
        """重放单个指定的请求"""
        if not self.current_requests:
            logger.error("没有选择会话或会话为空")
            return False
        
        if not (0 <= request_index < len(self.current_requests)):
            logger.error(f"无效的请求索引: {request_index}")
            return False
        
        request_data = self.current_requests[request_index]
        logger.info(f"重放请求 #{request_index + 1}")
        return self.replay_request(request_data, target_url)

def interactive_mode():
    """交互式模式"""
    print("🎮 NapCat HTTP POST 重放器 - 交互模式")
    print("=" * 60)
    
    # 初始化重放器
    replayer = NapCatReplayer()
    
    if not replayer.sessions:
        print("❌ 没有找到录制会话，请先使用 napcat_recorder.py 录制")
        return
    
    # 选择会话
    if not replayer.select_session():
        return
    
    # 设置目标URL
    while True:
        target_url = input("\n请输入目标URL (例如: http://localhost:8082): ").strip()
        if target_url:
            replayer.target_url = target_url
            break
        print("❌ 目标URL不能为空")
    
    # 主循环
    while True:
        print("\n" + "=" * 60)
        print("🎮 重放控制台")
        print("1. 列出所有请求")
        print("2. 重放单个请求")
        print("3. 重放整个会话")
        print("4. 选择其他会话")
        print("5. 按Enter键快速重放 (重放所有请求)")
        print("0. 退出")
        print("-" * 60)
        
        try:
            choice = input("请选择操作 (直接按Enter快速重放): ").strip()
            
            if choice == "" or choice == "5":
                # 快速重放模式
                print("\n🚀 快速重放模式 - 按Enter重放所有请求，输入'q'退出")
                while True:
                    user_input = input("按Enter重放 (q退出): ").strip().lower()
                    if user_input == 'q':
                        break
                    elif user_input == "":
                        print("\n🎬 开始重放...")
                        replayer.replay_session(delay=0.5)
                        print("✅ 重放完成")
                    else:
                        print("❌ 无效输入，请按Enter重放或输入'q'退出")
            
            elif choice == "1":
                replayer.list_requests()
            
            elif choice == "2":
                replayer.list_requests()
                try:
                    req_index = int(input("请输入要重放的请求编号: ")) - 1
                    replayer.replay_single_request(req_index)
                except ValueError:
                    print("❌ 无效的请求编号")
            
            elif choice == "3":
                try:
                    delay = float(input("请输入请求间隔秒数 (默认1.0): ") or "1.0")
                    replayer.replay_session(delay=delay)
                except ValueError:
                    print("❌ 无效的延迟时间")
            
            elif choice == "4":
                if replayer.select_session():
                    print("✅ 会话切换成功")
            
            elif choice == "0":
                break
            
            else:
                print("❌ 无效选择")
                
        except KeyboardInterrupt:
            print("\n👋 退出重放器")
            break
        except Exception as e:
            logger.error(f"操作失败: {e}")

def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description='NapCat HTTP POST 重放器')
    parser.add_argument('--dir', type=str, default='recordings', help='录制文件目录 (默认: recordings)')
    parser.add_argument('--target', type=str, help='目标URL (例如: http://localhost:8082)')
    parser.add_argument('--session', type=int, help='会话编号 (从1开始)')
    parser.add_argument('--request', type=int, help='请求编号 (从1开始，仅重放单个请求)')
    parser.add_argument('--delay', type=float, default=1.0, help='请求间隔秒数 (默认: 1.0)')
    parser.add_argument('--interactive', action='store_true', help='启动交互模式')
    
    args = parser.parse_args()
    
    if args.interactive:
        interactive_mode()
        return
    
    # 命令行模式
    replayer = NapCatReplayer(recordings_dir=args.dir, target_url=args.target)
    
    if not replayer.sessions:
        print("❌ 没有找到录制会话")
        return
    
    # 选择会话
    if args.session:
        session_index = args.session - 1
        if not replayer.select_session(session_index):
            return
    else:
        if not replayer.select_session():
            return
    
    # 设置目标URL
    if not args.target:
        target_url = input("请输入目标URL: ").strip()
        if not target_url:
            print("❌ 目标URL不能为空")
            return
        replayer.target_url = target_url
    
    # 重放
    if args.request:
        # 重放单个请求
        request_index = args.request - 1
        replayer.replay_single_request(request_index)
    else:
        # 重放整个会话
        replayer.replay_session(delay=args.delay)

if __name__ == "__main__":
    main()
