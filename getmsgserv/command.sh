#!/bin/bash
file_to_watch="./getmsgserv/all/priv_post.json"
command_file="./qqBot/command/commands.txt"
litegettag=$(grep 'use_lite_tag_generator' oqqwall.config | cut -d'=' -f2 | tr -d '"')
self_id=$2
sendmsggroup() {
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    curl -s -o /dev/null "http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg"
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
        encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
        # 构建 curl 命令，并发送编码后的消息
        cmd="curl \"http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg\""
        eval $cmd
        sleep 1  # 添加延时以避免过于频繁的请求
    done
    echo "所有文件已发送"
}
renewqzoneloginauto(){
    rm ./cookies-$self_id.json
    rm ./qrcode.png
    if [[ "$use_selenium_to_generate_qzone_cookies" == "true" ]]; then
        python3 ./SendQzone/qzonerenewcookies-selenium.py $1
    else
        python3 ./SendQzone/qzonerenewcookies.py $1
    fi
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
  echo "请提供mainqqid或minorqqid。"
  exit 1
fi
# 使用 jq 查找输入ID所属的组信息
group_info=$(jq -r --arg id "$input_id" '
  to_entries[] | select(.value.mainqqid == $id or (.value.minorqqid[]? == $id))
' "$json_file")
# 检查是否找到了匹配的组
if [ -z "$group_info" ]; then
  echo "未找到ID为 $input_id 的相关信息。"
  exit 1
fi
groupname=$(echo "$group_info" | jq -r '.key')
groupid=$(echo "$group_info" | jq -r '.value.mangroupid')
mainqqid=$(echo "$group_info" | jq -r '.value.mainqqid')
mainqq_http_port=$(echo "$group_info" | jq -r '.value.mainqq_http_port')

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
                    sendmsggroup '权限错误，无法对非本账号组的帖子进行操作，发送 @本账号 帮助 以查看帮助'
                fi
            else
                echo "error: $object 不存在对应的文件夹"
                sendmsggroup '没有可执行的对象,请检查,发送 @本账号 帮助 以查看帮助'
            fi
        else
            sendmsggroup 请尝试@主账号执行此指令
        fi
        ;;
    "手动重新登录")
        renewqzonelogin $self_id
        ;;
    "自动重新登录")
        renewqzoneloginauto $self_id
        sendmsggroup 自动登录QQ空间尝试完毕
        ;;
    "设定编号")
        if [[ $command =~ ^[0-9]+$ ]]; then
            echo $command > ./cache/numb/"$groupname"_numfinal.txt
            sendmsggroup 外部编号已设定为$command
        else
            echo "Error: arg is not a pure number."
            sendmsggroup "编号必须为纯数字，发送 @本账号 帮助 以获取帮助"
        fi
        ;;
    "待处理")
        numbpending=$(find ./cache/prepost -mindepth 1 -maxdepth 1 -type d -exec basename {} \;)
        if [ -z $numbpending ]; then
            sendmsggroup 没有待处理项目
        else
            sendmsggroup "待处理项目:
$numbpending"
        fi
        ;;
    "删除待处理")
        rm -rf ./cache/prepost/*
        sendmsggroup 已清空待处理列表
        ;;
    "帮助")
        help='全局指令:
语法: @本账号/次要账号 指令
(可以在任何时刻@本账号调用的指令)
手动重新登录:扫码登陆QQ空间
自动重新登录:尝试自动登录qq空间
(请注意是登录不是登陆)
待处理：检查当前等待处理的投稿
删除待处理：
清空待处理列表，相当于对列表中的所有项目执行"删"审核指令
设定编号
用法：设定编号 xxx （xxx是你希望下一条说说带有的外部编号，必须是纯数字）
帮助:查看这个帮助列表

审核指令:
语法: @本账号 内部编号 指令
(仅在稿件审核流程要求您发送指令时可用的指令)
是：发送,系统会给稿件发送者发送成功提示
否：机器跳过此条，人工去处理（常用于机器分段错误或者匿名判断失败，或是内容有视频的情况）
匿:切换匿名状态,用于在机器判断失误时使用，处理完毕后会再次询问指令
等：等待180秒，然后重新执行分段-渲染-审核流程，常用于稿件没发完的情况，等待完毕后会再次询问指令
删：此条不发送（不用机器发，也不会用人工发送）（常用于用户发来的不是稿件的情况）
拒：拒绝稿件,此条不发送（用于不过审的情况），系统会给发送者发送稿件被拒绝提示
刷新：重新进行 聊天记录->图片 的过程
评论：在编号和@发送者的下一行增加文本评论，处理完毕后会再次询问指令
用法：@本帐号 内部编号 评论 xxx （xxx是你希望增加的评论）
回复：向投稿人发送一条信息
用法：@本帐号 内部编号 回复 xxx （xxx是你希望回复的内容）
展示：展示稿件的内容
拉黑：不再接收来自此人的投稿'
        sendmsggroup "$help"
        ;;
    *)
        echo "error: 无效的指令"
        sendmsggroup '指令无效,请检查,发送 @本账号 帮助 以查看帮助'
        ;;
esac