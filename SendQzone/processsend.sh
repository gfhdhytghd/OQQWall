commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
file_to_watch="./getmsgserv/all/priv_post.json"
command_file="./qqBot/command/commands.txt"
use_selenium_to_generate_qzone_cookies=$(grep 'use_selenium_to_generate_qzone_cookies' oqqwall.config | cut -d'=' -f2 | tr -d '"')
disable_qzone_autologin=$(grep 'disable_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')
max_attempts=$(grep 'max_attempts_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')
mixid=$1
id="${mixid%-*}"
self_id="${mixid#*-}"
numnext=$2
# 输入参数ID
input_id="${mixid#*-}"
# JSON 文件路径
json_file="./AcountGroupcfg.json"
# 检查输入是否为空
if [ -z "$input_id" ]; then
  echo "请提供mainqqid或minorqqid。"
  exit 1
fi
# 使用 jq 查找输入ID所属的组信息
group_info=$(jq -r --arg id "$input_id" '
  to_entries[] | select(.value.mainqqid == $id or (.value.minorqqid[]? == $id))
' "$json_file")
# 检查是否找到了匹配的组
if [ -z "$group_info" ]; then
  echo "未找到ID为 $input_id 的相关信息。"
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
if [ "$input_id" == "$mainqqid" ]; then
  port=$mainqq_http_port
else
  # 遍历 minorqqid 数组并找到对应的端口
  i=0
  for minorqqid in $minorqqid; do
    if [ "$input_id" == "$minorqqid" ]; then
      port=$(echo "$minorqq_http_ports" | sed -n "$((i+1))p")
      break
    fi
    ((i++))
  done
fi
goingtosendid=("$mainqqid")
# 将minorqqid解析为数组并添加到goingtosendid
IFS=',' read -ra minorqqids <<< "$minorqqid"
for qqid in "${minorqqids[@]}"; do
    goingtosendid+=("$qqid")
done
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
        msg=[CQ:image,file=file://$file_path]
        encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
        # 构建 curl 命令，并发送编码后的消息
        cmd="curl \"http://127.0.0.1:8083/send_group_msg?group_id=$groupid&message=$encoded_msg\""
        eval $cmd
        sleep 1  # 添加延时以避免过于频繁的请求
    done
    echo "所有文件已发送"
}
getnumnext(){
    numnow=$(cat ./numb.txt)
    numnext=$((numnow + 1))
    echo "$numnext" > ./numb.txt
    echo "$numnext=$numnext"
}
askforintro(){
    sendmsggroup 请发送指令
    # 初始化文件的上次修改时间
    waitforfilechange "./qqBot/command/commands.txt"

    while true; do
        mapfile -t lines < "$command_file"
        found=false

        for (( i=${#lines[@]}-1 ; i>=0 ; i-- )); do
            line=${lines[i]}
            number=$(echo $line | awk '{print $1}')
            status=$(echo $line | awk '{print $2}')
            flag=$(echo $line | awk '{print $3}')

            if [[ "$number" -eq "$numnext" ]]; then
                sendmsggroup 已收到指令
                sed -i "${i}d" "$command_file"
                found=true
                numfinal=$(cat ./"$groupname"_numfinal.txt)
                case $status in
                是)
                    postcmd="true"
                    numfinal=$(cat ./"$groupname"_numfinal.txt)
                    postqzone
                    echo 结束发件流程,是
                    ;;
                否)
                    postcmd="false"
                    rm $id_file
                    rm -rf ./getmsgserv/post-step5/$numnext
                    numfinal=$(cat ./"$groupname"_numfinal.txt)
                    numfinal=$((numfinal + 1))
                    echo $numfinal > ./"$groupname"_numfinal.txt
                    sendmsgpriv $id "你的稿件已转交人工处理"
                    echo 结束发件流程,否
                    ;;
                等)
                    postcmd="wait"
                    sleep 180
                    processsend
                    ;;
                删)
                    postcmd="del"
                    rm $id_file
                    rm -rf ./getmsgserv/post-step5/$numnext
                    ;;
                拒)
                    postcmd="ref"
                    rm $id_file
                    rm -rf ./getmsgserv/post-step5/$numnext
                    sendmsgpriv $id '你的稿件被拒绝,请尝试修改后重新投稿'
                    echo 结束发件流程,拒
                    ;;
                拉黑)
                    sendmsggroup 不再接收来自$id的投稿
                    rm -rf ./getmsgserv/post-step5/$numnext
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
                    json_path="./getmsgserv/post-step2/$numnext.json"
                    need_priv=$(jq -r '.needpriv' "$json_path")
                    numfinal=$(cat ./"$groupname"_numfinal.txt)
                    if [[ "$need_priv" == "false" ]]; then
                        massege="#$numfinal @{uin:$id,nick:,who:1}"
                    else
                        massege="#$numfinal"
                    fi
                    sendimagetoqqgroup
                    sendmsggroup $numnext
                    echo askforgroup...
                    askforintro
                    ;;
                评论)
                    if [[ "$need_priv" == "false" ]]; then
                        massege="#$numfinal @{uin:$id,nick:,who:1}"
                    else
                        massege="#$numfinal"
                    fi
                    if [ -n "$flag" ]; then
                        massege="${massege}"$'\n'"${flag}"
                        sendmsggroup "增加评论后的文本：\n $massege"
                        askforintro
                    else
                        if [[ "$need_priv" == "false" ]]; then
                            massege="#$numfinal @{uin:$id,nick:,who:1}"
                        else
                            massege="#$numfinal"
                        fi
                        sendmsggroup "没有找到评论内容，文本内容已还原"
                        sendmsggroup "当前文本：\n $massege"
                    fi
                    ;;
                *)
                    sendmsggroup "没有此指令,请查看说明,发送 @本账号 帮助 以查看帮助"
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
postprocess(){
    if [ ! -f "./cookies-$1.json" ]; then
        echo "Cookies file does not exist. Executing relogin script."
        renewqzoneloginauto $1
    else
        echo "Cookies file exists. No action needed."
    fi
    json_path="./getmsgserv/post-step2/$numnext.json"
    need_priv=$(jq -r '.needpriv' "$json_path")
    postcommand="python3 ./SendQzone/send.py \"$massege\" ./getmsgserv/post-step5/$numnext/ $1"
    echo $postcommand
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        output=$(eval $postcommand)

        if echo "$output" | grep -q "Failed to publish."; then
            if [ $attempt -lt $max_attempts ]; then
                renewqzoneloginauto $1
            else
                sendmsggroup "空间发送错误，可能需要重新登陆，也可能是文件错误，出错账号$1"
                sendmsggroup "发送\"@出错账号 手动重新登陆\"以手动重新登陆",完毕后请重新发送审核指令
                askforintro
                break
            fi
        else
            goingtosendid=("${goingtosendid[@]/$qqid}")
            echo $1发送完毕
            sendmsggroup $1已发送
            break
        fi
        attempt=$((attempt+1))
    done
}
postqzone(){
    if [[ "$need_priv" == "false" ]]; then
        massege="#$numfinal @{uin:$id,nick:,who:1}"
    else
        massege="#$numfinal"
    fi
    sendqueue=("${goingtosendid[@]}")
    for qqid in "${sendqueue[@]}"; do
        echo "Sending qzone use id: $qqid"
        postprocess $qqid
    done
    sendmsgpriv $id "$numfinal 已发送(系统自动发送，请勿回复)"
    numfinal=$((numfinal + 1))
    echo $numfinal > ./"$groupname"_numfinal.txt
    id_file=./getmsgserv/rawpost/$id-$self_id.json
    current_mod_time_id=$(stat -c %Y "$id_file")
    echo "'current-mod-time-id:'$current_mod_time_id"
    echo "'last-mod-time-id:'$last_mod_time_id"
    if [ "$current_mod_time_id" -eq "$last_mod_time_id" ]; then
        echo "过程中此人无新消息，删除此人记录"
        rm $id_file
        rm -rf ./getmsgserv/post-step5/$numnext
    else
        rm -rf ./getmsgserv/post-step5/$numnext
        echo "过程中有新消息:needreprocess:$id"
        goingtosendid=""
        goingtosendid=("$mainqqid")
        IFS=',' read -ra minorqqids <<< "$minorqqid"
        for qqid in "${minorqqids[@]}"; do
            goingtosendid+=("$qqid")
        done
        getnumnext
        processsend
    fi
}
renewqzoneloginauto(){
    source ./venv/bin/activate
    if [[ "$disable_qzone_autologin" == "true" ]]; then
        renewqzonelogin $1
    else
        rm ./cookies-$self_id.json
        rm ./qrcode.png
        if [[ "$use_selenium_to_generate_qzone_cookies" == "true" ]]; then
            python3 ./SendQzone/qzonerenewcookies-selenium.py $1
        else
            python3 ./SendQzone/qzonerenewcookies.py $1
        fi
    fi
}
renewqzonelogin(){
    source ./venv/bin/activate
    rm ./cookies-$self_id.json
    rm ./qrcode.png
    python3 SendQzone/send.py relogin $1 &
        sleep 2
        sendmsggroup 请立即扫描二维码
        sendmsggroup "[CQ:image,file=$(pwd)/qrcode.png]"
        sleep 120
    postqzone
    sleep 2
    sleep 60
}
sendmsggroup(){
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:8083/send_group_msg?group_id=$groupid&message=$encoded_msg\""
    eval $cmd
}
sendmsgcommugroup(){
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:8083/send_group_msg?group_id=$commgroup_id&message=$encoded_msg\""
    eval $cmd
}
sendmsgpriv(){
    msg=$2
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:$port/send_private_msg?user_id=$1&message=$encoded_msg\""
    eval $cmd
}
processsend(){
    echo waitingforsender...
    sleep 120
    id_file=./getmsgserv/rawpost/$id-$self_id.json
    last_mod_time_id=$(stat -c %Y "$id_file")
    echo $id
    echo process-json...
    ./getmsgserv/LM_work/progress-lite-json.sh "${id}-${self_id}" ${numnext}
    echo 'wait-for-LM...'
    python3 ./getmsgserv/LM_work/sendtoLM-MTP.py ${numnext}
    for i in {1..3}
    do
        if [ -f "./getmsgserv/post-step2/${numnext}.json" ]; then
            echo "File exists, continuing..."
            break
        else
            echo "File not found, running Python LM script..."
            python3 ./getmsgserv/LM_work/sendtoLM-MTP.py "${numnext}"
        fi

        if [ "$i" -eq 3 ] && [ ! -f "./getmsgserv/post-step2/${numnext}.json" ]; then
            sendmsggroup LLM处理错误，请检查相关信息
        fi
    done
    json_path="./getmsgserv/post-step2/$numnext.json"
    need_priv=$(jq -r '.needpriv' "$json_path")
    numfinal=$(cat ./"$groupname"_numfinal.txt)
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
    content=$(<"$id_file")
    sendmsggroup "原始信息: $content /n $numnext"
    if [ "$safemsg" = "true" ]; then
        sendmsggroup AI审核判定安全
    elif [ "$safemsg" = "false" ]; then
        sendmsggroup AI审核判定不安全
    fi
    sendimagetoqqgroup
    numfinal=$(cat ./"$groupname"_numfinal.txt)
    sendmsggroup 内部编号$numnext，外部编号$numfinal
    echo askforgroup...
    askforintro
}
echo "开始处理来自$id的消息,账号$self_id,内部编号$numnext"
#初步处理文本消息
processsend
echo "来自$id的消息,内部编号$numnext,处理完毕"