import json
import time
import sys
from http import HTTPStatus
import dashscope
def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            key, value = line.strip().split('=')
            config[key.strip()] = value.strip().strip('"')
    return config
    
config = read_config('oqqwall.config')
dashscope.api_key=config.get('apikey')

if len(sys.argv) != 3:
    print("Usage: python3 test.py <input> <output>")
    sys.exit(1)
    
input = sys.argv[1]
output = sys.argv[2]

# 文件路径
input_file_path = f'./getmsgserv/rawpost/{input}.json'
output_file_path = f'./getmsgserv/post-step2/{output}.json'

# 读取JSON文件内容
with open(input_file_path, 'r', encoding='utf-8') as infile:
    data = json.load(infile)

# 遍历数据，删除无意义数据
cleaned_data = []
fields_to_remove = ['message_id', 'file', 'subType', 'file_id', 'file_size']

for item in data:
    # 删除顶层的字段
    for field in fields_to_remove:
        if field in item:
            del item[field]

    # 检查并删除嵌套在 "message" 列表中的字段
    if 'message' in item:
        for message in item['message']:
            if 'data' in message:
                for field in fields_to_remove:
                    if field in message['data']:
                        del message['data'][field]
    
    cleaned_data.append(item)


# 将清理后的数据转换为字符串
input_content = json.dumps(cleaned_data, ensure_ascii=False, indent=4)

timenow =  time.time()

# 构造提示词
prompt = (
    f"{input_content}\n\n"
    f"{timenow}\n"
    "这是按照时间顺序排序的一组的校园墙投稿的聊天记录\n"
    "将这里你认为需要放在同一稿件中，属于同一组事件的信息拆分出来，一组信息通常以在吗或者投稿或者墙之类的词语开始，但有时此类词语也会在中间才出现或者不出现,有时这些信息会包含image或者video,通常这些信息time会比较接近（大多数情况下time差距在600内,但也有例外），大部分情况下这整个记录里只包含一个稿件的内容（偶尔有例外），如果你认为这里只有一个稿件，那么所有内容都是一组中的，输出为json格式，只输出最后一组，不要输出任何额外内容,不要输出任何额外内容\n\n"
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
    "  \"safemsg\": \"true\"/\"false\",\n"
    "  # 判断这条信息是否可以过审（是否含有攻击性信息或者政治信息）\n"
    "  \"isover\": \"true\"/\"false\",\n"
    "  # 判断他有没有说完，通常通过用语义来判断，检查记录中是否有“没发完”“发完了”一类的语句，判断已经发来的内容是否构成一个完整的稿件,也可以通过time判断,在最后一条消息的time距离timenow很久远的情况下可以判断为完整稿件,只有在非常肯定他发完了的情况下才为true\n"
    "  \"notregular\": \"true/false\",\n"
    "  # 判断这条信息是否需要非常规,规则如下"
    "  #任何一个\"message\" [\"type\"的值,\"text\"/\"image\"的为常规,其他的,比如含有video,record,poke等的即为非常规"
    "  #内容中要求对之前发送的稿件进行修改或撤回等操作的为非常规"
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


# 调用Qwen模型
response = dashscope.Generation.call(
    model='qwen2-72b-instruct',
    prompt=prompt,
    seed=1234,
    top_p=0.8,
    result_format='message',
    max_tokens=1500,
    temperature=0.85,
    repetition_penalty=1.0
)

# 处理Qwen的响应
if response.status_code == HTTPStatus.OK:
    response_content = response.output  # 直接获取response的output字段

    # 提取choices字段内容
    choices = response_content.get('choices', [])
    if choices:
        # 获取第一个choice的内容
        message_content = choices[0].get('message', {}).get('content', '')
        
        if message_content:
            # 去掉JSON标记并解析
            message_content = message_content.strip('```json\n').strip('\n```')
            try:
                formatted_data = json.loads(message_content)
                
                # 将格式化后的内容保存到指定路径
                with open(output_file_path, 'w', encoding='utf-8') as outfile:
                    json.dump(formatted_data, outfile, ensure_ascii=False, indent=4)
                
                print("处理完成，输出已保存到:", output_file_path)
            except json.JSONDecodeError as e:
                print(f"JSON解析错误: {e}\n返回内容: {message_content}")
        else:
            print("返回内容为空。")
    else:
        print("没有返回有效的内容。")
else:
    print('Request id: %s, Status code: %s, error code: %s, error message: %s' % (
        response.request_id, response.status_code,
        response.code, response.message
    ))
