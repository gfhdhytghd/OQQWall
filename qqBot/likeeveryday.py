import requests

# 请求 URL
url = "http://127.0.0.1:8083"

# 获取好友列表
response = requests.post(f"{url}/get_friend_list")
friend_list = response.json()

if friend_list["status"] == "ok" and friend_list["retcode"] == 0:
    for friend in friend_list["data"]:
        user_id = friend["user_id"]
        
        # 为每个好友发送10个赞
        like_payload = {
            "user_id": user_id,
            "times": 20
        }
        
        like_response = requests.post(f"{url}/send_like", json=like_payload)
        
        if like_response.status_code == 200:
            print(f"已为 {friend['nick']} 发送 20 个赞。")
        else:
            print(f"未能为 {friend['nick']} 发送赞。状态码: {like_response.status_code}")
else:
    print("获取好友列表失败。")
