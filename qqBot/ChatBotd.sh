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
            echo 检测到指令
            break
        fi
    done
}

while true; do
    echo 启动等待循环
    waitforfilechange ./getmsgserv/all/commugroup.txt
    mapfile -t lines < "./getmsgserv/all/commugroup.txt"
        question=${lines[-1]}
        echo $question
        # 获取行的第一个和第二个字段
        botcmd="python3 ./qqBot/ChatBot.py $question"
        botoutput=$(eval $botcmd)
        cmd="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id='$commgroup_id'&message='$botoutput'"
        echo $cmd
        eval $cmd
done
