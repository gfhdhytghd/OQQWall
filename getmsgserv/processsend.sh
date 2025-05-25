sendmsgpriv(){
    msg=$2
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl -s -o /dev/null \"http://127.0.0.1:$port/send_private_msg?user_id=$1&message=$encoded_msg\""
    eval $cmd
}
sendmsggroup() {
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    curl -s -o /dev/null "http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg"
}
sendimagetoqqgroup() {
    # 设置文件夹路径
    folder_path="$(pwd)/cache/prepost/$object"
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
        cmd="curl \"http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg\""
        echo $cmd
        eval $cmd
        sleep 1  # 添加延时以避免过于频繁的请求
    done
    echo "所有文件已发送"
}
# 续登 QQ 空间：给 QQ 号自动刷新 Napcat Cookie
# 调用：renewqzoneloginauto <qqid>
renewqzoneloginauto() {
    local qqid="$1"
    if [[ -z "$qqid" ]]; then
        echo "[ERR] renewqzoneloginauto: 缺少 QQ 号参数"
        return 1
    fi

    #▶ 删除旧 cookie / 二维码
    rm -f "./cookies-${qqid}.json" qrcode.png

    #▶ 解析端口
    local qport=""
    if [[ "$qqid" == "$mainqqid" ]]; then
        qport="$mainqq_http_port"
    else
        # minorqqid / minorqq_http_ports 需用 **相同顺序** 的逗号或空格分隔
        IFS=',' read -ra id_arr   <<< "$minorqqid"
        IFS=',' read -ra port_arr <<< "$minorqq_http_ports"
        for idx in "${!id_arr[@]}"; do
            if [[ "${id_arr[$idx]}" == "$qqid" ]]; then
                qport="${port_arr[$idx]}"
                break
            fi
        done
    fi
    if [[ -z "$qport" ]]; then
        echo "[ERR] renewqzoneloginauto: 找不到 QQ $qqid 对应端口"
        return 1
    fi
    echo "[INFO] renewqzoneloginauto: qq=$qqid  port=$qport"

    #▶ 执行续登脚本
    python3 ./SendQzone/qzonerenewcookies-napcat.py "$qport"
    local ret=$?
    if [[ $ret -ne 0 ]]; then
        echo "[ERR] qzonerenewcookies-napcat.py 失败 (exit=$ret)"
        return $ret
    fi
    echo "[OK] cookie 刷新成功"
}

postqzone(){
    message=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT comment FROM preprocess WHERE tag = $object;")
    if [ -z "$message" ]; then
        send_single=true
        json_data=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$object';")
        need_priv=$(echo $json_data|jq -r '.needpriv')
        if [[ "$need_priv" == "false" ]]; then
            message="#$numfinal @{uin:$senderid,nick:,who:1}"
        else
            message="#$numfinal"
        fi
    else
        send_single=false
    fi
    echo {$goingtosendid[@]}
    sendqueue=("${goingtosendid[@]}")
    for qqid in "${sendqueue[@]}"; do
        echo "Sending qzone use id: $qqid"
        postprocess_pipe $qqid
    done
    sendmsgpriv $senderid "$numfinal 已发送(系统自动发送，请勿回复)"
    numfinal=$((numfinal + 1))
    echo $numfinal > ./cache/numb/"$groupname"_numfinal.txt
    current_mod_time_id=$(timeout 10s sqlite3 'cache/OQQWall.db' "select modtime from sender where senderid=$senderid;")
    echo "'current-mod-time-id:'$current_mod_time_id"
    echo "'last-mod-time-id:'$last_mod_time_id"
    if [[ "$current_mod_time_id" == "$last_mod_time_id" ]]; then
        echo "过程中此人无新消息，删除此人记录"
        timeout 10s sqlite3 "./cache/OQQWall.db" ".param set :id $senderid" "DELETE FROM sender WHERE senderid = :id;"
        rm -rf ./cache/prepost/$object
    else
        rm -rf ./cache/prepost/$object
        echo "过程中有新消息:needreprocess:$senderid"
        object=$1  
        # 创建新预处理项目
        max_tag=$(timeout 10s sqlite3 "cache/OQQWall.db" "SELECT MAX(tag) FROM preprocess;")
        new_tag=$((max_tag + 1))
        row_data=$(timeout 10s sqlite3 "cache/OQQWall.db" "SELECT * FROM preprocess WHERE tag='$object';")
        if [[ -n "$row_data" ]]; then
            # 解析原始数据并插入新的行，替换tag为新的tag值
            # 避免使用关键字 'else'，改用 'extra'
        IFS="|" read -r tag senderid nickname receiver ACgroup extra <<< "$row_data"

        # 检查 $new_tag 是否定义，如果未定义则用 $tag
        if [ -z "$new_tag" ]; then new_tag="$tag"; fi

        # 使用参数化查询，避免 SQL 注入和引号问题
timeout 10s sqlite3 "cache/OQQWall.db" <<EOF
INSERT INTO preprocess (tag, senderid, nickname, receiver, ACgroup) 
VALUES (:tag, :senderid, :nickname, :receiver, :ACgroup);
.parameter set :tag '$new_tag'
.parameter set :senderid '$senderid'
.parameter set :nickname '$nickname'
.parameter set :receiver '$receiver'
.parameter set :ACgroup '$ACgroup'
EOF

        # 检查 SQLite 执行结果
        if [ $? -eq 0 ]; then
            echo "新的一行插入成功，新的tag值为$new_tag"
        else
            echo "插入失败，请检查数据库或数据格式"
        fi
        else
            echo "没有找到tag=$object的行"
        fi
        ./getmsgserv/preprocess $new_tag
    fi
}
postprocess(){
    #此函数已被弃用
    if [ ! -f "./cookies-$1.json" ]; then
        echo "Cookies file does not exist. Executing relogin script."
        renewqzoneloginauto $1
    else
        echo "Cookies file exists. No action needed."
    fi
    json_data=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$object';")
    need_priv=$(echo $json_data|jq -r '.needpriv')
    postcommand="python3 ./SendQzone/send.py \"$message\" ./cache/prepost/$object $1"
    echo $postcommand
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        output=$(eval $postcommand)

        if echo "$output" | grep -q "Failed to publish."; then
            if [ $attempt -lt $max_attempts ]; then
                renewqzoneloginauto $1
            else
                sendmsggroup "空间发送错误，可能需要重新登陆，也可能是文件错误，出错账号$1,发送\"@出错账号 手动重新登陆\"以手动重新登陆,完毕后请重新发送审核指令,请发送指令"
                exit 1
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
postprocess_pipe(){
    if [ ! -f "./cookies-$1.json" ]; then
        echo "Cookies file does not exist. Executing relogin script."
        renewqzoneloginauto $1
    else
        echo "Cookies file exists. No action needed."
    fi
    json_data=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$object';")
    need_priv=$(echo $json_data|jq -r '.needpriv')
    sendimgfolder=$(pwd)/cache/prepost/$object
    # Collect image paths
    file_paths=()
    for file in "$sendimgfolder"/*; do
        file_paths+=("\"file://$file\"")
    done

    # Join the image paths with commas
    IFS=','
    filelist=$(echo "[${file_paths[*]}]")

    attempt=1
    while [ $attempt -le $max_attempts ]; do
        cookies=$(cat ./cookies-$1.json)
        
        # Fix JSON formatting by ensuring proper commas and quotes are placed
        echo "{\"text\":\"$message\",\"image\":$filelist,\"cookies\":$cookies}" > ./qzone_in_fifo
        
        echo "$postcommand"
        
        # Execute the command
        eval $postcommand
        
        # Check the status
        post_statue=$(cat ./qzone_out_fifo)
        if echo "$post_statue"  | grep -q "success"; then
            goingtosendid=("${goingtosendid[@]/$qqid}")
            echo "$1发送完毕"
            sendmsggroup "$1已发送"
            break
        elif echo "$post_statue"  | grep -q "failed"; then
            if [ $attempt -lt $max_attempts ]; then
                renewqzoneloginauto $1
            else
                sendmsggroup "空间发送错误，可能需要重新登陆，也可能是文件错误，出错账号$1,请发送指令"
                exit 1
            fi
        else
            if [ $attempt -lt $max_attempts ]; then
                renewqzoneloginauto $1
            else
                sendmsggroup "系统错误：$post_statue"
                exit 1
            fi
        fi
        attempt=$((attempt+1))
    done
}

max_attempts=$(grep 'max_attempts_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')
echo processsend收到审核指令:$1
object=$(echo $1 | awk '{print $1}')
command=$(echo $1 | awk '{print $2}')
flag=$(echo $1 | awk '{print $3}')
senderid=$(timeout 10s sqlite3 'cache/OQQWall.db' "select senderid from preprocess where tag=$object;")
groupname=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT ACgroup FROM preprocess WHERE tag = '$object';")
last_mod_time_id=$(timeout 10s sqlite3 'cache/OQQWall.db' "select processtime from sender where senderid=$senderid;")
receiver=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT receiver FROM preprocess WHERE tag = '$object';")

group_info=$(jq -r --arg receiver "$receiver" '
  to_entries[] | select(.value.mainqqid == $receiver or (.value.minorqqid[]? == $receiver))
' "AcountGroupcfg.json")
# 检查是否找到了匹配的组
if [ -z "$group_info" ]; then
  echo "未找到ID为 $receiver 的相关信息。"
  exit 1
fi
groupid=$(echo "$group_info" | jq -r '.value.mangroupid')
mainqqid=$(echo "$group_info" | jq -r '.value.mainqqid')
mainqq_http_port=$(echo "$group_info" | jq -r '.value.mainqq_http_port')
sendmsggroup 已收到指令
minorqq_http_ports=$(echo "$group_info" | jq -r '.value.minorqq_http_port[]')
minorqqid=$(echo "$group_info" | jq -r '.value.minorqqid[]')
port=""
# 检查输入ID是否为mainqqid
if [ "$receiver" == "$mainqqid" ]; then
  port=$mainqq_http_port
else
  # 遍历 minorqqid 数组并找到对应的端口
  i=0
  for minorqqid in $minorqqid; do
    if [ "$receiver" == "$minorqqid" ]; then
      port=$(echo "$minorqq_http_ports" | sed -n "$((i+1))p")
      break
    fi
    ((i++))
  done
fi
echo port=$port
goingtosendid=("$mainqqid")
# 将minorqqid解析为数组并添加到goingtosendid
IFS=',' read -ra minorqqids <<< "$minorqqid"
for qqid in "${minorqqids[@]}"; do
    goingtosendid+=("$qqid")
done
touch ./cache/numb/"$groupname"_numfinal.txt
numfinal=$(cat ./cache/numb/"$groupname"_numfinal.txt)

case $command in
    是)
        postcmd="true"
        numfinal=$(cat ./cache/numb/"$groupname"_numfinal.txt)
        postqzone
        echo 结束发件流程,是
        ;;
    否)
        postcmd="false"
        rm -rf ./cache/prepost/$object
        timeout 10s sqlite3 "./cache/OQQWall.db" ".param set :id $senderid" "DELETE FROM sender WHERE senderid = :id;"
        rm -rf cache/prepost/$object
        numfinal=$(cat ./cache/numb/"$groupname"_numfinal.txt)
        numfinal=$((numfinal + 1))
        echo $numfinal > ./cache/numb/"$groupname"_numfinal.txt
        echo 结束发件流程,否
        ;;
    等)
        postcmd="wait"
        sleep 180
        getmsgserv/preprocess.sh $object
        ;;
    删)
        postcmd="del"
        rm -rf ./cache/prepost/$object
        timeout 10s sqlite3 "./cache/OQQWall.db" ".param set :id $senderid" "DELETE FROM sender WHERE senderid = :id;"
        ;;
    拒)
        postcmd="ref"
        rm -rf ./cache/prepost/$object
        timeout 10s sqlite3 "./cache/OQQWall.db" ".param set :id $senderid" "DELETE FROM sender WHERE senderid = :id;"
        rm -rf cache/prepost/$object
        sendmsgpriv $senderid '你的稿件被拒绝,请尝试修改后重新投稿'
        echo 结束发件流程,拒
        ;;
    拉黑)
        sendmsggroup 不再接收来自$senderid的投稿
        rm -rf cache/prepost/$object
        ;;
    匿)
        sendmsggroup 尝试切换匿名状态...
        json_content=$(timeout 10s sqlite3 "./cache/OQQWall.db" "SELECT AfterLM FROM preprocess WHERE tag='$object';")
        modified_json=$(echo "$json_content" | jq '.needpriv = (.needpriv == "true" | not | tostring)')
        timeout 10s sqlite3 "./cache/OQQWall.db" "UPDATE preprocess SET AfterLM='$modified_json' WHERE tag='$object';"
        
        # {
        #     flock -x 200  # Acquire exclusive lock
        #     getmsgserv/HTMLwork/gotohtml.sh $object > /dev/shm/OQQWall/oqqwallhtmlcache.html
        #     google-chrome-stable --headless --disable-gpu --print-to-pdf=/dev/shm/OQQWall/oqqwallpdfcache.pdf \
        #     --run-all-compositor-stages-before-draw --no-pdf-header-footer --virtual-time-budget=2000 \
        #     --pdf-page-orientation=portrait --no-margins --enable-background-graphics --print-background=true \
        #     file:///dev/shm/OQQWall/oqqwallhtmlcache.html
        # } 200>/dev/shm/OQQWall/oqqwall.lock  # Lock the directory with a lock file
        # Step 3: Process the output into JPG and send
        getmsgserv/preprocess.sh $object randeronly
        ;;
    刷新)
        getmsgserv/preprocess.sh $object nowaittime
        ;;
    重渲染)
        getmsgserv/preprocess.sh $object randeronly
        ;;
    评论)
        json_data=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$object';")
        need_priv=$(echo $json_data|jq -r '.needpriv')
        if [[ "$need_priv" == "false" ]]; then
            message="#$numfinal @{uin:$senderid,nick:,who:1}"
        else
            message="#$numfinal"
        fi
        if [ -n "$flag" ]; then
            message="${message}"' '"${flag}"
            sendmsggroup "增加评论后的文本：\n $message"
            sendmsggroup 请发送指令
        else
            if [[ "$need_priv" == "false" ]]; then
                message="#$numfinal @{uin:$senderid,nick:,who:1}"
            else
                message="#$numfinal"
            fi
            sendmsggroup "没有找到评论内容，文本内容已还原"
            sendmsggroup "当前文本：\n $message"
        fi
        timeout 10s sqlite3 'cache/OQQWall.db' "UPDATE preprocess SET comment='$message' WHERE tag = '$object';"
        ;;
    回复)
        sendmsgpriv $senderid $flag
        ;;
    展示)
        sendimagetoqqgroup
        ;;
    *)
        sendmsggroup "没有此指令,请查看说明,发送 @本账号 帮助 以查看帮助"
        sendmsggroup 请发送指令
        ;;
esac
