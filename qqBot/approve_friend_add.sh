#!/bin/bash
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
echo "尝试通过来自$senderid 的好友请求，port：$port,flag: $1"
curl "http://127.0.0.1:$port/set_friend_add_request?flag=$1&approve=true"
source ./Global_toolkit.sh
sleep 30
sendmsgpriv "$senderid" "您的好友申请已通过，请阅读校园墙空间置顶后再投稿"