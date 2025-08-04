#!/bin/bash

# 激活虚拟环境
source ./Global_toolkit.sh

run_rules(){
    tag=$(echo "$in_json_data" | jq -r '.tag')
    local cur_tag="$tag"
    echo "max_post_stack: $max_post_stack"
    echo "max_image_number_one_post: $max_image_number_one_post"
    # 取出所有 tag，直接放进 tags 数组，同时计算总行数
    if [[ -n $comment && "$comment" != "null" ]]; then
        echo "评论: $comment"
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
        if [[ $current_image_num -gt $max_image_number_one_post ]]; then
            postmanager all
        fi
    fi
}

# 根据组名获取群组和账号发送参数
get_send_info(){
    json=$(sqlite3 -json cache/OQQWall.db "
    SELECT senderid, receiver, comment, AfterLM, ACgroup
    FROM preprocess WHERE tag='$1';
    ")
    senderid=$(jq -r '.[0].senderid' <<<"$json")
    receiver=$(jq -r '.[0].receiver' <<<"$json")
    comment=$(jq -r '.[0].comment'  <<<"$json")
    AfterLM=$(jq -r '.[0].AfterLM'  <<<"$json")
    groupname=$(jq -r '.[0].ACgroup' <<<"$json")  
    if [[ "$comment" == "null" ]]; then
        comment=""
    fi
    #检查 ACgroup 是否获取成功
        
    if [ -z "$groupname" ]; then
        log_and_continue   "获取 ACgroup 为空，请检查 preprocess 表中 tag: $1 对应的 ACgroup 字段"
        return 1
    fi
    # 当 json_data 为空时备用一个空 JSON 对象，避免 jq 解析出错
    [ -z "$json_data" ] && json_data="{}"
    need_priv=$(echo "$json_data" | jq -r '.needpriv // "false"' 2>/dev/null)
    group_info=$(jq -r --arg receiver "$receiver" '
        to_entries[] | select(.value.mainqqid == $receiver or (.value.minorqqid[]? == $receiver)) | .value
    ' AcountGroupcfg.json 2>/dev/null)
    if [ -z "$group_info" ] || [ "$group_info" = "null" ]; then
        log_and_continue "未找到账号为 $receiver 的账户配置！"
        return 1
    fi

    echo "$group_info"
    groupid=$(echo "$group_info" | jq -r '.mangroupid')
    echo "groupid:$groupid"
    mainqqid=$(echo "$group_info" | jq -r '.mainqqid')
    mainqq_http_port=$(echo "$group_info" | jq -r '.mainqq_http_port')
    minorqq_http_ports=$(echo "$group_info" | jq -r '.minorqq_http_port[]')
    minorqqid=$(echo "$group_info" | jq -r '.minorqqid[]')
    max_post_stack=$(echo "$group_info" | jq -r '.max_post_stack')
    max_image_number_one_post=$(echo "$group_info" | jq -r '.max_image_number_one_post')

    # 检查 max_post_stack 是否为数字且非空
    if ! [[ "$max_post_stack" =~ ^[0-9]+$ ]] || [ -z "$max_post_stack" ]; then
        max_post_stack=1
        sendmsggroup "警告: max_post_stack 配置无效，已使用默认值 1"
    fi
    # 检查 max_image_number_one_post 是否为数字且非空
    if ! [[ "$max_image_number_one_post" =~ ^[0-9]+$ ]] || [ -z "$max_image_number_one_post" ]; then
        max_image_number_one_post=30
        sendmsggroup "警告: max_image_number_one_post 配置无效，已使用默认值 30"
    fi
  
    echo "doing qq to port"
    qqidtoport "$receiver"
    echo "receiver:$receiver"
    echo "mainqqid:$mainqqid"
    echo "$port"
    run_rules || log_and_continue "run_rules 执行失败，tag: $1"
}

#把某个组的暂存内容全部发出
flush_staged(){
     # 直接用 groupname 在 AcountGroupcfg.json 中查配置（优先 key，次选 .acgroup）
    group_info=$(jq -r --arg g "$target_group" '
        if has($g) then .[$g]
        else (to_entries[] | select(.key==$g or (.value.acgroup? == $g)) | .value)
        end
    ' AcountGroupcfg.json 2>/dev/null)

    if [[ -z "$group_info" || "$group_info" == "null" ]]; then
        log_and_continue "flush_staged: 未找到组 $target_group 的账户配置"
        return 1
    fi

    # 设置全局变量，供 postmanager/send_list_gen/sendmsggroup 使用
    groupname="$target_group"
    mainqqid=$(echo "$group_info" | jq -r '.mainqqid')
    mainqq_http_port=$(echo "$group_info" | jq -r '.mainqq_http_port')
    groupid=$(echo "$group_info" | jq -r '.mangroupid')
    minorqq_http_ports=$(echo "$group_info" | jq -r '.minorqq_http_port[]? | select(. != "")')
    minorqqid=$(echo "$group_info" | jq -r '.minorqqid[]? | select(. != "")')

    local target_group="${1:-$groupname}"
    [[ -z "$target_group" ]] && { log_and_continue "flush_staged: groupname 未设置"; return 1; }

    # 拉取该组所有已暂存 tag
    mapfile -t tags < <(sqlite3 "$db_path" "SELECT tag FROM sendstorge_${target_group};")
    if (( ${#tags[@]} == 0 )); then
        sendmsggroup "flush: 组 ${target_group} 暂存为空，无需发送"
        return 0
    fi

    # 保障必要参数有效
    [[ "$max_image_number_one_post" =~ ^[0-9]+$ ]] || max_image_number_one_post=30
    [[ -n "$max_attempts" ]] || max_attempts=3

    # 校正数值型配置
    tmp_max_post_stack=$(echo "$group_info" | jq -r '.max_post_stack // empty')
    [[ "$tmp_max_post_stack" =~ ^[0-9]+$ ]] && max_post_stack="$tmp_max_post_stack" || max_post_stack=1

    tmp_max_img=$(echo "$group_info" | jq -r '.max_image_number_one_post // empty')
    [[ "$tmp_max_img" =~ ^[0-9]+$ ]] && max_image_number_one_post="$tmp_max_img" || max_image_number_one_post=30

    # 不带评论统一发送
    postmanager all || { log_and_continue "flush_staged: postmanager 失败（组：$target_group）"; return 1; }
    sendmsggroup "flush: 组 ${target_group} 暂存内容已全部发送"
    return 0
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
    [[ "$at_unprived_sender" == "false" ]] && return 1
    final_at=''
    local t
    for t in "$@"; do
        raw_output=$(timeout 10s sqlite3 -separator '|' 'cache/OQQWall.db' \
            "SELECT AfterLM,senderid FROM preprocess WHERE tag = '$t';" | tr -d '\n')
        IFS='|' read -r json_data atsenderid <<< "$raw_output"
        need_priv=$(echo "$json_data" | jq -r '.needpriv' 2>/dev/null)
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
    # 设置发送失败标志
    local send_failed=0
    sendmsggroup "执行发送..."
    send_list_gen
    # numfinal 合并
    IFS='|' read -r min_num max_num <<< "$(sqlite3 -noheader -separator '|' "$db_path" "SELECT MIN(num), MAX(num) FROM sendstorge_$groupname;")"
    if [[ "$min_num" == "$max_num" ]]; then
        message="#$min_num"
    else
        message="#${min_num}～${max_num}"
    fi
    echo "$message"
    message="${message} $(atgenerate "${tags[@]}")"
    if [[ -n $2 ]]; then
        message="${message} ${2}"
    fi
    # 图像列表创建
    mapfile -t file_arr < <(imglistgen "${tags[@]}")
    total=${#file_arr[@]}
    (( total == 0 )) && file_arr+=( )
    sendqueue=("${goingtosendid[@]}")
    for qqid in "${sendqueue[@]}"; do
        echo "Sending Qzone use id: $qqid (total images: $total)"
        for (( start=0; start<total || start==0; start+=max_image_number_one_post )); do
            slice=( "${file_arr[@]:start:max_image_number_one_post}" )
            sub_filelist=$(printf '%s\n' "${slice[@]}" | jq -R . | jq -sc .)
            [[ -z $sub_filelist || $sub_filelist == "null" ]] && sub_filelist='[]'
            postprocess_pipe "$qqid" "$message" "$sub_filelist" || { log_and_continue "postprocess_pipe 失败，qqid: $qqid, tag: $tag"; send_failed=1; }
        done
    done
    # 查表，发送反馈信息
    sqlite3 -separator '|' "$db_path" \
"SELECT senderid, port, num FROM sendstorge_$groupname;" |
    while IFS='|' read -r senderid port num; do
        # 若行为空则跳过（防止意外空行）
        [[ -z $senderid || -z $port || -z $num ]] && continue

        msg="#${num} 投稿已发送(系统自动发送，请勿回复)"
        sendmsgpriv_givenport "$senderid" "$port" "$msg"
    done
    # 发送结束后，仅在全部发送成功时删除缓存目录和清空暂存表
    if [[ $send_failed -eq 0 ]]; then
        sqlite3 "$db_path" "DELETE FROM sendstorge_$groupname;"
        # 删除对应的缓存目录释放空间
        if [[ ${#tags[@]} -gt 0 ]]; then
            for tag in "${tags[@]}"; do
                dir="./cache/prepost/$tag"
                if [[ -d $dir ]]; then
                    rm -rf -- "$dir"
                    echo "已删除缓存目录: $dir"
                fi
            done
        fi
    else
        echo "部分发送失败，保留缓存目录"
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
        renewqzoneloginauto "$1"
    else
        echo "Cookies file exists. No action needed."
    fi

    attempt=1
    while [ "$attempt" -le "$max_attempts" ]; do
        cookies=$(cat ./cookies-"$1".json)
        echo "{\"text\":\"$2\",\"image\":$3,\"cookies\":$cookies}" > ./qzone_in_fifo   
        post_statue=$(cat ./qzone_out_fifo)
        if echo "$post_statue"  | grep -q "success"; then
            goingtosendid=("${goingtosendid[@]/$1}")
            echo "$1发送完毕"
            sendmsggroup "$1已发送"
            break
        elif echo "$post_statue"  | grep -q "failed"; then
            if [ "$attempt" -lt "$max_attempts" ]; then
                renewqzoneloginauto "$1"
            else
                log_and_continue "空间发送错误，可能需要重新登陆，也可能是文件错误，出错账号$1,内部编号$tag,请发送指令"
                return 1
            fi
        else
            if [ "$attempt" -lt "$max_attempts" ]; then
                renewqzoneloginauto "$1"
            else
                log_and_continue "系统错误：$post_statue"
                return 1
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
    #启动定时发送
    scheduler_loop &
    # 准备发送命令占位（使用持续运行的 qzone-serv-pipe 服务时无需额外命令）
    postcommand=""
    echo "sendcontrol初始化完成"
}

# ===== 定时调度 =====
declare -A SCHEDULES   # 组 -> "HH:MM,HH:MM"
declare -A LASTFIRE    # "组|HH:MM" -> YYYY-MM-DD

load_schedules(){
    local cfg="AcountGroupcfg.json"
    SCHEDULES=()
    # 提取 (acgroup或key, 逗号拼接的时刻) 列表
    local rows
    rows=$(jq -r '
        to_entries[]
        | select(.value.send_schedule? and (.value.send_schedule|length)>0)
        | [ (.value.acgroup // .key), (.value.send_schedule | map(gsub("\\s+"; "")) | join(",")) ]
        | @tsv
    ' "$cfg" 2>/dev/null) || rows=""

    while IFS=$'\t' read -r g times; do
        [[ -z "$g" || -z "$times" ]] && continue
        SCHEDULES["$g"]="$times"
    done <<< "$rows"
}

mark_fired(){ local g="$1" hm="$2"; LASTFIRE["$g|$hm"]="$(date +%F)"; }
should_fire_now(){
    local g="$1" hm="$2" today; today=$(date +%F)
    [[ "${LASTFIRE[$g|$hm]}" == "$today" ]] && return 1 || return 0
}

scheduler_loop(){
    # 每轮都重载，便于热更新配置
    while true; do
        load_schedules
        local nowHM; nowHM=$(date +%H:%M)
        local g times hm list
        for g in "${!SCHEDULES[@]}"; do
            IFS=',' read -r -a list <<< "${SCHEDULES[$g]}"
            for hm in "${list[@]}"; do
                [[ "$hm" == "$nowHM" ]] || continue
                should_fire_now "$g" "$hm" || continue

                # 互斥锁，避免重入
                local LOCKDIR="./cache/.sched.lock"
                if mkdir "$LOCKDIR" 2>/dev/null; then
                    {
                        flush_staged "$g" || log_and_continue "定时发送失败：组 $g @ $hm"
                        mark_fired "$g" "$hm"
                    }
                    rmdir "$LOCKDIR" 2>/dev/null || true
                fi
            done
        done
        sleep 20
    done
}


# 主循环：持续从管道读取投稿发布请求
main_loop(){
    while true; do
        # 清空循环中使用的变量
        unset tag numfinal initsendstatue senderid receiver comment json_data need_priv groupname group_info groupid mainqqid mainqq_http_port minorqq_http_ports minorqqid port message file_arr goingtosendid
        groupname=""
        initsendstatue=""
        {
            in_json_data=$(cat ./presend_in_fifo)
            #echo "发送调度获取到$in_json_data"
            # 解析输入JSON字段
            action=$(jq -r '.action // empty' <<<"$in_json_data")
            if [[ "$action" == "flush" ]]; then
                target_group=$(jq -r '.group // empty' <<<"$in_json_data")
                if flush_staged "$target_group"; then
                    echo success > ./presend_out_fifo
                else
                    echo failed  > ./presend_out_fifo
                fi
                continue
            fi
            tag=$(echo "$in_json_data" | jq -r '.tag')
            numfinal=$(echo "$in_json_data" | jq -r '.numb')
            initsendstatue=$(echo "$in_json_data" | jq -r '.initsendstatue')  
            #echo "发送调度获取到tag=$tag,numfinal=$numfinal"
            # 获取该群组对应的发送参数（群号、端口等）
            get_send_info "$tag" || log_and_continue "get_send_info 执行失败，tag: $tag"
        } || {
            log_and_continue "主循环异常，输入数据: $in_json_data"
            continue
        }
    done
}

# 错误处理函数
log_and_continue() {
    local errmsg="$1"
    echo "sendcontrol $(date '+%Y-%m-%d %H:%M:%S') $errmsg" >> ./cache/SendControl_CrashReport.txt
    echo "sendcontrol 错误已记录: $errmsg"
}

# 启动 sendcontrol 模块
initialize
main_loop