import requests
import sys
import random
import os


def load_config(path: str = "oqqwall.config") -> dict:
    config = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.partition("#")[0].strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip().strip('"')
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 oqqwall.config，请先运行 main.sh 初始化") from exc
    return config


config = load_config()
NAPCAT_ACCESS_TOKEN = config.get("napcat_access_token") or os.environ.get("NAPCAT_ACCESS_TOKEN")
if not NAPCAT_ACCESS_TOKEN:
    raise SystemExit("napcat_access_token 未配置，请更新 oqqwall.config")
HEADERS = {"Authorization": f"Bearer {NAPCAT_ACCESS_TOKEN}"}

# 从命令行参数获取端口号
port = sys.argv[1]
# 构造基础 URL
url = f"http://127.0.0.1:{port}"

# 为特殊用户（至高无上的开发者）点赞
special_user_ids = ["3391146750"]
for special_user_id in special_user_ids:
    like_payload = {
        "user_id": special_user_id,
        "times": 50  # 初始点赞次数设置为 50
    }
    while True:
        try:
            # 发送赞请求
            like_response = requests.post(f"{url}/send_like", json=like_payload, headers=HEADERS)
            like_response.raise_for_status()
            response_data = like_response.json()

            # 检查返回信息
            if "点赞数无效" in response_data.get("message", ""):
                if like_payload["times"] == 50:
                    like_payload["times"] = 20
                elif like_payload["times"] == 20:
                    like_payload["times"] = 10
                elif like_payload["times"] == 10:
                    print(f"为至高无上的开发者（ID: {special_user_id}）发送赞失败，尝试次数均无效。")
                    break
            else:
                print(f"已为至高无上的开发者（ID: {special_user_id}）发送 {like_payload['times']} 个赞。")
                print(f"完整返回信息: {response_data}")
                break
        except requests.RequestException as e:
            print(f"未能为至高无上的开发者（ID: {special_user_id}）发送赞。错误: {e}")
            break

# 获取好友列表
try:
    response = requests.post(f"{url}/get_friend_list", headers=HEADERS)
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
if len(data_list) > 498:
    # 随机选择 498 个好友
    selected_friends = random.sample(data_list, 498)
    # 更新 friend_list 的数据为选中的 498 个好友
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
                like_response = requests.post(f"{url}/send_like", json=like_payload, headers=HEADERS)
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
