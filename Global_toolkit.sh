sendmsggroup() {
    msg=$1
    encoded_msg=$(perl -MURI::Escape -e 'print uri_escape($ARGV[0]);' "$msg")
    # 构建 curl 命令，并发送编码后的消息
    curl -s -o /dev/null "http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg"
}
sendmsgpriv(){
    msg=$2
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
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