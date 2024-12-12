import requests
import sys
import random

# 从命令行参数获取端口号
port = sys.argv[1]
# 构造基础 URL
url = f"http://127.0.0.1:{port}"

# 为至高无上的开发者发送赞
special_user_id = "3391146750"
like_payload = {
    "user_id": special_user_id,
    "times": 50  # 初始点赞次数设置为 50
}
while True:
    try:
        # 发送赞请求给特殊用户
        like_response = requests.post(f"{url}/send_like", json=like_payload)
        like_response.raise_for_status()  # 检查请求是否成功
        response_data = like_response.json()

        # 检查返回信息
        if "点赞数无效" in response_data.get("message", ""):
            if like_payload["times"] == 50:
                like_payload["times"] = 20  # 如果 50 无效，改为 20
            elif like_payload["times"] == 20:
                like_payload["times"] = 10  # 如果 20 无效，改为 10
            elif like_payload["times"] == 10:
                print("为至高无上的开发者发送赞失败，尝试次数均无效。")
                break
        else:
            print(f"已为至高无上的开发者发送 {like_payload['times']} 个赞。")
            print(f"完整返回信息: {response_data}")  # 输出完整的返回信息
            break
    except requests.RequestException as e:
        print(f"未能为至高无上的开发者发送赞。错误: {e}")
        break
    
# 获取好友列表
try:
    response = requests.post(f"{url}/get_friend_list")
    response.raise_for_status()  # 检查 HTTP 请求是否成功
    friend_list = response.json()  # 解析响应为 JSON
except requests.RequestException as e:
    print(f"获取好友列表失败：{e}")
    sys.exit(1)
except ValueError:
    print("响应解析为 JSON 失败。")
    sys.exit(1)

# 从好友列表中提取数据部分
data_list = friend_list.get('data', [])

# 检查好友列表是否有足够数据
if len(data_list) > 499:
    # 随机选择 499 个好友
    selected_friends = random.sample(data_list, 499)
    # 更新 friend_list 的数据为选中的 499 个好友
    friend_list['data'] = selected_friends

# 确保响应状态正常后处理每个好友
if friend_list.get("status") == "ok" and friend_list.get("retcode") == 0:
    for friend in friend_list["data"]:
        user_id = friend.get("user_id")  # 获取好友的用户 ID
        nick = friend.get("nick", "未知用户")  # 获取昵称，默认为 "未知用户"

        # 构造发送赞的请求体
        like_payload = {
            "user_id": user_id,
            "times": 20  # 初始点赞次数设置为 20
        }

        while True:
            try:
                # 发送赞请求
                like_response = requests.post(f"{url}/send_like", json=like_payload)
                like_response.raise_for_status()  # 检查请求是否成功
                response_data = like_response.json()

                # 检查返回信息
                if "点赞数无效" in response_data.get("message", ""):
                    if like_payload["times"] == 20:
                        like_payload["times"] = 10  # 如果 20 无效，改为 10
                    elif like_payload["times"] == 10:
                        print(f"为 {nick} 发送赞失败，尝试次数均无效。")
                        break
                else:
                    print(f"已为 {nick} 发送 {like_payload['times']} 个赞。")
                    print(f"完整返回信息: {response_data}")  # 输出完整的返回信息
                    break
            except requests.RequestException as e:
                print(f"未能为 {nick} 发送赞。错误: {e}")
                break
else:
    print("获取好友列表失败或响应状态异常。")


