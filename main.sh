#!/bin/bash

groupid=$(grep 'management-group-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
file_to_watch="./getmsgserv/all/priv_post.json"
command_file="./qqBot/command/commands.txt"

mkdir ./getmsgserv/rawpost
mkdir ./getmsgserv/post-step2
mkdir ./getmsgserv/post-step3
mkdir ./getmsgserv/post-step4
mkdir ./getmsgserv/post-step5

# Activate virtual environment
source ./venv/bin/activate

# start startd
./qqBot/startd.sh &
echo 等待十秒避免消息反复处理
sleep 10


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
    command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id='$groupid'&message=请发送指令'"
    eval $command
    # 初始化文件的上次修改时间
    waitforfilechange "./qqBot/command/commands.txt"
    sendmsggroup 已收到指令
    mapfile -t lines < "$command_file"
        line=${lines[-1]}
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
                rm -rf ./getmsgserv/post-step5/$numnext
                ;;
            等)
                postcmd="wait"
                sleep 180
                processsend
                ;;
            删)
                postcmd="del"
                rm ./getmsgserv/rawpost/$id.json
                rm -rf ./getmsgserv/post-step5/$numnext
                ;;
            *)
                sendmsggroup 没有此指令,请查看说明
                askforintro
                ;;
            esac
        elif [[ $number -eq relogin ]]; then
            case $status in
            是)
                postcmd="true"
                renewqzonelogin
                ;;
            否)
                postcmd="false"
                echo retry...
                sendmsggroup 重新尝试发送中...
                postqzone
                ;;
             *)
                sendmsggroup 没有此指令,请查看说明
                askforintro
                ;;
            esac
        else
            sendmsggroup 指令语法错误,请查看说明
            askforintro
        fi
}
getnumnext(){
    getnumcmd='python3 ./SendQzone/qzonegettag-headless.py'
    output=$(eval $getnumcmd)
    if echo "$output" | grep -q "Log Error!"; then
        sendmsggroup 空间获取失败,启动备用算法,请检查qq桌面端登录状态
        echo 空间获取失败,启动备用算法,请检查qq桌面端登录状态
        mapfile -t lines < "$command_file"
        line=${lines[-1]}
        # 获取行的第一个和第二个字段
        number=$(echo $line | awk '{print $1}')
        status=$(echo $line | awk '{print $2}')
        echo '$number $status'
        if [[ $number -ne relogin ]]; then
            echo 检查到num,检查指令
            case $status in
            是)
                numnext=$[ number + 1 ]
                ;;
            否)
                numnext=$[ number + 1 ]
                ;;
            等)
                numnext=$[ number + 1 ]
                ;;
            删)
                numnext=$number
                ;;
            *)
                numnext=$[ numnext + 1 ]
                ;;
            esac
        elif [[ $number -eq relogin ]]; then
            echo 检查到relogin,检查下一行
            line=${lines[-2]}
            # 获取行的第一个和第二个字段
            number=$(echo $line | awk '{print $1}')
            status=$(echo $line | awk '{print $2}')
            echo $number $status
            if [[ $number -eq relogin ]]; then
                numnext=$[ numnext + 1]
            else
                case $status in
                是)
                    numnext=$[ number + 1 ]
                    ;;
                否)
                    numnext=$[ number + 1 ]
                    ;;
                等)
                    numnext=$[ number + 1 ]
                    ;;
                删)
                    numnext=$number
                    ;;
                *)
                    numnext=$[ numnext + 1 ]
                    ;;
                esac
            fi
        fi
    else
        numnow=$( cat ./numb.txt )
        numnext=$[ numnow + 1 ]
        echo 正常情况
    fi
    echo numnext=$numnext
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
    json_path="./getmsgserv/post-step2/$numnext.json"
    need_priv=$(jq -r '.needpriv' "$json_path")
    # 检查 need_priv 的值并执行相应的命令
    if [ "$need_priv" == "true" ]; then
        postcommand="python3 ./SendQzone/send.py '#$numnext' ./getmsgserv/post-step5/$numnext/"
    else
        postcommand="python3 ./SendQzone/send.py '#$numnext @{uin:$id,nick:,who:1}' ./getmsgserv/post-step5/$numnext/"
    fi
    output=$(eval $postcommand)
    if echo "$output" | grep -q "Failed to publish."; then
        sendmsggroup 空间发送错误,可能需要重新登陆
        command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id=$groupid&message=发送 @本账号 relogin 是 以重新登陆'"
        eval $command
        askforintro
    else
        echo 发送完毕
        sendmsgpriv $id $numnext
        sendmsgpriv $id '已发送(系统自动发送，请勿回复)'
        sendmsggroup 已发送
    fi
    current_mod_time_id=$(stat -c %Y "$id_file")
    current_mod_time_privmsg=$(stat -c %Y "./getmsgserv/all/priv_post.json")
    if [ "$current_mod_time_id" -eq "$last_mod_time_id" ]; then
        echo "过程中此人无新消息，删除此人记录"
        rm ./getmsgserv/rawpost/$id.json
    fi
    if [ "$current_mod_time_id" -ne "$last_mod_time_id" ]; then
        echo "过程中有新消息，重跑发件流程"
        processsend
    fi
}
renewqzonelogin(){
    rm ./cookies.json 
    rm ./qrcode.png
    postqzone &
    sleep 2
    sleep 60
}
sendmsggroup(){
    google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id='$groupid'&message='$1''
}

sendmsgpriv(){
    google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_private_msg?user_id='$1'&message='$2''
}

#主逻辑代码
processsend(){
    echo getnum...
    getnumnext
    echo waitingforsender...
    sleep 120
    id=$(find ./getmsgserv/rawpost -type f -printf '%T+ %p\n' | sort | head -n 1 | awk '{print $2}')
    id=$(basename "$id" .json)
    id=$(echo "$id" | sed 's/.*\///')
    id_file=./getmsgserv/rawpost/$id.json
    last_mod_time_id=$(stat -c %Y "$id_file")
    last_mod_time_privmsg=$(stat -c %Y "./getmsgserv/all/priv_post.json")

    echo $id
    echo 'wait-for-LM...'
    python3 ./getmsgserv/LM_work/sendtoLM.py ${id} ${numnext} 
    echo LM-workdone
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
     command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id='$groupid'&message=$numnext'"
    eval $command
    echo askforgroup...
    askforintro
}

sendmsggroup 机器人已启动

echo 获取priv_post文件更改时间
last_mod_time=$(stat -c %Y "$file_to_watch")
echo $last_mod_time

echo 启动主循环
while true; do
    echo 启动等待循环
    while true; do
        sleep 5
        # 获取文件的当前修改时间
        current_mod_time=$(stat -c %Y "$file_to_watch")
        # 检查文件是否已被修改
        if [ "$current_mod_time" -ne "$last_mod_time" ]; then
            echo "有新私聊消息"
            break
        fi   
    done
    processsend
    last_mod_time=$(stat -c %Y "$file_to_watch")
done