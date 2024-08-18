#!/bin/bash
LLonebot=$(grep 'use_LLOnebot' oqqwall.config | cut -d'=' -f2 | tr -d '"')
commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
mainqqid=$(grep 'mainqq-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')

if pgrep -f "python3 ./getmsgserv/serv.py" > /dev/null
then
    echo "serv.py is already running"
else
    python3 ./getmsgserv/serv.py &
    echo "serv.py started"
fi

# Check if the OneBot server process is running
if pgrep -fx "qq" > /dev/null
then
    echo "OneBot is already running"
else
    if [[ "$LLonebot" == false ]]; then
    nohup xvfb-run -a qq --no-sandbox -q $mainqqid &
    echo "OneBot starting"
    elif [[ "$LLonebot" == true ]]; then
    nohup qq &
    echo "OneBot starting"
    else
    echo "please set config use_LLOneBot"
    fi
fi

if [ -n "$commgroup_id" ]; then 
    echo "commgroup_id不为空,chatbot启动" 
    if pgrep -f "./main.py" > /dev/null;then
            echo "ChatBot is already running"
        else
            source ./venv/bin/activate
            cd ./qqBot/QChatGPT/
            python3 ./main.py &
            cd -
            echo "OneBot starting"
    fi
fi

while true; do
    # 获取当前小时和分钟
    current_time=$(date +"%H:%M")

    # 检查是否为早上7点
    if [ "$current_time" == "07:00" ]; then
        # 运行 Python 脚本
        python3 ./qqBot/likeeveryday.py

        # 等待 24 小时，直到第二天的 7 点
        sleep 86340
    else
        # 如果不是7点，等待一分钟后再检查时间
        sleep 59
    fi
done