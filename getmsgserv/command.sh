#!/bin/bash
source ./Global_toolkit.sh

log_and_continue() {
    local errmsg="$1"
    mkdir -p ./cache
    echo "command $(date '+%Y-%m-%d %H:%M:%S') $errmsg" >> ./cache/Command_CrashReport.txt
    echo "command 错误已记录: $errmsg"
    sendmsggroup "$errmsg"
}

# 网页来源加前缀
sendmsggroup_ctx() {
    if [[ "$WEB_REVIEW" == "1" ]]; then
        sendmsggroup "[网页审核] $*"
    else
        sendmsggroup "$*"
    fi
}

# 递归杀死匹配进程及其所有子进程（用于系统修复）
kill_tree_by_pattern() {
  local pattern=$1
  local pids
  mapfile -t pids < <(pgrep -f -- "$pattern" || true)
  [[ ${#pids[@]} -eq 0 ]] && return 0
    echo "Killing processes matching pattern: $pattern"
  _kill_descendants() {
    local p=$1
    local children
    mapfile -t children < <(pgrep -P "$p" || true)
    echo "Killing PID $p with children: ${children[*]}"
    if (( ${#children[@]} > 0 )); then
      for c in "${children[@]}"; do
        _kill_descendants "$c"
      done
    fi
    kill -TERM "$p" 2>/dev/null || true
  }

  for pid in "${pids[@]}"; do
    _kill_descendants "$pid"
  done

  local deadline=$(( $(date +%s) + 3 ))
  while IFS= read -r p; do
    while kill -0 "$p" 2>/dev/null; do
      if (( $(date +%s) >= deadline )); then
        echo "Force killing PID $p"
        kill -KILL "$p" 2>/dev/null || true
        break
      fi
      sleep 0.1
    done
  done < <(printf '%s\n' "${pids[@]}")
}

file_to_watch="./getmsgserv/all/priv_post.jsonl"
legacy_priv="./getmsgserv/all/priv_post.json"
if [[ -f "$legacy_priv" && ! -f "$file_to_watch" ]]; then
    file_to_watch="$legacy_priv"
fi
command_file="./qqBot/command/commands.txt"
litegettag=$(grep 'use_lite_tag_generator' oqqwall.config | cut -d'=' -f2 | tr -d '"')
self_id=$2
echo 收到指令:$1
object=$(echo $1 | awk '{print $1}')
command=$(echo $1 | awk '{print $2}')
flag=$(echo $1 | awk '{print $3}')
input_id="$self_id"
#echo obj:$object
#echo cmd:$command
#echo flag:$flag
#echo self_id:$self_id
json_file="./AcountGroupcfg.json"
if [ -z "$input_id" ]; then
  log_and_continue "请提供mainqqid或minorqqid。"
  exit 1
fi
# 使用 jq 查找输入ID所属的组信息
group_info=$(jq -r --arg id "$input_id" '
  to_entries[] | select(.value.mainqqid == $id or (.value.minorqqid[]? == $id))
' "$json_file")
# 检查是否找到了匹配的组
if [ -z "$group_info" ]; then
  log_and_continue "未找到ID为 $input_id 的相关信息。"
  exit 1
fi
groupname=$(echo "$group_info" | jq -r '.key')
groupid=$(echo "$group_info" | jq -r '.value.mangroupid')
mainqqid=$(echo "$group_info" | jq -r '.value.mainqqid')
mainqq_http_port=$(echo "$group_info" | jq -r '.value.mainqq_http_port')

# 网页审核：发送一条摘要并抑制其它群提示
if [[ "$WEB_REVIEW" == "1" ]]; then
  user_display=${WEB_REVIEW_USER:-网页用户}
  summary_msg="$user_display使用网页审核执行了$object"
  encoded_msg=$(perl -MURI::Escape -e 'print uri_escape($ARGV[0]);' "$summary_msg")
  curl -s -o /dev/null -H "$NAPCAT_AUTH_HEADER" "http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg"
  # 覆盖群发函数，抑制后续消息
  sendmsggroup() { :; }
  sendmsggroup_ctx() { :; }
fi

case $object in
    [0-9]*)
        if [[ "$self_id" == "$mainqqid" ]]; then
            #判断可执行
             if [ -d "./cache/prepost/$object" ]; then
            #判断权限
                groupnameoftag=$(sqlite3 'cache/OQQWall.db' "SELECT ACgroup FROM preprocess WHERE tag = '$object';")
                if [[ "$groupnameoftag" == "$groupname" ]];then
                    ./getmsgserv/processsend.sh "$object $command $flag"
                else
                    sendmsggroup_ctx '权限错误，无法对非本账号组的帖子进行操作，发送 @本账号 帮助 以查看帮助'
                fi
            else
                echo "error: $object 不存在对应的文件夹"
                sendmsggroup_ctx '没有可执行的对象,请检查,发送 @本账号 帮助 以查看帮助'
            fi
        else
            sendmsggroup_ctx 请尝试@主账号执行此指令
        fi
        ;;
    "手动重新登录")
        renewqzonelogin $self_id
        ;;
    "自动重新登录")
        renewqzoneloginauto $self_id
        sendmsggroup_ctx 自动登录QQ空间尝试完毕
        ;;
    "设定编号")
        if [[ $command =~ ^[0-9]+$ ]]; then
            echo $command > ./cache/numb/"$groupname"_numfinal.txt
            sendmsggroup_ctx 外部编号已设定为$command
        else
            echo "Error: arg is not a pure number."
            sendmsggroup_ctx "编号必须为纯数字，发送 @本账号 帮助 以获取帮助"
        fi
        ;;
     "调出")
        #判断权限
        groupnameoftag=$(sqlite3 'cache/OQQWall.db' "SELECT ACgroup FROM preprocess WHERE tag = '$command';")
        echo groupnamefromtag=$groupnameoftag,groupname=$groupname
        if [[ "$groupnameoftag" == "$groupname" ]];then
            max_tag=$(sqlite3 "cache/OQQWall.db" "SELECT MAX(tag) FROM preprocess;")
            if [[ $command =~ ^[0-9]+$ ]]; then
                echo max:$max_tag
                if [[ $command -le $max_tag ]];then
                    ./getmsgserv/preprocess.sh "$command" randeronly
                else
                    sendmsggroup_ctx "当前编号不在数据库中"
                fi
            else
                echo "Error: arg is not a pure number."
                sendmsggroup_ctx "编号必须为纯数字，发送 @本账号 帮助 以获取帮助"
            fi
        else
            sendmsggroup_ctx '权限错误，无法对非本账号组的帖子进行操作，发送 @本账号 帮助 以查看帮助'
            exit 1
        fi
        ;;
    "信息")
        groupnameoftag=$(sqlite3 'cache/OQQWall.db' "SELECT ACgroup FROM preprocess WHERE tag = '$command';")
        echo groupnamefromtag=$groupnameoftag,groupname=$groupname
        if [[ "$groupnameoftag" == "$groupname" ]];then
            max_tag=$(sqlite3 "cache/OQQWall.db" "SELECT MAX(tag) FROM preprocess;")
            if [[ $command =~ ^[0-9]+$ ]]; then
                echo max:$max_tag
                if [[ $command -le $max_tag ]];then
                    receiver=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT receiver FROM preprocess WHERE tag = '$command';")
                    senderid=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT senderid FROM preprocess WHERE tag = $command;")
                    json_data=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$command';")
                    need_priv=$(echo $json_data|jq -r '.needpriv')
                    groupname=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT ACgroup FROM preprocess WHERE tag = '$command';")
                    orin_json=$(sqlite3 "cache/OQQWall.db" "SELECT rawmsg FROM sender WHERE senderid='$senderid';")
                    if [[ $? -ne 0 || -z "$orin_json" ]]; then
                        orin_json="不存在"
                    fi
                    sendmsggroup "接收者：$receiver
发送者：$senderid
所属组：$groupname
处理后 json 消息：$json_data
此人当前 json 消消息：$orin_json"
                else
                    sendmsggroup "当前编号不在数据库中"
                fi
            else
                echo "Error: arg is not a pure number."
                sendmsggroup "编号必须为纯数字，发送 @本账号 帮助 以获取帮助"
            fi
        else
            sendmsggroup '权限错误，无法对非本账号组的帖子进行操作，发送 @本账号 帮助 以查看帮助'
            exit 1
        fi
        ;;
    "待处理")
        numbpending=$(find ./cache/prepost -mindepth 1 -maxdepth 1 -type d -exec basename {} \;)
        if [ -z $numbpending ]; then
            sendmsggroup 没有待处理项目
        else
            group_pending=""
            for tag in $numbpending; do
                group=$(sqlite3 ./cache/OQQWall.db "SELECT ACgroup FROM preprocess WHERE tag = '$tag';")
                if [[ "$group" == "$groupname" ]]; then
                    group_pending="$group_pending$tag"$'\n'
                fi
            done
            if [[ -z "$group_pending" ]]; then
                sendmsggroup_ctx "本组没有待处理项目"
            else
                sendmsggroup_ctx "本组待处理项目:
$group_pending"
            fi
        fi
        ;;
    "删除待处理")
        # 获取所有 sendstorge_* 表中的 tag
        tags_to_keep=()
        for tbl in $(sqlite3 ./cache/OQQWall.db ".tables" | tr ' ' '\n' | grep '^sendstorge_'); do
            tags=$(sqlite3 ./cache/OQQWall.db "SELECT tag FROM $tbl;")
            for tag in $tags; do
                tags_to_keep+=("$tag")
            done
        done

        # 构建要保留的 tag 列表
        keep_pattern=""
        if [ ${#tags_to_keep[@]} -gt 0 ]; then
            for tag in "${tags_to_keep[@]}"; do
                keep_pattern+=" -name $tag -o"
            done
            # 去掉最后一个 -o
            keep_pattern=${keep_pattern::-3}
            # 删除不在 tags_to_keep 中的目录
            find ./cache/prepost -mindepth 1 -maxdepth 1 -type d ! \( $keep_pattern \) -exec rm -rf {} +
        else
            # 没有要保留的，全部删除
            rm -rf ./cache/prepost/*
        fi
        # 查找正在运行的 preprocess.sh 的 tag
        running_tags=()
        while read -r pid cmdline; do
            # Extract everything after the last '/' and then get the last argument
            tag=$(echo "$cmdline" | sed 's/.*preprocess.sh //')
            if [[ "$tag" =~ ^[0-9]+$ ]]; then
            echo "Found running preprocess.sh with tag: $tag"
            running_tags+=("$tag")
            fi
        done < <(pgrep -af "./getmsgserv/preprocess.sh")

        # 查找这些 tag 的 senderid
        running_senderids=()
        for tag in "${running_tags[@]}"; do
            senderid=$(sqlite3 ./cache/OQQWall.db "SELECT senderid FROM preprocess WHERE tag = '$tag';")
            if [[ -n "$senderid" ]]; then
            running_senderids+=("$senderid")
            fi
        done

        # 构建 NOT IN 子句
        not_in_clause=""
        if [ ${#running_senderids[@]} -gt 0 ]; then
            ids=$(printf "'%s'," "${running_senderids[@]}")
            ids=${ids%,}
            not_in_clause="WHERE senderid NOT IN ($ids)"
        fi

        # 删除 sender 表中未被占用的 senderid
        sqlite3 ./cache/OQQWall.db "DELETE FROM sender $not_in_clause;"
        sendmsggroup_ctx 已清空待处理列表
        ;;
    "删除暂存区")
        #获取sendstorge中最小的tag
        min_num=$(sqlite3 ./cache/OQQWall.db "SELECT MIN(num) FROM sendstorge_$groupname;")
        if [[ -z "$min_num" || "$min_num" == "NULL" ]]; then
            sendmsggroup_ctx "暂存区没有数据"
        else
            #获取全部tag
            all_tags=$(sqlite3 ./cache/OQQWall.db "SELECT tag FROM sendstorge_$groupname;")
            #删除所有。/prepost/tag
            while IFS= read -r tag; do
                if [ ! -z "$tag" ]; then
                    echo "tag=$tag"
                    rm -rf "./cache/prepost/$tag"
                fi
            done <<< "$all_tags"
            # 删除 sendstorge 中的所有数据
            sqlite3 ./cache/OQQWall.db "DELETE FROM sendstorge_$groupname;"
            #回滚numfinal为min_tag
            echo $min_num > ./cache/numb/"$groupname"_numfinal.txt
            sendmsggroup_ctx "已清空暂存区数据，当前外部编号为#$min_num"
        fi
        ;;
    "发送暂存区")
        sc_sock="${SENDCONTROL_UDS_PATH:-./sendcontrol_uds.sock}"
        post_statue=$(jq -nc --arg group "$groupname" '{action:"flush", group:$group}' \
            | socat -t 60 -T 60 - UNIX-CONNECT:"$sc_sock" 2>/dev/null)
        echo 已收到回报

        if echo "$post_statue"  | grep -q "success"; then
            goingtosendid=("${goingtosendid[@]/$1}")

        elif echo "$post_statue"  | grep -q "failed"; then
            log_and_continue "空间发送调度服务发生错误"
            exit 0
        else
            log_and_continue "空间发送调度服务发生错误"
            exit 0
        fi
        ;;
    "自检")
        # 1. 先通过 printf -v 初始化 syschecklist，并确保每条后面都有真实换行符
        printf -v syschecklist '== 系统自检报告 ==\n'

        # 2. CPU 使用率
        cpu_idle=$(top -bn1 | awk '/Cpu\(s\):/ {print $8}')
        cpu_usage=$(bc <<< "scale=1; 100 - $cpu_idle")
        printf -v syschecklist '%sCPU使用率: %s%%\n' "$syschecklist" "$cpu_usage"

        # 3. 内存使用情况
        #    free -h 输出第二行：total used free ...
        read total_mem used_mem _ <<< "$(free -h | awk 'NR==2 {print $2, $3}')"
        printf -v syschecklist '%s内存使用情况: 已用: %s / 总计: %s\n' \
            "$syschecklist" "$used_mem" "$total_mem"

        # 4. 硬盘使用情况
        disk_info=$(df -h --total | awk '/^total/ {print "已用: "$3" / 总计: "$2" ("$5" 已用)"}')
        printf -v syschecklist '%s硬盘使用情况: %s\n' "$syschecklist" "$disk_info"

        # 5. 检测各个服务是否在运行
        if pgrep -f "python3 getmsgserv/serv.py" > /dev/null; then
            printf -v syschecklist '%sqq消息接收服务已在运行\n' "$syschecklist"
        else
            printf -v syschecklist '%sqq消息接收服务不在运行，正在尝试重启\n' "$syschecklist"
            pgrep -f "python3 getmsgserv/serv.py" | xargs kill -15
            python3 ./getmsgserv/serv.py &
            echo "serv.py started"
        fi

        if pgrep -f "./Sendcontrol/sendcontrol.sh" > /dev/null; then
            printf -v syschecklist '%s发送调度服务已在运行\n' "$syschecklist"
        else
            printf -v syschecklist '%s发送调度服务服务不在运行，正在尝试重启\n' "$syschecklist"
            pgrep -f "/bin/bash ./Sendcontrol/sendcontrol.sh" | xargs kill -15
            ./Sendcontrol/sendcontrol.sh &
            echo "sendcontrol.sh started"
        fi

        # 改为检查 UDS（qzone-serv-UDS.py）而非 pipe
        qz_sock="${QZONE_UDS_PATH:-./qzone_uds.sock}"
        if [[ -S "$qz_sock" ]]; then
            if command -v socat >/dev/null 2>&1; then
                qz_payload='{"text":"UDS health-check","image":[],"cookies":{}}'
                qz_out=$(printf '%s' "$qz_payload" | socat -t 5 -T 5 - UNIX-CONNECT:"$qz_sock" 2>/dev/null) || qz_out=""
                if [[ -n "$qz_out" ]]; then
                    printf -v syschecklist '%s空间发送服务正常\n' "$syschecklist"
                else
                    printf -v syschecklist '%s空间发送服务不可用 (无响应)，正在尝试重启\n' "$syschecklist"
                    pgrep -f "python3 SendQzone/qzone-serv-UDS.py" | xargs kill -15 2>/dev/null
                    python3 ./SendQzone/qzone-serv-UDS.py &
                    echo "qzone-serv-UDS.py started"
                fi
            else
                printf -v syschecklist '%s空间发送服务已监听 (未安装 socat，跳过连通性探测)\n' "$syschecklist"
            fi
        else
            printf -v syschecklist '%s空间发送服务未监听 (socket 不存在)，正在尝试重启\n' "$syschecklist"
            pgrep -f "python3 SendQzone/qzone-serv-UDS.py" | xargs kill -15 2>/dev/null
            python3 ./SendQzone/qzone-serv-UDS.py &
            echo "qzone-serv-UDS.py started"
        fi

        # 6. 添加结尾
        printf -v syschecklist '%s==== 自检完成 ====' "$syschecklist"

        # 7. 调用已存在的发送函数，注意这里不修改 sendmsggroup 的定义
        sendmsggroup_ctx "$syschecklist"
        ;;
    "系统修复")
        # 强制重启 serv.py 以外的全部服务（含其子进程），并删除重建 UDS
        sendmsggroup_ctx "正在执行系统修复（重启除serv.py外服务，重建UDS）..."

        # 停服务：qzone-serv-UDS / sendcontrol 及其子进程；顺带清理 socat fork
        kill_tree_by_pattern "SendQzone/qzone-serv-UDS.py"
        kill_tree_by_pattern "./Sendcontrol/sendcontrol.sh"
        #kill_tree_by_pattern "socat .*sendcontrol_uds.sock"
        # 可选：网页审核
        kill_tree_by_pattern "web_review.py"

        # 清理 UDS 套接字
        qz_sock="${QZONE_UDS_PATH:-./qzone_uds.sock}"
        sc_sock="${SENDCONTROL_UDS_PATH:-./sendcontrol_uds.sock}"
        [[ -S "$qz_sock" ]] && rm -f -- "$qz_sock"
        [[ -S "$sc_sock" ]] && rm -f -- "$sc_sock"

        # 重启（serv.py 保持不动）
        if ! pgrep -f "python3 getmsgserv/serv.py" >/dev/null 2>&1; then
          python3 ./getmsgserv/serv.py &
          echo "serv.py started"
        fi
        ./Sendcontrol/sendcontrol.sh &
        sleep 2
        python3 ./SendQzone/qzone-serv-UDS.py &

        # 可选：网页审核（如有启用）
        if [[ "${use_web_review:-false}" == "true" ]]; then
          if ! pgrep -f "python3 web_review.py" >/dev/null 2>&1; then
            (cd web_review && PORT="${web_review_port:-8088}" HOST="0.0.0.0" nohup python3 web_review.py --host 0.0.0.0 --port "${web_review_port:-8088}" > web_review.log 2>&1 &)
          fi
        fi

        sendmsggroup_ctx "系统修复完成（UDS 已重建，服务已重启）"
        ;;
    "取消拉黑")
        if [[ -z "$command" ]]; then
            sendmsggroup_ctx "请提供要取消拉黑的 senderid"
            exit 1
        fi
        sqlite3 'cache/OQQWall.db' "DELETE FROM blocklist WHERE senderid = '$command' AND ACgroup = '$groupname';"
        sqlite3 'cache/OQQWall.db' "DELETE FROM sender WHERE senderid = '$command' AND ACgroup = '$groupname';"
        sendmsggroup_ctx "已取消拉黑 senderid: $command"
        ;;
    "列出拉黑")
        blocklist=$(sqlite3 'cache/OQQWall.db' "SELECT senderid, reason FROM blocklist WHERE ACgroup = '$groupname';")
        if [[ -z "$blocklist" ]]; then
            sendmsggroup_ctx "当前账户组没有被拉黑的账号"
        else
            msg="被拉黑账号列表："
            while IFS='|' read -r senderid reason; do
                msg+="
账号: $senderid，理由: $reason"
            done <<< "$blocklist"
            sendmsggroup_ctx "$msg"
        fi
        ;;
    "快捷回复")
        # 检查是否有子命令
        if [[ -n "$command" ]]; then
            case "$command" in
                "添加")
                    # 格式：快捷回复 添加 指令名=内容
                    if [[ -n "$flag" ]]; then
                        # 解析指令名和内容
                        if [[ "$flag" == *"="* ]]; then
                            cmd_name=$(echo "$flag" | cut -d'=' -f1)
                            cmd_content=$(echo "$flag" | cut -d'=' -f2-)
                            
                            # 检查指令名是否为空
                            if [[ -z "$cmd_name" ]]; then
                                sendmsggroup "错误：指令名不能为空"
                                exit 1
                            fi
                            
                            # 检查内容是否为空
                            if [[ -z "$cmd_content" ]]; then
                                sendmsggroup "错误：快捷回复内容不能为空"
                                exit 1
                            fi
                            
                            # 检查是否与审核指令冲突
                            audit_commands=("是" "否" "匿" "等" "删" "拒" "立即" "刷新" "重渲染" "扩列审查" "扩列" "查" "查成分" "评论" "回复" "展示" "拉黑")
                            for audit_cmd in "${audit_commands[@]}"; do
                                if [[ "$cmd_name" == "$audit_cmd" ]]; then
                                    sendmsggroup "错误：快捷回复指令 '$cmd_name' 与审核指令冲突，请使用其他指令名"
                                    exit 1
                                fi
                            done
                            
                            # 使用jq更新配置文件
                            temp_file=$(mktemp)
                            jq --arg group "$groupname" --arg cmd "$cmd_name" --arg content "$cmd_content" \
                               '.[$group].quick_replies[$cmd] = $content' "$json_file" > "$temp_file"
                            
                            if [[ $? -eq 0 ]]; then
                                mv "$temp_file" "$json_file"
                                sendmsggroup "已添加快捷回复指令：$cmd_name"
                            else
                                rm -f "$temp_file"
                                sendmsggroup "添加快捷回复失败，请检查配置文件格式"
                            fi
                        else
                            sendmsggroup "错误：格式不正确，请使用 '指令名=内容' 的格式"
                        fi
                    else
                        sendmsggroup "错误：请提供快捷回复指令名和内容，格式：快捷回复 添加 指令名=内容"
                    fi
                    ;;
                "删除")
                    # 格式：快捷回复 删除 指令名
                    if [[ -n "$flag" ]]; then
                        # 检查指令是否存在
                        existing_content=$(jq -r --arg group "$groupname" --arg cmd "$flag" '.[$group].quick_replies[$cmd] // empty' "$json_file")
                        if [[ -z "$existing_content" || "$existing_content" == "null" ]]; then
                            sendmsggroup "错误：快捷回复指令 '$flag' 不存在"
                            exit 1
                        fi
                        
                        # 使用jq删除配置
                        temp_file=$(mktemp)
                        jq --arg group "$groupname" --arg cmd "$flag" \
                           '.[$group].quick_replies = (.[$group].quick_replies | del(.[$cmd]))' "$json_file" > "$temp_file"
                        
                        if [[ $? -eq 0 ]]; then
                            mv "$temp_file" "$json_file"
                            sendmsggroup "已删除快捷回复指令：$flag"
                        else
                            rm -f "$temp_file"
                            sendmsggroup "删除快捷回复失败，请检查配置文件格式"
                        fi
                    else
                        sendmsggroup "错误：请提供要删除的快捷回复指令名"
                    fi
                    ;;
                *)
                    sendmsggroup "错误：未知的子命令 '$command'，支持的子命令：添加、删除"
                    ;;
            esac
        else
            # 显示快捷回复列表
            quick_replies=$(jq -r --arg group "$groupname" '.[$group].quick_replies // empty' "$json_file")
            if [[ -z "$quick_replies" || "$quick_replies" == "null" ]]; then
                sendmsggroup "当前账户组未配置快捷回复"
            else
                msg="当前账户组快捷回复列表：
"
                # 使用jq遍历快捷回复配置
                while IFS='|' read -r key value; do
                    if [[ -n "$key" && -n "$value" ]]; then
                        msg+="
指令: $key
内容: $value
"
                    fi
                done < <(echo "$quick_replies" | jq -r 'to_entries[] | .key + "|" + .value')
                sendmsggroup "$msg"
            fi
        fi
        ;;
    "帮助")
        help='全局指令:
这些是可以在任何时刻@本账号调用的指令
语法: @本账号/次要账号 指令

调出：
用于调出曾经接收到过的投稿
用法：调出 xxx（xxx为内部编号）

手动重新登录:
扫码登陆QQ空间

自动重新登录:
尝试自动登录qq空间
(请注意是登录不是登陆)

待处理：
检查当前等待处理的投稿

删除待处理：
清空待处理列表，相当于对列表中的所有项目执行"删"审核指令

删除暂存区：
清空暂存区的内容，相当于对所有暂存区中的内容执行"删"审核指令，外部编号会一并回滚

发送暂存区：
将暂存区中的内容发送到QQ空间

列出拉黑：
列出当前被拉黑的全部内容

取消拉黑：
取消对某个账号的拉黑
用法：取消拉黑 xxx（xxx为被拉黑的qq号）

设定编号
用法：设定编号 xxx （xxx是你希望下一条说说带有的外部编号，必须是纯数字）

快捷回复：
查看当前账户组配置的快捷回复列表
快捷回复 添加 指令名=内容：
添加快捷回复指令
快捷回复 删除 指令名：
删除指定的快捷回复指令

帮助:
查看这个帮助列表

自检：
系统与服务自检

系统修复：
强制重启serv.py以外的全部服务，删除并重建UDS



审核指令:
这些指令仅在稿件审核流程中要求您发送指令时可用
语法: @本账号 内部编号 指令
或 回复审核消息 指令

是：
发送,系统会给稿件发送者发送成功提示

否：
机器跳过此条，人工去处理（常用于机器分段错误或者匿名判断失败，或是内容有视频的情况）

匿:
切换匿名状态,用于在机器判断失误时使用，处理完毕后会再次询问指令

等：
等待180秒，然后重新执行分段-渲染-审核流程，常用于稿件没发完的情况，等待完毕后会再次询问指令

删：
此条不发送（不用机器发，也不会用人工发送）（常用于用户发来的不是稿件的情况，这条指令会把外部编号+1)

拒：
拒绝稿件,此条不发送（用于不过审的情况），系统会给发送者发送稿件被拒绝提示

立即：
系统会立刻发送暂存区的所有投稿，并立即把当前投稿单发。

刷新：
重新进行 聊天记录->图片 的过程

重渲染：
重新进行 聊天记录->图片 的过程，但是不重新进行AI分段步骤（通常仅用于调试渲染管道）

消息全选：
将本次投稿的所有用户消息全部作为投稿内容（用于分段判断错误时的强制全选），并重新渲染；处理完毕后会再次询问指令

扩列审查：
扩列审核流程，系统会自动获取对方QQ等级，空间开放状态和qq名片，并尝试寻找和扫描二维码，然后将相关信息发送到群中

评论：
在编号和@发送者的下一行增加文本评论，处理完毕后会再次询问指令
用法：@本帐号 内部编号 评论 xxx （xxx是你希望增加的评论）

回复：
向投稿人发送一条信息
用法：@本帐号 内部编号 回复 xxx （xxx是你希望回复的内容）

展示：
展示稿件的内容

拉黑：
不再接收来自此人的投稿
用法： @本帐号 内部编号 拉黑 理由 （理由是可选的，若不提供则会记录无理由拉黑）

快捷回复指令：
使用预设的快捷回复模板向投稿人发送消息
用法：@本帐号 内部编号 快捷指令名'
        sendmsggroup_ctx "$help"
        ;;
    *)
        echo "error: 无效的指令"
        sendmsggroup_ctx '指令无效,请检查,发送 @本账号 帮助 以查看帮助'
        ;;
esac
