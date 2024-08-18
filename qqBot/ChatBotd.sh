#!/bin/bash
commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
source ./venv/bin/activate
echo $commgroup_id


question=$1
echo $question
escaped_question=$(printf '%s' "$question" | sed 's/[\&/\]/\\&/g')
# 构建 botcmd，并执行
botcmd="python3 ./qqBot/ChatBot.py \"$escaped_question\""
botoutput=$(eval "$botcmd")
encoded_output=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$botoutput'''))")
# 构建 curl 命令，并发送编码后的消息
cmd="curl \"http://127.0.0.1:8083/send_group_msg?group_id=$commgroup_id&message=$encoded_output\""
echo $cmd
eval $cmd

