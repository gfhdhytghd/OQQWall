import json
import time
import sys
import random
import dashscope
from http import HTTPStatus
from dashscope import Generation
from dashscope.api_entities.dashscope_response import Role
import re


def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            key, value = line.strip().split('=')
            config[key.strip()] = value.strip().strip('"')
    return config


def fetch_response_in_parts(prompt, max_rounds=5):
    messages = [{'role': 'system', 'content': '你是一个校园墙投稿管理员'},
                {'role': 'user', 'content': prompt}]

    full_response = ""
    round_count = 0
    is_complete = False

    while not is_complete and round_count < max_rounds:
        seed = random.randint(1, 10000)
        print(f"Round {round_count + 1} - Using seed: {seed}")

        # 使用流式输出方式调用生成模型
        responses = Generation.call(
            model='qwen2-72b-instruct',
            messages=messages,
            seed=seed,
            result_format='message',
            stream=True,
            incremental_output=True,
            max_tokens=6000,
            temperature=0.50,
            repetition_penalty=1.0
        )

        # 处理流式响应
        output_content = ""
        for response in responses:
            if response.status_code == HTTPStatus.OK:
                chunk = response.output.get('choices', [])[0].get('message', {}).get('content', '')
                output_content += chunk
                sys.stdout.write(chunk)  # 实时打印每个chunk
                sys.stdout.flush()
            else:
                print(f"Error in API call: {response.status_code}, {response.message}")
                break

        if round_count > 0:
            # 只处理从第二轮开始的输出内容
            start_index = output_content.find("```json")
            if start_index != -1:
                end_index = start_index
                while end_index < len(output_content):
                    if '\u4e00' <= output_content[end_index] <= '\u9fff':  # 检查是否有汉字
                        break
                    end_index += 1
                output_content = output_content[:start_index] + output_content[end_index:]

        full_response += output_content

        # 检查响应是否包含结束标志
        if output_content.endswith('```'):
            is_complete = True
        else:
            messages.append({
                'role': Role.ASSISTANT,
                'content': output_content
            })
            messages.append({'role': Role.USER, 'content': '接着上次停下的地方继续输出，不要重复之前的内容，不要重复sender和needpriv等内容，不要在开头重复一遍```json {"time": },{"message": [{"type": ,"data": {，不要在开头重复任何格式内容，直接接着上次结束的那个字继续'})


        round_count += 1

    return full_response


def main():
    config = read_config('oqqwall.config')
    dashscope.api_key = config.get('apikey')

    input_file = sys.argv[1]
    output_file = sys.argv[1]

    input_file_path = f'./getmsgserv/post-step1/{input_file}.json'
    output_file_path = f'./getmsgserv/post-step2/{output_file}.json'

    with open(input_file_path, 'r', encoding='utf-8') as infile:
        data = json.load(infile)

    cleaned_messages = []
    fields_to_remove = ['message_id', 'file', 'file_id', 'file_size']

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
        "sender": data.get("sender"),
        "notregular": data.get("notregular"),
        "messages": cleaned_messages
    }

    input_content = json.dumps(output_data, ensure_ascii=False, indent=4)
    timenow = time.time()

    prompt = (
        "当前时间"f"{timenow}\n"
        f"{input_content}\n\n"
        "这是按照时间顺序排序的一组的校园墙投稿的聊天记录\n"
        "将这里你认为需要放在同一稿件中，属于同一组事件的信息拆分出来，一组信息通常以在吗或者投稿或者墙之类的词语开始，但有时此类词语也会在中间才出现或者不出现,有时这些信息会包含image或者video,通常这些信息time会比较接近（大多数情况下time差距在600内,但也有例外），大部分情况下这整个记录里只包含一个稿件的内容（偶尔有例外），如果你认为这里只有一个稿件，那么所有内容都是一组中的，输出为json格式(需要```json开头和```结尾)，只输出最后一组，不要输出任何额外内容\n\n"
        "输出格式如下：\n"
        "{\n"
        "  \"sender\": {\n"
        "    #直接抄写即可\n"
        "    \"user_id\": ,\n"
        "    \"nickname\": ,\n"
        "    \"sex\": \n"
        "  },\n"
        "  \"needpriv\": \"true\"/\"false\",\n"
        "  # 判断这条信息是否需要匿名\n"
        "  # 有时匿名意思会通过“匿”或者”码”的谐音字传达（比如逆，腻，拟或者马，吗，嘛），有时也会通过“🐎”“🐴”之类的emojy传达\n"
        "  # 凡遇到只有一字意义不明的消息组，就要考虑一下这个字是否传达了匿名意思"
        "  \"safemsg\": \"true\"/\"false\",\n"
        "  # 判断这条信息是否可以过审（是否含有攻击性信息或者政治信息）\n"
        "  \"isover\": \"true\"/\"false\",\n"
        "  # 判断他有没有说完，通常通过用语义来判断，检查记录中是否有“没发完”“发完了”一类的语句，判断已经发来的内容是否构成一个完整的稿件,也可以通过time判断,在最后一条消息的time距离timenow很久远的情况下可以判断为完整稿件,只有在非常肯定他发完了的情况下才为true\n"
        "  \"notregular\": \"true/false\",\n"
        "  # 直接抄写即可"
        "  \"messages\": [\n"
        "    # 接下来输出分好组的message信息\n"
        "    {\n"
        "      \"message\": [\n"
        "        {\n"
        "          \"type\": ,\n"
        "          \"data\": {\n"
        "            # 填写数据\n"
        "          }\n"
        "        }\n"
        "      ],\n"
        "      \"time\": \n"
        "    }\n"
        "  ]\n"
        "  \"why\": {\n"
        "  #在此填写你分段和填写各项目的依据与理由和原因\n"
        "   }\n"
        "}"
    )

    # 使用流式传输获取模型响应
    final_response = fetch_response_in_parts(prompt)

    try:
        formatted_data = json.loads(final_response.strip('```json\n').strip('\n```'))
        with open(output_file_path, 'w', encoding='utf-8') as outfile:
            json.dump(formatted_data, outfile, ensure_ascii=False, indent=4)
        print("处理完成，输出已保存到:", output_file_path)
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}\n返回内容: {final_response}")


if __name__ == '__main__':
    main()
