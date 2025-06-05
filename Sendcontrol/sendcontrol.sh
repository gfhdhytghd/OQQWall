#!/bin/bash

# 激活虚拟环境
source ./Global_toolkit.sh

run_rules(){
    tag=$(echo "$in_json_data" | jq -r '.tag') 
    local cur_tag="$tag"
    max_post_stack=$(grep 'max_post_stack' oqqwall.config | cut -d'=' -f2 | tr -d '"')
    max_imaga_number_one_post=$(grep 'max_imaga_number_one_post' oqqwall.config | cut -d'=' -f2 | tr -d '"')
    # 取出所有 tag，直接放进 tags 数组，同时计算总行数
    if [[ -n $comment ]]; then
        initsendstatue=now
    fi
    if [[ $initsendstatue == "now" ]]; then
        echo "立即发送..."
        if [[ $(sqlite3 "$db_path" "SELECT COUNT(*) FROM sendstorge_$groupname;") -gt 0 ]]; then
            tags=( $(sqlite3 "$db_path" "SELECT tag FROM sendstorge_$groupname;") )
            postmanager all  # 不带评论
        fi
        sqlite3 "$db_path" "DELETE FROM sendstorge_$groupname;"   # 清空表
        savetostorge "$cur_tag" "$numfinal" "$port" "$senderid"
        # 重新拉取本组全部 tag
        readarray -t tags < <(sqlite3 "$db_path" "SELECT tag FROM sendstorge_$groupname;")
        current_post_num="${#tags[@]}"
        current_image_num=$(image_counter "${tags[@]}")
        echo "当前投稿数: $current_post_num"
        echo "当前总图片数: $current_image_num"
        # 再统一发送
        postmanager all "$comment"
    else
        savetostorge "$cur_tag" "$numfinal" "$port" "$senderid"
        readarray -t tags < <(sqlite3 "$db_path" "SELECT tag FROM sendstorge_$groupname;")
        # 使用数组长度作为 current_post_num
        current_post_num="${#tags[@]}"
        # 计算当前所有图片数
        current_image_num=$(image_counter "${tags[@]}")
        if [[ $current_post_num -ge $max_post_stack ]]; then
            postmanager all
        fi
        if [[ $current_image_num -gt $max_imaga_number_one_post ]]; then
            postmanager all
        fi
    fi
}

# 根据组名获取群组和账号发送参数
get_send_info(){
    receiver=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT receiver FROM preprocess WHERE tag = '$1';")
    comment=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT comment FROM preprocess WHERE tag = $1;")
    json_data=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$1';")
    need_priv=$(echo $json_data|jq -r '.needpriv')
    groupname=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT ACgroup FROM preprocess WHERE tag = '$1';")
    group_info=$(jq -r --arg groupname "$groupname" '.[$groupname]' AcountGroupcfg.json)
    if [ -z "$group_info" ] || [ "$group_info" = "null" ]; then
        echo "未找到组名为 $groupname 的账户配置！"
        exit 1
    fi

    echo $group_info
    groupid=$(echo "$group_info" | jq -r '.mangroupid')
    echo "groupid:$groupid"
    mainqqid=$(echo "$group_info" | jq -r '.mainqqid')
    mainqq_http_port=$(echo "$group_info" | jq -r '.mainqq_http_port')
    minorqq_http_ports=$(echo "$group_info" | jq -r '.value.minorqq_http_port[]')
    minorqqid=$(echo "$group_info" | jq -r '.value.minorqqid[]')
    # 设置需要发送说说的账号列表（主账号 + 副账号）
    echo "doing qq to port"
    qqidtoport $receiver
    echo "receiver:$receiver"
    echo "mainqqid:$mainqqid"
    echo $port
    run_rules 
}

image_counter(){
    local total_count=0
    for tag in "$@"; do
        dir="./cache/prepost/$tag"
        if [ -d "$dir" ]; then
        count=$(find "$dir" -type f | wc -l)
        total_count=$((total_count + count))
        fi
    done
    echo "$total_count"
}
atgenerate(){
    if [[ "$at_unprived_sender" == "false" ]]; then
        return 1
    fi
    final_at=''
    local t       
    for t in "$@"; do
        local json_data=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$t';")
        local atsenderid=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT senderid FROM preprocess WHERE tag = '$t';")
        need_priv=$(echo $json_data|jq -r '.needpriv')
        if [[ "$need_priv" == "false" ]]; then
            final_at+=", @{uin:$atsenderid,nick:,who:1}"
        fi
    done
    echo "${final_at#, }"
}

imglistgen() {
    local tags=("$@")
    local filelist=()
    for tag in "${tags[@]}"; do
        local dir="./cache/prepost/$tag"
        [[ -d $dir ]] || continue
        for f in "$dir"/*; do
            [[ -f $f ]] && filelist+=("file://$f")
        done
    done
    printf '%s\n' "${filelist[@]}"
}

postmanager(){
    local rowcount
    rowcount=$(sqlite3 "$db_path" "SELECT COUNT(*) FROM sendstorge_$groupname;")
    if (( rowcount == 0 )); then
        echo "数据库为空，跳过本次发送"
        return            # 若在独立脚本里单独执行，可改为 exit 0
    fi
    sendmsggroup "执行发送..."
    send_list_gen
    #numfinal合并
    # 从数据库查询 min_num 和 max_num
    IFS='|' read -r min_num max_num <<< "$(sqlite3 -noheader -separator '|' "$db_path" "SELECT MIN(num), MAX(num) FROM sendstorge_$groupname;")"

    # 拼接成 xxx～xxx 格式
    if [[ "$min_num" == "$max_num" ]]; then
        message="#$min_num"
    else
        message="#${min_num}～${max_num}"
    fi

    # 输出 message 看看
    echo "$message"

    message="${message} $(atgenerate "${tags[@]}")"
    if [[ -n $2 ]];then
        message="${message} ${2}"
    fi
    #图像列表创建
    file_arr=( $(imglistgen "${tags[@]}") )
    total=${#file_arr[@]}
    (( total == 0 )) && file_arr+=( )

    sendqueue=("${goingtosendid[@]}")
    for qqid in "${sendqueue[@]}"; do
        echo "Sending Qzone use id: $qqid (total images: $total)"
        for (( start=0; start<total || start==0; start+=max_imaga_number_one_post )); do
            slice=( "${file_arr[@]:start:max_imaga_number_one_post}" )
            sub_filelist=$(printf '%s\n' "${slice[@]}" | jq -R . | jq -sc .)
            [[ -z $sub_filelist || $sub_filelist == "null" ]] && sub_filelist='[]'
            postprocess_pipe "$qqid" "$message" "$sub_filelist"
        done
    done
    #查表，发送反馈信息
    sqlite3 -separator '|' "$db_path" \
"SELECT senderid, port, num FROM sendstorge_$groupname;" |
    while IFS='|' read -r senderid port num; do
        # 若行为空则跳过（防止意外空行）
        [[ -z $senderid || -z $port || -z $num ]] && continue

        msg="#${num} 投稿已发送(系统自动发送，请勿回复)"
        sendmsgpriv_givenport "$senderid" "$port" "$msg"
    done
   # 清空暂存表
    sqlite3 "$db_path" "DELETE FROM sendstorge_$groupname;"

    #########################################################
    # 发送结束后，删除对应 ./cache/prepost/$tag 目录释放空间
    #########################################################
    if [[ ${#tags[@]} -gt 0 ]]; then
        for tag in "${tags[@]}"; do
            dir="./cache/prepost/$tag"
            if [[ -d $dir ]]; then
                rm -rf -- "$dir"
                echo "已删除缓存目录: $dir"
            fi
        done
    fi
}


qqidtoport(){
    if [ "$1" == "$mainqqid" ]; then
    port=$mainqq_http_port
    else
    # 遍历 minorqqid 数组并找到对应的端口
    i=0
    for minorqq in $minorqqid; do
        if [ "$1" == "$minorqq" ]; then
        port=$(echo "$minorqq_http_ports" | sed -n "$((i+1))p")
        break
        fi
        ((i++))
    done
    fi
}

# 将投稿保存到暂存表
savetostorge(){
    # 插入投稿记录
    sqlite3 "$db_path" "INSERT INTO sendstorge_$groupname (tag,num,port,senderid) VALUES ('$1', '$2','$3','$4');"
    echo success > ./presend_out_fifo
}

send_list_gen(){
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
}

postprocess_pipe(){
    if [ ! -f "./cookies-$1.json" ]; then
        echo "Cookies file does not exist. Executing relogin script."
        renewqzoneloginauto $1
    else
        echo "Cookies file exists. No action needed."
    fi

    attempt=1
    while [ $attempt -le $max_attempts ]; do
        cookies=$(cat ./cookies-$1.json)
        # Fix JSON formatting by ensuring proper commas and quotes are placed
        echo "{\"text\":\"$2\",\"image\":$3,\"cookies\":$cookies}" > ./qzone_in_fifo   
        # Check the status
        post_statue=$(cat ./qzone_out_fifo)
        if echo "$post_statue"  | grep -q "success"; then
            goingtosendid=("${goingtosendid[@]/$1}")
            echo "$1发送完毕"
            sendmsggroup "$1已发送"
            break
        elif echo "$post_statue"  | grep -q "failed"; then
            if [ $attempt -lt $max_attempts ]; then
                renewqzoneloginauto $1
            else
                sendmsggroup "空间发送错误，可能需要重新登陆，也可能是文件错误，出错账号$1,内部编号$tag,请发送指令"
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


# 初始化：读取配置并创建通信管道
initialize(){
    db_path="./cache/OQQWall.db"
    max_attempts=$(grep 'max_attempts_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')
    at_unprived_sender=$(grep 'at_unprived_sender' oqqwall.config | cut -d'=' -f2 | tr -d '"')
    [ -z "$max_attempts" ] && max_attempts=3
    # 创建发送控制输入FIFO管道
    if [ ! -p ./presend_in_fifo ]; then
        mkfifo ./presend_in_fifo
    fi
    if [ ! -p ./presend_out_fifo ]; then
        mkfifo ./presend_out_fifo
    fi
    # 准备发送命令占位（使用持续运行的 qzone-serv-pipe 服务时无需额外命令）
    postcommand=""
    echo "sendcontrol初始化完成"
}

# 主循环：持续从管道读取投稿发布请求
main_loop(){
    while true; do
        # 清空循环中使用的变量
        unset tag numfinal initsendstatue senderid receiver comment json_data need_priv groupname group_info groupid mainqqid mainqq_http_port minorqq_http_ports minorqqid port message file_arr goingtosendid
        groupname=""
        initsendstatue=""
        in_json_data=$(cat ./presend_in_fifo)
        echo "$in_json_data"
        # 解析输入JSON字段
        tag=$(echo "$in_json_data" | jq -r '.tag') 
        numfinal=$(echo "$in_json_data" | jq -r '.numb')      
        initsendstatue=$(echo "$in_json_data" | jq -r '.initsendstatue')
        senderid=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT senderid FROM preprocess WHERE tag = '$tag';")
        # 获取该群组对应的发送参数（群号、端口等）
        get_send_info $tag
    done
}

# 启动 sendcontrol 模块
initialize
main_loop
