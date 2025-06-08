import json
import time
import sys
import random
import os
import dashscope
from http import HTTPStatus
from dashscope import Generation, MultiModalConversation
from dashscope.api_entities.dashscope_response import Role
from PIL import Image
import re
import sqlite3

# File path used to save erroneous JSON output
output_file_path_error = "./cache/LM_error.json"

def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            key, value = line.strip().split('=')
            config[key.strip()] = value.strip().strip('"')
    return config


def insert_missing_commas(json_like_string):
    # 正则表达式检测可能缺少逗号的地方
    missing_comma_pattern = re.compile(r'(\})(\s*[\{\[])')
    
    # 在可能缺少逗号的地方插入逗号
    corrected_json = missing_comma_pattern.sub(r'\1,\2', json_like_string)
    
    return corrected_json


def clean_json_output(output_content):
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
    """Resize and recompress the image so it satisfies pixel and size limits."""
    with Image.open(path) as img:
        width, height = img.size
        pixels = width * height
        if pixels > max_pixels:
            ratio = (max_pixels / pixels) ** 0.5
            new_size = (int(width * ratio), int(height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            img.save(path)
        if os.path.getsize(path) > size_limit:
            quality = 90
            while os.path.getsize(path) > size_limit and quality > 10:
                img.save(path, quality=quality, optimize=True)
                quality -= 5


def image_safe(path, model, api_key):
    """Check whether a local image contains unsafe content using DashScope."""
    messages = [{
        'role': 'user',
        'content': [
            {'image': 'file://' + os.path.abspath(path)},
            {'text': '这张图片是否含有暴力、血腥、色情或其他违法内容？如果安全仅回答safe，否则回答unsafe'}
        ]
    }]
    try:
        rsp = MultiModalConversation.call(model=model, messages=messages, api_key=api_key)
        if rsp.status_code == HTTPStatus.OK:
            content = rsp.output.get('choices', [])[0].get('message', {}).get('content', '')
            return 'unsafe' not in content.lower()
    except Exception:
        pass
    return True


def update_safemsg(tag, safe):
    """Update the safemsg field in the database according to the result."""
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
    """Compress and scan all images for a tag and update safemsg."""
    folder = os.path.join('cache/picture', str(tag))
    # Skip if there is no picture directory or it is empty
    if not os.path.isdir(folder) or not os.listdir(folder):
        return
    api_key = config.get('apikey')
    max_pixels = int(config.get('vision_pixel_limit', 12000000))
    size_limit = float(config.get('vision_size_limit_mb', 9.5)) * 1024 * 1024
    model = config.get('vision_model', 'qwen-vl-max-latest')
    dashscope.api_key = api_key

    safe = True
    for file in os.listdir(folder):
        path = os.path.join(folder, file)
        compress_image(path, max_pixels, size_limit)
        if not image_safe(path, model, api_key):
            safe = False

    update_safemsg(tag, safe)


def fetch_response_in_parts(prompt, max_rounds=5):
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
        for response in responses:
            if response.status_code == HTTPStatus.OK:
                chunk = response.output.get('choices', [])[0].get('message', {}).get('content', '')
                output_content += chunk
                #sys.stdout.write(chunk)  # 实时打印每个chunk
                sys.stdout.flush()
            else:
                print(f"Ecesrror in API call: {response.status_code}, {response.message}")
                break
        #print(output_content)
        if previous_output:
            # Get the last 100 characters of the previous output
            overlap_content = previous_output[-100:]
            # Search for these 100 characters within the first 500 characters of the current output
            start_index = output_content[:500].find(overlap_content)
            if start_index != -1:
                # If found, remove everything before this occurrence
                output_content = output_content[start_index + len(overlap_content):]

        # Update the full response
        full_response += output_content
        previous_output = output_content

        # Check if the response contains the ending indicator '```'
        if output_content.endswith('```'):
            print("complete!")
            is_complete = True
        else:
            # Truncate the last 100 characters before adding to messages
            truncated_output = output_content[:-100] if len(output_content) > 100 else output_content
            messages.append({
                'role': Role.ASSISTANT,
                'content': truncated_output
            })
            # Prompt the model to continue without repeating content
            messages.append({'role': Role.USER, 'content': '接着上次停下的地方继续输出，不要重复之前的内容，不要重复sender和needpriv等内容，不要在开头重复一遍```json {"time": },{"message": [{"type": ,"data": {，不要在开头重复任何格式内容，直接接着上次结束的那个字继续,但是如果json已经到达末尾，请用\n```结束输出'})
        round_count += 1

    return full_response

def save_to_sqlite(output_data, tag):
    # SQLite database file path
    db_path = './cache/OQQWall.db'
    
    # Connect to the SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Update the `AfterLM` column in the table for the given tag
    try:
        # Prepare the SQL update statement
        sql_update_query = '''UPDATE preprocess SET AfterLM = ? WHERE tag = ?'''
        # Execute the update query with the final_response_json and tag
        cursor.execute(sql_update_query, (output_data, tag))
        
        # Commit the transaction
        conn.commit()
        
        # Print success message
        print(f"Data successfully saved to SQLite for tag: {tag}")
    except sqlite3.Error as e:
        print(f"SQLite error occurred: {e}")
    finally:
        # Close the cursor and connection
        cursor.close()
        conn.close()

def main():
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
    final_response = fetch_response_in_parts(prompt)
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

        # Convert the final JSON response to a string for storage
        output_data = json.dumps(final_response_json, ensure_ascii=False, indent=4)
        
        # Save the result into the SQLite database
        save_to_sqlite(output_data, tag)

        # Compress and scan associated images, if present, then update safemsg
        process_image_safety(tag, config)

    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}\n返回内容: {final_response}")
        with open(output_file_path_error, 'w', encoding='utf-8') as errorfile:
            errorfile.write(final_response)
        print("错误的JSON已保存到:", output_file_path_error)


if __name__ == '__main__':
    main()
