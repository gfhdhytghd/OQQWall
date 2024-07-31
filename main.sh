#!/bin/bash

groupid=

# Activate virtual environment
source ./venv/bin/activate

# Check if the serv.py process is running
if pgrep -f "python3 ./getmsgserv/serv.py" > /dev/null
then
    echo "serv.py is already running"
else
    python3 ./getmsgserv/serv.py &
    echo "serv.py started"
fi

# Check if the Lagrange.OneBot process is running
if pgrep -f "./qqBot/Lagrange.OneBot" > /dev/null
then
    echo "Lagrange.OneBot is already running"
else
    nohup ./qqBot/Lagrange.OneBot &
    echo "Lagrange.OneBot started"
fi

sleep 10
#避免消息反复处理
file_to_watch="./getmsgserv/all/priv_post.json"
command_file="./qqBot/command/commands.txt"


sendimagetoqqgroup() {
    # 设置文件夹路径
    folder_path="$(pwd)/getmsgserv/post-step5/$numnext"

    # 检查文件夹是否存在
    if [ ! -d "$folder_path" ]; then
    echo "文件夹 $folder_path 不存在"
    exit 1
    fi

    find "$folder_path" -maxdepth 1 -type f | sort | while IFS= read -r file_path; do
    echo "发送文件: $file_path"
    command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id='$groupid'&message=[CQ:image,file=$file_path]'"
    eval $command
    sleep 1  # 添加延时以避免过于频繁的请求
    done
    echo "所有文件已发送"
}


askforintro(){
    command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id='$groupid'&message=$numnext 请发送指令'"
    eval $command
    # 初始化文件的上次修改时间
    last_mod_time_cmd=$(stat -c %Y "$command_file")

    while true; do
        sleep 5
        # 获取文件的当前修改时间
        current_mod_time_cmd=$(stat -c %Y "$command_file")

        # 检查文件是否已被修改
        if [ "$current_mod_time_cmd" -ne "$last_mod_time_cmd" ]; then
            echo 检测到指令
            break
        fi
    done

    mapfile -t lines < "$command_file"
    for (( i=${#lines[@]}-1; i>=0; i-- )); do
    line=${lines[$i]}
    # 获取行的第一个和第二个字段
    number=$(echo $line | awk '{print $1}')
    status=$(echo $line | awk '{print $2}')
    
    # 检查行的第一个字段是否等于 numnext
    if [[ $number -eq $numnext ]]; then
        case $status in
        是)
            postcmd="true"
            postqzone
            ;;
        否)
            postcmd="false"
            rm ./getmsgserv/rawpost/$id.json
            rm -rf ./getmsgserv/post-step5/350
            ;;
        等)
            postcmd="wait"
            sleep 180
            ;;
        删)
            postcmd="del"
            rm ./getmsgserv/rawpost/$id.json
            rm -rf ./getmsgserv/post-step5/350
            ;;
        esac
        # 找到符合条件的行后退出循环
        break
    fi
        if [[ $number -eq relogin ]]; then
        case $status in
        是)
            postcmd="true"
            renewqzonelogin
            ;;
        否)
            postcmd="false"
            echo retry...
            sendmsggroup 重新尝试发送中...
            ;;
        esac
        # 找到符合条件的行后退出循环
        break
    fi
    done
}
postqzone(){
    if [ ! -f "./cookies.json" ]; then
        echo "Cookies file does not exist. Executing relogin script."
        python3 SendQzone/send.py relogin &
        sleep 2
        sendmsggroup 请立即扫描二维码
        command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id=$groupid&message=[CQ:image,file=$(pwd)/qrcode.png]'"
        eval $command
        sleep 60
    else
        echo "Cookies file exists. No action needed."
    fi

    postcommand="python3 ./SendQzone/send.py '#$numnext' ./getmsgserv/post-step5/$numnext/"
    output=$(eval $postcommand)
    if echo "$output" | grep -q "Failed to publish."; then
    sendmsggroup 空间发送错误,可能需要重新登陆,错误: 
    sendmsggroup 发送 '@本账号 relogin 是' 以重新登陆
    askforintro
    rm ./getmsgserv/rawpost/$id.json
    fi
}
renewqzonelogin(){
    rm ./cookies.json 
    rm ./qrcode.png
    postqzone &
    sleep 2
    command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id='$groupid'&message=[CQ:image,file=$(pwd)/qrcode.png]'"
    eval $command
    sleep 60
}
sendmsggroup(){
google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id='$groupid'&message='$1''
}

last_mod_time=$(stat -c %Y "$file_to_watch")

while true; do

    while true; do
        sleep 5
        # 获取文件的当前修改时间
        current_mod_time=$(stat -c %Y "$file_to_watch")

        # 检查文件是否已被修改
        if [ "$current_mod_time" -ne "$last_mod_time" ]; then
            echo "有新消息"
            break
        fi   
    done

    #主逻辑代码
    python3 ./SendQzone/qzonegettag.py
    numnow=$( cat ./numb.txt )
    numnext=$[ numnow + 1 ]
    sleep 120
    id=$(find ./getmsgserv/rawpost -type f -printf '%T+ %p\n' | sort | head -n 1 | awk '{print $2}')
    id=$(basename "$id" .json)
    id=$(echo "$id" | sed 's/.*\///')
    echo $id
    echo 'wait-for-LM...'
    python3 ./getmsgserv/LM_work/sendtoLM.py ${id} ${numnext} 

    json_file=./getmsgserv/post-step2/${numnext}.json 
    isover=$(jq -r '.isover' "$json_file")
    notregular=$(jq -r '.notregular' "$json_file")
    safemsg=$(jq -r '.safemsg' "$json_file")

    python3 ./getmsgserv/HTMLwork/gotohtml.py "$numnext"
    ./getmsgserv/HTMLwork/gotopdf.sh "$numnext"
    ./getmsgserv/HTMLwork/gotojpg.sh "$numnext"

    if [ "$isover" = "true" ] && [ "$notregular" = "false" ]; then
        sendmsggroup 有常规消息
    elif [ "$isover" = "true" ] && [ "$notregular" = "true" ]; then
        sendmsggroup 有非常规消息
    elif [ "$isover" = "false" ] && [ "$notregular" = "true" ]; then
        sendmsggroup 有常规但疑似未写完帖子
    elif [ "$isover" = "false" ] && [ "$notregular" = "false" ]; then
        sendmsggroup 有非常规且疑似未写完帖子
    else
        sendmsggroup 有需要审核的消息
    fi

    if [ "$safemsg" = "true" ]; then
        sendmsggroup AI审核判定安全
    elif [ "$safemsg" = "false" ]; then
        sendmsggroup AI审核判定不安全
    fi

    sendimagetoqqgroup
    echo askforgroup...
    askforintro
    last_mod_time=$(stat -c %Y "$file_to_watch")
done