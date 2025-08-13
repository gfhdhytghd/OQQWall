#!/bin/bash

# =============================================================================
# OQQWall SendControl 模块 - 优化版本
# 功能：管理QQ空间投稿的发送控制
# =============================================================================

set -euo pipefail  # 严格模式

# 激活虚拟环境
source ./Global_toolkit.sh

# =============================================================================
# 配置管理模块
# =============================================================================

# 配置常量
readonly CONFIG_FILE="oqqwall.config"
readonly DB_PATH="./cache/OQQWall.db"
readonly ACCOUNT_CONFIG_FILE="AcountGroupcfg.json"
readonly DEFAULT_MAX_ATTEMPTS=3
readonly DEFAULT_MAX_POST_STACK=1
readonly DEFAULT_MAX_IMAGE_NUMBER=30

# 全局配置变量
declare -g max_attempts
declare -g at_unprived_sender

# 加载基础配置
load_base_config() {
    max_attempts=$(grep 'max_attempts_qzone_autologin' "$CONFIG_FILE" | cut -d'=' -f2 | tr -d '"' || echo "$DEFAULT_MAX_ATTEMPTS")
    at_unprived_sender=$(grep 'at_unprived_sender' "$CONFIG_FILE" | cut -d'=' -f2 | tr -d '"' || echo "false")
    
    # 验证配置
    [[ "$max_attempts" =~ ^[0-9]+$ ]] || max_attempts=$DEFAULT_MAX_ATTEMPTS
}

# =============================================================================
# 数据库操作模块
# =============================================================================

# 获取投稿信息
get_post_info() {
    local tag="$1"
    local json
    
    json=$(sqlite3 -json "$DB_PATH" "
        SELECT senderid, receiver, comment, AfterLM, ACgroup
        FROM preprocess WHERE tag='$tag';
    ")
    
    if [[ -z "$json" || "$json" == "[]" ]]; then
        log_error "未找到tag为 $tag 的投稿信息"
        return 1
    fi
    
    echo "$json"
}

# 保存投稿到暂存表
save_to_storage() {
    local tag="$1" num="$2" port="$3" senderid="$4" groupname="$5"
    
    sqlite3 "$DB_PATH" "INSERT INTO sendstorge_$groupname (tag,num,port,senderid) VALUES ('$tag', '$num','$port','$senderid');"
    echo "success" > ./presend_out_fifo
}

# 获取暂存的投稿列表
get_stored_posts() {
    local groupname="$1"
    local tags=()
    
    mapfile -t tags < <(sqlite3 "$DB_PATH" "SELECT tag FROM sendstorge_$groupname;")
    printf '%s\n' "${tags[@]}"
}

# 清空暂存表
clear_storage() {
    local groupname="$1"
    sqlite3 "$DB_PATH" "DELETE FROM sendstorge_$groupname;"
}

# 获取投稿编号范围
get_post_number_range() {
    local groupname="$1"
    sqlite3 -noheader -separator '|' "$DB_PATH" "SELECT MIN(num), MAX(num) FROM sendstorge_$groupname;"
}

# =============================================================================
# 账户配置管理模块
# =============================================================================

# 获取账户组配置
get_account_group_config() {
    local receiver="$1"
    local group_info
    
    group_info=$(jq -r --arg receiver "$receiver" '
        to_entries[] | select(.value.mainqqid == $receiver or (.value.minorqqid[]? == $receiver)) | .value
    ' "$ACCOUNT_CONFIG_FILE" 2>/dev/null)
    
    if [[ -z "$group_info" || "$group_info" == "null" ]]; then
        log_error "未找到账号为 $receiver 的账户配置"
        return 1
    fi
    
    echo "$group_info"
}

# 获取组配置（用于flush操作）
get_group_config() {
    local target_group="$1"
    local group_info
    
    group_info=$(jq -r --arg g "$target_group" '
        if has($g) then .[$g]
        else (to_entries[] | select(.key==$g or (.value.acgroup? == $g)) | .value)
        end
    ' "$ACCOUNT_CONFIG_FILE" 2>/dev/null)
    
    if [[ -z "$group_info" || "$group_info" == "null" ]]; then
        log_error "未找到组 $target_group 的账户配置"
        return 1
    fi
    
    echo "$group_info"
}

# 解析账户配置
parse_account_config() {
    local group_info="$1"
    local -n config_ref="$2"
    
    config_ref[groupid]=$(echo "$group_info" | jq -r '.mangroupid')
    config_ref[mainqqid]=$(echo "$group_info" | jq -r '.mainqqid')
    config_ref[mainqq_http_port]=$(echo "$group_info" | jq -r '.mainqq_http_port')
    config_ref[minorqq_http_ports]=$(echo "$group_info" | jq -r '.minorqq_http_port[]?')
    config_ref[minorqqid]=$(echo "$group_info" | jq -r '.minorqqid[]?')
    
    # 设置默认值
    local tmp_max_post_stack=$(echo "$group_info" | jq -r '.max_post_stack // empty')
    config_ref[max_post_stack]=$([[ "$tmp_max_post_stack" =~ ^[0-9]+$ ]] && echo "$tmp_max_post_stack" || echo "$DEFAULT_MAX_POST_STACK")
    
    local tmp_max_img=$(echo "$group_info" | jq -r '.max_image_number_one_post // empty')
    config_ref[max_image_number_one_post]=$([[ "$tmp_max_img" =~ ^[0-9]+$ ]] && echo "$tmp_max_img" || echo "$DEFAULT_MAX_IMAGE_NUMBER")
}

# =============================================================================
# 图片处理模块
# =============================================================================

# 计算图片总数
count_images() {
    local total_count=0
    for tag in "$@"; do
        local dir="./cache/prepost/$tag"
        if [[ -d "$dir" ]]; then
            local count=$(find "$dir" -type f | wc -l)
            total_count=$((total_count + count))
        fi
    done
    echo "$total_count"
}

# 生成图片列表
generate_image_list() {
    local tags=("$@")
    local filelist=()
    
    for tag in "${tags[@]}"; do
        local dir="./cache/prepost/$tag"
        [[ -d "$dir" ]] || continue
        
        for f in "$dir"/*; do
            [[ -f "$f" ]] && filelist+=("file://$f")
        done
    done
    
    printf '%s\n' "${filelist[@]}"
}

# 清理缓存目录
cleanup_cache_dirs() {
    local tags=("$@")
    
    for tag in "${tags[@]}"; do
        local dir="./cache/prepost/$tag"
        if [[ -d "$dir" ]]; then
            rm -rf -- "$dir"
            echo "已删除缓存目录: $dir"
        fi
    done
}

# =============================================================================
# @功能模块
# =============================================================================

# 生成@列表
generate_at_list() {
    [[ "$at_unprived_sender" == "false" ]] && return 1
    
    local final_at=''
    local t
    local -A seen_senders  # 用于去重
    
    echo "DEBUG: generate_at_list called with tags: $*" >&2
    
    for t in "$@"; do
        local raw_output
        raw_output=$(timeout 10s sqlite3 -separator '|' "$DB_PATH" \
            "SELECT AfterLM,senderid FROM preprocess WHERE tag = '$t';")
        
        # 检查是否有结果
        if [[ -z "$raw_output" ]]; then
            echo "DEBUG: No result for tag $t" >&2
            continue
        fi
        
        local json_data atsenderid
        IFS='|' read -r json_data atsenderid <<< "$raw_output"
        local need_priv
        need_priv=$(echo "$json_data" | jq -r '.needpriv' 2>/dev/null)
        
        echo "DEBUG: Tag $t -> needpriv=$need_priv, senderid=$atsenderid" >&2
        
        if [[ "$need_priv" == "false" && -n "$atsenderid" && -z "${seen_senders[$atsenderid]}" ]]; then
            final_at+=", @{uin:$atsenderid,nick:,who:1}"
            seen_senders[$atsenderid]=1  # 标记为已处理
        fi
    done
    
    echo "DEBUG: Final at list: ${final_at#, }" >&2
    echo "${final_at#, }"
}

# =============================================================================
# 端口映射模块
# =============================================================================

# QQ号到端口映射
map_qq_to_port() {
    local qqid="$1"
    local mainqqid="$2"
    local mainqq_http_port="$3"
    local minorqqid="$4"
    local minorqq_http_ports="$5"
    
    if [[ "$qqid" == "$mainqqid" ]]; then
        echo "$mainqq_http_port"
    else
        local i=0
        for minorqq in $minorqqid; do
            if [[ "$qqid" == "$minorqq" ]]; then
                echo "$minorqq_http_ports" | sed -n "$((i+1))p"
                break
            fi
            ((i++))
        done
    fi
}

# =============================================================================
# 发送列表生成模块
# =============================================================================

# 生成发送列表
generate_send_list() {
    local group_info="$1"
    local -n send_list_ref="$2"
    
    send_list_ref=()
    send_list_ref+=("$(echo "$group_info" | jq -r '.mainqqid')")
    
    # 添加副账户
    local minor_ids
    minor_ids=$(echo "$group_info" | jq -r '.minorqqid[]?')
    if [[ -n "$minor_ids" && "$minor_ids" != "" ]]; then
        for mid in $minor_ids; do
            [[ -n "$mid" ]] && send_list_ref+=("$mid")
        done
    fi
}

# =============================================================================
# 发送处理模块
# =============================================================================

# 发送到QQ空间
send_to_qzone() {
    local qqid="$1"
    local message="$2"
    local image_list="$3"
    
    # 检查cookies文件
    if [[ ! -f "./cookies-$qqid.json" ]]; then
        echo "Cookies文件不存在，执行重新登录"
        renewqzoneloginauto "$qqid"
    fi
    
    local attempt=1
    while [[ "$attempt" -le "$max_attempts" ]]; do
        local cookies
        cookies=$(cat "./cookies-$qqid.json")
        
        echo "{\"text\":\"$message\",\"image\":$image_list,\"cookies\":$cookies}" > ./qzone_in_fifo
        local post_status
        post_status=$(cat ./qzone_out_fifo)
        
        if echo "$post_status" | grep -q "success"; then
            echo "$qqid发送完毕"
            sendmsggroup "$qqid已发送"
            return 0
        elif echo "$post_status" | grep -q "failed"; then
            if [[ "$attempt" -lt "$max_attempts" ]]; then
                renewqzoneloginauto "$qqid"
            else
                log_error "空间发送错误，可能需要重新登录，出错账号$qqid"
                return 1
            fi
        else
            if [[ "$attempt" -lt "$max_attempts" ]]; then
                renewqzoneloginauto "$qqid"
            else
                log_error "系统错误：$post_status"
                return 1
            fi
        fi
        ((attempt++))
    done
    
    return 1
}

# 发送反馈信息
send_feedback() {
    local groupname="$1"
    
    sqlite3 -separator '|' "$DB_PATH" \
        "SELECT senderid, port, num FROM sendstorge_$groupname;" |
    while IFS='|' read -r senderid port num; do
        [[ -z "$senderid" || -z "$port" || -z "$num" ]] && continue
        
        local msg="#${num} 投稿已发送(系统自动发送，请勿回复)"
        sendmsgpriv_givenport "$senderid" "$port" "$msg"
    done
}

# =============================================================================
# 发送管理模块
# =============================================================================

# 发送管理器
manage_posts() {
    local tags=()
    local comment=""
    local send_failed=0
    
    # 处理参数：最后一个参数可能是评论
    if [[ $# -gt 0 ]]; then
        # 检查最后一个参数是否看起来像评论（不是纯数字）
        if [[ "${!#}" =~ ^[0-9]+$ ]]; then
            # 最后一个参数是纯数字，可能是tag，所有参数都是tags
            tags=("$@")
        else
            # 最后一个参数不是纯数字，可能是评论
            comment="${!#}"
            # 前面的参数都是tags
            tags=("${@:1:$(( $# - 1 ))}")
        fi
    fi
    
    echo "DEBUG: manage_posts called with args: $*" >&2
    echo "DEBUG: tags array: ${tags[*]}" >&2
    echo "DEBUG: comment: '$comment'" >&2
    
    sendmsggroup "执行发送..."
    
    # 生成发送列表
    local goingtosendid=()
    generate_send_list "$group_info" goingtosendid
    
    # 生成消息内容
    local message
    local num_range
    num_range=$(get_post_number_range "$groupname")
    IFS='|' read -r min_num max_num <<< "$num_range"
    
    if [[ "$min_num" == "$max_num" ]]; then
        message="#$min_num"
    else
        message="#${min_num}～${max_num}"
    fi
    
    # 添加@列表
    local at_list
    at_list=$(generate_at_list "${tags[@]}")
    [[ -n "$at_list" ]] && message="${message} $at_list"
    
    # 添加评论
    [[ -n "$comment" ]] && message="${message} $comment"
    
    echo "DEBUG: Final message: $message" >&2
    
    # 生成图片列表
    local file_arr=()
    mapfile -t file_arr < <(generate_image_list "${tags[@]}")
    local total=${#file_arr[@]}
    (( total == 0 )) && file_arr+=( )
    
    # 发送到每个QQ号
    for qqid in "${goingtosendid[@]}"; do
        echo "Sending Qzone use id: $qqid (total images: $total)"
        
        for (( start=0; start<total || start==0; start+=max_image_number_one_post )); do
            local slice=("${file_arr[@]:start:max_image_number_one_post}")
            local sub_filelist
            sub_filelist=$(printf '%s\n' "${slice[@]}" | jq -R . | jq -sc .)
            [[ -z "$sub_filelist" || "$sub_filelist" == "null" ]] && sub_filelist='[]'
            
            send_to_qzone "$qqid" "$message" "$sub_filelist" || {
                log_error "发送失败，qqid: $qqid"
                send_failed=1
            }
        done
    done
    
    # 发送反馈
    send_feedback "$groupname"
    
    # 清理工作
    if [[ $send_failed -eq 0 ]]; then
        clear_storage "$groupname"
        cleanup_cache_dirs "${tags[@]}"
    else
        echo "部分发送失败，保留缓存目录"
    fi
    
    return $send_failed
}

# =============================================================================
# 发送规则模块
# =============================================================================

# 执行发送规则
execute_send_rules() {
    local tag="$1"
    local numfinal="$2"
    local port="$3"
    local senderid="$4"
    local comment="$5"
    local init_send_status="$6"
    
    echo "max_post_stack: $max_post_stack"
    echo "max_image_number_one_post: $max_image_number_one_post"
    
    if [[ -n "$comment" && "$comment" != "null" ]]; then
        echo "评论: $comment"
        init_send_status="now"
    fi
    
    # 保存当前投稿
    save_to_storage "$tag" "$numfinal" "$port" "$senderid" "$groupname"
    
    if [[ "$init_send_status" == "now" ]]; then
        echo "立即发送..."
        
        # 发送所有暂存内容（包括刚保存的）
        local stored_tags=()
        mapfile -t stored_tags < <(get_stored_posts "$groupname")
        
        if (( ${#stored_tags[@]} > 0 )); then
            manage_posts "${stored_tags[@]}" "$comment"
        fi
    else
        # 获取所有暂存投稿（包括刚保存的）
        local tags=()
        mapfile -t tags < <(get_stored_posts "$groupname")
        local current_post_num=${#tags[@]}
        local current_image_num
        current_image_num=$(count_images "${tags[@]}")
        
        echo "当前投稿数: $current_post_num"
        echo "当前总图片数: $current_image_num"
        echo "投稿列表: ${tags[*]}"
        
        # 检查是否需要发送
        if [[ $current_post_num -ge $max_post_stack ]] || [[ $current_image_num -gt $max_image_number_one_post ]]; then
            # 达到发送条件
            manage_posts "${tags[@]}"
        fi
    fi
}

# =============================================================================
# 发送信息处理模块
# =============================================================================

# 获取发送信息
get_send_info() {
    local tag="$1"
    local post_info group_info
    
    # 获取投稿信息
    post_info=$(get_post_info "$tag") || return 1
    
    # 解析投稿信息
    local senderid receiver comment AfterLM groupname
    senderid=$(jq -r '.[0].senderid' <<<"$post_info")
    receiver=$(jq -r '.[0].receiver' <<<"$post_info")
    comment=$(jq -r '.[0].comment' <<<"$post_info")
    AfterLM=$(jq -r '.[0].AfterLM' <<<"$post_info")
    groupname=$(jq -r '.[0].ACgroup' <<<"$post_info")
    
    # 处理空值
    [[ "$comment" == "null" ]] && comment=""
    
    # 验证组名
    if [[ -z "$groupname" ]]; then
        log_error "获取 ACgroup 为空，请检查 preprocess 表中 tag: $tag 对应的 ACgroup 字段"
        return 1
    fi
    
    # 获取账户配置
    group_info=$(get_account_group_config "$receiver") || return 1
    
    # 解析配置
    local -A config
    parse_account_config "$group_info" config
    
    # 设置全局变量（为了兼容现有代码）
    declare -g groupname="$groupname"
    declare -g group_info="$group_info"
    declare -g groupid="${config[groupid]}"
    declare -g mainqqid="${config[mainqqid]}"
    declare -g mainqq_http_port="${config[mainqq_http_port]}"
    declare -g minorqq_http_ports="${config[minorqq_http_ports]}"
    declare -g minorqqid="${config[minorqqid]}"
    declare -g max_post_stack="${config[max_post_stack]}"
    declare -g max_image_number_one_post="${config[max_image_number_one_post]}"
    
    # 获取端口
    local port
    port=$(map_qq_to_port "$receiver" "$mainqqid" "$mainqq_http_port" "$minorqqid" "$minorqq_http_ports")
    
    echo "doing qq to port"
    echo "receiver: $receiver"
    echo "mainqqid: $mainqqid"
    echo "port: $port"
    
    # 执行发送规则
    execute_send_rules "$tag" "$numfinal" "$port" "$senderid" "$comment" "$initsendstatue" || {
        log_error "execute_send_rules 执行失败，tag: $tag"
        return 1
    }
}

# =============================================================================
# 批量发送模块
# =============================================================================

# 批量发送暂存内容
flush_staged_posts() {
    local target_group="${1:-}"
    [[ -z "$target_group" ]] && {
        log_error "flush_staged_posts: 未指定目标组"
        return 1
    }
    
    # 获取组配置
    local group_info
    group_info=$(get_group_config "$target_group") || return 1
    
    # 解析配置
    local -A config
    parse_account_config "$group_info" config
    
    # 设置全局变量
    declare -g groupname="$target_group"
    declare -g group_info="$group_info"
    declare -g groupid="${config[groupid]}"
    declare -g mainqqid="${config[mainqqid]}"
    declare -g mainqq_http_port="${config[mainqq_http_port]}"
    declare -g groupid="${config[groupid]}"
    declare -g minorqq_http_ports="${config[minorqq_http_ports]}"
    declare -g minorqqid="${config[minorqqid]}"
    declare -g max_post_stack="${config[max_post_stack]}"
    declare -g max_image_number_one_post="${config[max_image_number_one_post]}"
    
    # 获取暂存投稿
    local tags=()
    mapfile -t tags < <(get_stored_posts "$target_group")
    
    if (( ${#tags[@]} == 0 )); then
        sendmsggroup "flush: 组 ${target_group} 暂存为空，无需发送"
        return 0
    fi
    
    # 发送所有暂存内容
    if manage_posts "${tags[@]}"; then
        sendmsggroup "flush: 组 ${target_group} 暂存内容已全部发送"
        return 0
    else
        log_error "flush_staged_posts: 发送失败（组：$target_group）"
        return 1
    fi
}

# =============================================================================
# 定时调度模块
# =============================================================================

# 调度配置
declare -A SCHEDULES   # 组 -> "HH:MM,HH:MM"
declare -A LASTFIRE    # "组|HH:MM" -> YYYY-MM-DD

# 加载调度配置
load_schedules() {
    SCHEDULES=()
    
    local rows
    rows=$(jq -r '
        to_entries[]
        | select(.value.send_schedule? and (.value.send_schedule|length)>0)
        | [ (.value.acgroup // .key), (.value.send_schedule | map(gsub("\\s+"; "")) | join(",")) ]
        | @tsv
    ' "$ACCOUNT_CONFIG_FILE" 2>/dev/null) || rows=""
    
    while IFS=$'\t' read -r g times; do
        [[ -z "$g" || -z "$times" ]] && continue
        SCHEDULES["$g"]="$times"
    done <<< "$rows"
}

# 标记已执行
mark_fired() {
    local g="$1" hm="$2"
    LASTFIRE["$g|$hm"]="$(date +%F)"
}

# 检查是否应该执行
should_fire_now() {
    local g="$1" hm="$2"
    local today
    today=$(date +%F)
    [[ "${LASTFIRE[$g|$hm]:-}" == "$today" ]] && return 1 || return 0
}

# 调度循环
scheduler_loop() {
    while true; do
        load_schedules
        local nowHM
        nowHM=$(date +%H:%M)
        
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
                        flush_staged_posts "$g" || log_error "定时发送失败：组 $g @ $hm"
                        mark_fired "$g" "$hm"
                    }
                    rmdir "$LOCKDIR" 2>/dev/null || true
                fi
            done
        done
        sleep 20
    done
}

# =============================================================================
# 错误处理模块
# =============================================================================

# 错误日志记录
log_error() {
    local errmsg="$1"
    echo "sendcontrol $(date '+%Y-%m-%d %H:%M:%S') $errmsg" >> ./cache/SendControl_CrashReport.txt
    echo "sendcontrol 错误已记录: $errmsg"
}

# =============================================================================
# 初始化模块
# =============================================================================

# 初始化函数
initialize() {
    # 加载基础配置
    load_base_config
    
    # 创建FIFO管道
    [[ ! -p ./presend_in_fifo ]] && mkfifo ./presend_in_fifo
    [[ ! -p ./presend_out_fifo ]] && mkfifo ./presend_out_fifo
    
    # 启动定时调度
    scheduler_loop &
    
    echo "sendcontrol初始化完成"
}

# =============================================================================
# 主循环模块
# =============================================================================

# 主循环
main_loop() {
    while true; do
        # 清空循环变量
        unset tag numfinal initsendstatue senderid receiver comment json_data need_priv groupname group_info groupid mainqqid mainqq_http_port minorqq_http_ports minorqqid port message file_arr goingtosendid
        groupname=""
        initsendstatue=""
        
        {
            local in_json_data
            in_json_data=$(cat ./presend_in_fifo)
            
            # 解析输入JSON
            local action
            action=$(jq -r '.action // empty' <<<"$in_json_data")
            
            if [[ "$action" == "flush" ]]; then
                local target_group
                target_group=$(jq -r '.group // empty' <<<"$in_json_data")
                
                if flush_staged_posts "$target_group"; then
                    echo "success" > ./presend_out_fifo
                else
                    echo "failed" > ./presend_out_fifo
                fi
                continue
            fi
            
            # 解析投稿信息
            tag=$(echo "$in_json_data" | jq -r '.tag')
            numfinal=$(echo "$in_json_data" | jq -r '.numb')
            initsendstatue=$(echo "$in_json_data" | jq -r '.initsendstatue')
            
            # 获取发送信息并执行
            get_send_info "$tag" || log_error "get_send_info 执行失败，tag: $tag"
            
        } || {
            log_error "主循环异常，输入数据: $in_json_data"
            continue
        }
    done
}

# =============================================================================
# 启动脚本
# =============================================================================

# 启动sendcontrol模块
initialize
main_loop