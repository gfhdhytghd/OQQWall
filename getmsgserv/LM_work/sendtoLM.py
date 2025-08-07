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
from typing import Dict, Any, List

# 错误JSON输出的文件路径
output_file_path_error = "./cache/LM_error.json"

def read_config(file_path):
    # 读取配置文件，返回字典
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            key, value = line.strip().split('=')
            config[key.strip()] = value.strip().strip('"')
    return config


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


def compress_image(path, max_pixels, size_limit):
    """先尝试把 >8bit 图降到 8bit，再看体积是否达标；不达标再降分辨率到满足 size_limit（也会遵守 max_pixels）。"""
    logging.info(f"开始处理图片: {path}")
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
    except Exception as e:
        logging.error(f"处理图片 {path} 时发生意外错误: {e}", exc_info=True)



def image_safe(path, model, api_key):
    """使用DashScope检测本地图片是否含有不安全内容。"""
    logging.info(f"检测图片安全性: {path}")
    messages = [{
        'role': 'user',
        'content': [
            {'image': 'file://' + os.path.abspath(path)},
            {'text': '这张图片是否含有暴力、血腥、色情、政治敏感，人生攻击或其他敏感内容(发到国内平台，被举报后会导致处罚的都算)？如果安全仅回答safe，否则回答unsafe'}
        ]
    }]
    try:
        response = MultiModalConversation.call(model=model, messages=messages, api_key=api_key)
        if response.status_code == HTTPStatus.OK:
            content = response.output.choices[0].message.content
            if isinstance(content, list):
                content = " ".join(map(str, content))
            result = 'unsafe' not in content.lower()
            logging.info(f"图片安全检测结果: {result}, 原始响应: {content}")
            return result
        else:
            logging.warning(f"图片安全检测返回非200状态码: {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"图片安全检测发生错误: {str(e)}, 错误类型: {type(e)}", exc_info=True)
        return True


def update_safemsg(tag, safe):
    """根据图片安全性结果，更新数据库中的safemsg字段。"""
    conn = sqlite3.connect('./cache/OQQWall.db')
    cur = conn.cursor()
    row = cur.execute('SELECT AfterLM FROM preprocess WHERE tag=?', (tag,)).fetchone()
    if not row:
        conn.close()
        return
    data = json.loads(row[0])
    if not safe:
        data['safemsg'] = 'false'
    updated = json.dumps(data, ensure_ascii=False)
    cur.execute('UPDATE preprocess SET AfterLM=? WHERE tag=?', (updated, tag))
    conn.commit()
    conn.close()


def process_image_safety(tag, config):
    """对指定tag的所有图片进行压缩和安全检测，并更新safemsg。"""
    folder = os.path.join('cache/picture', str(tag))
    logging.info(f"处理tag {tag}的图片安全性检查")
    
    if not os.path.isdir(folder) or not os.listdir(folder):
        logging.info(f"目录 {folder} 不存在或为空，跳过图片处理")
        return
    api_key = config.get('apikey')
    max_pixels = int(config.get('vision_pixel_limit', 12000000))
    size_limit = float(config.get('vision_size_limit_mb', 9.5)) * 1024 * 1024
    model = config.get('vision_model', 'qwen-vl-max-latest')
    dashscope.api_key = api_key

    safe = True
    for file in os.listdir(folder):
        path = os.path.join(folder, file)
        logging.info(f"处理图片: {file}")
        compress_image(path, max_pixels, size_limit)
        if not image_safe(path, model, api_key):
            logging.warning(f"图片 {file} 被标记为不安全")
            safe = False
    
    logging.info(f"图片安全检查完成，结果: {'安全' if safe else '不安全'}")
    update_safemsg(tag, safe)


def fetch_response_in_parts(prompt, config, max_rounds=5):
    # 分多轮流式获取大模型响应，拼接完整输出
    messages = [{'role': 'system', 'content': '你是一个校园墙投稿管理员'},
                {'role': 'user', 'content': prompt}]

    full_response = ""
    round_count = 0
    is_complete = False
    previous_output = ""

    while not is_complete and round_count < max_rounds:
        seed = 1354
        print(f"Round {round_count + 1} - Using seed: {seed}")

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
            repetition_penalty=1.0
        )

        # 处理流式响应
        output_content = ""
        try:
            for response in responses:
                # 只拼接内容，不访问status_code
                chunk = response.output.get('choices', [])[0].get('message', {}).get('content', '')
                output_content += chunk
                sys.stdout.flush()
        except Exception as e:
            print(f"Error in API call: {e}")
            break

        if previous_output:
            # 获取上一次输出的最后100个字符
            overlap_content = previous_output[-100:]
            # 在当前输出的前500字符中查找重叠部分
            start_index = output_content[:500].find(overlap_content)
            if start_index != -1:
                # 如果找到，去除重叠部分
                output_content = output_content[start_index + len(overlap_content):]

        # 更新完整响应
        full_response += output_content
        previous_output = output_content

        # 检查输出是否以结束标志'```'结尾
        if output_content.endswith('```'):
            print("complete!")
            is_complete = True
        else:
            # 截断最后100字符后加入messages，防止重复
            truncated_output = output_content[:-100] if len(output_content) > 100 else output_content
            messages.append({
                'role': Role.ASSISTANT,
                'content': truncated_output
            })
            # 提示模型继续输出，不要重复内容
            messages.append({'role': Role.USER, 'content': '接着上次停下的地方继续输出，不要重复之前的内容，不要重复sender和needpriv等内容，不要在开头重复一遍```json {"time": },{"message": [{"type": ,"data": {，不要在开头重复任何格式内容，直接接着上次结束的那个字继续,但是如果json已经到达末尾，请用\n```结束输出'})
        round_count += 1

    return full_response

def save_to_sqlite(output_data, tag):
    # 将结果保存到SQLite数据库
    db_path = './cache/OQQWall.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        sql_update_query = '''UPDATE preprocess SET AfterLM = ? WHERE tag = ?'''
        cursor.execute(sql_update_query, (output_data, tag))
        conn.commit()
        print(f"Data successfully saved to SQLite for tag: {tag}")
    except sqlite3.Error as e:
        print(f"SQLite error occurred: {e}")
    finally:
        cursor.close()
        conn.close()

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
        "remove_in_data": [],
        "remove_msg": [],
        "remove_event": [],
        "hide_from_LM_only": ["data"]
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

def main():
    # 配置日志输出
    logging.basicConfig(
        level=logging.INFO,
        format='LMWork:%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
        ]
    )

    # 主入口，处理输入、调用模型、保存结果
    config = read_config('oqqwall.config')
    dashscope.api_key = config.get('apikey')
    data = json.load(sys.stdin)
    # === 基于 per_type_rules 的精细化删改 ===
    lm_messages, origin_messages = make_lm_sanitized_and_original(data)

    lm_input = {
        "notregular": data.get("notregular"),
        "messages": lm_messages
    }

    input_content = json.dumps(lm_input, ensure_ascii=False, indent=4)
    timenow = time.time()

    print(f"input content:\n{input_content}\n")
    # 构造prompt，详细说明分组和输出要求
    prompt = f"""当前时间 {timenow}
    以下内容是一组按时间顺序排列的校园墙投稿聊天记录：

    {input_content}

    请根据以下标准，提取出这些消息中属于**最后一组投稿**的信息：

    ### 分组标准
    - 通常以关键词“在吗”、“投稿”、“墙”等开始，但这些关键词可能出现在中途或根本不出现。
    - 属于同一组投稿的消息，时间间隔一般较近（通常小于 600 秒），但也存在例外。
    - 投稿内容可能包含文本、图片（image）、视频（video）、文件（file）、戳一戳（poke）、合并转发的聊天记录（forward）等多种类型。
    - 你无法查看合并转发的聊天记录的内容
    - 大多数情况下该记录只包含一组投稿，这种情况下认为所有消息都在组中，偶尔可能有多组，需要你自己判断。
    - 信息只可能包含多个完整的投稿，户可能出现半个投稿+一个投稿的情况，如果真的出现了，说明你判断错误，前面那个“半个投稿”，是后面投稿的一部分。

    ### 你需要给出的判断

    - `needpriv`（是否需要匿名）  
    - 如果信息中明确表达“匿名”意图或使用谐音字（如：“匿”、“腻”、“拟”、“逆”、“🐎”、“🐴”、“马” 等），则为 `true`。  
    - 当信息仅包含单个含义模糊的字或 emoji 时，也应考虑匿名的可能性。  
    - 否则为 `false`。
    - 如果用户明确说了不匿(也可能是不腻，不码，不马之类的谐音内容)，那么一定为`false`

    - `safemsg`（投稿是否安全）  
    - 投稿若包含攻击性言论、辱骂内容、敏感政治信息，应判定为 `false`。  
    - 否则为 `true`。

    - `isover`（投稿是否完整）  
    - 若投稿者明确表示“发完了”、“没了”、“完毕”等；或投稿语义完整且最后一条消息距离当前时间较远，则为 `true`。  
    - 若存在“没发完”之类的未结束迹象，或最后消息距当前时间较近且不明确，则为 `false`。

    - `notregular`（投稿是否异常）  
    - 若投稿者明确表示“不合常规”或你主观判断此内容异常，则为 `true`。  
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
    final_response = fetch_response_in_parts(prompt, config)
    final_response = clean_json_output(final_response)
    print(f"final response:{final_response}")
    # 解析并保存最终的JSON响应
    try:
        tag = sys.argv[1]
        # 去除markdown格式并加载JSON内容
        final_response_json = json.loads(final_response.strip('```json\n').strip('\n```'))
        # 以原始消息为基准恢复 + 按规则裁剪（保留 hide_from_LM_only）
        origin_lookup = {msg["message_id"]: msg for msg in origin_messages}
        final_list = []
        for mid in final_response_json.get("messages", []):
            if mid in origin_lookup:
                final_list.append(finalize_item_for_output(origin_lookup[mid]))
        final_response_json["messages"] = final_list

        output_data = json.dumps(final_response_json, ensure_ascii=False, indent=4)
        save_to_sqlite(output_data, tag)

        # 压缩并检测图片安全性，更新safemsg
        process_image_safety(tag, config)

    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}\n返回内容: {final_response}")
        with open(output_file_path_error, 'w', encoding='utf-8') as errorfile:
            errorfile.write(final_response)
        print("错误的JSON已保存到:", output_file_path_error)


if __name__ == '__main__':
    main()
