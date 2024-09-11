#!/bin/bash
LLonebot=$(grep 'use_LLOnebot' oqqwall.config | cut -d'=' -f2 | tr -d '"')
#commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
#mainqqid=$(grep 'mainqq-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
json_content=$(cat ./AcountGroupcfg.json)
runidlist=($(echo "$json_content" | jq -r '.[] | .mainqqid, .minorqqid[]'))


if pgrep -f "python3 ./getmsgserv/serv.py" > /dev/null
then
    echo "serv.py is already running"
else
    source ./venv/bin/activate
    python3 ./getmsgserv/serv.py &
    echo "serv.py started"
fi

# Check if the OneBot server process is running
if pgrep -f "xvfb-run -a qq --no-sandbox -q" > /dev/null; then
    pkill qq
fi

if [[ "$LLonebot" == false ]]; then
for qqid in "${runidlist[@]}"; do
    echo "Starting QQ process for ID: $qqid"
    xvfb-run -a qq --no-sandbox -q "$qqid" &
done
echo "OneBot starting"
elif [[ "$LLonebot" == true ]]; then
nohup qq &
echo "OneBot starting"
else
echo "please set config use_LLOneBot"
fi


#if [ -n "$commgroup_id" ]; then 
#    echo "commgroup_id不为空,chatbot启动" 
#    if pgrep -f "./main.py" > /dev/null;then
#            echo "ChatBot is already running"
#        else
#            source ./venv/bin/activate
#            cd ./qqBot/QChatGPT/
#            python3 ./main.py &
#            cd -
#            echo "OneBot starting"
#    fi
#fi

while true; do
    # 获取当前小时和分钟
    current_time=$(date +"%H:%M")
    current_M=$(date +"%M")
    if [ "current_M" == "00" ];then
        #检查是否为早上7点
        if [ "$current_time" == "07:00" ]; then
            source ./venv/bin/activate
            # 运行 Python 脚本
            for qqid in "${runidlist[@]}"; do
                echo "Like everyone with ID: $qqid"
                python3 ./qqBot/likeeveryday.py $qqid
            done
        fi
        pgrep -f "python3 ./getmsgserv/serv.py" | xargs kill -15
        python3 ./getmsgserv/serv.py &
        echo serv.py 已重启
        # 等待 1 小时，直到下一个小时
        sleep 3539
    else
        # 如果不是整点，等待一分钟后再检查时间
        sleep 59
    fi
done