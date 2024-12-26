#!/bin/bash

# 激活虚拟环境
activate_venv() {
    if [ -f "./venv/bin/activate" ]; then
        source ./venv/bin/activate
    else
        echo "虚拟环境激活脚本不存在！"
        exit 1
    fi
}

# 续期 Qzone 登录
renewqzoneloginauto(){
    receiver=$1
    activate_venv
    rm -f "./cookies-$receiver.json"
    rm -f "./qrcode.png"
    python3 ./SendQzone/qzonerenewcookies.py "$receiver"
}

# 发送私信
sendmsgpriv(){
    user_id=$1
    msg=$2
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    cmd="curl \"http://127.0.0.1:$port/send_private_msg?user_id=$user_id&message=$encoded_msg\""
    eval "$cmd"
}

# 发送群消息
sendmsggroup(){
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    cmd="curl \"http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg\""
    eval "$cmd"
}

# 发送图片到群
sendimagetoqqgroup() {
    folder_path="$(pwd)/cache/prepost/$object"
    if [ ! -d "$folder_path" ]; then
        echo "文件夹 $folder_path 不存在"
        exit 1
    fi

    find "$folder_path" -maxdepth 1 -type f | sort | while IFS= read -r file_path; do
        echo "发送文件: $file_path"
        msg="[CQ:image,file=$file_path]"
        encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
        cmd="curl \"http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg\""
        eval "$cmd"
        sleep 1  # 添加延时以避免过于频繁的请求
    done
    echo "所有文件已发送"
}

renewqzoneloginauto(){
    source ./venv/bin/activate
    rm ./cookies-$receiver.json
    rm ./qrcode.png
    python3 ./SendQzone/qzonerenewcookies.py $1
}
postqzone(){
    message_sending=$1
    image_send_list=$2
    echo {$goingtosendid[@]}
    sendqueue=("${goingtosendid[@]}")
    for qqid in "${sendqueue[@]}"; do
        echo "Sending qzone use id: $qqid"
        postprocess_pipe "$qqid" "$image_send_list" "$message_sending"
    done
    #sendmsgpriv $senderid "$numfinal 已发送(系统自动发送，请勿回复)"
    #numfinal=$((numfinal + 1))
    #echo $numfinal > ./cache/numb/"$groupname"_numfinal.txt
}

postprocess_pipe(){
    image_send_list=$2
    message_sending=$3
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        cookies=$(cat ./cookies-$1.json)
        
        # Fix JSON formatting by ensuring proper commas and quotes are placed
        echo "{\"text\":\"$message_sending\",\"image\":$image_send_list,\"cookies\":$cookies}" > ./qzone_in_fifo
        
        echo "$postcommand"
        
        # Execute the command
        eval $postcommand
        
        # Check the status
        post_statue=$(cat ./qzone_out_fifo)
        if echo "$post_statue"  | grep -q "failed"; then
            if [ $attempt -lt $max_attempts ]; then
                renewqzoneloginauto $1
            else
                sendmsggroup "空间发送错误，可能需要重新登陆，也可能是文件错误，出错账号$1,请发送指令"
                exit 1
            fi
        elif echo "$post_statue"  | grep -q "success"; then
            goingtosendid=("${goingtosendid[@]/$qqid}")
            echo "$1发送完毕"
            sendmsggroup "$1已发送"
            break
        else
            sendmsggroup "系统错误：$post_statue"
        fi
        attempt=$((attempt+1))
    done
}

# 检查并创建 SQLite 表
checkandcreattable(){
    local db_path="./cache/OQQWall.db"
    if ! sqlite3 "$db_path" "SELECT name FROM sqlite_master WHERE type='table' AND name='sendstorge_$groupname';" | grep -q "sendstorge_$groupname"; then
        sqlite3 "$db_path" "CREATE TABLE sendstorge_$groupname (tag INTEGER, atsender TEXT, image TEXT);"
        echo "表 sendstorge_$groupname 已创建。"
    else
        echo "表 sendstorge_$groupname 已存在。"
    fi
}

# 保存到存储
savetostorge(){
    local text="$1"
    shift
    local images=("$@")
    local db_path="./cache/OQQWall.db"
    
    tag=""
    char=""

    # 使用正则表达式匹配
    if [[ $text =~ ^#([0-9]+)(.*)$ ]]; then
        num="${BASH_REMATCH[1]}"  # 提取数字部分
        char="${BASH_REMATCH[2]}" # 提取字符部分（可能为空）
    else
        # 不以 # 开头，整个字符串作为字符部分
        char="$text"
    fi

    checkandcreattable
    # 将所有图片连接为逗号分隔的字符串
    image_list=$(IFS=,; echo "${images[*]}")

    # 将消息文本保存到 atsender 字段，图片列表保存到 image 字段
    sqlite3 "$db_path" "INSERT INTO sendstorge_$groupname (tag, atsender, image) VALUES ($tag, '$char', '$image_list');"
    
    echo "内容已保存到存储，tag=$tag"
}

# 处理组
process_group(){
    local db_path="./cache/OQQWall.db"
    local count=$(sqlite3 "$db_path" "SELECT COUNT(*) FROM sendstorge_$groupname;")
    if [ "$count" -ge 9 ]; then  # 假设阈值为40
        echo "sendnow"
    else
        echo "hold"
    fi
}

# 预处理发布
post_pre(){
    local mode="$1"  # all 或 single

    if [ "$mode" == "all" ]; then
        # 获取所有存储的消息和图片
        db_path="./cache/OQQWall.db"

        combined_message=$(sqlite3 "$db_path" "SELECT GROUP_CONCAT(atsender, ' ') FROM sendstorge_$groupname;")
        combined_images=$(sqlite3 "$db_path" "SELECT GROUP_CONCAT(image, ',') FROM sendstorge_$groupname;")
        mintag=$(sqlite3 "$db_path" "SELECT MIN(tag) FROM sendstorge_$groupname;")
        maxtag=$(sqlite3 "$db_path" "SELECT MAX(tag) FROM sendstorge_$groupname;")

        # 将图片列表转换为 JSON 数组
        combined_images="${combined_images// /,}"
        IFS=',' read -r image_array <<< "$combined_images"
        image_list="["
        first=true
        for img in "${image_array[@]}"; do
            if [ "$first" = true ]; then
                image_list+="\"$img\""
                first=false
            else
                image_list+=",\"$img\""
            fi
        done
        image_list+="]"

        # 发送合并后的内容
        postqzone "#$mintag~$maxtag $combined_message" "$image_list"
        sqlite3 "$db_path" "DELETE FROM sendstorge_$groupname;"

        # 清空存储
        sqlite3 "$db_path" "DELETE FROM sendstorge_$groupname;"
        sqlite3 "$db_path" "DELETE FROM sendstorge_$groupname;"
        echo "所有存储内容已发送并清空。"

    elif [ "$mode" == "single" ]; then

        # 将图片列表转换为 JSON 数组
        image_list="["
        first=true
        for img in "${image_in[@]}"; do
            if [ "$first" = true ]; then
                image_list+="\"${img#file://}\""
                first=false
            else
                image_list+=",\"${img#file://}\""
            fi
        done
        image_list+="]"

        # 发送直接输入的内容
        postqzone "$text_in" "$image_list"
        
        echo "最新的FIFO输入已发送。"
    fi
}

# 运行规则
run_rules(){
    local text_in="$1"
    shift
    local image_in=("$@")

    if [[ "$initsendstatue" == "sendnow" ]]; then
        # 先发送当前的所有库存投稿，再发送当前传入的投稿
        post_pre "all"
        post_pre "single"
    else
        savetostorge "$text_in" "${image_in[@]}"
    fi

    local statue_amount=$(process_group)
    if [[ "$statue_amount" == "sendnow" ]]; then
        post_pre "all"
    fi
}

# 获取发送信息
get_send_info(){
    group_info=$(jq -r --arg groupname "$groupname" '
    to_entries[] | select(.key == $groupname)
    ' "AcountGroupcfg.json")

    if [ -z "$group_info" ]; then
        echo "未找到组名为$groupname 的相关信息。"
        exit 1
    fi

    groupid=$(echo "$group_info" | jq -r '.value.mangroupid')
    mainqqid=$(echo "$group_info" | jq -r '.value.mainqqid')
    mainqq_http_port=$(echo "$group_info" | jq -r '.value.mainqq_http_port')
    minorqq_http_ports=$(echo "$group_info" | jq -r '.value.minorqq_http_port[]')
    minorqqids=$(echo "$group_info" | jq -r '.value.minorqqid[]')
    goingtosendid=("$mainqqid")
    IFS=',' read -ra minorqqids_array <<< "$minorqqids"
    for qqid in "${minorqqids_array[@]}"; do
        goingtosendid+=("$qqid")
    done
}

# 主循环
main_loop(){
    while true; do
        text_in=""
        image_in=()
        groupname=""
        initsendstatue=""
        if read -r in_json_data < ./presend_in_fifo; then
            text_in=$(echo "$in_json_data" | jq -r '.text')
            image_in=($(echo "$in_json_data" | jq -r '.image[]'))  
            groupname=$(echo "$in_json_data" | jq -r '.groupname')
            initsendstatue=$(echo "$in_json_data" | jq -r '.initsendstatue')

            get_send_info
            run_rules "$text_in" "${image_in[@]}"
        else
            echo "读取 FIFO 失败或 FIFO 被关闭。"
            sleep 1
        fi
    done
}

# 初始化
initialize(){
    max_attempts=$(grep 'max_attempts_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')
    if [ -z "$max_attempts" ]; then
        max_attempts=3  # 默认重试次数
    fi
     # 创建 FIFO 管道
    if [ ! -p ./presend_in_fifo ]; then
        mkfifo ./presend_in_fifo
    fi
    if [ ! -p ./presend_out_fifo ]; then
        mkfifo ./presend_out_fifo
    fi
}

# 添加清理函数
cleanup(){
    # 清理临时文件
    rm -f /dev/shm/OQQWall/oqqwallhtmlcache.html
    rm -f /dev/shm/OQQWall/oqqwallpdfcache.pdf
    
    # 关闭数据库连接
    sqlite3 "$db_path" ".quit"
    
    # 删除FIFO
    rm -f ./presend_in_fifo ./presend_out_fifo
}

# 添加信号处理
trap cleanup EXIT SIGINT SIGTERM

# 启动脚本
initialize
main_loop
