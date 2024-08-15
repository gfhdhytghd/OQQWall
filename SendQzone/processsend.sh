groupid=$(grep 'management-group-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
file_to_watch="./getmsgserv/all/priv_post.json"
command_file="./qqBot/command/commands.txt"
litegettag=$(grep 'use_lite_tag_generator' oqqwall.config | cut -d'=' -f2 | tr -d '"')
max_attempts=$(grep 'max_attempts_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')


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
    msg=[CQ:image,file=file://$file_path]
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:8083/send_group_msg?group_id=$groupid&message=$encoded_msg\""
    echo $cmd
    eval $cmd
    sleep 1  # 添加延时以避免过于频繁的请求
    done
    echo "所有文件已发送"
}
getnumnext(){
    if [[ "$litegettag" == false ]]; then
        echo 使用主算法...
        getnumcmd='python3 ./SendQzone/qzonegettag-headless.py'
        output=$(eval $getnumcmd)
    else
        output="Log Error!"
    fi
    if echo "$output" | grep -q "Log Error!"; then
        echo 使用备用算法...
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
            拒)
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
                拒)
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
    fi
    echo numnext=$numnext
}
askforintro(){
    sendmsggroup 请发送指令
    # 初始化文件的上次修改时间
    waitforfilechange "./qqBot/command/commands.txt"
    sendmsggroup 已收到指令
    
    while true; do
        mapfile -t lines < "$command_file"
        found=false
        
        for (( i=${#lines[@]}-1 ; i>=0 ; i-- )); do
            line=${lines[i]}
            number=$(echo $line | awk '{print $1}')
            status=$(echo $line | awk '{print $2}')
            
            if [[ $number -eq $numnext ]]; then
                sed -i "${i}d" "$command_file"
                found=true
                case $status in
                numfinal=$(cat ./numfinal.txt)
                是)
                    postcmd="true"
                    numfinal=$((numfinal + 1))
                    echo $numfinal > ./numfinal.txt
                    postqzone
                    ;;
                否)
                    postcmd="false"
                    rm ./getmsgserv/rawpost/$id.json
                    rm -rf ./getmsgserv/post-step5/$numnext
                    numfinal=$((numfinal + 1))
                    echo $numfinal > ./numfinal.txt
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
                拒)
                    postcmd="ref"
                    rm ./getmsgserv/rawpost/$id.json
                    rm -rf ./getmsgserv/post-step5/$numnext
                    sendmsgpriv $id '你的稿件被拒绝,请尝试修改后重新投稿'
                    ;;
                匿)
                    sendmsggroup 尝试切换匿名状态...
                    file="./getmsgserv/post-step2/$numnext.json"
                    json_content=$(cat "$file")
                    modified_json=$(echo "$json_content" | jq '.needpriv = (.needpriv == "true" | not | tostring)')
                    echo "$modified_json" > "$file"
                    python3 ./getmsgserv/HTMLwork/gotohtml.py "$numnext"
                    ./getmsgserv/HTMLwork/gotopdf.sh "$numnext"
                    ./getmsgserv/HTMLwork/gotojpg.sh "$numnext"
                    sendimagetoqqgroup
                    sendmsggroup $numnext
                    echo askforgroup...
                    askforintro
                    ;;
                *)
                    sendmsggroup 没有此指令,请查看说明
                    askforintro
                    ;;
                esac
                break
            fi
        done

        if $found; then
            break
        fi

        sleep 5
    done
}




postqzone(){
    if [ ! -f "./cookies.json" ]; then
        echo "Cookies file does not exist. Executing relogin script."
        python3 SendQzone/send.py relogin &
        sleep 2
        sendmsggroup 请立即扫描二维码
        sendmsggroup "[CQ:image,file=$(pwd)/qrcode.png]"
        eval $command
        sleep 60
    else
        echo "Cookies file exists. No action needed."
    fi
    json_path="./getmsgserv/post-step2/$numnext.json"
    need_priv=$(jq -r '.needpriv' "$json_path")
    # 检查 need_priv 的值并执行相应的命令
    if [ "$need_priv" == "true" ]; then
        postcommand="python3 ./SendQzone/send.py '#$numfinal' ./getmsgserv/post-step5/$numnext/"
    else
        postcommand="python3 ./SendQzone/send.py '#$numfinal @{uin:$id,nick:,who:1}' ./getmsgserv/post-step5/$numnext/"
    fi
    output=$(eval $postcommand)
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        output=$(eval $postcommand)

        if echo "$output" | grep -q "Failed to publish."; then
            if [ $attempt -eq 1 ]; then
                renewqzonelogin-auto
            fi
            
            if [ $attempt -eq $max_attempts ]; then
                sendmsggroup "空间发送错误，可能需要重新登陆,也可能是文件错误"
                sendmsggroup "发送\"@本账号 relogin 是\"以手动重新登陆"
                askforintro
            fi
        else
            echo 发送完毕
            sendmsgpriv $id "$numfinal 已发送(系统自动发送，请勿回复)"
            sendmsggroup 已发送
            break
        fi

        attempt=$((attempt+1))
    done
    current_mod_time_id=$(stat -c %Y "$id_file")
    current_mod_time_privmsg=$(stat -c %Y "./getmsgserv/all/priv_post.json")
    echo "'current-mod-time-id:'$current_mod_time_id"
    echo "'last-mod-time-id:'$last_mod_time_id"
    echo "'current_mod_time_privmsg'$current_mod_time_privmsg"
    echo "'last_mod_time_privmsg':$last_mod_time_privmsg"
    if [ "$current_mod_time_id" -eq "$last_mod_time_id" ]; then
        echo "过程中此人无新消息，删除此人记录"
        rm ./getmsgserv/rawpost/$id.json
    fi
}

renewqzonelogin-auto(){
    rm ./cookies.json
    rm ./qrcode.png
    python3 ./SendQzone/qzonerenewcookies.py
}

renewqzonelogin(){
    rm ./cookies.json
    rm ./qrcode.png
    postqzone &
    sleep 2
    sleep 60
}


sendmsggroup(){
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:8083/send_group_msg?group_id=$groupid&message=$encoded_msg\""
    echo $cmd
    eval $cmd
}

sendmsgpriv(){
    msg=$2
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:8083/send_private_msg?user_id=$1&message=$encoded_msg\""
    echo $cmd
    eval $cmd
}

processsend(){
    echo waitingforsender...
    sleep 120
    id_file=./getmsgserv/rawpost/$id.json
    last_mod_time_id=$(stat -c %Y "$id_file")
    echo $id
    echo 'wait-for-LM...'
    python3 ./getmsgserv/LM_work/sendtoLM.py ${id} ${numnext}
    for i in {1..3}
    do
        if [ -f "./getmsgserv/post-step2/${numnext}.json" ]; then
            echo "File exists, continuing..."
            break
        else
            echo "File not found, running Python script..."
            python3 ./getmsgserv/LM_work/sendtoLM.py "${id}" "${numnext}"
        fi

        if [ "$i" -eq 3 ] && [ ! -f "./getmsgserv/post-step2/${numnext}.json" ]; then
            sendmsggroup LLM处理错误，请检查相关信息
        fi
    done
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
    content=$(<"$id_file")
    sendmsggroup "原始信息: $content"
    sendimagetoqqgroup
    sendmsggroup $numnext
    echo askforgroup...
    askforintro
}

id=$1
numnext=$2
echo "'开始处理来自$id'的消息,内部编号'$numnext"
processsend



