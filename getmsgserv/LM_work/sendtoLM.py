import json
import time
import sys
import random
import os
import logging
import dashscope
from http import HTTPStatus
from dashscope import Generation, MultiModalConversation
from dashscope.api_entities.dashscope_response import Role
from PIL import Image
from PIL import ImageFile
from PIL import UnidentifiedImageError
ImageFile.LOAD_TRUNCATED_IMAGES = True
import re
import sqlite3
import copy
import traceback
import signal
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import urllib3
from typing import Dict, Any, List, Optional, Tuple
from contextlib import contextmanager
from functools import wraps

# 配置SSL和HTTP设置
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context

# 错误JSON输出的文件路径
output_file_path_error = "./cache/LM_error.json"

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒
API_TIMEOUT = 30  # 秒

# 数据库连接配置
DB_PATH = './cache/OQQWall.db'

# 信号处理
def signal_handler(signum, frame):
    """处理中断信号，确保优雅退出"""
    logging.warning(f"收到信号 {signum}，正在优雅退出...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def retry_on_exception(max_retries=MAX_RETRIES, delay=RETRY_DELAY, exceptions=(Exception,)):
    """重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logging.warning(f"函数 {func.__name__} 第 {attempt + 1} 次尝试失败: {e}")
                        time.sleep(delay * (2 ** attempt))  # 指数退避
                    else:
                        logging.error(f"函数 {func.__name__} 在 {max_retries + 1} 次尝试后仍然失败: {e}")
                        raise last_exception
            return None
        return wrapper
    return decorator

@contextmanager
def safe_db_connection():
    """安全的数据库连接上下文管理器"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20.0)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
    except sqlite3.Error as e:
        logging.error(f"数据库连接错误: {e}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception as e:
                logging.warning(f"关闭数据库连接时出错: {e}")

@retry_on_exception(max_retries=2, exceptions=(FileNotFoundError, IOError))
def read_config(file_path):
    """读取配置文件，返回字典，增加错误处理"""
    config = {}
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"配置文件不存在: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    if '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip().strip('"')
                    else:
                        logging.warning(f"配置文件第 {line_num} 行格式错误: {line}")
                except ValueError as e:
                    logging.warning(f"配置文件第 {line_num} 行解析错误: {line}, 错误: {e}")
        
        # 验证必要的配置项
        required_keys = ['apikey', 'text_model', 'vision_model']
        missing_keys = [key for key in required_keys if key not in config]
        if missing_keys:
            logging.warning(f"配置文件缺少必要项: {missing_keys}")
        
        return config
    except Exception as e:
        logging.error(f"读取配置文件失败: {e}")
        raise


def insert_missing_commas(json_like_string):
    # 用正则表达式检测并插入可能缺少的逗号
    missing_comma_pattern = re.compile(r'(\})(\s*[\{\[])')
    
    # 在可能缺少逗号的地方插入逗号
    corrected_json = missing_comma_pattern.sub(r'\1,\2', json_like_string)
    
    return corrected_json


def clean_json_output(output_content):
    # 清理和修正模型输出的JSON字符串
    try:
        # 尝试解析JSON以确保其有效
        parsed_output = json.loads(output_content)
        # 如果JSON有效，重新格式化以纠正括号问题
        clean_output = json.dumps(parsed_output, ensure_ascii=False, indent=4)
        return clean_output
    except json.JSONDecodeError:
        # 如果解码错误，尝试纠正缺少的逗号
        corrected_json = insert_missing_commas(output_content)
        try:
            # 再次尝试解析纠正后的JSON
            parsed_output = json.loads(corrected_json)
            return json.dumps(parsed_output, ensure_ascii=False, indent=4)
        except json.JSONDecodeError:
            # 如果仍然失败，返回纠正后的字符串以供手动检查
            return corrected_json


from PIL import UnidentifiedImageError
from PIL import ImageOps  # 放到你的 import 区域

def _is_high_bitdepth(img: Image.Image) -> bool:
    """粗略判断是否为高位深图（>8bit）。"""
    # 常见高位深模式或 mode 名称里带 16
    if img.mode in ("I;16", "I;16B", "I;16L", "I", "F", "RGB;16", "RGBA;16"):
        return True
    if "16" in (img.mode or ""):
        return True
    # 一些 PNG 会在 info 里带 bitdepth/bits
    bits = img.info.get("bitdepth") or img.info.get("bits")
    try:
        if bits and int(bits) > 8:
            return True
    except Exception:
        pass
    return False


def _save_with_format(img: Image.Image, path: str, fmt_hint: str = None, quality: int = None):
    """
    统一保存：
    - PNG：使用 optimize + 最大压缩等级（仍为无损）
    - JPEG：使用质量/渐进式/子采样
    - WEBP：使用有损质量参数
    其他：按 PNG 处理
    """
    ext = os.path.splitext(path)[1].lower()
    fmt = (fmt_hint or "").upper()
    if not fmt:
        if ext in (".jpg", ".jpeg"):
            fmt = "JPEG"
        elif ext == ".webp":
            fmt = "WEBP"
        elif ext == ".png":
            fmt = "PNG"
        else:
            fmt = "PNG"  # 默认用 PNG

    if fmt in ("JPEG", "JPG"):
        # JPEG 不支持 alpha；若有 alpha 则铺白底
        if "A" in img.getbands():
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        params = dict(
            quality=quality if quality is not None else 85,
            optimize=True,
            progressive=True,
            subsampling="4:2:0",
        )
        img.save(path, format="JPEG", **params)

    elif fmt == "WEBP":
        # 有损 webp，若你不想有损可把 quality 去掉并设 lossless=True
        params = dict(quality=quality if quality is not None else 80, method=6)
        img.save(path, format="WEBP", **params)

    else:
        # PNG（无损）。注意：quality 对 PNG 无效
        # compress_level: 0(快,大)~9(慢,小)
        img.save(path, format="PNG", optimize=True, compress_level=9)


@retry_on_exception(max_retries=2, exceptions=(OSError, IOError))
def compress_image(path, max_pixels, size_limit):
    """先尝试把 >8bit 图降到 8bit，再看体积是否达标；不达标再降分辨率到满足 size_limit（也会遵守 max_pixels）。"""
    logging.info(f"开始处理图片: {path}")
    
    # 验证输入参数
    if not os.path.exists(path):
        logging.error(f"图片文件不存在: {path}")
        return
    
    if max_pixels <= 0 or size_limit <= 0:
        logging.error(f"无效的参数: max_pixels={max_pixels}, size_limit={size_limit}")
        return
    
    try:
        with Image.open(path) as img:
            fmt_hint = (img.format or "").upper()
            width, height = img.size
            pixels = width * height
            logging.info(f"图片尺寸: {width}x{height}, 总像素: {pixels}, 模式: {img.mode}, 格式: {fmt_hint or 'N/A'}")

            # === Step 1: 降位深到 8bit（若需要） ===
            if _is_high_bitdepth(img):
                logging.info("检测到高位深图像，转换到 8bit…")
                # 将所有情况统一转换到 8bit 通道：
                #   有 alpha => RGBA；否则 RGB 或 L
                if "A" in img.getbands():
                    img = img.convert("RGBA")   # RGBA 为 8bit/通道
                else:
                    # 多通道转 RGB，单通道转 L
                    img = img.convert("RGB" if len(img.getbands()) >= 3 else "L")
                _save_with_format(img, path, fmt_hint)
                new_size = os.path.getsize(path)
                logging.info(f"位深降到 8bit 后大小: {new_size/1024/1024:.2f}MB")

            # 读取最新文件/尺寸状态
            with Image.open(path) as img2:
                fmt_hint = (img2.format or fmt_hint or "").upper()
                width, height = img2.size
                pixels = width * height
            file_size = os.path.getsize(path)

            # 若位深处理后已满足大小要求，并且像素也不超上限，直接返回
            if file_size <= size_limit and pixels <= max_pixels:
                logging.info("已满足大小与像素限制，结束。")
                return

            # === Step 2a: 若像素数超上限，按上限等比缩放 ===
            if pixels > max_pixels:
                ratio = (max_pixels / float(pixels)) ** 0.5
                new_w, new_h = max(1, int(width * ratio)), max(1, int(height * ratio))
                logging.info(f"像素超过上限，调整至: {new_w}x{new_h}")
                with Image.open(path) as img2:
                    img2 = img2.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    _save_with_format(img2, path, fmt_hint, quality=85)
                file_size = os.path.getsize(path)
                width, height = new_w, new_h
                pixels = width * height
                logging.info(f"像素降至上限后大小: {file_size/1024/1024:.2f}MB")

            # === Step 2b: 若仍超 size_limit，再按需降低分辨率（并结合格式化参数） ===
            if file_size > size_limit:
                logging.info(f"图片大小({file_size/1024/1024:.2f}MB)超过限制({size_limit/1024/1024:.2f}MB)，开始降分辨率/有损压缩…")

                # 为了减少循环次数，按理论比例一次性给出初始缩放因子（再细调）
                # （体积大约与像素数近似线性，先按 sqrt 比例缩）
                scale = max(0.3, min(0.95, (size_limit / float(file_size)) ** 0.5))
                target_w, target_h = max(1, int(width * scale)), max(1, int(height * scale))

                with Image.open(path) as img2:
                    img2 = img2.resize((target_w, target_h), Image.Resampling.LANCZOS)
                    if fmt_hint in ("JPEG", "JPG", "WEBP"):
                        # 先用一个保守质量保存，再逐步降低
                        _save_with_format(img2, path, fmt_hint, quality=85)
                        file_size = os.path.getsize(path)
                        if file_size > size_limit:
                            for q in (80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30):
                                _save_with_format(img2, path, fmt_hint, quality=q)
                                file_size = os.path.getsize(path)
                                logging.info(f"压缩质量: {q}, 当前大小: {file_size/1024/1024:.2f}MB")
                                if file_size <= size_limit:
                                    break
                    else:
                        # PNG 路线（无损）：先按最大压缩保存
                        _save_with_format(img2, path, "PNG")
                        file_size = os.path.getsize(path)
                        logging.info(f"PNG 最大压缩后大小: {file_size/1024/1024:.2f}MB")

                        # 若仍然很大（截图/大色彩图常见），尝试调色板 256 色（仍是 PNG，但更小）
                        if file_size > size_limit:
                            logging.info("尝试 PNG 调色板(256色)以进一步压缩…")
                            pal = img2.convert("P", palette=Image.ADAPTIVE, colors=256)
                            _save_with_format(pal, path, "PNG")
                            file_size = os.path.getsize(path)
                            logging.info(f"PNG 调色板后大小: {file_size/1024/1024:.2f}MB")

                        # 若还是超限，继续等比缩小，直到达标或边长到阈值
                        while file_size > size_limit and min(img2.size) > 512:
                            nw = max(1, int(img2.size[0] * 0.85))
                            nh = max(1, int(img2.size[1] * 0.85))
                            img2 = img2.resize((nw, nh), Image.Resampling.LANCZOS)
                            # 先试普通 RGB/RGBA PNG，再试 256 色
                            _save_with_format(img2, path, "PNG")
                            if os.path.getsize(path) > size_limit:
                                pal = img2.convert("P", palette=Image.ADAPTIVE, colors=256)
                                _save_with_format(pal, path, "PNG")
                            file_size = os.path.getsize(path)
                            logging.info(f"继续降分辨率到 {nw}x{nh}，当前大小: {file_size/1024/1024:.2f}MB")

        logging.info("图片压缩流程完成。")
    except UnidentifiedImageError:
        logging.warning(f"跳过无法识别的图片文件: {path}")
    except (OSError, IOError) as e:
        logging.error(f"图片文件操作错误 {path}: {e}")
        raise
    except Exception as e:
        logging.error(f"处理图片 {path} 时发生意外错误: {e}", exc_info=True)
        raise



@retry_on_exception(max_retries=2, exceptions=(Exception,))
def process_image_safety_and_description(path, model, api_key):
    """使用DashScope同时进行图片安全检查和描述生成。"""
    logging.info(f"处理图片安全检查和描述生成: {path}")
    
    # 验证输入参数
    if not os.path.exists(path):
        logging.error(f"图片文件不存在: {path}")
        return True, ""  # 默认安全，无描述
    
    if not api_key or not model:
        logging.error("缺少API密钥或模型配置")
        return True, ""  # 默认安全，无描述
    
    messages = [{
        'role': 'user',
        'content': [
            {'image': 'file://' + os.path.abspath(path)},
            {'text': '''请分析这张图片并回答以下两个问题：

1. 安全性检查：这张图片是否含有暴力、血腥、色情、政治敏感，人生攻击或其他敏感内容(发到国内平台，被举报后会导致处罚的都算)？如果安全请回答"safe"，否则回答"unsafe"。

2. 图片描述：请详细描述这张图片的内容，包括图片中的主要元素、场景、颜色、风格等。描述要准确、详细，但不要过于冗长。

请按以下格式回答：
安全性：[safe/unsafe]
描述：[详细描述内容]'''}
        ]
    }]
    
    # Debug输出：显示发送给模型的输入
    logging.debug(f"发送给视觉模型的输入:")
    logging.debug(f"  模型: {model}")
    logging.debug(f"  图片路径: {os.path.abspath(path)}")
    logging.debug(f"  消息内容: {json.dumps(messages, ensure_ascii=False, indent=2)}")
    
    try:
        response = MultiModalConversation.call(
            model=model, 
            messages=messages, 
            api_key=api_key,
            timeout=API_TIMEOUT
        )
        
        # Debug输出：显示API响应状态
        logging.debug(f"视觉模型API响应状态码: {response.status_code}")
        
        if response.status_code == HTTPStatus.OK:
            content = response.output.choices[0].message.content
            if isinstance(content, list):
                content = " ".join(map(str, content))
            
            # Debug输出：显示模型返回的完整内容
            logging.debug(f"视觉模型返回的完整内容:")
            logging.debug(f"  {content}")
            
            # 解析响应内容
            is_safe = True
            description = ""
            
            # 提取安全性信息
            if 'unsafe' in content.lower():
                is_safe = False
                logging.warning(f"图片被标记为不安全: {path}")
            
            # 提取描述信息
            description_start = content.find('描述：')
            if description_start != -1:
                description = content[description_start + 3:].strip()
            else:
                # 如果没有找到"描述："标记，尝试提取其他格式的描述
                lines = content.split('\n')
                for line in lines:
                    if line.strip() and not line.lower().startswith('安全性：') and 'safe' not in line.lower() and 'unsafe' not in line.lower():
                        description = line.strip()
                        break
            
            logging.info(f"图片处理结果 - 安全: {is_safe}, 描述长度: {len(description)} 字符")
            return is_safe, description.strip()
            
        elif response.status_code == 400:
            # API返回400错误，通常表示图片内容过于敏感，被API拒绝处理
            logging.warning(f"图片被API拒绝处理(400错误)，可能包含极度敏感内容: {path}")
            logging.debug(f"API错误详情: {getattr(response, 'message', '未知错误')}")
            return False, ""  # 标记为不安全，无描述
        elif response.status_code == 401:
            logging.error(f"API密钥无效(401错误): {path}")
            return True, ""  # 默认安全，无描述
        elif response.status_code == 403:
            logging.error(f"API权限不足或被封禁(403错误): {path}")
            return True, ""  # 默认安全，无描述
        elif response.status_code == 429:
            logging.warning(f"API请求频率限制(429错误): {path}")
            return True, ""  # 默认安全，无描述
        elif response.status_code >= 500:
            logging.error(f"API服务器错误({response.status_code}): {path}")
            return True, ""  # 默认安全，无描述
        else:
            logging.warning(f"图片处理返回未知状态码: {response.status_code}, 图片: {path}")
            return True, ""  # 默认安全，无描述
            
    except Exception as e:
        error_msg = str(e).lower()
        if '400' in error_msg or 'bad request' in error_msg:
            # 捕获到400相关异常
            logging.warning(f"捕获到400错误异常，图片可能包含极度敏感内容: {path}")
            logging.debug(f"400错误异常详情: {str(e)}")
            return False, ""  # 标记为不安全，无描述
        elif 'ssl' in error_msg:
            logging.warning(f"图片处理SSL错误: {path}, 错误: {str(e)}")
            return True, ""  # 默认安全，无描述
        elif 'timeout' in error_msg or 'timed out' in error_msg:
            logging.warning(f"图片处理超时: {path}")
            return True, ""  # 默认安全，无描述
        elif 'connection' in error_msg or 'network' in error_msg:
            logging.error(f"网络连接错误: {str(e)}")
            return True, ""  # 默认安全，无描述
        else:
            logging.error(f"图片处理发生未知错误: {str(e)}, 错误类型: {type(e)}", exc_info=True)
            return True, ""  # 默认安全，无描述


def process_single_image_task(image_info):
    """
    处理单个图片的完整任务（压缩+安全检查+描述生成）
    
    Args:
        image_info: dict containing:
            - image_path: 图片文件路径
            - file_name: 图片文件名
            - model: 视觉模型名称
            - api_key: API密钥
            - max_pixels: 最大像素数
            - size_limit: 大小限制
            - msg: 消息对象（用于添加描述）
            - is_additional: 是否为额外图片（非消息关联的图片）
    
    Returns:
        dict: 处理结果
    """
    try:
        image_path = image_info['image_path']
        file_name = image_info['file_name']
        model = image_info['model']
        api_key = image_info['api_key']
        max_pixels = image_info['max_pixels']
        size_limit = image_info['size_limit']
        msg = image_info.get('msg')
        is_additional = image_info.get('is_additional', False)
        
        thread_id = threading.current_thread().ident
        logging.info(f"[线程{thread_id}] 开始处理图片: {file_name}")
        
        # 步骤1: 压缩图片
        compress_image(image_path, max_pixels, size_limit)
        
        # 步骤2: 安全检查和描述生成
        is_safe, description = process_image_safety_and_description(image_path, model, api_key)
        
        result = {
            'file_name': file_name,
            'image_path': image_path,
            'is_safe': is_safe,
            'description': description,
            'msg': msg,
            'is_additional': is_additional,
            'thread_id': thread_id,
            'success': True,
            'error': None
        }
        
        logging.info(f"[线程{thread_id}] 完成处理图片: {file_name}, 安全: {is_safe}, 描述长度: {len(description)}")
        return result
        
    except Exception as e:
        error_msg = str(e).lower()
        result = {
            'file_name': image_info.get('file_name', 'unknown'),
            'image_path': image_info.get('image_path', ''),
            'is_safe': False if ('400' in error_msg or 'bad request' in error_msg) else True,
            'description': '',
            'msg': image_info.get('msg'),
            'is_additional': image_info.get('is_additional', False),
            'thread_id': threading.current_thread().ident,
            'success': False,
            'error': str(e),
            'is_api_400': '400' in error_msg or 'bad request' in error_msg
        }
        
        logging.error(f"[线程{result['thread_id']}] 处理图片 {result['file_name']} 时出错: {e}")
        return result


@retry_on_exception(max_retries=3, exceptions=(sqlite3.Error, json.JSONDecodeError))
def process_images_comprehensive(tag, config, input_data=None):
    """对指定tag的所有图片进行压缩、安全检查、描述生成，并更新JSON数据。"""
    if not tag or not config:
        logging.error("缺少必要参数: tag 或 config")
        return
    
    folder = os.path.join('cache/picture', str(tag))
    logging.info(f"处理tag {tag}的图片综合处理（压缩、安全检查、描述生成）")
    
    if not os.path.isdir(folder):
        logging.info(f"目录 {folder} 不存在，跳过图片处理")
        return
    
    files = os.listdir(folder)
    if not files:
        logging.info(f"目录 {folder} 为空，跳过图片处理")
        return
    
    # 验证配置参数
    api_key = config.get('apikey')
    if not api_key:
        logging.error("配置中缺少API密钥")
        return
    
    try:
        max_pixels = int(config.get('vision_pixel_limit', 12000000))
        size_limit = float(config.get('vision_size_limit_mb', 9.5)) * 1024 * 1024
    except (ValueError, TypeError) as e:
        logging.error(f"配置参数解析错误: {e}")
        return
    
    model = config.get('vision_model', 'qwen-vl-max-latest')
    dashscope.api_key = api_key

    # 读取当前数据库中的JSON数据
    with safe_db_connection() as conn:
        cur = conn.cursor()
        try:
            # 优先使用传入的input_data
            if input_data is not None:
                data = input_data
                messages = data.get('messages', [])
                logging.info("使用传入的input_data")
            else:
                # 首先尝试从preprocess表的AfterLM字段获取数据
                row = cur.execute('SELECT AfterLM FROM preprocess WHERE tag=?', (tag,)).fetchone()
                if row and row[0] is not None:
                    data = json.loads(row[0])
                    messages = data.get('messages', [])
                    logging.info("从AfterLM字段获取消息数据")
                else:
                    # 如果AfterLM字段为空，从sender表的rawmsg字段获取原始数据
                    logging.info("AfterLM字段为空，尝试从sender表获取原始消息数据")
                    sender_row = cur.execute('''
                        SELECT s.rawmsg 
                        FROM sender s 
                        JOIN preprocess p ON s.senderid = p.senderid AND s.receiver = p.receiver 
                        WHERE p.tag = ?
                    ''', (tag,)).fetchone()
                    
                    if not sender_row or sender_row[0] is None:
                        logging.warning(f"未找到标签 {tag} 的原始消息数据")
                        return
                    
                    raw_messages = json.loads(sender_row[0])
                    # 构造data结构以保持一致性
                    data = {"messages": raw_messages}
                    messages = raw_messages
                    logging.info("从sender.rawmsg字段获取原始消息数据")
            
            # 为了图片处理，我们需要访问完整的data字段，所以使用原始数据
            # 而不是经过make_lm_sanitized_and_original处理的数据
            
            # 统计信息
            processed_count = 0
            error_count = 0
            description_count = 0
            api_400_count = 0
            sensitive_files = []
            safe = True
            
            # 遍历所有消息，找到图片类型的消息
            image_count = 0
            processed_files = set()  # 记录已处理的文件
            
            # 首先收集所有需要处理的常规图片任务
            regular_image_tasks = []
            for item in messages:
                if 'message' in item and isinstance(item['message'], list):
                    for msg in item['message']:
                        if msg.get('type') == 'image':
                            # 检查sub_type，只处理sub_type为0的图片
                            sub_type = msg.get('data', {}).get('sub_type', 0)
                            if sub_type != 0:
                                logging.info(f"跳过处理sub_type={sub_type}的图片，只处理sub_type=0的图片")
                                continue
                            
                            image_count += 1
                            # 查找对应的图片文件
                            file_name = None
                            
                            # 方法1: 尝试从data字段获取文件名
                            if 'data' in msg and 'url' in msg['data']:
                                # 优先使用URL字段，因为它包含实际的文件路径
                                url = msg['data']['url']
                                logging.debug(f"从data.url获取URL: {url}")
                                if url.startswith('file://'):
                                    file_name = os.path.basename(url[7:])  # 去掉file://前缀
                                    logging.debug(f"从URL提取文件名: {file_name}")
                            elif 'data' in msg and 'file' in msg['data']:
                                file_name = os.path.basename(msg['data']['file'])
                                logging.debug(f"从data.file获取文件名: {file_name}")
                            elif 'file' in msg:
                                file_name = os.path.basename(msg['file'])
                                logging.debug(f"从msg.file获取文件名: {file_name}")
                            
                            # 方法2: 如果找不到文件名，尝试按tag-index.png格式匹配
                            if not file_name:
                                # 查找匹配的图片文件
                                for f in files:
                                    if f.startswith(f"{tag}-{image_count}.") and f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')):
                                        file_name = f
                                        break
                            
                            # 方法3: 如果仍然找不到，尝试匹配任何图片文件
                            if not file_name and len(files) == 1:
                                # 如果只有一个文件，直接使用它
                                file_name = files[0]
                                logging.info(f"只有一个图片文件，直接使用: {file_name}")
                            elif not file_name:
                                # 如果有多个文件，尝试按顺序匹配
                                for f in files:
                                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')):
                                        file_name = f
                                        logging.info(f"按顺序匹配到图片文件: {file_name}")
                                        break
                            
                            if file_name and file_name in files:
                                processed_files.add(file_name)
                                image_path = os.path.join(folder, file_name)
                                
                                # 添加到任务列表
                                task_info = {
                                    'image_path': image_path,
                                    'file_name': file_name,
                                    'model': model,
                                    'api_key': api_key,
                                    'max_pixels': max_pixels,
                                    'size_limit': size_limit,
                                    'msg': msg,
                                    'is_additional': False
                                }
                                regular_image_tasks.append(task_info)
                            else:
                                logging.warning(f"未找到图片文件，image_count={image_count}, 可用文件: {files}")
                                logging.debug(f"图片消息结构: {json.dumps(msg, ensure_ascii=False)}")
            
            # 并行处理常规图片任务
            if regular_image_tasks:
                logging.info(f"开始并行处理 {len(regular_image_tasks)} 个常规图片消息")
                max_workers = min(len(regular_image_tasks), 3)  # 限制最大并发数
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # 提交所有任务
                    future_to_task = {executor.submit(process_single_image_task, task): task for task in regular_image_tasks}
                    
                    # 收集结果
                    for future in as_completed(future_to_task):
                        task = future_to_task[future]
                        try:
                            result = future.result()
                            file_name = result['file_name']
                            msg = result['msg']
                            
                            if result['success']:
                                # 处理成功
                                if not result['is_safe']:
                                    logging.warning(f"图片 {file_name} 被标记为不安全")
                                    safe = False
                                    sensitive_files.append(file_name)
                                
                                if result['description']:
                                    # 将描述添加到消息的顶层，这样大模型可以看到
                                    msg['describe'] = result['description']
                                    description_count += 1
                                    logging.info(f"[线程{result['thread_id']}] 成功为图片 {file_name} 添加描述")
                                else:
                                    logging.warning(f"图片 {file_name} 描述生成失败")
                                    error_count += 1
                                
                                processed_count += 1
                                
                            else:
                                # 处理失败
                                if result.get('is_api_400', False):
                                    logging.error(f"图片 {file_name} 触发API 400错误，可能包含极度敏感内容: {result['error']}")
                                    safe = False
                                    sensitive_files.append(file_name)
                                    api_400_count += 1
                                else:
                                    logging.error(f"处理图片 {file_name} 时出错: {result['error']}")
                                    error_count += 1
                                
                        except Exception as e:
                            logging.error(f"获取常规图片任务结果时出错: {task['file_name']}, 错误: {e}")
                            error_count += 1
                
                logging.info(f"常规图片并行处理完成，总计 {len(regular_image_tasks)} 个文件")
            
            # 处理剩余的图片文件（没有对应消息记录的，比如forward聊天记录中的图片）
            remaining_files = [f for f in files if f not in processed_files and f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'))]
            
            # 收集forward聊天记录中sub_type=0的图片文件名 - 需要递归处理嵌套forward
            def collect_subtype_0_images(item_list, depth=0):
                subtype_0_files = set()
                logging.debug(f"递归深度 {depth}: 处理 {len(item_list)} 个项目")
                
                for i, item in enumerate(item_list):
                    logging.debug(f"递归深度 {depth}: 处理项目 {i}, 类型: {type(item)}, 键: {list(item.keys()) if isinstance(item, dict) else 'N/A'}")
                    
                    # 如果item有message字段，处理其中的消息
                    if 'message' in item and isinstance(item['message'], list):
                        logging.debug(f"递归深度 {depth}: 项目 {i} 有 {len(item['message'])} 个消息")
                        for j, msg in enumerate(item['message']):
                            msg_type = msg.get('type')
                            logging.debug(f"递归深度 {depth}: 消息 {j} 类型: {msg_type}")
                            if msg_type == 'forward' and 'data' in msg:
                                logging.debug(f"递归深度 {depth}: 处理forward消息")
                                data_keys = list(msg['data'].keys())
                                logging.debug(f"递归深度 {depth}: forward data键: {data_keys}")
                                # 处理forward消息的content或messages字段
                                if 'content' in msg['data'] and isinstance(msg['data']['content'], list):
                                    logging.debug(f"递归深度 {depth}: 找到forward消息content，{len(msg['data']['content'])} 个内容项")
                                    sub_files = collect_subtype_0_images(msg['data']['content'], depth + 1)
                                    subtype_0_files.update(sub_files)
                                elif 'messages' in msg['data'] and isinstance(msg['data']['messages'], list):
                                    logging.debug(f"递归深度 {depth}: 找到forward消息messages，{len(msg['data']['messages'])} 个消息项")
                                    sub_files = collect_subtype_0_images(msg['data']['messages'], depth + 1)
                                    subtype_0_files.update(sub_files)
                                else:
                                    logging.debug(f"递归深度 {depth}: forward消息没有有效的content或messages字段")
                            elif msg_type == 'image':
                                logging.debug(f"递归深度 {depth}: 处理image消息")
                                sub_type = msg.get('data', {}).get('sub_type')
                                logging.debug(f"递归深度 {depth}: 找到image消息，sub_type={sub_type}")
                                if sub_type == 0:
                                    logging.debug(f"递归深度 {depth}: 找到sub_type=0图片消息")
                                    # 直接使用URL中的文件名进行精确匹配
                                    url = msg.get('data', {}).get('url', '')
                                    if url.startswith('file://'):
                                        cache_file_name = os.path.basename(url[7:])  # 去掉file://前缀
                                        logging.debug(f"从URL提取文件名: {cache_file_name}, remaining_files包含: {cache_file_name in remaining_files}")
                                        if cache_file_name in remaining_files:
                                            subtype_0_files.add(cache_file_name)
                                            logging.debug(f"找到sub_type=0的图片: {cache_file_name}")
                                        else:
                                            logging.debug(f"sub_type=0图片文件不存在: {cache_file_name}")
                                    else:
                                        logging.debug(f"URL格式不正确: {url}")
                                else:
                                    logging.debug(f"递归深度 {depth}: 跳过sub_type={sub_type}的图片")
                            else:
                                logging.debug(f"递归深度 {depth}: 跳过消息类型: {msg_type}")
                    
                    # 如果item是原始forward messages格式（包含所有元数据的消息项）
                    elif 'message' in item and isinstance(item['message'], list):
                        # 这个条件重复了，移除
                        pass
                    
                    # 如果item本身就是消息格式（content数组中的直接消息项）
                    elif item.get('type') == 'image' and item.get('data', {}).get('sub_type') == 0:
                        logging.debug(f"递归深度 {depth}: 项目 {i} 是sub_type=0图片")
                        url = item.get('data', {}).get('url', '')
                        if url.startswith('file://'):
                            cache_file_name = os.path.basename(url[7:])  # 去掉file://前缀
                            if cache_file_name in remaining_files:
                                subtype_0_files.add(cache_file_name)
                                logging.debug(f"找到sub_type=0的图片: {cache_file_name}")
                            else:
                                logging.debug(f"sub_type=0图片文件不存在: {cache_file_name}")
                
                logging.debug(f"递归深度 {depth}: 找到 {len(subtype_0_files)} 个sub_type=0图片: {subtype_0_files}")
                return subtype_0_files
            
            subtype_0_files = collect_subtype_0_images(messages)
            
            # 只处理sub_type=0的图片文件
            files_to_process = [f for f in remaining_files if f in subtype_0_files]
            
            if remaining_files:
                logging.info(f"发现 {len(remaining_files)} 个没有对应消息记录的图片文件")
                logging.info(f"其中 {len(files_to_process)} 个是sub_type=0的图片，需要进行安全检查: {files_to_process}")
                logging.info(f"跳过 {len(remaining_files) - len(files_to_process)} 个非sub_type=0的图片")
            
            if files_to_process:
                # 并行处理剩余图片文件
                logging.info(f"开始并行处理 {len(files_to_process)} 个图片文件")
                
                # 准备并行任务
                image_tasks = []
                for file_name in files_to_process:
                    image_path = os.path.join(folder, file_name)
                    task_info = {
                        'image_path': image_path,
                        'file_name': file_name,
                        'model': model,
                        'api_key': api_key,
                        'max_pixels': max_pixels,
                        'size_limit': size_limit,
                        'msg': None,
                        'is_additional': True
                    }
                    image_tasks.append(task_info)
                
                # 使用线程池并行处理
                max_workers = min(len(files_to_process), 3)  # 限制最大并发数为3，避免API频率限制
                logging.info(f"使用 {max_workers} 个线程并行处理图片")
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # 提交所有任务
                    future_to_task = {executor.submit(process_single_image_task, task): task for task in image_tasks}
                    
                    # 收集结果
                    for future in as_completed(future_to_task):
                        task = future_to_task[future]
                        try:
                            result = future.result()
                            file_name = result['file_name']
                            
                            if result['success']:
                                # 处理成功
                                if not result['is_safe']:
                                    logging.warning(f"图片 {file_name} 被标记为不安全")
                                    safe = False
                                    sensitive_files.append(file_name)
                                
                                if result['description']:
                                    logging.info(f"[线程{result['thread_id']}] 为图片 {file_name} 生成了描述: {result['description'][:100]}...")
                                    description_count += 1
                                    
                                    # 添加到additional_images
                                    if 'additional_images' not in data:
                                        data['additional_images'] = []
                                    data['additional_images'].append({
                                        'file': file_name,
                                        'description': result['description'],
                                        'source': 'forward_content'
                                    })
                                
                                processed_count += 1
                                
                            else:
                                # 处理失败
                                if result.get('is_api_400', False):
                                    logging.error(f"图片 {file_name} 触发API 400错误，可能包含极度敏感内容: {result['error']}")
                                    safe = False
                                    sensitive_files.append(file_name)
                                    api_400_count += 1
                                else:
                                    logging.error(f"处理图片 {file_name} 时出错: {result['error']}")
                                    error_count += 1
                                
                        except Exception as e:
                            logging.error(f"获取并行任务结果时出错: {task['file_name']}, 错误: {e}")
                            error_count += 1
                
                logging.info(f"并行图片处理完成，总计 {len(files_to_process)} 个文件")
            
            # 更新数据库
            if description_count > 0 or not safe:
                # 更新safemsg字段
                if not safe:
                    data['safemsg'] = 'false'
                
                updated_data = json.dumps(data, ensure_ascii=False, indent=4)
                cur.execute('UPDATE preprocess SET AfterLM=? WHERE tag=?', (updated_data, tag))
                conn.commit()
                logging.info(f"成功更新数据库，添加了 {description_count} 个图片描述，安全状态: {'不安全' if not safe else '安全'}")
            
            # 详细的统计信息
            logging.info(f"图片综合处理完成:")
            logging.info(f"  - 总图片文件数: {len(files)}")
            logging.info(f"  - 处理的图片消息: {processed_count} 个")
            logging.info(f"  - 成功生成描述: {description_count} 个")
            logging.info(f"  - 处理错误: {error_count} 个")
            logging.info(f"  - API 400错误: {api_400_count} 个")
            logging.info(f"  - 敏感文件: {len(sensitive_files)} 个")
            if sensitive_files:
                logging.warning(f"  - 敏感文件列表: {sensitive_files}")
            logging.info(f"  - 最终安全结果: {'安全' if safe else '不安全'}")
            
            # 如果有API 400错误，记录特殊标记
            if api_400_count > 0:
                logging.warning(f"标签 {tag} 包含 {api_400_count} 个可能极度敏感的文件，已被标记为不安全")
            
        except json.JSONDecodeError as e:
            logging.error(f"解析JSON数据失败: {e}")
            raise
        except sqlite3.Error as e:
            logging.error(f"数据库操作失败: {e}")
            raise

############################################
#      Flexible per-type redact & restore  #
############################################

# 支持更复杂的“按消息类型字段处理”配置：
# - remove_in_data:     从 msg.data 中删除
# - remove_msg:         从 msg 顶层(非data)删除
# - remove_event:       从事件(item)顶层删除（与类型无关的通用字段放在 global_event_rules）
# - hide_from_LM_only:  仅用于发给LM时隐藏，最终输出时会恢复（或保留）
#
# 说明：hide_from_LM_only 使用“点路径”语法，例如：
#   - 'data.file'      指向 msg.data.file
#   - 'summary'        指向 msg.summary（如果存在）
#   - 事件(item)级请使用 global_event_rules.hide_from_LM_only

per_type_rules = {
    "image": {
        "remove_in_data": ["file_id", "file_size"],
        "remove_msg": ["summary"],
        "remove_event": [],
        "hide_from_LM_only": ["data"]
    },
    "video": {
        "remove_in_data": ["file_id", "file_size"],
        "remove_msg": [],
        "remove_event": [],
        "hide_from_LM_only": ["data.file", "data.file_id", "data.file_size"]
    },
    "audio": {
        "remove_in_data": ["file_id", "file_size"],
        "remove_msg": [],
        "remove_event": [],
        "hide_from_LM_only": ["data.file", "data.file_id", "data.file_size"]
    },
    "json": {
        "remove_in_data": [],
        "remove_msg": [],
        "remove_event": [],
        "hide_from_LM_only": []
    },
    "text": {
        "remove_in_data": [],
        "remove_msg": [],
        "remove_event": [],
        "hide_from_LM_only": []
    },
    "file": {
        "remove_in_data": ["file_id"],
        "remove_msg": [],
        "remove_event": [],
        "hide_from_LM_only": ["data.file_size"]
    },
    "poke": {
        "remove_in_data": [],
        "remove_msg": [],
        "remove_event": [],
        "hide_from_LM_only": ["data"]
    },
    "forward": {
        "remove_in_data": ["id"],  # 删除data.id字段
        "remove_msg": [],
        "remove_event": [],
        "hide_from_LM_only": []
    },
}

# 默认规则：用于未匹配到的 type
default_rules = {
    "remove_in_data": ["file", "file_id", "file_size"],
    "remove_msg": [],
    "remove_event": [],
    "hide_from_LM_only": []
}

# 全局事件级规则（与类型无关，直接作用于每个顶层 item）
# 兼容历史行为：删除 item 级别中可能出现的 file/file_id/file_size
global_event_rules = {
    "remove_event": ["file", "file_id", "file_size"],
    "hide_from_LM_only": []  # 如果希望某些事件级字段仅对LM隐藏、最终输出显示，可把字段名加入这里
}


def _pop_path(obj, dotted):
    """根据点路径删除字段。例如 'data.file' 或 'summary'。不存在则忽略。"""
    if not dotted:
        return
    parts = dotted.split('.')
    cur = obj
    for i, k in enumerate(parts):
        if not isinstance(cur, dict) or k not in cur:
            return
        if i == len(parts) - 1:
            cur.pop(k, None)
        else:
            cur = cur.get(k)


def _remove_many(obj, paths):
    for p in paths:
        _pop_path(obj, p)


def clean_forward_content(content_list):
    """
    递归清理forward消息内容，删除不需要发给模型的字段，支持嵌套forward。
    同时对forward内部的每个消息按照per_type_rules进行处理。
    
    Args:
        content_list: forward消息的content列表
    
    Returns:
        清理后的content列表
    """
    if not isinstance(content_list, list):
        return content_list
    
    cleaned_content = []
    for item in content_list:
        if not isinstance(item, dict):
            cleaned_content.append(item)
            continue
        
        # 只保留message字段，删除id、message_id、message_seq、real_id、real_seq、time、sender、message_type、raw_message、font、sub_type、message_format、post_type、group_id、self_id、user_id
        cleaned_item = {}
        if "message" in item and isinstance(item["message"], list):
            cleaned_item["message"] = []
            for msg in item["message"]:
                if isinstance(msg, dict):
                    cleaned_msg = msg.copy()
                    
                    # 对每个消息按照类型应用per_type_rules
                    mtype = msg.get("type")
                    rules = per_type_rules.get(mtype, default_rules)
                    
                    # 应用hide_from_LM_only规则（删除对LM隐藏的字段）
                    for field_path in rules.get('hide_from_LM_only', []):
                        _pop_path(cleaned_msg, field_path)
                    
                    # 如果是图片消息，且有描述信息，需要从图片处理结果中获取描述并添加
                    # 这里先保留消息结构，描述会在外层函数中添加
                    
                    # 如果是嵌套的forward消息，递归清理
                    if mtype == "forward" and "data" in cleaned_msg:
                        if "content" in cleaned_msg["data"]:
                            cleaned_msg["data"]["content"] = clean_forward_content(cleaned_msg["data"]["content"])
                        elif "messages" in cleaned_msg["data"]:
                            cleaned_msg["data"]["messages"] = clean_forward_content(cleaned_msg["data"]["messages"])
                    
                    cleaned_item["message"].append(cleaned_msg)
                else:
                    cleaned_item["message"].append(msg)
        
        if cleaned_item:  # 只有当有message字段时才添加
            cleaned_content.append(cleaned_item)
    
    return cleaned_content


def make_lm_sanitized_and_original(data_root):
    """
    返回两个列表：
      - lm_messages:   发给LM的消息（按 per_type_rules/默认规则 删除 + 隐藏hide_from_LM_only）
      - origin_messages: 原始消息的深拷贝（不改变）
    同时会对事件级字段应用 global_event_rules。
    """
    origin_messages = copy.deepcopy(data_root.get("messages", []))
    lm_messages = copy.deepcopy(origin_messages)

    # 事件级字段（对LM删除 remove_event + hide_from_LM_only）
    for item in lm_messages:
        _remove_many(item, global_event_rules.get('remove_event', []))
        _remove_many(item, global_event_rules.get('hide_from_LM_only', []))

        # 处理子消息
        if "message" in item and isinstance(item["message"], list):
            for msg in item["message"]:
                mtype = msg.get("type")
                rules = per_type_rules.get(mtype, default_rules)

                # 对forward消息进行特殊清理
                if mtype == "forward" and "data" in msg:
                    if "content" in msg["data"]:
                        msg["data"]["content"] = clean_forward_content(msg["data"]["content"])
                    elif "messages" in msg["data"]:
                        msg["data"]["messages"] = clean_forward_content(msg["data"]["messages"])

                # msg 顶层删除
                _remove_many(msg, rules.get('remove_msg', []))
                _remove_many(msg, rules.get('hide_from_LM_only', []))  # 对LM隐藏

                # data 内删除
                if isinstance(msg.get("data"), dict):
                    _remove_many(msg, [f"data.{k}" for k in rules.get('remove_in_data', [])])

    return lm_messages, origin_messages


def finalize_item_for_output(item_origin):
    """基于原始事件构造最终输出事件：
       - 事件级：删除 global_event_rules.remove_event 中列出但不在 hide_from_LM_only 的字段
       - 子消息级：对每个消息按类型删除 remove_msg / remove_in_data，但跳过 hide_from_LM_only 指定的路径
    """
    out_item = copy.deepcopy(item_origin)

    # 事件级最终删除（仅保留 hide_from_LM_only）
    for key in global_event_rules.get('remove_event', []):
        if key not in global_event_rules.get('hide_from_LM_only', []):
            _pop_path(out_item, key)

    # 子消息级
    if "message" in out_item and isinstance(out_item["message"], list):
        for msg in out_item["message"]:
            mtype = msg.get("type")
            rules = per_type_rules.get(mtype, default_rules)
            hide_set = set(rules.get('hide_from_LM_only', []))

            # msg 顶层删除
            for p in rules.get('remove_msg', []):
                if p not in hide_set:
                    _pop_path(msg, p)

            # data 内删除
            if isinstance(msg.get('data'), dict):
                for k in rules.get('remove_in_data', []):
                    dotted = f"data.{k}"
                    if dotted not in hide_set:
                        _pop_path(msg, dotted)

    return out_item


@retry_on_exception(max_retries=2, exceptions=(Exception,))
def fetch_response_in_parts(prompt, config, max_rounds=5):
    """分多轮流式获取大模型响应，拼接完整输出"""
    if not prompt or not config:
        logging.error("缺少必要参数: prompt 或 config")
        return ""
    
    messages = [{'role': 'system', 'content': '你是一个校园墙投稿管理员'},
                {'role': 'user', 'content': prompt}]

    # Debug输出：显示发送给文本模型的输入，用户消息显示完整的
    logging.debug(f"发送给文本模型的输入:")
    logging.debug(f"  模型: {config.get('text_model', 'qwen-plus-latest')}")
    logging.debug(f"  消息数量: {len(messages)}")
    logging.debug(f"  系统消息: {messages[0]['content']}")
    logging.debug(f"  用户消息长度: {len(messages[1]['content'])} 字符")
    logging.debug(f"  用户消息完整内容: {messages[1]['content']}")

    full_response = ""
    round_count = 0
    is_complete = False
    previous_output = ""

    while not is_complete and round_count < max_rounds:
        seed = 1354
        logging.info(f"Round {round_count + 1} - Using seed: {seed}")

        try:
            # 使用流式输出方式调用生成模型
            responses = Generation.call(
                model=config.get('text_model', 'qwen-plus-latest'),
                messages=messages,
                seed=seed,
                result_format='message',
                stream=True,
                incremental_output=True,
                max_tokens=8192,
                temperature=0.50,
                repetition_penalty=1.0,
                timeout=API_TIMEOUT
            )

            # 处理流式响应
            output_content = ""
            for response in responses:
                # 只拼接内容，不访问status_code
                chunk = response.output.get('choices', [])[0].get('message', {}).get('content', '')
                output_content += chunk
                sys.stdout.flush()
            
            # Debug输出：显示本轮接收到的内容
            logging.debug(f"Round {round_count + 1} 接收到的内容长度: {len(output_content)} 字符")
            logging.debug(f"Round {round_count + 1} 接收到的内容: {output_content}")
                
        except Exception as e:
            error_msg = str(e).lower()
            if 'ssl' in error_msg or 'connection' in error_msg or 'timeout' in error_msg:
                logging.warning(f"Round {round_count + 1} 网络错误，尝试重试: {e}")
                if round_count < max_rounds - 1:  # 如果不是最后一轮，继续重试
                    time.sleep(2)  # 等待2秒后重试
                    continue
                else:
                    logging.error(f"在 {max_rounds} 轮后仍然遇到网络错误: {e}")
                    break
            else:
                logging.error(f"API调用错误: {e}")
                break

        if previous_output:
            # 获取上一次输出的最后100个字符
            overlap_content = previous_output[-100:]
            # 在当前输出的前500字符中查找重叠部分
            start_index = output_content[:500].find(overlap_content)
            if start_index != -1:
                # 如果找到，去除重叠部分
                output_content = output_content[start_index + len(overlap_content):]
                logging.debug(f"Round {round_count + 1} 去除重叠内容后长度: {len(output_content)} 字符")

        # 更新完整响应
        full_response += output_content
        previous_output = output_content

        # 检查输出是否以结束标志'```'结尾
        if output_content.endswith('```'):
            logging.info("响应完成!")
            is_complete = True
        else:
            # 截断最后100字符后加入messages，防止重复
            truncated_output = output_content[:-100] if len(output_content) > 100 else output_content
            messages.append({
                'role': Role.ASSISTANT,
                'content': truncated_output
            })
            # 提示模型继续输出，不要重复内容
            continue_prompt = '接着上次停下的地方继续输出，不要重复之前的内容，不要重复sender和needpriv等内容，不要在开头重复一遍```json {"time": },{"message": [{"type": ,"data": {，不要在开头重复任何格式内容，直接接着上次结束的那个字继续,但是如果json已经到达末尾，请用\n```结束输出'
            messages.append({'role': Role.USER, 'content': continue_prompt})
            
            # Debug输出：显示继续提示
            logging.debug(f"Round {round_count + 1} 添加继续提示: {continue_prompt}")
        round_count += 1

    if not is_complete:
        logging.warning(f"在 {max_rounds} 轮后仍未完成响应")
    
    # Debug输出：显示最终完整响应
    logging.debug(f"文本模型最终完整响应长度: {len(full_response)} 字符")
    logging.debug(f"文本模型最终完整响应: {full_response}")
    
    return full_response


@retry_on_exception(max_retries=3, exceptions=(sqlite3.Error,))
def save_to_sqlite(output_data, tag):
    """将结果保存到SQLite数据库"""
    if not output_data or not tag:
        logging.error("缺少必要参数: output_data 或 tag")
        return False
    
    with safe_db_connection() as conn:
        cursor = conn.cursor()
        try:
            sql_update_query = '''UPDATE preprocess SET AfterLM = ? WHERE tag = ?'''
            cursor.execute(sql_update_query, (output_data, tag))
            conn.commit()
            logging.info(f"数据成功保存到SQLite，标签: {tag}")
            return True
        except sqlite3.Error as e:
            logging.error(f"SQLite错误: {e}")
            raise


def main():
    # 配置日志输出
    logging.basicConfig(
        level=logging.DEBUG,  # 改为DEBUG级别以显示debug输出
        format='LMWork:%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
        ]
    )

    try:
        # 验证命令行参数
        if len(sys.argv) < 2:
            logging.error("缺少必要的命令行参数: tag")
            sys.exit(1)
        
        tag = sys.argv[1]
        logging.info(f"开始处理标签: {tag}")
        
        # 读取配置
        config = read_config('oqqwall.config')
        if not config.get('apikey'):
            logging.error("配置中缺少API密钥")
            sys.exit(1)
        
        dashscope.api_key = config.get('apikey')
        
        # 读取输入数据
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            logging.error(f"输入JSON解析错误: {e}")
            sys.exit(1)
        
        # === 第一步：先处理图片（压缩、安全检查、描述生成） ===
        logging.info("第一步：开始处理图片（压缩、安全检查、描述生成）...")
        process_images_comprehensive(tag, config, data)
        
        # === 第二步：重新读取处理后的数据（只在有图片处理的情况下） ===
        # 检查是否有图片消息需要合并处理结果（包括forward消息中的图片）
        def has_images_in_data(messages):
            """递归检查消息中是否包含图片（包括forward消息内部的图片）"""
            for item in messages:
                if "message" in item and isinstance(item["message"], list):
                    for msg in item["message"]:
                        if msg.get("type") == "image":
                            return True
                        elif msg.get("type") == "forward" and "data" in msg:
                            # 检查forward消息内部的图片
                            if "messages" in msg["data"] and isinstance(msg["data"]["messages"], list):
                                if has_images_in_data(msg["data"]["messages"]):
                                    return True
                            elif "content" in msg["data"] and isinstance(msg["data"]["content"], list):
                                if has_images_in_data(msg["data"]["content"]):
                                    return True
            return False
        
        has_image_messages = has_images_in_data(data.get("messages", []))
        
        if has_image_messages:
            with safe_db_connection() as conn:
                cur = conn.cursor()
                try:
                    row = cur.execute('SELECT AfterLM FROM preprocess WHERE tag=?', (tag,)).fetchone()
                    if row and row[0] is not None:
                        # 只有在有图片消息时才重新加载数据库中的数据
                        processed_data = json.loads(row[0])
                        
                        # 合并图片处理结果（describe字段）到原始数据
                        image_descriptions = {}
                        
                        # 收集顶层图片消息的描述
                        for item in processed_data.get("messages", []):
                            if "message" in item and isinstance(item["message"], list):
                                for msg in item["message"]:
                                    if msg.get("type") == "image" and "describe" in msg:
                                        # 使用消息ID+类型作为key来匹配
                                        key = f"{item.get('message_id')}_{msg.get('type')}"
                                        image_descriptions[key] = msg["describe"]
                        
                        # 收集additional_images中的描述（来自forward消息中的图片）
                        additional_images = processed_data.get("additional_images", [])
                        additional_descriptions = {}
                        for img_info in additional_images:
                            if "file" in img_info and "description" in img_info:
                                # 使用文件名作为key
                                file_name = img_info["file"]
                                additional_descriptions[file_name] = img_info["description"]
                        
                        # 将描述信息合并到原始数据中
                        def merge_descriptions_recursive(messages, depth=0):
                            """递归合并图片描述到forward消息中"""
                            for item in messages:
                                if "message" in item and isinstance(item["message"], list):
                                    for msg in item["message"]:
                                        if msg.get("type") == "image":
                                            # 首先尝试匹配顶层图片
                                            key = f"{item.get('message_id')}_{msg.get('type')}"
                                            if key in image_descriptions:
                                                msg["describe"] = image_descriptions[key]
                                            else:
                                                # 尝试匹配additional_images中的描述（通过URL文件名）
                                                url = msg.get("data", {}).get("url", "")
                                                if url.startswith("file://"):
                                                    file_name = os.path.basename(url[7:])
                                                    if file_name in additional_descriptions:
                                                        msg["describe"] = additional_descriptions[file_name]
                                                        logging.debug(f"为forward中的图片 {file_name} 添加了描述")
                                        elif msg.get("type") == "forward" and "data" in msg:
                                            # 递归处理forward消息内部的图片
                                            if "messages" in msg["data"]:
                                                merge_descriptions_recursive(msg["data"]["messages"], depth + 1)
                                            elif "content" in msg["data"]:
                                                merge_descriptions_recursive(msg["data"]["content"], depth + 1)
                        
                        merge_descriptions_recursive(data.get("messages", []))
                        
                        logging.info("合并了图片处理结果到原始数据")
                    else:
                        logging.warning(f"未找到标签 {tag} 的记录或AfterLM字段为空，使用原始数据")
                except json.JSONDecodeError as e:
                    logging.error(f"重新加载数据时JSON解析错误: {e}")
                    # 继续使用原始数据
        else:
            logging.info("没有图片消息，直接使用原始输入数据")
        
        # === 第三步：基于 per_type_rules 的精细化删改 ===
        
        # 调试：检查原始数据中的forward消息
        original_forward_count = 0
        for item in data.get("messages", []):
            if "message" in item and isinstance(item["message"], list):
                for msg in item["message"]:
                    if msg.get("type") == "forward":
                        original_forward_count += 1
                        logging.debug(f"原始数据中发现forward消息: {json.dumps(msg, ensure_ascii=False)}")
        
        logging.info(f"原始数据中包含 {original_forward_count} 个forward消息")
        
        lm_messages, origin_messages = make_lm_sanitized_and_original(data)

        # 调试：检查forward消息是否被保留
        forward_count = 0
        for item in lm_messages:
            if "message" in item and isinstance(item["message"], list):
                for msg in item["message"]:
                    if msg.get("type") == "forward":
                        forward_count += 1
                        logging.debug(f"处理后的forward消息: {json.dumps(msg, ensure_ascii=False)}")
        
        logging.info(f"处理后的消息中包含 {forward_count} 个forward消息")

        lm_input = {
            "notregular": data.get("notregular"),
            "messages": lm_messages
        }

        input_content = json.dumps(lm_input, ensure_ascii=False, indent=4)
        timenow = time.time()

        logging.info(f"输入内容长度: {len(input_content)} 字符")
        
        # 构造prompt，详细说明分组和输出要求
        prompt = f"""当前时间 {timenow}
    以下内容是一组按时间顺序排列的校园墙投稿聊天记录：

    {input_content}

    请根据以下标准，提取出这些消息中属于**最后一组投稿**的信息：

    ### 分组标准
    - 通常以关键词"在吗"、"投稿"、"墙"等开始，但这些关键词可能出现在中途或根本不出现。
    - 属于同一组投稿的消息，时间间隔一般较近（通常小于 600 秒），但也存在例外。
    - 投稿内容可能包含文本、图片（image）、视频（video）、文件（file）、戳一戳（poke）、合并转发的聊天记录（forward）等多种类型。
    - 大多数情况下该记录只包含一组投稿，这种情况下认为所有消息都在组中，偶尔可能有多组，需要你自己判断。
    - 信息只可能包含多个完整的投稿，户可能出现半个投稿+一个投稿的情况，如果真的出现了，说明你判断错误，前面那个"半个投稿"，是后面投稿的一部分。

    ### 你需要给出的判断

    - `needpriv`（是否需要匿名）  
    - 如果信息中明确表达"匿名"意图或使用谐音字（如："匿"、"腻"、"拟"、"逆"、"🐎"、"🐴"、"马" 等），则为 `true`。  
    - 当信息仅包含单个含义模糊的字或 emoji 时，也应考虑匿名的可能性。  
    - 否则为 `false`。
    - 如果用户明确说了不匿(也可能是不腻，不码，不马之类的谐音内容)，那么一定为`false`

    - `safemsg`（投稿是否安全）  
    - 投稿若包含攻击性言论、辱骂内容、敏感政治信息，应判定为 `false`。  
    - 否则为 `true`。

    - `isover`（投稿是否完整）  
    - 若投稿者明确表示"发完了"、"没了"、"完毕"等；或投稿语义完整且最后一条消息距离当前时间较远，则为 `true`。  
    - 若存在"没发完"之类的未结束迹象，或最后消息距当前时间较近且不明确，则为 `false`。

    - `notregular`（投稿是否异常）  
    - 若投稿者明确表示"不合常规"或你主观判断此内容异常，则为 `true`。  
    - 否则为 `false`。

    ### 输出格式

    严格按照下面的 JSON 格式输出，仅填写最后一组投稿的 `message_id`，不要输出任何额外的文字或说明：

    ```json
    {{
    "needpriv": "true" 或 "false",
    "safemsg": "true" 或 "false",
    "isover": "true" 或 "false",
    "notregular": "true" 或 "false",
    "messages": [
        "message_id1",
        "message_id2",
        ...
    ]
    }}
    ```
    """

        # 使用流式传输获取模型响应
        logging.info("第二步：开始调用大模型API...")
        final_response = fetch_response_in_parts(prompt, config)
        
        if not final_response:
            logging.error("未获得有效的模型响应")
            sys.exit(1)
        
        final_response = clean_json_output(final_response)
        logging.info(f"模型响应长度: {len(final_response)} 字符")
        
        # 解析并保存最终的JSON响应
        try:
            # 去除markdown格式并加载JSON内容
            cleaned_response = final_response.strip('```json\n').strip('\n```')
            final_response_json = json.loads(cleaned_response)
            
            # 以原始消息为基准恢复 + 按规则裁剪（保留 hide_from_LM_only）
            origin_lookup = {msg["message_id"]: msg for msg in origin_messages}
            final_list = []
            for mid in final_response_json.get("messages", []):
                if mid in origin_lookup:
                    final_list.append(finalize_item_for_output(origin_lookup[mid]))
                else:
                    logging.warning(f"未找到消息ID: {mid}")
            
            final_response_json["messages"] = final_list

            output_data = json.dumps(final_response_json, ensure_ascii=False, indent=4)
            
            # 保存到数据库
            if save_to_sqlite(output_data, tag):
                logging.info("数据保存成功")
            else:
                logging.error("数据保存失败")
                sys.exit(1)

            logging.info("处理完成")

        except json.JSONDecodeError as e:
            logging.error(f"JSON解析错误: {e}")
            logging.error(f"返回内容: {final_response}")
            
            # 保存错误内容到文件
            try:
                with open(output_file_path_error, 'w', encoding='utf-8') as errorfile:
                    errorfile.write(final_response)
                logging.info(f"错误的JSON已保存到: {output_file_path_error}")
            except Exception as save_error:
                logging.error(f"保存错误文件失败: {save_error}")
            
            sys.exit(1)
            
    except KeyboardInterrupt:
        logging.info("用户中断操作")
        sys.exit(0)
    except Exception as e:
        logging.error(f"程序执行过程中发生未预期的错误: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()