source ./Global_toolkit.sh
postqzone(){
    comment=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT comment FROM preprocess WHERE tag = $object;")
    json_data=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$object';")
    need_priv=$(echo $json_data|jq -r '.needpriv')
    if [[ "$need_priv" == "false" ]]; then
        message="#$numfinal @{uin:$senderid,nick:,who:1}"
    else
        message="#$numfinal"
    fi
    if [[ -n "$comment" && "$comment" != "null" ]]; then
    message="$message $comment"
    fi
    echo {$goingtosendid[@]}
    sendqueue=("${goingtosendid[@]}")
    for qqid in "${sendqueue[@]}"; do
        echo "Sending qzone use id: $qqid"
        postprocess_pipe $qqid
    done
    sendmsgpriv $senderid "# $numfinal 投稿已发送(系统自动发送，请勿回复)"
    numfinal=$((numfinal + 1))
    echo $numfinal > ./cache/numb/"$groupname"_numfinal.txt
    current_mod_time_id=$(timeout 10s sqlite3 'cache/OQQWall.db' "select modtime from sender where senderid=$senderid;")
    if [[ "$current_mod_time_id" == "$last_mod_time_id" ]]; then
        echo "过程中此人无新消息，删除此人记录"
        timeout 10s sqlite3 "./cache/OQQWall.db" ".param set :id $senderid" "DELETE FROM sender WHERE senderid = :id;"
        rm -rf ./cache/prepost/$object
    else
        rm -rf ./cache/prepost/$object
        echo "过程中有新消息:needreprocess:$senderid"
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
.parameter set :oldtag  $object
.parameter set :newtag  $new_tag
INSERT INTO preprocess (tag, senderid, nickname, receiver, ACgroup)
SELECT :newtag, senderid, nickname, receiver, ACgroup
  FROM preprocess
 WHERE tag = :oldtag;
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
        getmsgserv/preprocess.sh $new_tag
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
                sendmsggroup "空间发送错误，可能需要重新登陆，也可能是文件错误，出错账号$1,发送\"@出错账号 手动重新登陆\"以手动重新登陆,完毕后请重新发送审核指令,内部编号$object,请发送指令"
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
                sendmsggroup "空间发送错误，可能需要重新登陆，也可能是文件错误，出错账号$1,内部编号$object,请发送指令"
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
        getmsgserv/preprocess.sh $object randeronly
        ;;
    刷新)
        getmsgserv/preprocess.sh $object nowaittime
        ;;
    重渲染)
        getmsgserv/preprocess.sh $object randeronly
        ;;
    扩列审查|扩列|查|查成分)
        response=$(curl -s -H "$NAPCAT_AUTH_HEADER" "http://127.0.0.1:$port/get_stranger_info?user_id=$senderid")
        # 使用 jq 提取 qqLevel
        qqLevel=$(echo "$response" | jq '.data.qqLevel')
        qzoneopenstatus=$(check_qzone_open "$senderid")
        # 草料二维码
        src_dir="./cache/picture/$object"
        API_URL="https://api.2dcode.biz/v1/read-qr-code"

        scan_result=""
        for img in "$src_dir"/*.{jpg,jpeg,png}; do
            resp=$(curl -s -F "file=@${img}" "$API_URL")
            content=$(echo "$resp" | jq -r '.data.contents? // empty | (if type=="array" then join("\n") else . end)')
            if [[ -n $content ]]; then
                scan_result+="$img: $content"$'\n'
            fi
        done
        scan_result=${scan_result%$'\n'}
        [[ -z $scan_result ]] && scan_result="没有找到二维码"
        sendmsggroup "用户的QQ等级为: $qqLevel
对方空间对主账号$qzoneopenstatus
二维码扫描结果：$scan_result"
        getandsendcard "$senderid"
        sendmsggroup "内部编号$object, 请发送指令"
        ;;
    评论)
        json_data=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$object';")
        #need_priv=$(echo $json_data|jq -r '.needpriv')
        # if [[ "$need_priv" == "false" ]]; then
        #     message="#$numfinal @{uin:$senderid,nick:,who:1}"
        # else
        #     message="#$numfinal"
        # fi
        if [ -n "$flag" ]; then
            timeout 10s sqlite3 'cache/OQQWall.db' "UPDATE preprocess SET comment='$flag' WHERE tag = '$object';"
            sendmsggroup "已储存评论内容：\n $flag"
            sendmsggroup "内部编号$object, 请发送指令"
        else
            # if [[ "$need_priv" == "false" ]]; then
            #     message="#$numfinal @{uin:$senderid,nick:,who:1}"
            # else
            #     message="#$numfinal"
            # fi
            timeout 10s sqlite3 'cache/OQQWall.db' "UPDATE preprocess SET comment='' WHERE tag = '$object';"
            sendmsggroup "没有找到评论内容，评论已清空"
            sendmsggroup "内部编号$object, 请发送指令"
        fi
        ;;
    回复)
        sendmsgpriv $senderid $flag
        ;;
    展示)
        sendimagetoqqgroup
        ;;
    *)
        sendmsggroup "没有此指令,请查看说明,发送 @本账号 帮助 以查看帮助"
        sendmsggroup "内部编号$object, 请发送指令"
        ;;
esac
