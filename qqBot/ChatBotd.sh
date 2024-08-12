#!/bin/bash
commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
source ./venv/bin/activate
echo $commgroup_id
waitforfilechange(){
        last_mod_time_cmd=$(stat -c %Y "$1")

    while true; do
        sleep 5
        # 获取文件的当前修改时间
        current_mod_time_cmd=$(stat -c %Y "$1")

        # 检查文件是否已被修改
        if [ "$current_mod_time_cmd" -ne "$last_mod_time_cmd" ]; then
            echo 检测到文件修改
            break
        fi
    done
}

while true; do
    echo “ChatBotd：启动等待循环”
    waitforfilechange ./getmsgserv/all/commugroup.txt
    mapfile -t lines < "./getmsgserv/all/commugroup.txt"
        question=${lines[-1]}
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
done
