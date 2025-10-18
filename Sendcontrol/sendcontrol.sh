#!/bin/bash

# =============================================================================
# OQQWall SendControl 模块 - 优化版本
# 功能：管理QQ空间投稿的发送控制
# =============================================================================

# Test with python3 -m unittest Sendcontrol.tests.test_sendcontrol
# 服务说明（UDS）
# - 本脚本既是发送调度器，又作为一个基于 Unix Domain Socket 的服务端对外提供接口。
# - 监听方式：AF_UNIX/STREAM，使用 socat 在前台监听并为每个连接派生一次处理进程。
# - 套接字路径：环境变量 `SENDCONTROL_UDS_PATH`（默认 `./sendcontrol_uds.sock`）。
# - 连接模型：
#   * 客户端一次连接发送一条 JSON，请求结束以 EOF 表示；本服务处理后回写纯文本结果并断开。
#   * 每个连接互不影响；内部发送仍按业务规则顺序组织（分组/堆栈/限额）。
#
# 目标输入（JSON，无需换行，EOF 结束）：
# 1) 传递投稿
#    {
#      "tag":            "<整数/字符串>",   # preprocess.tag
#      "numb":           "<当前发布序号>",  # 用于生成文案的编号
#      "initsendstatue": "now" | "stacking"  # 立即发送/进入暂存堆栈
#    }
#
# 2) 触发组刷新发送（将暂存区的内容批量发送）
#    {
#      "action": "flush",
#      "group":  "<组键名或 acgroup>"
#    }
#
# 输出（纯文本）：
# - "success"：请求已被接收并按期望处理（或触发成功）
# - "failed"：请求解析/处理失败（含参数缺失、配置缺失、数据库/发送异常等）
#
# 客户端示例（socat）：
#   printf '%s' '{"tag":"123","numb":"7","initsendstatue":"now"}' \
#     | socat - UNIX-CONNECT:"${SENDCONTROL_UDS_PATH:-./sendcontrol_uds.sock}"
#   printf '%s' '{"action":"flush","group":"MyGroup"}' \
#     | socat - UNIX-CONNECT:"${SENDCONTROL_UDS_PATH:-./sendcontrol_uds.sock}"

set -euo pipefail  # 严格模式

# 调试开关：导出 SENDCONTROL_DEBUG=1 生效
SENDCONTROL_DEBUG=${SENDCONTROL_DEBUG:-0}

log_debug() {
    [[ "$SENDCONTROL_DEBUG" == "1" ]] || return 0
    local msg="$1"
    mkdir -p ./cache 2>/dev/null || true
    printf 'sendcontrol %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$msg" >> ./cache/SendControl_Debug.log
}

# 按需加载运行环境（仅在需要发消息/访问 NapCat 时加载）
__SC_TOOLKIT_LOADED=0
ensure_runtime_env() {
    if [[ "$__SC_TOOLKIT_LOADED" != "1" ]]; then
        # 激活虚拟环境/工具函数等（依赖 NAPCAT_ACCESS_TOKEN）
        # 放在需要时再加载，避免 --handle-conn 轻量回复阶段阻塞或报错
        source ./Global_toolkit.sh
        __SC_TOOLKIT_LOADED=1
    fi
}

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
    local tag_raw="$1"
    local tag json err retries=5 delay=0.2

    # 清理 tag（去除空白和不可见字符）
    tag=$(printf '%s' "$tag_raw" | tr -d '\r\n\t ')
    if [[ -z "$tag" ]]; then
        log_error "get_post_info: tag 为空（原始: '$tag_raw')"
        return 1
    fi

    # 重试以应对偶发的 DB 锁或初始化竞态
    while (( retries > 0 )); do
        err=""
        json=$(sqlite3 -json "$DB_PATH" "
            SELECT senderid, receiver, comment, AfterLM, ACgroup
            FROM preprocess WHERE tag='$tag';
        " 2> >(cat >&2)) || true

        # 正常返回行
        if [[ -n "$json" && "$json" != "[]" ]]; then
            echo "$json"
            return 0
        fi

        # 若无结果或锁冲突，短暂等待后重试
        sleep "$delay"
        retries=$((retries-1))
    done

    log_error "未找到tag为 $tag 的投稿信息"
    return 1
}

# 保存投稿到暂存表
save_to_storage() {
    local tag="$1" num="$2" port="$3" senderid="$4" groupname="$5"
    # 确保暂存表存在（首次运行场景）
    sqlite3 "$DB_PATH" "CREATE TABLE IF NOT EXISTS sendstorge_$groupname (tag TEXT, num TEXT, port TEXT, senderid TEXT);"
    sqlite3 "$DB_PATH" "INSERT INTO sendstorge_$groupname (tag,num,port,senderid) VALUES ('$tag', '$num','$port','$senderid');"
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
# 生成@列表（替换原函数）
generate_at_list() {
    [[ "$at_unprived_sender" == "false" ]] && return 1

    local final_at=''
    local t
    declare -A seen_senders  # 去重

    echo "DEBUG: generate_at_list called with tags: $*" >&2

    for t in "$@"; do
        # 清理 tag 里的不可见字符（防止 WHERE 不命中）
        local t_clean
        t_clean=$(printf '%s' "$t" | tr -d '\r\n\t ')

        # 拉数据；用 COALESCE 防止 NULL 变空串
        local afterlm_raw atsenderid
        afterlm_raw=$(timeout 10s sqlite3 "$DB_PATH" \
            "SELECT COALESCE(AfterLM,'') FROM preprocess WHERE tag = '$t_clean';")
        atsenderid=$(timeout 10s sqlite3 "$DB_PATH" \
            "SELECT COALESCE(senderid,'') FROM preprocess WHERE tag = '$t_clean';")

        if [[ -z "$afterlm_raw" ]]; then
            echo "DEBUG: No result for tag $t_clean" >&2
            continue
        fi

        local need_priv
        need_priv=$(
            printf '%s' "$afterlm_raw" | jq -r 'try .needpriv catch empty' 2>/dev/null
        )
        if [[ -z "$need_priv" ]]; then
            need_priv=$(
                printf '%s' "$afterlm_raw" | jq -r 'try (fromjson | .needpriv) catch empty' 2>/dev/null
            )
        fi

        echo "DEBUG: Tag $t_clean -> needpriv=$need_priv, senderid=$atsenderid" >&2

        if [[ "$need_priv" == "false" && -n "$atsenderid" && -z "${seen_senders[$atsenderid]:-}" ]]; then
            final_at+=", @{uin:$atsenderid,nick:,who:1}"
            seen_senders[$atsenderid]=1
        fi
    done

    # 去掉前导逗号+空格
    final_at="${final_at#, }"
    echo "DEBUG: Final at list: $final_at" >&2
    printf '%s' "$final_at"
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
        local cookies_file
        cookies_file="./cookies-$qqid.json"
        
        local post_status
        # 通过 UDS 使用 socat 与服务交互（一次请求一次连接，等待服务端回包）
        if ! command -v socat >/dev/null 2>&1; then
            log_error "未检测到 socat，请安装后再试"
            return 1
        fi

        # 首次轻量尝试构造 JSON；失败后才进行更严格的校验与重试
        local json_payload
        local jq_err
        jq_err=$(mktemp 2>/dev/null || echo "/tmp/jq_err_$$")
        json_payload=$(jq -nc \
            --arg text "$message" \
            --argjson image "$image_list" \
            --slurpfile cookies "$cookies_file" \
            '{text:$text, image:$image, cookies:$cookies[0]}') 2>"$jq_err" || {
            local errfirst
            errfirst=$(head -n1 "$jq_err" 2>/dev/null || true)
            rm -f "$jq_err" 2>/dev/null || true
            if (( attempt == 1 )); then
                log_error "构造投稿 JSON 首次失败，进入诊断重试: ${errfirst:-unknown}"
                # 1) cookies 文件 JSON 校验
                if ! jq -e . "$cookies_file" >/dev/null 2>&1; then
                    log_error "cookies JSON 无效或损坏: ./cookies-$qqid.json"
                    renewqzoneloginauto "$qqid"
                fi
                # 2) image_list 必须为数组
                if ! printf '%s' "$image_list" | jq -e 'type=="array"' >/dev/null 2>&1; then
                    log_error "image_list 非法（应为 JSON 数组），前200字节: ${image_list:0:200}"
                    ((attempt++))
                    continue
                fi
                # 3) message UTF-8 清洗
                if command -v iconv >/dev/null 2>&1; then
                    if ! printf '%s' "$message" | iconv -f UTF-8 -t UTF-8 >/dev/null 2>&1; then
                        log_error "message 包含非法 UTF-8，已自动清洗后重试构造 JSON"
                        message=$(printf '%s' "$message" | iconv -f UTF-8 -t UTF-8 -c)
                    fi
                fi
                # 4) 打印概要参数
                local image_count cookies_size
                image_count=$(printf '%s' "$image_list" | jq -r 'length' 2>/dev/null || echo "unknown")
                cookies_size=$(wc -c < "$cookies_file" 2>/dev/null | tr -d ' ' || echo "unknown")
                log_debug "构造JSON参数(重试): text_len=${#message}, images=${image_count}, cookies_size=${cookies_size}B"
                ((attempt++))
                continue
            else
                log_error "构造投稿 JSON 失败: ${errfirst:-unknown}"
                log_error "message前120字: ${message:0:120}, image_list前200字节: ${image_list:0:200}"
                return 1
            fi
        }
        rm -f "$jq_err" 2>/dev/null || true

        local uds_path
        uds_path="${QZONE_UDS_PATH:-./qzone_uds.sock}"

        # 等待 UDS 可用（系统修复/重启后需要重建）
        local waited=0 max_wait=15
        while [[ ! -S "$uds_path" && $waited -lt $max_wait ]]; do
            log_debug "等待 QZone UDS 重建: $uds_path ($waited/$max_wait)"
            sleep 1; ((waited++))
        done
        if [[ ! -S "$uds_path" ]]; then
            log_error "QZone UDS 不可用: $uds_path"
            return 1
        fi

        if ! post_status=$(printf '%s' "$json_payload" \
            | socat -t 60 -T 180 - UNIX-CONNECT:"$uds_path" 2>/dev/null); then
            log_error "投稿传输失败，尝试第${attempt}次，账号: $qqid"
            if [[ "$attempt" -lt "$max_attempts" ]]; then
                renewqzoneloginauto "$qqid"
                ((attempt++))
                continue
            else
                log_error "投稿传输失败，已达最大重试次数，账号: $qqid"
                return 1
            fi
        fi

        if echo "$post_status" | grep -q "success"; then
            echo "$qqid发送完毕"
            sendmsggroup "$qqid已发送"
            return 0
        elif echo "$post_status" | grep -q "failed"; then
            if [[ "$attempt" -lt "$max_attempts" ]]; then
                renewqzoneloginauto "$qqid"
                ((attempt++))
                continue
            else
                log_error "空间发送错误，已达最大重试次数，出错账号$qqid"
                return 1
            fi
        else
            if [[ "$attempt" -lt "$max_attempts" ]]; then
                renewqzoneloginauto "$qqid"
                ((attempt++))
                continue
            else
                log_error "系统错误：$post_status"
                return 1
            fi
        fi
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
    
    # 仅在启用堆栈模式时提示“执行发送...”
    if [[ "$max_post_stack" -ne 1 ]]; then
        sendmsggroup "执行发送..."
    fi
    
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
    
    # 按发送结果反馈
    if [[ $send_failed -eq 0 ]]; then
        # 仅在所有发布均成功时通知“投稿已发送”
        send_feedback "$groupname"
        # 清理缓存与暂存
        clear_storage "$groupname"
        cleanup_cache_dirs "${tags[@]}"
    else
        # 发布失败时，不要发送“已发送”提示；改为失败提示并保留缓存
        echo "部分发送失败，保留缓存目录"
        sendmsggroup "投稿发送失败，已保留缓存，稍后将自动重试或请管理员处理"
        # 逐条私聊告知失败
        sqlite3 -separator '|' "$DB_PATH" \
            "SELECT senderid, port, num FROM sendstorge_$groupname;" |
        while IFS='|' read -r senderid port num; do
            [[ -z "$senderid" || -z "$port" || -z "$num" ]] && continue
            sendmsgpriv_givenport "$senderid" "$port" "#${num} 投稿发送失败，请稍后重试"
        done
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
    
    # 提示入栈：在启用堆栈模式(max_post_stack!=1)且非立即发送时，通知已入暂存区
    if [[ "$init_send_status" != "now" && "$max_post_stack" -ne 1 ]]; then
        sendmsggroup "#${numfinal}投稿已存入暂存区"
        sendmsgpriv_givenport "$senderid" "$port" "#${numfinal}投稿已存入暂存区(系统自动发送，请勿回复)"
    fi
    
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
    
    if [[ -z "${tags[*]// }" ]]; then
        printf '%s' "no pending posts"
        return 0
    fi
    
    # 发送所有暂存内容
    if manage_posts "${tags[@]}"; then
        sendmsggroup "暂存区调度器: 组 ${target_group} 暂存内容已全部发送"
        printf '%s' "success"
        return 0
    else
        log_error "flush_staged_posts: 发送失败（组：$target_group）"
        printf '%s' "failed"
        return 1
    fi
}
# =============================================================================
# 定时调度模块（单实例 + 分钟锁 + 当日标记）
# =============================================================================

readonly SCHED_GLOBAL_LOCK="./cache/.sched.global.lock"
readonly SCHED_PID_FILE="./cache/.sched.pid"

# 读取：每行  <group>\t<HH:MM,HH:MM,...>
_load_schedules() {
  jq -r '
    to_entries[]
    | select(.value.send_schedule? and (.value.send_schedule|length)>0)
    | [ (.value.acgroup // .key), (.value.send_schedule | map(gsub("\\s+"; "")) | join(",")) ]
    | @tsv
  ' "$ACCOUNT_CONFIG_FILE" 2>/dev/null
}

# 当日只触发一次 + 同一分钟互斥
_fire_once() {
  local g="$1" hm="$2"
  local today markfile lockdir
  today=$(date +%F)
  markfile="./cache/.sched.fired.${g}.${hm}.${today}"
  lockdir="./cache/.sched.lock.${g}.${hm}"

  # 已触发过：直接返回
  [[ -f "$markfile" ]] && return 0

  # 同一分钟锁
  if mkdir "$lockdir" 2>/dev/null; then
    : > "$markfile"  # 先落地“已触发”标记，避免失败后重复
    if ! flush_staged_posts "$g"; then
      echo "sendcontrol $(date '+%F %T') 定时发送失败：组 ${g} @ ${hm}" >> ./cache/SendControl_CrashReport.txt
    fi
    # 锁保持到分钟跳变
    while [[ "$(date +%H:%M)" == "$hm" ]]; do sleep 1; done
    rmdir "$lockdir" 2>/dev/null || true
  fi
}

# 单实例守护的 scheduler（不要再另起旧的 scheduler_loop）
_run_scheduler() {
  mkdir -p ./cache

  # 全局单实例锁：整个进程生命周期持有
  exec {__sched_fd}> "$SCHED_GLOBAL_LOCK" || true
  if ! flock -n "${__sched_fd}"; then
    echo "scheduler 已在运行（跳过重复启动）"
    return 0
  fi
  echo $$ > "$SCHED_PID_FILE"

  # 正常循环：对齐到整分
  while true; do
    local nowHM; nowHM=$(date +%H:%M)

    while IFS=$'\t' read -r g times; do
      [[ -z "$g" || -z "$times" ]] && continue
      IFS=',' read -r -a arr <<< "$times"
      for hm in "${arr[@]}"; do
        [[ "$hm" == "$nowHM" ]] && _fire_once "$g" "$hm"
      done
    done < <(_load_schedules)

    sleep $((60-10#$(date +%S)))
  done
}

# 对外启动函数：确保旧实例被清掉、且只启动一次
start_scheduler() {
  mkdir -p ./cache
  # 如果有残留 PID 但进程已不存在，清理
  if [[ -f "$SCHED_PID_FILE" ]]; then
    local oldpid; oldpid=$(cat "$SCHED_PID_FILE" 2>/dev/null || true)
    if [[ -n "$oldpid" && ! -d "/proc/$oldpid" ]]; then
      rm -f "$SCHED_PID_FILE"
    fi
  fi

  # 后台启动单实例调度器
  _run_scheduler &
  echo "scheduler 已启动(单实例)"
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
    # 依赖自检
    if ! command -v socat >/dev/null 2>&1; then
        echo "[ERR] sendcontrol 需要 socat，请先安装（apt/pacman/dnf/yum/brew/pkg）。" >&2
        return 1
    fi
    # 加载运行环境（NapCat 相关工具）
    ensure_runtime_env
    # 启动定时调度
    start_scheduler
    echo "sendcontrol初始化完成"
}

# =============================================================================
# 主循环模块
# =============================================================================

# 单次连接处理：从 STDIN 读取一条 JSON，请求结束以 EOF 表示；将结果写回 STDOUT
handle_connection() {
    # 清空循环变量
    unset tag numfinal initsendstatue senderid receiver comment json_data need_priv groupname group_info groupid mainqqid mainqq_http_port minorqq_http_ports minorqqid port message file_arr goingtosendid
    groupname=""
    initsendstatue=""

    local in_json_data
    in_json_data=$(cat) || true
    log_debug "recv raw=${in_json_data:0:200}..."

    # 解析输入JSON
    local action
    action=$(jq -r '.action // empty' <<<"$in_json_data")

    if [[ "$action" == "flush" ]]; then
        local target_group
        target_group=$(jq -r '.group // empty' <<<"$in_json_data")
        log_debug "action=flush group=$target_group"
        # 确保已加载运行环境与基础配置，避免 sendmsggroup/变量未绑定
        ensure_runtime_env
        load_base_config
        local flush_output
        if flush_output=$(flush_staged_posts "$target_group"); then
            log_debug "flush result=$flush_output"
            [[ -n "$flush_output" ]] || flush_output="success"
            printf '%s\n' "$flush_output"
        else
            log_debug "flush result=failed"
            [[ -n "$flush_output" ]] || flush_output="failed"
            printf '%s\n' "$flush_output"
        fi
        return 0
    fi

    # 解析投稿信息
    tag=$(echo "$in_json_data" | jq -r '.tag // empty')
    # 清理 tag 的不可见字符，避免 WHERE 不命中
    tag=$(printf '%s' "$tag" | tr -d '\r\n\t ')
    numfinal=$(echo "$in_json_data" | jq -r '.numb // empty')
    initsendstatue=$(echo "$in_json_data" | jq -r '.initsendstatue // empty')

    # 基本校验：tag 必须存在
    if [[ -z "$tag" ]]; then
        log_error "收到的投稿JSON缺少tag字段或为空，原始输入: $in_json_data"
        printf '%s\n' "failed"
        return 0
    fi

    # 立即应答 success，避免前台等待长任务（发送/调度）导致超时
    # 随后在后台执行完整的 get_send_info/execute_send_rules 流程
    # 输出换行，避免某些场景下 pty/行缓冲不立刻刷出
    printf '%s\n' "success"
    log_debug "ack success tag=$tag num=$numfinal init=$initsendstatue"

    # 后台处理：自包含调用，确保即使本进程退出也继续执行
    # 注意：bash -lc 会将工作目录切到 $HOME；脚本内部使用了相对路径
    # 因此这里显式切换到仓库根目录（sendcontrol.sh 的上级上级目录）再执行。
    {
      self_path=$(readlink -f "$0" 2>/dev/null || echo "$0")
      self_dir=$(dirname "$self_path")
      repo_root=$(cd "$self_dir/.." 2>/dev/null && pwd || echo ".")
      nohup bash -lc "cd '${repo_root}' && '${self_path}' --run-tag '$tag' '$numfinal' '$initsendstatue'" \
        >/dev/null 2>&1 &
    } >/dev/null 2>&1 || true
    log_debug "spawn --run-tag for tag=$tag"
    return 0
}

# UDS 服务器：将每个连接交给本脚本的 --handle-conn 模式处理
run_uds_server() {
    local uds_path
    uds_path="${SENDCONTROL_UDS_PATH:-./sendcontrol_uds.sock}"
    echo "sendcontrol UDS 监听: $uds_path "
    # 监督循环：socat 异常退出后 1s 内自动重监听并重建 UDS
    while true; do
        [[ -e "$uds_path" ]] && rm -f -- "$uds_path"
        socat -t 60 -T 180 UNIX-LISTEN:"$uds_path",fork,unlink-early \
            EXEC:"./Sendcontrol/sendcontrol.sh --handle-conn",pipes
        rc=$?
        echo "sendcontrol: socat 退出, rc=$rc，1s后自愈重启..."
        sleep 1
    done
}

# =============================================================================
# 启动脚本
# =============================================================================

# 入口：
case "${1:-}" in
  # 兼容历史误引号调用（例如 --handle-conn,pipes 被当作单个参数传入）
  --handle-conn*)
    handle_connection
    ;;
  --run-tag)
    # 后台执行单个 tag 的完整发送/入栈流程
    # 用法：sendcontrol.sh --run-tag <tag> <numfinal> <initsendstatue>
    tag="$2"; numfinal="$3"; initsendstatue="$4"
    log_debug "run-tag start tag=$tag num=$numfinal init=$initsendstatue"
    # 需要 NapCat/工具函数环境
    ensure_runtime_env
    # 需要基础配置（避免未绑定变量）
    load_base_config
    if [[ -z "$tag" ]]; then
      echo "[ERR] --run-tag 缺少 tag 参数" >&2
      exit 1
    fi
    # 调用内部流程；失败也仅记录日志
    if ! get_send_info "$tag"; then
      log_error "--run-tag: get_send_info 失败，tag=$tag"
      exit 1
    else
      log_debug "run-tag done tag=$tag"
      exit 0
    fi
    ;;
  *)
    initialize
    run_uds_server
    ;;
esac
