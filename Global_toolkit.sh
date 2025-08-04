sendmsggroup() {
    msg=$1
    encoded_msg=$(perl -MURI::Escape -e 'print uri_escape($ARGV[0]);' "$msg")
    echo "发送消息: $msg到QQ群$groupid,端口$mainqq_http_port"
    # 构建 curl 命令，并发送编码后的消息
    curl -s -o /dev/null "http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg"
}
getandsendcard() {
    response=$(curl -s "http://127.0.0.1:$mainqq_http_port/ArkSharePeer?user_id=$1")
    # 使用 jq 提取 qqLevel
    arkMsg=$(echo "$response" | jq -r '.data.arkMsg')
    # 获取用户信息
    # 构造 JSON 请求体
    json_payload=$(jq -n \
    --arg group_id "$groupid" \
    --arg ark "$arkMsg" \
    '{
        group_id: $group_id,
        message: [
        {
            type: "json",
            data: {
            data: $ark
            }
        }
        ]
    }'
    )

    # 使用 curl 发送 POST 请求
    curl --location --request POST "http://127.0.0.1:$port/send_group_msg" \
--header 'Content-Type: application/json' \
--data-raw "$json_payload"

}
sendmsgpriv(){
    msg=$2
    encoded_msg=$(perl -MURI::Escape -e 'print uri_escape($ARGV[0]);' "$msg")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl -s -o /dev/null \"http://127.0.0.1:$port/send_private_msg?user_id=$1&message=$encoded_msg\""
    eval $cmd
}
sendmsgpriv_givenport(){
    msg=$3
    port=$2
    encoded_msg=$(perl -MURI::Escape -e 'print uri_escape($ARGV[0]);' "$msg")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl -s -o /dev/null \"http://127.0.0.1:$port/send_private_msg?user_id=$1&message=$encoded_msg\""
    eval $cmd
}
sendimagetoqqgroup() {
    # 设置文件夹路径
    folder_path="$(pwd)/cache/prepost/$1"
    # 检查文件夹是否存在
    if [ ! -d "$folder_path" ]; then
    sendmsggroup "不存在此待处理项目"
    exit 1
    fi
    find "$folder_path" -maxdepth 1 -type f | sort | while IFS= read -r file_path; do
        echo "发送文件: $file_path"
        msg=[CQ:image,file=file://$file_path]
        encoded_msg=$(perl -MURI::Escape -e 'print uri_escape($ARGV[0]);' "$msg")
        # 构建 curl 命令，并发送编码后的消息
        cmd="curl \"http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg\""
        eval $cmd
        sleep 1  # 添加延时以避免过于频繁的请求
    done
    sendmsggroup 
    echo "所有文件已发送"
}
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

renewqzonelogin(){
    rm ./cookies-$self_id.json
    rm ./qrcode.png
    python3 SendQzone/send.py relogin "" $1 &
        sleep 2
        sendmsggroup 请立即扫描二维码
        sendmsggroup "[CQ:image,file=$(pwd)/qrcode.png]"
        sleep 120
    postqzone
    sleep 2
    sleep 60
}
check_qzone_open() {
    local target_qq="$1"
    local api_url="http://127.0.0.1:$mainqq_http_port/get_cookies?domain=user.qzone.qq.com"

    # 最新 Chrome UA（Win10）
    local ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36"

    # 获取 cookies JSON 并提取 cookie 字符串
    local cookies_json
    cookies_json=$(curl -s "$api_url")

    local cookie
    cookie=$(echo "$cookies_json" | jq -r '.data.cookies')

    # 判断 Cookie 是否为空
    if [[ -z "$cookie" || "$cookie" == "null" ]]; then
        echo "不开放"
        return
    fi

    # 请求目标空间页面
    local html
    html=$(curl -s -A "$ua" -H "Cookie: $cookie" "https://user.qzone.qq.com/$target_qq")

    # 判断是否含有限制访问的提示
    if echo "$html" | grep -q "主人设置了权限，您可通过以下方式访问"; then
        echo "不开放"
    else
        echo "开放"
    fi
}
