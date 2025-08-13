#!/usr/bin/env python3
"""
NapCat 一键重放控制器
简化版控制器，实现"按Enter发送消息"的功能
"""

import json
import os
import glob
import time
import logging
import requests
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class SimpleNapCatController:
    def __init__(self, recordings_dir="recordings", config_file="controller_config.json"):
        self.recordings_dir = recordings_dir
        self.config_file = config_file
        self.config = self.load_config()
        self.current_session = None
        self.current_requests = []
        
        self.load_default_session()
    
    def load_config(self):
        """加载配置文件"""
        default_config = {
            "target_url": "http://localhost:8082",
            "default_session": None,
            "replay_delay": 0.5,
            "auto_select_latest": True
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    default_config.update(config)
            except Exception as e:
                logger.warning(f"加载配置文件失败: {e}，使用默认配置")
        
        return default_config
    
    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
    
    def get_sessions(self):
        """获取所有录制会话"""
        if not os.path.exists(self.recordings_dir):
            return []
        
        session_files = glob.glob(os.path.join(self.recordings_dir, "session_*.json"))
        sessions = []
        
        for session_file in sorted(session_files, reverse=True):  # 最新的在前
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                sessions.append({
                    "file": session_file,
                    "data": session_data,
                    "filename": os.path.basename(session_file)
                })
            except Exception as e:
                logger.error(f"加载会话文件失败 {session_file}: {e}")
        
        return sessions
    
    def load_default_session(self):
        """加载默认会话"""
        sessions = self.get_sessions()
        
        if not sessions:
            logger.warning("没有找到录制会话")
            return False
        
        # 优先使用配置中指定的会话
        if self.config.get("default_session"):
            for session in sessions:
                if session["data"]["session_id"] == self.config["default_session"]:
                    self.current_session = session
                    self.current_requests = session["data"].get("requests", [])
                    logger.info(f"加载配置指定的会话: {session['data']['session_id']}")
                    return True
        
        # 如果启用自动选择最新会话
        if self.config.get("auto_select_latest", True):
            self.current_session = sessions[0]  # sessions已按时间倒序排列
            self.current_requests = self.current_session["data"].get("requests", [])
            logger.info(f"自动加载最新会话: {self.current_session['data']['session_id']}")
            return True
        
        return False
    
    def select_session_interactive(self):
        """交互式选择会话"""
        sessions = self.get_sessions()
        
        if not sessions:
            print("❌ 没有找到录制会话")
            return False
        
        print("\n📋 可用的录制会话:")
        print("-" * 80)
        for i, session in enumerate(sessions):
            data = session["data"]
            status = "✅ 当前" if self.current_session and session["file"] == self.current_session["file"] else "  "
            print(f"{status} {i+1:2d}. {data['session_id']}")
            print(f"      时间: {data['start_time']}")
            print(f"      请求: {len(data.get('requests', []))} 个")
            print()
        
        try:
            choice = input(f"选择会话 (1-{len(sessions)}, 回车保持当前): ").strip()
            if not choice:
                return True
            
            session_index = int(choice) - 1
            if 0 <= session_index < len(sessions):
                self.current_session = sessions[session_index]
                self.current_requests = self.current_session["data"].get("requests", [])
                self.config["default_session"] = self.current_session["data"]["session_id"]
                self.save_config()
                print(f"✅ 切换到会话: {self.current_session['data']['session_id']}")
                return True
            else:
                print("❌ 无效选择")
                return False
        except (ValueError, KeyboardInterrupt):
            return False
    
    def show_requests_preview(self, limit=5):
        """显示请求预览"""
        if not self.current_requests:
            print("❌ 当前会话没有请求")
            return
        
        print(f"\n📋 当前会话预览 ({len(self.current_requests)} 个请求):")
        print("-" * 60)
        
        for i, req in enumerate(self.current_requests[:limit]):
            timestamp = req['timestamp'][:19]  # 只显示到秒
            print(f"{i+1:2d}. [{timestamp}] {req['method']} {req['path']}")
            
            # 显示消息预览
            if req.get('body_parsed'):
                parsed = req['body_parsed']
                preview_parts = []
                
                if 'message' in parsed:
                    msg = str(parsed['message'])[:40]
                    preview_parts.append(f"消息: {msg}...")
                
                if 'user_id' in parsed:
                    preview_parts.append(f"用户: {parsed['user_id']}")
                
                if 'group_id' in parsed:
                    preview_parts.append(f"群组: {parsed['group_id']}")
                
                if 'post_type' in parsed:
                    preview_parts.append(f"类型: {parsed['post_type']}")
                
                if preview_parts:
                    print(f"     {' | '.join(preview_parts)}")
        
        if len(self.current_requests) > limit:
            print(f"     ... 还有 {len(self.current_requests) - limit} 个请求")
    
    def replay_all_requests(self, show_progress=True):
        """重放所有请求"""
        if not self.current_requests:
            print("❌ 没有可重放的请求")
            return False
        
        target_url = self.config["target_url"]
        delay = self.config["replay_delay"]
        
        if show_progress:
            print(f"🎬 开始重放 {len(self.current_requests)} 个请求到 {target_url}")
        
        success_count = 0
        
        for i, request_data in enumerate(self.current_requests):
            try:
                # 准备请求
                method = request_data.get('method', 'POST')
                path = request_data.get('path', '/')
                headers = request_data.get('headers', {})
                body = request_data.get('body', '')
                
                # 构建完整URL
                full_url = target_url.rstrip('/') + path
                
                # 清理headers
                clean_headers = {}
                for key, value in headers.items():
                    if key.lower() not in ['host', 'content-length', 'connection']:
                        clean_headers[key] = value
                
                # 发送请求
                if show_progress:
                    progress = f"[{i+1}/{len(self.current_requests)}]"
                    print(f"{progress} 发送中...", end=' ', flush=True)
                
                if method.upper() == 'POST':
                    response = requests.post(
                        full_url, 
                        data=body, 
                        headers=clean_headers,
                        timeout=5
                    )
                else:
                    response = requests.get(
                        full_url,
                        headers=clean_headers,
                        timeout=5
                    )
                
                if response.status_code == 200:
                    success_count += 1
                    if show_progress:
                        print("✅")
                else:
                    if show_progress:
                        print(f"❌ ({response.status_code})")
                
                # 延迟
                if i < len(self.current_requests) - 1:
                    time.sleep(delay)
                
            except Exception as e:
                if show_progress:
                    print(f"❌ ({str(e)[:20]}...)")
                logger.error(f"请求 {i+1} 失败: {e}")
        
        success_rate = (success_count / len(self.current_requests)) * 100
        print(f"✅ 重放完成: {success_count}/{len(self.current_requests)} 成功 ({success_rate:.1f}%)")
        return success_count == len(self.current_requests)
    
    def setup_wizard(self):
        """设置向导"""
        print("\n🔧 设置向导")
        print("-" * 40)
        
        # 设置目标URL
        current_url = self.config["target_url"]
        new_url = input(f"目标URL [{current_url}]: ").strip()
        if new_url:
            self.config["target_url"] = new_url
        
        # 设置延迟
        current_delay = self.config["replay_delay"]
        try:
            new_delay = input(f"请求间隔秒数 [{current_delay}]: ").strip()
            if new_delay:
                self.config["replay_delay"] = float(new_delay)
        except ValueError:
            print("❌ 无效的延迟时间，保持原值")
        
        # 保存配置
        self.save_config()
        print("✅ 配置已保存")
    
    def run_simple_mode(self):
        """运行简单模式 - 按Enter重放"""
        print("🎮 NapCat 一键重放控制器")
        print("=" * 50)
        
        if not self.current_session:
            print("❌ 没有可用的录制会话")
            return
        
        print(f"📁 当前会话: {self.current_session['data']['session_id']}")
        print(f"🎯 目标URL: {self.config['target_url']}")
        print(f"⏱️  延迟: {self.config['replay_delay']} 秒")
        
        self.show_requests_preview()
        
        print("\n" + "=" * 50)
        print("🚀 简单重放模式")
        print("   按 Enter   - 重放所有请求")
        print("   输入 's'   - 会话管理")
        print("   输入 'c'   - 配置设置")
        print("   输入 'q'   - 退出")
        print("-" * 50)
        
        while True:
            try:
                user_input = input("👉 ").strip().lower()
                
                if user_input == "":
                    # 按Enter重放
                    print()
                    self.replay_all_requests()
                    print()
                
                elif user_input == "s":
                    # 会话管理
                    if self.select_session_interactive():
                        print(f"📁 当前会话: {self.current_session['data']['session_id']}")
                        self.show_requests_preview()
                
                elif user_input == "c":
                    # 配置设置
                    self.setup_wizard()
                    print(f"🎯 目标URL: {self.config['target_url']}")
                    print(f"⏱️  延迟: {self.config['replay_delay']} 秒")
                
                elif user_input == "q":
                    print("👋 退出控制器")
                    break
                
                else:
                    print("❌ 无效命令")
                    print("   Enter=重放, s=会话, c=配置, q=退出")
                    
            except KeyboardInterrupt:
                print("\n👋 退出控制器")
                break
            except Exception as e:
                logger.error(f"操作失败: {e}")

def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description='NapCat 一键重放控制器')
    parser.add_argument('--dir', type=str, default='recordings', help='录制文件目录')
    parser.add_argument('--config', type=str, default='controller_config.json', help='配置文件路径')
    parser.add_argument('--target', type=str, help='目标URL (会覆盖配置文件设置)')
    parser.add_argument('--once', action='store_true', help='执行一次重放后退出')
    
    args = parser.parse_args()
    
    # 创建控制器
    controller = SimpleNapCatController(
        recordings_dir=args.dir,
        config_file=args.config
    )
    
    # 覆盖目标URL
    if args.target:
        controller.config["target_url"] = args.target
    
    if not controller.current_session:
        print("❌ 没有可用的录制会话，请先使用 napcat_recorder.py 录制")
        return
    
    if args.once:
        # 一次性执行模式
        print(f"🎬 一次性重放模式")
        print(f"📁 会话: {controller.current_session['data']['session_id']}")
        print(f"🎯 目标: {controller.config['target_url']}")
        controller.replay_all_requests()
    else:
        # 交互模式
        controller.run_simple_mode()

if __name__ == "__main__":
    main()
