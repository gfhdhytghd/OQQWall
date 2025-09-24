#!/bin/bash
source ./Global_toolkit.sh

json_file="./AcountGroupcfg.json"
senderid=$2
receiver=$3
group_info=$(jq -r --arg receiver "$receiver" '
  to_entries[] | select(.value.mainqqid == $receiver or (.value.minorqqid[]? == $receiver))
' "$json_file")
groupname=$(echo "$group_info" | jq -r '.key')
groupid=$(echo "$group_info" | jq -r '.value.mangroupid')
mainqqid=$(echo "$group_info" | jq -r '.value.mainqqid')
minorqqid=$(echo "$group_info" | jq -r '.value.minorqqid[]')
mainqq_http_port=$(echo "$group_info" | jq -r '.value.mainqq_http_port')
minorqq_http_ports=$(echo "$group_info" | jq -r '.value.minorqq_http_port[]')
friend_add_message=$(echo "$group_info" | jq -r '.value.friend_add_message')
port=""
# 检查输入ID是否为mainqqid
if [ "$receiver" == "$mainqqid" ]; then
  port=$mainqq_http_port
else
  # 遍历 minorqqid 数组并找到对应的端口
  i=0
  for minorqqid in $minorqqid; do
    if [ "$receiver" == "$minorqqid" ]; then
      port=$(echo "$minorqq_http_ports" | sed -n "$((i+1))p")
      break
    fi
    ((i++))
  done
fi
echo "将在四分钟内通过来自$senderid 的好友请求，port：$port,flag: $1"
sleep $((RANDOM % 241))
curl -H "$NAPCAT_AUTH_HEADER" "http://127.0.0.1:$port/set_friend_add_request?flag=$1&approve=true"
sleep 30
sendmsgpriv "$senderid" "$friend_add_message"
