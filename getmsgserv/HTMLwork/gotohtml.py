import json
import sys

if len(sys.argv) != 2:
    print("Usage: python3 test.py <input>")
    sys.exit(1)
    
input = sys.argv[1]

# 从指定路径读取 JSON 数据
input_file_path = f"./getmsgserv/post-step2/{input}.json"
output_file_path = f"./getmsgserv/post-step3/{input}.html"

with open(input_file_path, "r", encoding="utf-8") as file:
    json_data = json.load(file)

userid=json_data["sender"]["user_id"]

# 检查 needpriv 和 safemsg，并根据条件修改 user_id 和 nickname
if json_data.get("needpriv") == "true" and json_data.get("safemsg") == "true":
    json_data["sender"]["user_id"] = 10000
    userid = “”
    json_data["sender"]["nickname"] = "匿名"

# 生成 HTML 内容
html_template = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{nickname}</title>
    <style>
        @page {{
          margin: 0!important;
          margin-top: 0cm!important;
          margin-bottom: 0cm!important;
          margin-left: 0cm!important;
          margin-right: 0cm!important;
          size:4in 8in;
        }}
        body {{
            font-family: Arial, sans-serif;
            background-color: #f2f2f2;
            margin: 0;
            padding: 5px;
        }}
        .container {{
             max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            border-radius: 10px;
        }}
        .header {{
            display: flex;
            align-items: center;
        }}
        .header img {{
            border-radius: 50%;
            width: 50px;
            height: 50px;
            margin-right: 10px;
        }}
                .header-text {{
            display: block;
        }}
        .header h1 {{
            font-size: 24px;
            margin: 0;
        }}
        .header h2 {{
            font-size: 12px;
            margin: 0;
        }}
        .content {{
            margin-top: 20px;
        }}
        .content div{{
            display: block;
            background-color: #ffffff;
            border-radius: 10px;
            padding: 10px;
            margin-bottom: 10px;
            word-break: break-word;
            max-width: fit-content;
        }}
        .content img, .content video {{
            display: block;
            border-radius: 10px;
            padding: 0px;
            margin-top: 10px !important;
            margin-bottom: 10px !important;
            max-width: 50%;
            border-radius: 10px;
            padding: 0;
            margin: 0;
            max-height: 300px; 
        }}
        .content video {{
            background-color: transparent;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="http://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640&img_type=jpg" alt="Profile Image">
            <div class="header-text">
                <h1>{nickname}</h1>
                <h2>{userid}</h2>
                </div>
        </div>
        <div class="content">
            {messages}
        </div>
    </div>
</body>
</html>
"""

# 生成每个消息的 HTML
message_html = ""
for message in json_data["messages"]:
    combined_text = ""
    for msg in message["message"]:
        if msg["type"] == "text":
            combined_text += msg["data"]["text"] + " "
        elif msg["type"] == "image":
            message_html += f'<img src="{msg["data"]["url"]}" alt="Image">\n'
        elif msg["type"] == "video":
            try:
                message_html += f'<video controls autoplay muted><source src="file://{msg["data"]["file"]}" type="video/mp4">Your browser does not support the video tag.</video>\n'
            except:
                message_html += f'<video controls autoplay muted><source src="{msg["data"]["url"]}" type="video/mp4">Your browser does not support the video tag.</video>\n'
            else:
                print ('video success')
    if combined_text:
        # 替换 \n 为 <br/>
        combined_text = combined_text.replace("\n", "<br/>")
        message_html += f'<div>{combined_text.strip()}</div>\n'

# 格式化 HTML
html_content = html_template.format(
    nickname=json_data["sender"]["nickname"],
    user_id=json_data["sender"]["user_id"],
    userid=userid,
    messages=message_html
)

# 将 HTML 内容写入文件
with open(output_file_path, "w", encoding="utf-8") as file:
    file.write(html_content)

print("HTML 文件生成完毕！")
