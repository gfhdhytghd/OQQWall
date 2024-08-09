#!/bin/bash
source ./venv/bin/activate
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

waitforfilechange "./getmsgserv/all/commugroup.json"
while true; do
    echo 启动等待循环
    waitforfilechange "./getmsgserv/all/commugroup.json"
    mapfile -t lines < "$command_file"
        line=${lines[-1]}
        # 获取行的第一个和第二个字段
        question=$(echo $line | awk '{print $1}')
        python3 /home/wilf/data/OQQWall/qqBot/ChatBot.py
done