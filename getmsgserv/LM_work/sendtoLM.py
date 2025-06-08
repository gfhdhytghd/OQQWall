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
ImageFile.LOAD_TRUNCATED_IMAGES = True
import re
import sqlite3

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


def compress_image(path, max_pixels, size_limit):
    """调整图片尺寸和压缩图片大小，确保不超过像素和文件大小限制。"""
    logging.info(f"开始处理图片: {path}")
    with Image.open(path) as img:
        width, height = img.size
        pixels = width * height
        logging.info(f"图片尺寸: {width}x{height}, 总像素: {pixels}")
        if pixels > max_pixels:
            ratio = (max_pixels / pixels) ** 0.5
            new_size = (int(width * ratio), int(height * ratio))
            logging.info(f"图片超过像素限制，调整至: {new_size[0]}x{new_size[1]}")
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            img.save(path)
        
        file_size = os.path.getsize(path)
        if file_size > size_limit:
            logging.info(f"图片大小({file_size/1024/1024:.2f}MB)超过限制({size_limit/1024/1024:.2f}MB)，开始压缩")
            quality = 90
            while os.path.getsize(path) > size_limit and quality > 10:
                img.save(path, quality=quality, optimize=True)
                logging.info(f"压缩质量: {quality}, 当前大小: {os.path.getsize(path)/1024/1024:.2f}MB")
                quality -= 5


def image_safe(path, model, api_key):
    """使用DashScope检测本地图片是否含有不安全内容。"""
    logging.info(f"检测图片安全性: {path}")
    messages = [{
        'role': 'user',
        'content': [
            {'image': 'file://' + os.path.abspath(path)},
            {'text': '这张图片是否含有暴力、血腥、色情、政治敏感，人生攻击或其他敏感内容？如果安全仅回答safe，否则回答unsafe'}
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
    # 处理输入数据并移除不需要的字段
    cleaned_messages = []
    fields_to_remove = ['file', 'file_id', 'file_size']

    for item in data.get('messages', []):
        for field in fields_to_remove:
            item.pop(field, None)
        if 'message' in item and isinstance(item['message'], list):
            for message in item['message']:
                if 'data' in message and isinstance(message['data'], dict):
                    for field in fields_to_remove:
                        message['data'].pop(field, None)
        cleaned_messages.append(item)

    output_data = {
        "notregular": data.get("notregular"),
        "messages": cleaned_messages
    }

    input_content = json.dumps(output_data, ensure_ascii=False, indent=4)
    timenow = time.time()

    # 构造prompt，详细说明分组和输出要求
    prompt = f"""当前时间 {timenow}
    以下内容是一组按时间顺序排列的校园墙投稿聊天记录：

    {input_content}

    请根据以下标准，提取出这些消息中属于**最后一组投稿**的信息：

    ### 分组标准
    - 通常以关键词“在吗”、“投稿”、“墙”等开始，但这些关键词可能出现在中途或根本不出现。
    - 属于同一组投稿的消息，时间间隔一般较近（通常小于 600 秒），但也存在例外。
    - 投稿内容可能包含文本、图片（image）、视频（video）等多种类型。
    - 大多数情况下该记录只包含一组投稿，但偶尔可能有多组。

    ### 你需要给出的判断

    - `needpriv`（是否需要匿名）  
    - 如果信息中明确表达“匿名”意图或使用谐音字（如：“匿”、“腻”、“拟”、“逆”、“🐎”、“🐴”、“马” 等），则为 `true`。  
    - 当信息仅包含单个含义模糊的字或 emoji 时，也应考虑匿名的可能性。  
    - 否则为 `false`。
    - 如果用户明确说了不匿，那么一定为`false`

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

        # 将input_content从字符串转换回字典
        input_data_dict = json.loads(input_content)

        # 创建一个从message_id到完整消息的查找字典
        message_lookup = {msg["message_id"]: msg for msg in input_data_dict["messages"]}

        # 用完整的消息数据替换final_response_json中的message_id
        final_response_json["messages"] = [message_lookup[msg_id] for msg_id in final_response_json["messages"] if msg_id in message_lookup]

        # 转换为字符串以便存储
        output_data = json.dumps(final_response_json, ensure_ascii=False, indent=4)
        
        # 保存到SQLite数据库
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
