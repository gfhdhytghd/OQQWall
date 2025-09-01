import json
import time
import sys
import random
import os
import logging
import dashscope
from http import HTTPStatus
from dashscope import Generation, MultiModalConversation
# from dashscope.api_entities.dashscope_response import Role  # 不再需要，已删除多轮对话
from PIL import Image
from PIL import ImageFile
from PIL import UnidentifiedImageError
ImageFile.LOAD_TRUNCATED_IMAGES = True
import re
import regex
import unicodedata
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

# ============================================================================
# 配置区域：词典、规则、提示词模板
# ============================================================================

# 日志配置
LOG_FILE_PATH = './logs/sendtoLM_debug.log'
ENABLE_FILE_LOGGING = True  # 是否启用文件日志记录（设为False则只输出到控制台）

def get_logging_config():
    """动态生成日志配置，确保日志目录存在"""
    handlers = [logging.StreamHandler()]  # 始终输出到控制台
    
    # 如果启用文件日志，添加文件处理器
    if ENABLE_FILE_LOGGING:
        # 确保日志目录存在
        log_dir = os.path.dirname(LOG_FILE_PATH)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # 创建文件处理器，带有轮转功能
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH, 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        handlers.append(file_handler)
        
        # 打印日志文件位置信息（仅在第一次时打印）
        print(f"日志同时输出到文件: {os.path.abspath(LOG_FILE_PATH)}")
    
    return {
        'level': logging.DEBUG,
        'format': 'LMWork:%(asctime)s - %(levelname)s - %(message)s',
        'handlers': handlers
    }

# 明确"要匿名"的正向信号（命中任一则偏向 needpriv=true）
POSITIVE_PATTERNS = [
    r"(求|请|要|需要|帮我|给我)?(打?马|打?码|马赛克)",   # 求打码/打马
    r"(匿名|匿)(一下|处理|发)?",                     # 匿名/匿一下
    r"别(显示|露|暴露)(我的)?(名字|姓名|id|qq|q号|号)", # 别显示名字/ID
    r"(不要|别|不想)实名",                           # 不要实名=要匿名
    r"不留名",                                       # 不留名
    r"(代发|帮朋友(匿名)?发|代po)",                  # 代发/帮朋友匿名发
    r"(走马|走码)",                                  # 口语
    r"(匿下|腻|拟|逆|尼)",                          # 谐音变体
    r"🙈|🐎|🐴|🆔|🔒",                             # 表情符号
    r"(打|加|上)马赛克",                            # 打马赛克
    r"(隐藏|遮挡|屏蔽)(姓名|名字|id|账号)",          # 隐藏信息
]

# 明确"不匿名/公开"的反向信号（命中任一则偏向 needpriv=false）  
NEGATIVE_PATTERNS = [
    r"不(用|要)?(匿名|匿)",                          # 不匿名/不用匿名
    r"不(用|要)?打?马",                              # 不用打马
    r"不(用|要)?打?码",                              # 不用打码
    r"不(用|要)?(马赛克)",                           # 不用马赛克
    r"不(用|要)?(腻|拟|逆|尼)",                      # 不腻/不拟等（谐音否定）
    r"(?<!不要)(?<!不想)(?<!别)(实名|公开|可留名|署名)", # 实名/公开等（但排除"不要实名"等）
    r"可以?(挂|显示)(我|id|账号|名字)",              # 可以挂我ID等
    r"(直接|就)发",                                  # 直接发
    r"(不用|无需)(匿名|打码|马赛克)",                # 不用匿名等
]

# 图像中若出现疑似个人信息的提示词（弱信号；仅加权）
IMAGE_PRIV_SIGNALS = [
    r"(姓名|真实?姓名|学号|工号|手机号|电话|身份证|名片|二维码|微信|qq号?|学生证|校园卡|课表|住址|邮箱)",
    r"(个人信息|联系方式|联系电话|手机|微信号|qq号)",
    r"(证件|学生卡|工作证|身份证明)",
]

# 安全检查规则（简化版本，可扩展为更复杂的规则系统）
UNSAFE_PATTERNS = [
    r"(傻逼|草泥马|fuck|shit|妈的|操你|去死|滚)",  # 基础脏话
    r"(法轮功|六四|天安门|习近平|毛泽东|共产党)",    # 政治敏感（简化示例）
    r"(人身攻击|恶意中伤|网络暴力)",              # 攻击性
]

# LLM兜底判断的提示词模板
LLM_PRIVACY_PROMPT_TEMPLATE = """你是内容安全与意图判定助手。基于下面的投稿文本内容，判断"是否需要匿名(needpriv)"。
只在出现明确表达（包括否定表达、谐音、口语、emoji）或明显隐私线索时才判定为 true/false；否则应基于常识给出合理判断并说明不确定性。

示例(要匿名)：
- "求打马""帮我匿名一下""不要实名""代发/帮朋友匿名发""别显示名字/ID""匿一下""🙈""🐎"
- "腻""拟""逆""打码""马赛克""走马""走码"

示例(不匿名)：
- "不匿名""实名/公开""可以挂我ID/署名""不用打码/马""直接发"

注意否定作用域：
- "不要实名" => 要匿名；"不匿名/公开/实名" => 不匿名；相邻最近表达优先。

请仅以 JSON 输出：
{{
  "needpriv": "true" or "false",
  "reason": "简要依据（引用关键片段）",
  "confidence": 0.0~1.0
}}

投稿文本内容：
{payload}
"""

# 主要分组任务的提示词模板
MAIN_GROUPING_PROMPT_TEMPLATE = """当前时间 {timenow}
以下内容是一组按时间顺序排列的校园墙投稿聊天记录，格式为"消息ID: 内容"：

{input_content}

请根据以下标准，提取出这些消息中属于**最后一组投稿**的信息：

### 分组标准
- 通常以关键词"在吗"、"投稿"、"墙"等开始，但这些关键词可能出现在中途或根本不出现。
- 属于同一组投稿的消息，时间间隔一般较近（通常小于 600 秒），但也存在例外。
- 投稿内容可能包含文本、图片、视频、文件、戳一戳、合并转发的聊天记录等多种类型。
- 大多数情况下该记录只包含一组投稿，这种情况下认为所有消息都在组中，偶尔可能有多组，需要你自己判断。
- 信息只可能包含多个完整的投稿，户可能出现半个投稿+一个投稿的情况，如果真的出现了，说明你判断错误，前面那个"半个投稿"，是后面投稿的一部分。

### 你需要给出的判断

- `isover`（投稿是否完整）  
- 若投稿者明确表示"发完了"、"没了"、"完毕"等；或投稿语义完整且最后一条消息距离当前时间较远，则为 `true`。  
- 若存在"没发完"之类的未结束迹象，或最后消息距当前时间较近且不明确，则为 `false`。

### 输出格式

严格按照下面的 JSON 格式输出，仅填写最后一组投稿的 `message_id`，不要输出任何额外的文字或说明：

```json
{{"isover": "true/false","messages":["message_id1","message_id2",...]}}
```
"""

# 图片安全检查和描述生成的提示词
IMAGE_ANALYSIS_PROMPT = '''请分析这张图片并回答以下两个问题：

1. 安全性检查：这张图片是否含有暴力、血腥、色情、政治敏感，人生攻击或其他敏感内容(发到国内平台，被举报后会导致处罚的都算)？如果安全请回答"safe"，否则回答"unsafe"。

2. 图片描述：请详细描述这张图片的内容，包括图片中的主要元素、场景、颜色、风格等。描述要准确、详细，但不要过于冗长。

请按以下格式回答：
安全性：[safe/unsafe]
描述：[详细描述内容]'''

# 文本内容安全检查的提示词模板
TEXT_SAFETY_PROMPT_TEMPLATE = """你是内容安全审查专家。请分析以下校园墙投稿文本内容的安全性。

投稿文本内容：
{text_content}

请根据以下标准判断内容是否安全：

### 不安全内容包括：
- 暴力威胁、仇恨言论、人身攻击
- 色情、低俗、猥亵内容  
- 政治敏感信息、煽动性言论
- 恶意诽谤、造谣传谣
- 歧视性言论（种族、性别、地域等）
- 自杀、自残等危险行为倡导
- 违法犯罪相关内容
- 严重脏话谩骂、恶意中伤

### 可接受的内容：
- 正常的情感表达和抱怨
- 学术讨论和观点交流
- 日常生活分享
- 轻微的网络用语和俚语
- 善意的玩笑和调侃

请仅以 JSON 格式输出判断结果：
{{
  "safe": true/false,
  "reason": "简要说明判断依据",
  "severity": "low/medium/high"
}}

注意：
- safe: true表示内容安全，false表示不安全
- reason: 说明判断的主要依据
- severity: 如果不安全，标注严重程度（low=轻微违规, medium=中等违规, high=严重违规）
"""

# 重试和API配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒
API_TIMEOUT = 30  # 秒

# 数据库和文件路径配置
DB_PATH = './cache/OQQWall.db'
OUTPUT_FILE_PATH_ERROR = "./cache/LM_error.json"

# 图片处理配置
DEFAULT_MAX_PIXELS = 12000000
DEFAULT_SIZE_LIMIT_MB = 9.5
DEFAULT_VISION_MODEL = 'qwen-vl-max-latest'
DEFAULT_TEXT_MODEL = 'qwen-plus-latest'

# ============================================================================
# 文本标准化与匿名判定规则系统
# ============================================================================

def normalize_text(s: str) -> str:
    """文本标准化：NFKC归一化 + 小写 + 去控制字符 + 压缩空白"""
    if not isinstance(s, str):
        return ""
    # NFKC 归一化 + 小写
    s = unicodedata.normalize("NFKC", s).lower()
    # 去控制字符
    s = regex.sub(r"[\p{C}]+", "", s)
    # 压缩空白
    s = regex.sub(r"\s+", " ", s).strip()
    return s


def extract_text_windows(grouped_messages: list, window: int = 12) -> list[str]:
    """抽取最近 window 条消息中的可读文本（text + image.describe + file name 等）"""
    buf = []
    # 取最后window条消息
    last_msgs = grouped_messages[-window:] if len(grouped_messages) > window else grouped_messages
    
    for item in last_msgs:
        if "message" in item and isinstance(item["message"], list):
            for sub in item["message"]:
                msg_type = sub.get("type", "")
                if msg_type == "text":
                    text_content = sub.get("data", {}).get("text", "")
                    if text_content:
                        buf.append(text_content)
                elif msg_type == "image":
                    # 描述优先
                    if "describe" in sub:
                        buf.append(sub["describe"])
                elif msg_type == "file":
                    file_name = sub.get("data", {}).get("name", "")
                    if file_name:
                        buf.append(file_name)
                elif msg_type == "forward":
                    # 可选：递归 forward 里的内容（这里简化处理）
                    buf.append("[转发的聊天记录]")
    
    return [normalize_text(x) for x in buf if x.strip()]


def rule_needpriv_vote(grouped_messages: list) -> tuple[Optional[bool], dict]:
    """
    基于规则判定匿名倾向
    返回: (倾向结果, 证据字典)
    - 倾向结果: True(要匿名), False(不匿名), None(不确定)
    - 证据字典: 包含命中的模式和文本
    """
    texts = extract_text_windows(grouped_messages, window=12)
    evidence = {"positive": [], "negative": [], "image_hits": []}
    
    # 1) 强规则：最近优先（倒序扫描，命中即返回）
    for idx, text in enumerate(reversed(texts), 1):
        # 先检查反向信号（优先级更高，因为用户明确说不匿名）
        for pat in NEGATIVE_PATTERNS:
            if regex.search(pat, text):
                evidence["negative"].append({
                    "text": text, 
                    "pattern": pat, 
                    "rank": idx
                })
                logging.debug(f"命中反向匿名信号 (rank {idx}): {pat} in '{text[:50]}...'")
                return False, evidence
        
        # 再检查正向信号
        for pat in POSITIVE_PATTERNS:
            if regex.search(pat, text):
                evidence["positive"].append({
                    "text": text, 
                    "pattern": pat, 
                    "rank": idx
                })
                logging.debug(f"命中正向匿名信号 (rank {idx}): {pat} in '{text[:50]}...'")
                return True, evidence
    
    # 2) 弱规则：图片隐私线索（仅加权，不直接定案）
    weak_bias = 0
    for item in grouped_messages:
        if "message" in item and isinstance(item["message"], list):
            for sub in item["message"]:
                if sub.get("type") == "image":
                    desc = normalize_text(sub.get("describe", ""))
                    if desc:
                        for pat in IMAGE_PRIV_SIGNALS:
                            if regex.search(pat, desc):
                                evidence["image_hits"].append({
                                    "desc": desc[:100] + "..." if len(desc) > 100 else desc, 
                                    "pattern": pat
                                })
                                weak_bias += 1
                                logging.debug(f"图片隐私信号: {pat} in '{desc[:50]}...'")
    
    # 记录弱偏向
    if weak_bias > 0:
        logging.debug(f"发现 {weak_bias} 个图片隐私线索，倾向匿名但需LLM确认")
        return None, evidence  # 表示倾向匿名，但仍需 LLM 兜底
    
    # 无任何命中 => 交由 LLM 兜底
    logging.debug("未发现明确的匿名信号，交由LLM判断")
    return None, evidence


def extract_all_text_content(grouped_messages: list) -> str:
    """
    提取所有文本内容用于安全检查
    包括：文本消息、图片描述、文件名、forward消息中的文本等
    """
    text_parts = []
    
    def extract_from_messages(messages):
        """递归提取消息中的文本内容"""
        for item in messages:
            if "message" in item and isinstance(item["message"], list):
                for sub in item["message"]:
                    msg_type = sub.get("type", "")
                    
                    if msg_type == "text":
                        text_content = sub.get("data", {}).get("text", "").strip()
                        if text_content:
                            text_parts.append(text_content)
                    
                    elif msg_type == "image":
                        # 包含图片描述（如果有）
                        if "describe" in sub:
                            desc = sub["describe"].strip()
                            if desc:
                                text_parts.append(f"[图片描述: {desc}]")
                    
                    elif msg_type == "file":
                        # 包含文件名
                        file_name = sub.get("data", {}).get("name", "").strip()
                        if file_name:
                            text_parts.append(f"[文件: {file_name}]")
                    
                    elif msg_type == "json":
                        # 包含json消息的title（如果已经被提取）
                        title = sub.get("title", "")
                        if title:
                            text_parts.append(f"[分享: {title}]")
                        else:
                            # 如果没有title字段，尝试从原始data中提取
                            try:
                                json_data = sub.get("data", {}).get("data", "")
                                if json_data:
                                    parsed_json = json.loads(json_data)
                                    if "meta" in parsed_json and "news" in parsed_json["meta"]:
                                        extracted_title = parsed_json["meta"]["news"].get("title", "")
                                        if extracted_title:
                                            text_parts.append(f"[分享: {extracted_title}]")
                                        else:
                                            text_parts.append("[分享内容]")
                                    else:
                                        prompt = sub.get("data", {}).get("prompt", "")
                                        if prompt:
                                            text_parts.append(f"[分享: {prompt}]")
                                        else:
                                            text_parts.append("[分享内容]")
                                else:
                                    prompt = sub.get("data", {}).get("prompt", "")
                                    if prompt:
                                        text_parts.append(f"[分享: {prompt}]")
                                    else:
                                        text_parts.append("[分享内容]")
                            except (json.JSONDecodeError, KeyError, TypeError):
                                text_parts.append("[分享内容]")
                    
                    elif msg_type == "forward":
                        # 递归处理forward消息中的内容
                        forward_data = sub.get("data", {})
                        if "content" in forward_data and isinstance(forward_data["content"], list):
                            extract_from_messages(forward_data["content"])
                        elif "messages" in forward_data and isinstance(forward_data["messages"], list):
                            extract_from_messages(forward_data["messages"])
    
    extract_from_messages(grouped_messages)
    
    # 合并所有文本，用换行分隔
    combined_text = "\n".join(text_parts)
    return combined_text.strip()


def llm_text_safety_check(text_content: str, config: dict) -> dict:
    """
    使用LLM进行文本安全检查
    返回: {"safe": bool, "reason": str, "severity": str}
    """
    if not text_content or not text_content.strip():
        return {"safe": True, "reason": "无文本内容", "severity": "low"}
    
    if not config:
        logging.error("缺少配置参数")
        return {"safe": True, "reason": "配置错误，默认安全", "severity": "low"}
    
    prompt = TEXT_SAFETY_PROMPT_TEMPLATE.format(text_content=text_content)
    
    try:
        response = fetch_response_simple(prompt, config)
        if not response:
            logging.warning("文本安全检查未获得响应，默认为安全")
            return {"safe": True, "reason": "API无响应，默认安全", "severity": "low"}
        
        # 清理响应并解析JSON
        cleaned_response = response.strip('```json\n').strip('\n```').strip()
        result = json.loads(cleaned_response)
        
        # 验证和标准化结果
        safe = result.get("safe", True)
        if not isinstance(safe, bool):
            safe = str(safe).lower() == "true"
        
        reason = result.get("reason", "")
        if not isinstance(reason, str):
            reason = "LLM判断"
        
        severity = result.get("severity", "low")
        if severity not in ["low", "medium", "high"]:
            severity = "low"
        
        final_result = {
            "safe": safe,
            "reason": reason,
            "severity": severity
        }
        
        logging.info(f"文本安全检查结果: safe={safe}, reason='{reason[:100]}', severity={severity}")
        return final_result
        
    except json.JSONDecodeError as e:
        logging.error(f"文本安全检查JSON解析失败: {e}")
        logging.error(f"原始响应: {response}")
        return {"safe": True, "reason": "解析错误，默认安全", "severity": "low"}
    except Exception as e:
        logging.error(f"文本安全检查异常: {e}")
        return {"safe": True, "reason": "检查异常，默认安全", "severity": "low"}


def simplify_for_llm(grouped_messages: list) -> dict:
    """将分组消息简化为LLM可处理的简洁格式
    返回格式: {"message_id": "content", ...}
    """
    simplified = {}
    
    for item in grouped_messages:
        message_id = item.get("message_id", "")
        if not message_id:
            continue
            
        content_parts = []
        
        if "message" in item and isinstance(item["message"], list):
            for sub in item["message"]:
                msg_type = sub.get("type", "")
                
                if msg_type == "text":
                    text_content = sub.get("data", {}).get("text", "")
                    if text_content:
                        content_parts.append(text_content)
                        
                elif msg_type == "image":
                    # 优先使用描述，如果没有则使用文件名
                    if "describe" in sub:
                        content_parts.append(f"[图片内容]: {sub['describe']}")
                    else:
                        file_name = sub.get("data", {}).get("file", "")
                        if file_name:
                            content_parts.append(f"[图片内容]: {file_name}")
                        else:
                            content_parts.append("[图片内容]: 无描述")
                            
                elif msg_type == "file":
                    file_name = sub.get("data", {}).get("name", "")
                    if file_name:
                        content_parts.append(f"[文件: {file_name}]")
                    else:
                        content_parts.append("[文件]")
                        
                elif msg_type == "forward":
                    # 对于forward消息，提取其中的文本内容
                    forward_content = extract_forward_text_content(sub)
                    if forward_content:
                        # 使用结构化格式存储转发内容
                        content_parts.append({
                            "[转发内容]": forward_content
                        })
                    else:
                        content_parts.append("[转发聊天记录]")
                        
                elif msg_type == "video":
                    file_name = sub.get("data", {}).get("file", "")
                    if file_name:
                        content_parts.append(f"[视频: {file_name}]")
                    else:
                        content_parts.append("[视频]")
                        
                elif msg_type == "audio":
                    content_parts.append("[语音]")
                    
                elif msg_type == "json":
                    # 检查是否已经被make_lm_sanitized_and_original处理过
                    if "title" in sub:
                        # 已经被处理过，直接使用title字段
                        title = sub.get("title", "")
                        if title and title != "[分享内容]":
                            content_parts.append(f"[分享内容]: {title}")
                        else:
                            content_parts.append("[分享内容]: 无标题")
                    else:
                        # 未被处理过，使用原始的extract_json_title函数
                        title = extract_json_title(sub)
                        if title:
                            content_parts.append(f"[分享内容]: {title}")
                        else:
                            content_parts.append("[分享内容]: 无标题")
                        
                elif msg_type == "poke":
                    content_parts.append("[戳一戳]")
                    
                elif msg_type == "reply":
                    # 回复消息，提取引用的文本
                    reply_id = sub.get("data", {}).get("id", "")
                    if reply_id:
                        content_parts.append(f"[回复消息{reply_id}]")
                    else:
                        content_parts.append("[回复]")
                        
                else:
                    content_parts.append(f"[{msg_type}消息]")
        
        # 合并所有内容部分
        if content_parts:
            # 检查是否包含结构化内容（如转发消息）
            has_structured_content = any(isinstance(part, dict) for part in content_parts)
            
            if has_structured_content:
                # 如果有结构化内容，创建混合格式
                result_content = {}
                text_parts = []
                
                for part in content_parts:
                    if isinstance(part, dict):
                        # 结构化内容直接添加
                        result_content.update(part)
                    else:
                        # 普通文本内容收集到text_parts
                        text_parts.append(part)
                
                # 如果有普通文本内容，添加到"文本内容"字段
                if text_parts:
                    result_content["文本内容"] = " ".join(text_parts)
                
                simplified[str(message_id)] = result_content
            else:
                # 纯文本内容，使用原来的格式
                simplified[str(message_id)] = " ".join(content_parts)
        else:
            simplified[str(message_id)] = "[无内容]"
    
    return simplified


def extract_forward_text_content(forward_msg: dict) -> list:
    """从forward消息中提取文本内容，返回文本列表"""
    content_parts = []
    
    def extract_from_content(content_list, depth=0):
        """递归提取forward内容中的文本"""
        if not isinstance(content_list, list) or depth > 3:  # 防止无限递归
            return
            
        for item in content_list:
            if not isinstance(item, dict):
                continue
                
            if "message" in item and isinstance(item["message"], list):
                for msg in item["message"]:
                    if msg.get("type") == "text":
                        text = msg.get("data", {}).get("text", "")
                        if text:
                            content_parts.append(text.strip())  # 保留完整文本，去除首尾空格
                    elif msg.get("type") == "image":
                        content_parts.append("[图片]")
                    elif msg.get("type") == "forward":
                        # 递归处理嵌套forward
                        if depth < 3:
                            extract_from_content(msg.get("data", {}).get("content", []), depth + 1)
                            extract_from_content(msg.get("data", {}).get("messages", []), depth + 1)
    
    # 处理forward消息的content和messages字段
    if "data" in forward_msg:
        extract_from_content(forward_msg["data"].get("content", []))
        extract_from_content(forward_msg["data"].get("messages", []))
    
    # 返回文本列表，过滤空字符串
    return [text for text in content_parts if text.strip()]


def extract_json_title(json_msg: dict) -> str:
    """从json消息中提取标题"""
    try:
        if "data" in json_msg and "data" in json_msg["data"]:
            json_data = json_msg["data"]["data"]
            if isinstance(json_data, str):
                parsed = json.loads(json_data)
                if "meta" in parsed and "news" in parsed["meta"]:
                    return parsed["meta"]["news"].get("title", "")
                elif "meta" in parsed and "miniapp" in parsed["meta"]:
                    return parsed["meta"]["miniapp"].get("title", "")
                elif "meta" in parsed and "contact" in parsed["meta"]:
                    return parsed["meta"]["contact"].get("nickname", "")
        elif "data" in json_msg and "prompt" in json_msg["data"]:
            return json_msg["data"]["prompt"]
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    
    return ""


def llm_needpriv_fallback(text_content: str, config: dict) -> dict:
    """
    LLM兜底判断匿名需求
    返回: {"needpriv": "true"/"false", "reason": "...", "confidence": 0.0~1.0}
    """
    prompt = LLM_PRIVACY_PROMPT_TEMPLATE.format(payload=text_content)

    try:
        response = fetch_response_simple(prompt, config)
        if not response:
            return {"needpriv": "false", "reason": "no-response", "confidence": 0.4}
        
        cleaned = response.strip('```json').strip('```').strip()
        result = json.loads(cleaned)
        
        # 兜底健壮化
        needpriv_val = str(result.get("needpriv", "")).lower().strip()
        result["needpriv"] = "true" if needpriv_val == "true" else "false"
        
        conf = result.get("confidence")
        if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
            result["confidence"] = 0.5
        
        reason = result.get("reason", "")
        if not isinstance(reason, str):
            result["reason"] = "llm-judgment"
        
        logging.debug(f"LLM兜底判断: needpriv={result['needpriv']}, confidence={result['confidence']}, reason='{reason[:100]}'")
        return result
        
    except json.JSONDecodeError as e:
        logging.error(f"LLM兜底判断JSON解析失败: {e}")
        return {"needpriv": "false", "reason": "parse-error", "confidence": 0.4}
    except Exception as e:
        logging.error(f"LLM兜底判断异常: {e}")
        return {"needpriv": "false", "reason": "error", "confidence": 0.3}


# 配置SSL和HTTP设置
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context

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
        
        # 验证必要的配置项，并设置默认值
        if 'text_model' not in config:
            config['text_model'] = DEFAULT_TEXT_MODEL
            logging.info(f"使用默认文本模型: {DEFAULT_TEXT_MODEL}")
        if 'vision_model' not in config:
            config['vision_model'] = DEFAULT_VISION_MODEL
            logging.info(f"使用默认视觉模型: {DEFAULT_VISION_MODEL}")
        
        required_keys = ['apikey']
        missing_keys = [key for key in required_keys if key not in config]
        if missing_keys:
            logging.error(f"配置文件缺少必要项: {missing_keys}")
        
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
            logging.debug(f"图片尺寸: {width}x{height}, 总像素: {pixels}, 模式: {img.mode}, 格式: {fmt_hint or 'N/A'}")

            # === Step 1: 降位深到 8bit（若需要） ===
            if _is_high_bitdepth(img):
                logging.debug("检测到高位深图像，转换到 8bit…")
                # 将所有情况统一转换到 8bit 通道：
                #   有 alpha => RGBA；否则 RGB 或 L
                if "A" in img.getbands():
                    img = img.convert("RGBA")   # RGBA 为 8bit/通道
                else:
                    # 多通道转 RGB，单通道转 L
                    img = img.convert("RGB" if len(img.getbands()) >= 3 else "L")
                _save_with_format(img, path, fmt_hint)
                new_size = os.path.getsize(path)
                logging.debug(f"位深降到 8bit 后大小: {new_size/1024/1024:.2f}MB")

            # 读取最新文件/尺寸状态
            with Image.open(path) as img2:
                fmt_hint = (img2.format or fmt_hint or "").upper()
                width, height = img2.size
                pixels = width * height
            file_size = os.path.getsize(path)

            # 若位深处理后已满足大小要求，并且像素也不超上限，直接返回
            if file_size <= size_limit and pixels <= max_pixels:
                logging.debug("已满足大小与像素限制，结束。")
                return

            # === Step 2a: 若像素数超上限，按上限等比缩放 ===
            if pixels > max_pixels:
                ratio = (max_pixels / float(pixels)) ** 0.5
                new_w, new_h = max(1, int(width * ratio)), max(1, int(height * ratio))
                logging.debug(f"像素超过上限，调整至: {new_w}x{new_h}")
                with Image.open(path) as img2:
                    img2 = img2.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    _save_with_format(img2, path, fmt_hint, quality=85)
                file_size = os.path.getsize(path)
                width, height = new_w, new_h
                pixels = width * height
                logging.debug(f"像素降至上限后大小: {file_size/1024/1024:.2f}MB")

            # === Step 2b: 若仍超 size_limit，再按需降低分辨率（并结合格式化参数） ===
            if file_size > size_limit:
                logging.debug(f"图片大小({file_size/1024/1024:.2f}MB)超过限制({size_limit/1024/1024:.2f}MB)，开始降分辨率/有损压缩…")

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
                        logging.debug(f"PNG 最大压缩后大小: {file_size/1024/1024:.2f}MB")

                        # 若仍然很大（截图/大色彩图常见），尝试调色板 256 色（仍是 PNG，但更小）
                        if file_size > size_limit:
                            logging.debug("尝试 PNG 调色板(256色)以进一步压缩…")
                            pal = img2.convert("P", palette=Image.ADAPTIVE, colors=256)
                            _save_with_format(pal, path, "PNG")
                            file_size = os.path.getsize(path)
                            logging.debug(f"PNG 调色板后大小: {file_size/1024/1024:.2f}MB")

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
                            logging.debug(f"继续降分辨率到 {nw}x{nh}，当前大小: {file_size/1024/1024:.2f}MB")

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
            {'text': IMAGE_ANALYSIS_PROMPT}
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
        max_pixels = int(config.get('vision_pixel_limit', DEFAULT_MAX_PIXELS))
        size_limit = float(config.get('vision_size_limit_mb', DEFAULT_SIZE_LIMIT_MB)) * 1024 * 1024
    except (ValueError, TypeError) as e:
        logging.error(f"配置参数解析错误: {e}")
        return
    
    model = config.get('vision_model', DEFAULT_VISION_MODEL)
    dashscope.api_key = api_key

    # 读取当前数据库中的JSON数据
    with safe_db_connection() as conn:
        cur = conn.cursor()
        try:
            # 优先使用传入的input_data
            if input_data is not None:
                data = input_data
                messages = data.get('messages', [])
                logging.debug("使用传入的input_data")
            else:
                # 首先尝试从preprocess表的AfterLM字段获取数据
                row = cur.execute('SELECT AfterLM FROM preprocess WHERE tag=?', (tag,)).fetchone()
                if row and row[0] is not None:
                    data = json.loads(row[0])
                    messages = data.get('messages', [])
                    logging.debug("从AfterLM字段获取消息数据")
                else:
                    # 如果AfterLM字段为空，从sender表的rawmsg字段获取原始数据
                    logging.debug("AfterLM字段为空，尝试从sender表获取原始消息数据")
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
                    logging.debug("从sender.rawmsg字段获取原始消息数据")
            
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
                                logging.debug(f"跳过处理sub_type={sub_type}的图片，只处理sub_type=0的图片")
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
                                    logging.debug(f"[线程{result['thread_id']}] 成功为图片 {file_name} 添加描述")
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

# 支持更复杂的"按消息类型字段处理"配置：
# - remove_in_data:     从 msg.data 中删除
# - remove_msg:         从 msg 顶层(非data)删除
# - remove_event:       从事件(item)顶层删除（与类型无关的通用字段放在 global_event_rules）
# - hide_from_LM_only:  仅用于发给LM时隐藏，最终输出时会恢复（或保留）
#
# 说明：hide_from_LM_only 使用"点路径"语法，例如：
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
        
        # 只有当有message字段时才添加，但也要检查message是否为空
        if cleaned_item and "message" in cleaned_item and cleaned_item["message"]:
            cleaned_content.append(cleaned_item)
        elif cleaned_item and "message" in cleaned_item:
            # 如果message字段存在但为空，记录警告
            logging.warning(f"发现空的message字段: {cleaned_item}")
    
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
    logging.debug(f"make_lm_sanitized_and_original: 原始消息数量: {len(origin_messages)}")

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

                # 对json类型消息进行特殊处理：提取title字段
                if mtype == "json":
                    logging.debug(f"处理json类型消息: {json.dumps(msg, ensure_ascii=False)[:200]}...")
                    if "data" in msg:
                        try:
                            json_data = msg["data"].get("data", "")
                            if json_data:
                                parsed_json = json.loads(json_data)
                                # 尝试提取title字段 - 使用extract_json_title函数的逻辑
                                title = ""
                                if "meta" in parsed_json and "news" in parsed_json["meta"]:
                                    title = parsed_json["meta"]["news"].get("title", "")
                                elif "meta" in parsed_json and "miniapp" in parsed_json["meta"]:
                                    title = parsed_json["meta"]["miniapp"].get("title", "")
                                elif "meta" in parsed_json and "contact" in parsed_json["meta"]:
                                    title = parsed_json["meta"]["contact"].get("nickname", "")
                                
                                if title:
                                    # 替换原有的data字段为title字段
                                    msg["title"] = title
                                    msg.pop("data", None)
                                    logging.debug(f"提取json消息title: {title}")
                                else:
                                    # 如果没有从meta中提取到title，尝试使用prompt字段
                                    prompt = msg["data"].get("prompt", "")
                                    if prompt:
                                        msg["title"] = prompt
                                        msg.pop("data", None)
                                        logging.debug(f"提取json消息prompt: {prompt}")
                                    else:
                                        msg["title"] = "[分享内容]"
                                        msg.pop("data", None)
                                        logging.debug("json消息无法提取标题，使用默认值")
                            else:
                                # 如果没有data.data字段，尝试使用prompt字段
                                prompt = msg["data"].get("prompt", "")
                                if prompt:
                                    msg["title"] = prompt
                                    msg.pop("data", None)
                                else:
                                    msg["title"] = "[分享内容]"
                                    msg.pop("data", None)
                        except (json.JSONDecodeError, KeyError, TypeError) as e:
                            logging.warning(f"解析json消息失败: {e}")
                            # 如果解析失败，尝试使用prompt字段作为备选
                            prompt = msg["data"].get("prompt", "")
                            if prompt:
                                msg["title"] = prompt
                                msg.pop("data", None)
                            else:
                                msg["title"] = "[分享内容]"
                                msg.pop("data", None)
                    else:
                        logging.warning(f"json消息没有data字段: {json.dumps(msg, ensure_ascii=False)}")

                # msg 顶层删除
                _remove_many(msg, rules.get('remove_msg', []))
                _remove_many(msg, rules.get('hide_from_LM_only', []))  # 对LM隐藏

                # data 内删除
                if isinstance(msg.get("data"), dict):
                    _remove_many(msg, [f"data.{k}" for k in rules.get('remove_in_data', [])])

    logging.debug(f"make_lm_sanitized_and_original: 处理后消息数量: lm_messages={len(lm_messages)}, origin_messages={len(origin_messages)}")
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
def fetch_response_simple(prompt, config):
    """简单的单轮调用大模型获取响应"""
    if not prompt or not config:
        logging.error("缺少必要参数: prompt 或 config")
        return ""
    
    messages = [{'role': 'system', 'content': '你是一个校园墙投稿管理员'},
                {'role': 'user', 'content': prompt}]

    # Debug输出：显示发送给文本模型的输入
    logging.debug(f"发送给文本模型的输入:")
    logging.debug(f"  模型: {config.get('text_model', DEFAULT_TEXT_MODEL)}")
    logging.debug(f"  消息数量: {len(messages)}")
    logging.debug(f"  系统消息: {messages[0]['content']}")
    logging.debug(f"  用户消息长度: {len(messages[1]['content'])} 字符")
    logging.debug(f"  用户消息完整内容: {messages[1]['content']}")

    try:
        seed = 1354
        logging.info(f"调用大模型API - Using seed: {seed}")

        # 使用流式输出方式调用生成模型
        responses = Generation.call(
            model=config.get('text_model', DEFAULT_TEXT_MODEL),
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
        
        # Debug输出：显示接收到的内容
        logging.debug(f"接收到的内容长度: {len(output_content)} 字符")
        logging.debug(f"接收到的内容: {output_content}")
        logging.info("模型响应完成")
        
        return output_content
                
    except Exception as e:
        error_msg = str(e).lower()
        if 'ssl' in error_msg or 'connection' in error_msg or 'timeout' in error_msg:
            logging.error(f"网络错误: {e}")
        else:
            logging.error(f"API调用错误: {e}")
        raise


@retry_on_exception(max_retries=2, exceptions=(Exception,))
def judge_privacy_and_safety(grouped_messages, config):
    """
    对分好组的消息进行隐私和安全判断
    使用"规则优先 + LLM 兜底 + 冲突仲裁"策略
    """
    if not grouped_messages:
        logging.error(f"缺少必要参数: grouped_messages 为空或None, 类型: {type(grouped_messages)}, 长度: {len(grouped_messages) if isinstance(grouped_messages, (list, dict)) else 'N/A'}")
        return "false", "true"  # 默认值：不需要匿名，安全
    
    if not config:
        logging.error(f"缺少必要参数: config 为空或None, 类型: {type(config)}")
        return "false", "true"  # 默认值：不需要匿名，安全
    
    logging.info("开始进行隐私和安全判断...")
    
    # === 第一步：本地规则优先判断 needpriv ===
    rule_result, evidence = rule_needpriv_vote(grouped_messages)
    
    needpriv_reason = ""
    if rule_result is True:
        needpriv = "true"
        needpriv_reason = "local-rule: positive signal"
        if evidence.get("positive"):
            hit = evidence["positive"][0]  # 取最近的命中
            needpriv_reason += f" | hit: '{hit['pattern']}' in '{hit['text'][:50]}...'"
        logging.info(f"规则判定：需要匿名 - {needpriv_reason}")
        
    elif rule_result is False:
        needpriv = "false"
        needpriv_reason = "local-rule: negative signal"
        if evidence.get("negative"):
            hit = evidence["negative"][0]  # 取最近的命中
            needpriv_reason += f" | hit: '{hit['pattern']}' in '{hit['text'][:50]}...'"
        logging.info(f"规则判定：不需要匿名 - {needpriv_reason}")
        
    else:
        # === 不确定或仅弱倾向 -> 调用 LLM 兜底 ===
        logging.info("规则未能明确判定，调用LLM兜底...")
        all_text_content = extract_all_text_content(grouped_messages)
        llm_result = llm_needpriv_fallback(all_text_content, config)
        
        needpriv = llm_result.get("needpriv", "false")
        needpriv_reason = f"llm-fallback: {llm_result.get('reason', '')}, conf={llm_result.get('confidence', 0)}"
        
        # === 图片隐私弱信号加权 ===
        if evidence.get("image_hits") and llm_result.get("confidence", 0) < 0.6:
            needpriv = "true"
            needpriv_reason += f" | boosted-by-image-privacy-signal (hits: {len(evidence['image_hits'])})"
            logging.info(f"LLM低置信度({llm_result.get('confidence', 0)})，由图片隐私信号提升为匿名")
        
        logging.info(f"LLM兜底判定：needpriv={needpriv} - {needpriv_reason}")
    
    # === 第二步：安全性判断（safemsg）===
    # 使用LLM进行文本安全检查
    safemsg = "true"  # 默认安全
    safemsg_reason = "default-safe"
    
    # 提取所有文本内容
    all_text_content = extract_all_text_content(grouped_messages)
    
    if all_text_content:
        logging.info("开始LLM文本安全检查...")
        safety_result = llm_text_safety_check(all_text_content, config)
        
        if not safety_result.get("safe", True):
            safemsg = "false"
            safemsg_reason = f"LLM判定不安全: {safety_result.get('reason', '')}, 严重程度: {safety_result.get('severity', 'unknown')}"
            logging.warning(f"LLM判定文本内容不安全: {safety_result}")
        else:
            safemsg_reason = f"LLM判定安全: {safety_result.get('reason', '')}"
            logging.info(f"LLM判定文本内容安全: {safety_result.get('reason', '')}")
    else:
        safemsg_reason = "无文本内容，默认安全"
        logging.debug("无文本内容可检查，保持默认安全状态")
    
    # 记录判定依据（可选：用于调试和审计）
    judgment_log = {
        "needpriv": needpriv,
        "needpriv_reason": needpriv_reason,
        "safemsg": safemsg,
        "safemsg_reason": safemsg_reason,
        "evidence": {
            "positive_hits": len(evidence.get("positive", [])),
            "negative_hits": len(evidence.get("negative", [])),
            "image_privacy_hits": len(evidence.get("image_hits", []))
        }
    }
    
    logging.debug(f"判定详情: {json.dumps(judgment_log, ensure_ascii=False, indent=2)}")
    logging.info(f"最终判定结果: needpriv={needpriv}, safemsg={safemsg}")
    
    return needpriv, safemsg


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
    logging.basicConfig(**get_logging_config())

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
        
        logging.info("读取config完成")
        # 读取输入数据
        try:
            data = json.load(sys.stdin)
            logging.debug(data)
        except json.JSONDecodeError as e:
            logging.error(f"输入JSON解析错误: {e}")
            sys.exit(1)
        
        

        # === 第一步：先处理图片（压缩、安全检查、描述生成） ===
        logging.info("第一步：开始处理图片（压缩、安全检查、描述生成）...")
        
        # 检查data的类型，如果是列表则转换为字典格式
        if isinstance(data, list):
            data = {"messages": data}
            logging.debug("检测到输入数据是列表格式，已转换为字典格式")
        
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
        logging.debug(f"make_lm_sanitized_and_original 返回: lm_messages 长度={len(lm_messages)}, origin_messages 长度={len(origin_messages)}")

        # 调试：检查forward消息是否被保留
        forward_count = 0
        for item in lm_messages:
            if "message" in item and isinstance(item["message"], list):
                for msg in item["message"]:
                    if msg.get("type") == "forward":
                        forward_count += 1
                        logging.debug(f"处理后的forward消息: {json.dumps(msg, ensure_ascii=False)}")
        
        logging.info(f"处理后的消息中包含 {forward_count} 个forward消息")

        # 使用新的简化格式
        simplified_input = simplify_for_llm(lm_messages)
        
        input_content = json.dumps(simplified_input, ensure_ascii=False, separators=(',', ':'))
        timenow = time.time()

        logging.info(f"输入内容长度: {len(input_content)} 字符")
        
        # 构造prompt，详细说明分组和输出要求
        prompt = MAIN_GROUPING_PROMPT_TEMPLATE.format(
            timenow=timenow,
            input_content=input_content
        )

        # 使用简单的单轮调用获取模型响应
        logging.info("第二步：开始调用大模型API进行分组...")
        final_response = fetch_response_simple(prompt, config)
        
        if not final_response:
            logging.error("未获得有效的模型响应")
            sys.exit(1)
        
        final_response = clean_json_output(final_response)
        logging.info(f"模型响应长度: {len(final_response)} 字符")
        
        # 解析并保存最终的JSON响应
        try:
            # 去除markdown格式并加载JSON内容
            cleaned_response = final_response.strip('```json\n').strip('\n```')
            logging.debug(f"清理后的响应内容: {cleaned_response[:500]}...")
            final_response_json = json.loads(cleaned_response)
            logging.debug(f"解析后的JSON结构: {json.dumps(final_response_json, ensure_ascii=False, indent=2)}")
            
            # 以原始消息为基准恢复 + 按规则裁剪（保留 hide_from_LM_only）
            logging.debug(f"origin_messages 长度: {len(origin_messages)}")
            if origin_messages:
                logging.debug(f"origin_messages 第一个元素: {json.dumps(origin_messages[0], ensure_ascii=False)[:200]}...")
            logging.debug(f"final_response_json.get('messages', []) 长度: {len(final_response_json.get('messages', []))}")
            logging.debug(f"final_response_json.get('messages', []) 内容: {final_response_json.get('messages', [])}")
            
            origin_lookup = {msg["message_id"]: msg for msg in origin_messages}
            logging.debug(f"origin_lookup 键数量: {len(origin_lookup)}")
            if origin_lookup:
                logging.debug(f"origin_lookup 的键: {list(origin_lookup.keys())[:5]}")
            
            final_list = []
            for mid in final_response_json.get("messages", []):
                # 转换消息ID为整数类型，以匹配origin_lookup的键
                try:
                    mid_int = int(mid) if isinstance(mid, str) else mid
                    if mid_int in origin_lookup:
                        final_list.append(finalize_item_for_output(origin_lookup[mid_int]))
                    else:
                        logging.warning(f"未找到消息ID: {mid} (转换后: {mid_int})")
                except (ValueError, TypeError) as e:
                    logging.warning(f"无法转换消息ID {mid} 为整数: {e}")
            
            logging.debug(f"final_list 长度: {len(final_list)}")
            final_response_json["messages"] = final_list
            
            # === 第三步：对分好组的消息再次调用模型判断 needpriv 和 safemsg ===
            logging.info("第三步：开始调用大模型判断 needpriv 和 safemsg...")
            logging.debug(f"调用 judge_privacy_and_safety 前，final_list 长度: {len(final_list)}")
            logging.debug(f"调用 judge_privacy_and_safety 前，config 类型: {type(config)}")
            if final_list:
                logging.debug(f"final_list 第一个元素: {json.dumps(final_list[0], ensure_ascii=False)[:200]}...")
            
            # 如果 final_list 为空，尝试使用原始消息
            messages_for_judgment = final_list
            if not final_list and origin_messages:
                logging.warning("final_list 为空，使用 origin_messages 进行判断")
                messages_for_judgment = origin_messages
            
            needpriv, safemsg = judge_privacy_and_safety(messages_for_judgment, config)
            
            # 将判断结果添加到最终输出中
            final_response_json["needpriv"] = needpriv
            final_response_json["safemsg"] = safemsg

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
                with open(OUTPUT_FILE_PATH_ERROR, 'w', encoding='utf-8') as errorfile:
                    errorfile.write(final_response)
                logging.info(f"错误的JSON已保存到: {OUTPUT_FILE_PATH_ERROR}")
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


def test_privacy_rules():
    """测试隐私判定规则的准确性"""
    test_cases = [
        # 最简单的基础测试用例
        {"messages": [{"message": [{"type": "text", "data": {"text": "匿名"}}]}], "expected": "true", "desc": "匿名（最基础）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "不匿"}}]}], "expected": "false", "desc": "不匿（简写）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "不腻"}}]}], "expected": "false", "desc": "不腻（谐音否定）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "匿"}}]}], "expected": "true", "desc": "匿（单字）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "腻"}}]}], "expected": "true", "desc": "腻（谐音单字）"},
        
        # 更多基础单字和简写测试
        {"messages": [{"message": [{"type": "text", "data": {"text": "拟"}}]}], "expected": "true", "desc": "拟（谐音单字）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "逆"}}]}], "expected": "true", "desc": "逆（谐音单字）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "尼"}}]}], "expected": "true", "desc": "尼（谐音单字）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "不拟"}}]}], "expected": "false", "desc": "不拟（谐音否定）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "不逆"}}]}], "expected": "false", "desc": "不逆（谐音否定）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "不尼"}}]}], "expected": "false", "desc": "不尼（谐音否定）"},
        
        # 明确要匿名的案例
        {"messages": [{"message": [{"type": "text", "data": {"text": "求打马发一下"}}]}], "expected": "true", "desc": "求打马"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "帮我匿名一下"}}]}], "expected": "true", "desc": "帮我匿名"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "别显示我的名字"}}]}], "expected": "true", "desc": "别显示名字"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "不要实名"}}]}], "expected": "true", "desc": "不要实名"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "代发"}}]}], "expected": "true", "desc": "代发"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "腻一下"}}]}], "expected": "true", "desc": "腻一下（谐音）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "🙈"}}]}], "expected": "true", "desc": "emoji表情"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "打马赛克"}}]}], "expected": "true", "desc": "打马赛克"},
        
        # 明确不匿名的案例
        {"messages": [{"message": [{"type": "text", "data": {"text": "不匿名"}}]}], "expected": "false", "desc": "不匿名（完整）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "不匿名，直接发"}}]}], "expected": "false", "desc": "不匿名直接发"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "实名发布"}}]}], "expected": "false", "desc": "实名发布"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "可以挂我ID"}}]}], "expected": "false", "desc": "可以挂我ID"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "署名发布"}}]}], "expected": "false", "desc": "署名发布"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "不用打马"}}]}], "expected": "false", "desc": "不用打马"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "公开发布"}}]}], "expected": "false", "desc": "公开发布"},
        
        # 谐音变体测试
        {"messages": [{"message": [{"type": "text", "data": {"text": "拟一下"}}]}], "expected": "true", "desc": "拟一下（谐音）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "逆名"}}]}], "expected": "true", "desc": "逆名（谐音）"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "尼一下"}}]}], "expected": "true", "desc": "尼一下（谐音）"},
        
        # 冲突和优先级测试
        {"messages": [{"message": [{"type": "text", "data": {"text": "匿一下"}}, {"type": "text", "data": {"text": "算了不匿名"}}]}], "expected": "false", "desc": "冲突-最近优先"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "不匿名"}}, {"type": "text", "data": {"text": "还是匿一下吧"}}]}], "expected": "true", "desc": "冲突-最近优先2"},
        {"messages": [{"message": [{"type": "text", "data": {"text": "匿"}}, {"type": "text", "data": {"text": "不腻"}}]}], "expected": "false", "desc": "匿vs不腻-最近优先"},
        
        # 图片隐私信号测试
        {"messages": [{"message": [{"type": "image", "describe": "这是一张包含学号和姓名的学生证照片"}]}], "expected": "none", "desc": "图片隐私信号-需LLM"},
        
        # 安全内容测试（这些不会在单元测试中调用LLM，只验证文本提取）
        {"messages": [{"message": [{"type": "text", "data": {"text": "今天天气很好"}}]}], "expected": "none", "desc": "普通文本提取测试"},
    ]
    
    print("=== 开始测试隐私判定规则 ===")
    passed = 0
    total = len(test_cases)
    
    for i, case in enumerate(test_cases, 1):
        try:
            result, evidence = rule_needpriv_vote(case["messages"])
            
            if case["expected"] == "none":
                # 期望交由LLM处理
                success = result is None
            else:
                # 期望明确结果
                expected_bool = case["expected"] == "true"
                success = result == expected_bool
            
            status = "✓ PASS" if success else "✗ FAIL"
            print(f"{i:2d}. {status} | {case['desc']:<20} | 期望: {case['expected']:<5} | 实际: {result}")
            
            if success:
                passed += 1
            else:
                print(f"    证据: {evidence}")
                
        except Exception as e:
            print(f"{i:2d}. ✗ ERROR | {case['desc']:<20} | 异常: {e}")
    
    print(f"\n=== 测试结果: {passed}/{total} 通过 ===")
    return passed == total


def test_text_extraction():
    """测试文本内容提取功能"""
    print("=== 开始测试文本内容提取功能 ===")
    
    test_cases = [
        {
            "messages": [{"message": [{"type": "text", "data": {"text": "这是一条普通文本"}}]}],
            "expected_contains": ["这是一条普通文本"],
            "desc": "简单文本提取"
        },
        {
            "messages": [{"message": [
                {"type": "text", "data": {"text": "文本1"}},
                {"type": "image", "describe": "图片描述内容"},
                {"type": "text", "data": {"text": "文本2"}}
            ]}],
            "expected_contains": ["文本1", "[图片描述: 图片描述内容]", "文本2"],
            "desc": "混合内容提取"
        },
        {
            "messages": [{"message": [{"type": "file", "data": {"name": "test.pdf"}}]}],
            "expected_contains": ["[文件: test.pdf]"],
            "desc": "文件名提取"
        }
    ]
    
    passed = 0
    total = len(test_cases)
    
    for i, case in enumerate(test_cases, 1):
        try:
            result = extract_all_text_content(case["messages"])
            
            # 检查是否包含期望的内容
            success = True
            for expected in case["expected_contains"]:
                if expected not in result:
                    success = False
                    break
            
            status = "✓ PASS" if success else "✗ FAIL"
            print(f"{i:2d}. {status} | {case['desc']:<20}")
            if not success:
                print(f"    期望包含: {case['expected_contains']}")
                print(f"    实际结果: '{result}'")
            
            if success:
                passed += 1
                
        except Exception as e:
            print(f"{i:2d}. ✗ ERROR | {case['desc']:<20} | 异常: {e}")
    
    print(f"\n=== 文本提取测试结果: {passed}/{total} 通过 ===")
    return passed == total


if __name__ == '__main__':
    # 检查是否是测试模式
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # 为测试模式也配置日志
        logging.basicConfig(**get_logging_config())
        logging.info("开始运行测试...")
        
        # 运行隐私规则测试
        logging.info("开始运行隐私规则测试...")
        privacy_result = test_privacy_rules()
        logging.info("隐私规则测试完成")
        
        print()  # 空行分隔
        
        # 运行文本提取测试
        logging.info("开始运行文本提取测试...")
        extraction_result = test_text_extraction()
        logging.info("文本提取测试完成")
        
        # 总结测试结果
        print(f"\n=== 总体测试结果 ===")
        print(f"隐私规则测试: {'通过' if privacy_result else '失败'}")
        print(f"文本提取测试: {'通过' if extraction_result else '失败'}")
        print(f"全部测试: {'✅ 全部通过' if privacy_result and extraction_result else '❌ 存在失败'}")
        
    elif len(sys.argv) > 1 and sys.argv[1] == "--test-text":
        # 仅运行文本提取测试
        logging.basicConfig(**get_logging_config())
        test_text_extraction()
    else:
        main()