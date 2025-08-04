source ./Global_toolkit.sh

log_and_continue() {
    local errmsg="$1"
    mkdir -p ./cache
    echo "processsend $(date '+%Y-%m-%d %H:%M:%S') $errmsg" >> ./cache/Processsend_CrashReport.txt
    echo "processsend 错误已记录: $errmsg"
}

postqzone(){
    #传给sendcontrol
    echo "开始传递给sendcontrol"
    json_data=$(jq -n --arg tag "$object" --arg numb "$numfinal" --arg initsendstatue "$initsendstatus" \
        '{tag:$tag, numb: $numb, initsendstatue: $initsendstatue}')
    echo "$json_data"
    echo "$json_data" > ./presend_in_fifo
    echo 已传递给sendcontrol
    # Check the status
    post_statue=$(cat ./presend_out_fifo)
    echo 已收到回报

    if echo "$post_statue"  | grep -q "success"; then
        goingtosendid=("${goingtosendid[@]/$1}")
        sendmsgpriv $senderid "#$numfinal 投稿已存入暂存区,你现在可以继续投稿(系统自动发送，请勿回复)"
        sendmsggroup "#$numfinal 投稿已存入暂存区"

    elif echo "$post_statue"  | grep -q "failed"; then
        log_and_continue "空间发送调度服务发生错误"
        exit 0
    else
        log_and_continue "空间发送调度服务发生错误"
        exit 0
    fi
    numfinal=$((numfinal + 1))
    echo $numfinal > ./cache/numb/"$groupname"_numfinal.txt
    current_mod_time_id=$(timeout 10s sqlite3 'cache/OQQWall.db' "select modtime from sender where senderid=$senderid;")
    if [[ "$current_mod_time_id" == "$last_mod_time_id" ]]; then
        echo "过程中此人无新消息，删除此人记录"
        timeout 10s sqlite3 "./cache/OQQWall.db" ".param set :id $senderid" "DELETE FROM sender WHERE senderid = :id;"
    else
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
  log_and_continue "未找到ID为 $receiver 的相关信息。"
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
        initsendstatus="stacking"
        numfinal=$(cat ./cache/numb/"$groupname"_numfinal.txt)
        postqzone
        echo 结束发件流程,是
        ;;
    立即)
        postcmd="true"
        initsendstatus="now"
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
        getmsgserv/preprocess.sh $object nowaittime
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
        # 允许拉黑，即使 flag 为空，但记录无拉黑理由
        if [ -z "$flag" ]; then
            reason="未提供"
        else
            reason="$flag"
        fi
        timeout 10s sqlite3 "./cache/OQQWall.db" <<EOF
INSERT OR IGNORE INTO blocklist (senderid, ACgroup, receiver, reason)
VALUES ('$senderid', '$groupname', '$receiver', '$reason');
EOF
        sendmsggroup 已拉黑$senderid
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
    扩列审查)
        response=$(curl -s "http://127.0.0.1:$port/get_stranger_info?user_id=$senderid")
        # 使用 jq 提取 qqLevel
        qqLevel=$(echo "$response" | jq '.data.qqLevel')
        qzoneopenstatus=$(check_qzone_open "$senderid")
        #草料二维码
        src_dir="./cache/picture/$object"
        API_URL="https://api.2dcode.biz/v1/read-qr-code"

        scan_result=""
        for img in "$src_dir"/*.{jpg,jpeg,png}; do

        # 上传文件并解析返回 JSON
        resp=$(curl -s -F "file=@${img}" "$API_URL")
        # 有些接口返回数组，有些返回字符串；统一兼容
        content=$(echo "$resp" | jq -r '
            .data.contents? //
            empty | (if type=="array" then join("\n") else . end)')

        # 若成功识别
        if [[ -n $content ]]; then
            # 扫描多张并全部汇总：
            scan_result+="$img: $content"$'\n'
        fi
        done

        # 去掉最后一个换行
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
        sendimagetoqqgroup $object
        sendmsggroup "内部编号$object, 请发送指令"
        ;;
    *)
        sendmsggroup "没有此指令,请查看说明,发送 @本账号 帮助 以查看帮助"
        sendmsggroup "内部编号$object, 请发送指令"
        ;;
esac
