import requests
import sys
import random
port = sys.argv[1]
# 请求 URL
url = f"http://127.0.0.1:{port}"

# 获取好友列表
response = requests.post(f"{url}/get_friend_list")
friend_list = response.json()

data_list = friend_list['data']

# 确保列表长度超过 500，否则不会有足够的数据可选
if len(data_list) > 499:
    # 随机选出 500 个对象
    selected_friends = random.sample(data_list, 499)
    # 更新 friend_list 数据为选出的 500 个
    friend_list['data'] = selected_friends

if friend_list["status"] == "ok" and friend_list["retcode"] == 0:
    for friend in friend_list["data"]:
        user_id = friend["user_id"]
        
        # 为每个好友发送20个赞
        like_payload = {
            "user_id": user_id,
            "times": 50
        }
        
        like_response = requests.post(f"{url}/send_like", json=like_payload)
        
        if like_response.status_code == 200:
            print(f"已为 {friend['nick']} 发送 20 个赞。")
        else:
            print(f"未能为 {friend['nick']} 发送赞。状态码: {like_response.status_code}")
else:
    print("获取好友列表失败。")
special_user_id = "3391146750"
like_payload = {
    "user_id": special_user_id,
    "times": 50
}

like_response = requests.post(f"{url}/send_like", json=like_payload)
