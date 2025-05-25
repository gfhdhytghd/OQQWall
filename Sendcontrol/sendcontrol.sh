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

# 发送私信（通过 OneBot HTTP 接口）
sendmsgpriv(){
    user_id=$1
    msg=$2
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    curl -s -o /dev/null "http://127.0.0.1:$port/send_private_msg?user_id=$user_id&message=$encoded_msg"
}

# 发送群消息（通过 OneBot HTTP 接口）
sendmsggroup(){
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    curl -s -o /dev/null "http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg"
}

# 根据组名获取群组和账号发送参数
get_send_info(){
    group_info=$(jq -r --arg groupname "$groupname" '.[$groupname]' AcountGroupcfg.json)
    if [ -z "$group_info" ] || [ "$group_info" = "null" ]; then
        echo "未找到组名为 $groupname 的账户配置！"
        exit 1
    fi
    groupid=$(echo "$group_info" | jq -r '.mangroupid')
    mainqqid=$(echo "$group_info" | jq -r '.mainqqid')
    mainqq_http_port=$(echo "$group_info" | jq -r '.mainqq_http_port')
    # 设置需要发送说说的账号列表（主账号 + 副账号）
    goingtosendid=()
    goingtosendid+=("$(echo "$group_info" | jq -r '.mainqqid')")
    # 如有副账户配置，加入发送列表
    minor_ids=$(echo "$group_info" | jq -r '.minorqqid[]')
    if [ -n "$minor_ids" ] && [ "$minor_ids" != "" ]; then
        for mid in $minor_ids; do
            if [ -n "$mid" ]; then
                goingtosendid+=("$mid")
            fi
        done
    fi
    # 获取私信发送端口（假定所有账号共用同一 HTTP 服务端口）
    port=$(grep 'http-serv-port' oqqwall.config | cut -d'=' -f2 | tr -d '"[:space:]"')
}

# 检查并创建SQLite暂存表（按群区分）
check_and_create_table(){
    local db_path="./cache/OQQWall.db"
    sqlite3 "$db_path" "CREATE TABLE IF NOT EXISTS sendstorge_$groupname (tag INTEGER, atsender TEXT, image TEXT);"
}

# 将投稿保存到暂存表
savetostorge(){
    local text="$1"
    shift
    local images=("$@")
    local db_path="./cache/OQQWall.db"
    # 提取投稿编号和正文内容（如文本以#开头表示评论回复）
    local tag_num=""
    local content="$text"
    if [[ $text =~ ^#([0-9]+)(.*)$ ]]; then
        tag_num="${BASH_REMATCH[1]}"
        content="${BASH_REMATCH[2]}"
    fi
    # 转义文本中的单引号以防SQL错误
    local content_sql=$(echo "$content" | sed "s/'/''/g")
    # 拼接图片路径列表为逗号分隔字符串
    local image_list=""
    if [ ${#images[@]} -gt 0 ]; then
        image_list=$(IFS=,; echo "${images[*]}")
    fi
    check_and_create_table
    # 插入投稿记录
    sqlite3 "$db_path" "INSERT INTO sendstorge_$groupname (tag, atsender, image) VALUES ($tag_num, '$content_sql', '$image_list');"
}

# 检查暂存队列是否达到发送阈值
process_group(){
    local db_path="./cache/OQQWall.db"
    local count=$(sqlite3 "$db_path" "SELECT COUNT(*) FROM sendstorge_$groupname;")
    # 计算队列中累计的图片总数
    local total_images=0
    local images_lists=$(sqlite3 "$db_path" "SELECT image FROM sendstorge_$groupname;")
    while IFS= read -r line; do
        if [ -n "$line" ]; then
            IFS=',' read -ra imgs <<< "$line"
            total_images=$((total_images + ${#imgs[@]}))
        fi
    done <<< "$images_lists"
    # 读取阈值配置（没有配置则使用默认值）
    local max_count=$(grep 'merge_threshold' oqqwall.config | cut -d'=' -f2 | tr -d '"')
    local max_images=$(grep 'image_threshold' oqqwall.config | cut -d'=' -f2 | tr -d '"')
    [ -z "$max_count" ] && max_count=40
    [ -z "$max_images" ] && max_images=9
    if [ "$count" -ge "$max_count" ] || [ "$total_images" -ge "$max_images" ]; then
        echo "sendnow"
    else
        echo "hold"
    fi
}

# 发送前准备：将暂存队列合并/单条组织成 QQ空间说说内容并通过FIFO发送
post_pre(){
    local mode="$1"  # 模式："all" 合并全部暂存，"single" 发送单条
    local db_path="./cache/OQQWall.db"
    local message_text=""
    local image_array_json="[]"
    if [ "$mode" = "all" ]; then
        # 合并所有暂存消息文本（换行分隔）
        message_text=$(sqlite3 "$db_path" "SELECT GROUP_CONCAT(atsender, '\n') FROM sendstorge_$groupname;")
        # 汇总所有图片路径到数组
        combined_images=$(sqlite3 "$db_path" "SELECT image FROM sendstorge_$groupname WHERE image != '';")
        if [ -n "$combined_images" ]; then
            declare -a all_imgs
            while IFS= read -r line; do
                if [ -n "$line" ]; then
                    IFS=',' read -ra imgs <<< "$line"
                    for img in "${imgs[@]}"; do
                        all_imgs+=("$img")
                    done
                fi
            done <<< "$combined_images"
            if [ ${#all_imgs[@]} -gt 0 ]; then
                local img_json_elems=""
                for img in "${all_imgs[@]}"; do
                    if [ -n "$img_json_elems" ]; then
                        img_json_elems+=", \\\"$img\\\""
                    else
                        img_json_elems="\\\"$img\\\""
                    fi
                done
                image_array_json="[${img_json_elems}]"
            fi
        fi
    elif [ "$mode" = "single" ]; then
        # 取暂存表中最后一条记录的内容和图片
        message_text=$(sqlite3 "$db_path" "SELECT atsender FROM sendstorge_$groupname ORDER BY rowid DESC LIMIT 1;")
        local images_line=$(sqlite3 "$db_path" "SELECT image FROM sendstorge_$groupname ORDER BY rowid DESC LIMIT 1;")
        if [ -n "$images_line" ]; then
            IFS=',' read -ra imgs <<< "$images_line"
            if [ ${#imgs[@]} -gt 0 ]; then
                local img_json_elems=""
                for img in "${imgs[@]}"; do
                    if [ -n "$img_json_elems" ]; then
                        img_json_elems+=", \\\"$img\\\""
                    else
                        img_json_elems="\\\"$img\\\""
                    fi
                done
                image_array_json="[${img_json_elems}]"
            fi
        fi
    fi
    # 逐个账号尝试发送（支持多账号协同）
    for qqid in "${goingtonsendid[@]}"; do
        attempt=1
        while [ $attempt -le $max_attempts ]; do
            cookies=$(cat "./cookies-$qqid.json")
            # 写入待发送内容到 QQ空间输入管道
            echo "{\"text\":\"$message_text\",\"image\":$image_array_json,\"cookies\":$cookies}" > ./qzone_in_fifo
            # 读取发送结果输出
            post_status=$(cat ./qzone_out_fifo)
            if echo "$post_status" | grep -q "failed"; then
                if [ $attempt -lt $max_attempts ]; then
                    echo "QQ空间发送失败，尝试重新登录账号 $qqid （第 $((attempt+1)) 次重试）..."
                    renewqzoneloginauto $qqid
                else
                    sendmsggroup "投稿发送失败：账号 $qqid 可能需要重新登录，请检查。"
                fi
            elif echo "$post_status" | grep -q "success"; then
                echo "账号 $qqid 投稿发送成功。"
                sendmsggroup "账号 $qqid 已发布墙贴。"
                break
            else
                sendmsggroup "发布出现系统错误：$post_status"
            fi
            attempt=$((attempt+1))
        done
    done
    # 清理暂存队列内容
    if [ "$mode" = "all" ]; then
        sqlite3 "$db_path" "DELETE FROM sendstorge_$groupname;"
    elif [ "$mode" = "single" ]; then
        sqlite3 "$db_path" "DELETE FROM sendstorge_$groupname WHERE rowid = (SELECT MAX(rowid) FROM sendstorge_$groupname);"
    fi
}

# 处理新投稿的规则逻辑
run_rules(){
    # 如为管理员触发的立即发送所有指令（无正文），直接发送所有暂存内容
    if [ "$initsendstatue" = "sendnow" ] && [ -z "$text_in" ]; then
        # 立即发送所有暂存的投稿
        post_pre "all"
        return
    fi
    # 保存投稿到暂存数据库
    savetostorge "$text_in" "${image_in[@]}"
    # 决策是否需要发送
    local decide=$(process_group)
    if [ "$initsendstatue" = "single" ]; then
        # 管理员指令要求立即发送此帖
        post_pre "single"
    elif [ -n "$text_in" ] && [[ $text_in =~ ^#([0-9]+) ]]; then
        # 用户评论指令（#开头），即时单独发送
        post_pre "single"
    elif [ "$decide" = "sendnow" ]; then
        # 达到合并阈值，发送暂存队列所有内容
        post_pre "all"
    else
        # 未触发发送条件，暂不发送（内容已暂存队列）
        :
    fi
}

# 清理函数：退出时移除FIFO等
cleanup(){
    rm -f ./presend_in_fifo
    # （qzone_in_fifo 和 qzone_out_fifo 由 SendQzone 服务统一管理）
    echo "sendcontrol 已退出。"
}

# 初始化：读取配置并创建通信管道
initialize(){
    max_attempts=$(grep 'max_attempts_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')
    [ -z "$max_attempts" ] && max_attempts=3
    # 创建发送控制输入FIFO管道
    if [ ! -p ./presend_in_fifo ]; then
        mkfifo ./presend_in_fifo
    fi
    # 准备发送命令占位（使用持续运行的 qzone-serv-pipe 服务时无需额外命令）
    postcommand=""
}

# 主循环：持续从管道读取投稿发布请求
main_loop(){
    while true; do
        text_in=""
        image_in=()
        groupname=""
        initsendstatue=""
        if read -r in_json_data < ./presend_in_fifo; then
            # 解析输入JSON字段
            text_in=$(echo "$in_json_data" | jq -r '.text')
            # 提取图片数组
            local imgCount
            imgCount=$(echo "$in_json_data" | jq '.image | length')
            if [ "$imgCount" -gt 0 ]; then
                mapfile -t image_in < <(echo "$in_json_data" | jq -r '.image[]')
            fi
            groupname=$(echo "$in_json_data" | jq -r '.groupname')
            initsendstatue=$(echo "$in_json_data" | jq -r '.initsendstatue')
            # 获取该群组对应的发送参数（群号、端口等）
            get_send_info
            # 应用发送控制规则
            run_rules
        else
            echo "[sendcontrol] FIFO 读取失败或已关闭，等待重试..."
            sleep 1
        fi
    done
}

# 设置退出信号捕获，确保程序中止时清理资源
trap cleanup EXIT SIGINT SIGTERM

# 启动 sendcontrol 模块
initialize
main_loop
