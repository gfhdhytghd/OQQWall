#!/bin/bash
LLonebot=$(grep 'use_LLOnebot' oqqwall.config | cut -d'=' -f2 | tr -d '"')
#commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
#mainqqid=$(grep 'mainqq-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
json_content=$(cat ./AcountGroupcfg.json)
runidlist=($(echo "$json_content" | jq -r '.[] | .mainqqid, .minorqqid[]'))
getinfo(){
    json_file="./AcountGroupcfg.json"
    # 检查输入是否为空
    if [ -z "$1" ]; then
    echo "请提供mainqqid或minorqqid。"
    exit 1
    fi
    # 使用 jq 查找输入ID所属的组信息
    group_info=$(jq -r --arg id "$1" '
    to_entries[] | select(.value.mainqqid == $id or (.value.minorqqid[]? == $id))
    ' "$json_file")
    # 检查是否找到了匹配的组
    if [ -z "$group_info" ]; then
    echo "未找到ID为 $1 的相关信息。"
    exit 1
    fi
    # 提取各项信息并存入变量
    groupname=$(echo "$group_info" | jq -r '.key')
    groupid=$(echo "$group_info" | jq -r '.value.mangroupid')
    mainqqid=$(echo "$group_info" | jq -r '.value.mainqqid')
    minorqqid=$(echo "$group_info" | jq -r '.value.minorqqid[]')
    mainqq_http_port=$(echo "$group_info" | jq -r '.value.mainqq_http_port')
    minorqq_http_ports=$(echo "$group_info" | jq -r '.value.minorqq_http_port[]')
    # 初始化端口变量
    port=""
    # 检查输入ID是否为mainqqid
    if [ "$1" == "$mainqqid" ]; then
    port=$mainqq_http_port
    else
    # 遍历 minorqqid 数组并找到对应的端口
    i=0
    for minorqqid in $minorqqid; do
        if [ "$1" == "$minorqqid" ]; then
        port=$(echo "$minorqq_http_ports" | sed -n "$((i+1))p")
        break
        fi
        ((i++))
    done
    fi
}
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
    nohup xvfb-run -a qq --no-sandbox -q "$qqid" &
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
    echo $current_time
    current_M=$(date +"%M")
    if [ "$current_M" == "00" ];then
        echo 'reach :00'
        #检查是否为早上7点
        if [ "$current_time" == "07:00" ]; then
            echo 'reach 7:00'
            source ./venv/bin/activate
            # 运行 Python 脚本
            for qqid in "${runidlist[@]}"; do
                echo "Like everyone with ID: $qqid"
                getinfo $qqid
                python3 ./qqBot/likeeveryday.py $port
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