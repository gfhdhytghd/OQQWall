#!/bin/bash
groupid=$(grep 'management-group-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
file_to_watch="./getmsgserv/all/priv_post.json"
command_file="./qqBot/command/commands.txt"
litegettag=$(grep 'use_lite_tag_generator' oqqwall.config | cut -d'=' -f2 | tr -d '"')
sendmsggroup(){
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:8083/send_group_msg?group_id=$groupid&message=$encoded_msg\""
    echo $cmd
    eval $cmd
}
renewqzonelogin(){
    rm ./cookies.json
    rm ./qrcode.png
    postqzone &
    python3 SendQzone/send.py relogin &
    sleep 2
    sendmsggroup 请立即扫描二维码
    sendmsggroup "[CQ:image,file=$(pwd)/qrcode.png]"
}
renewqzoneloginauto(){
    rm ./cookies.json
    rm ./qrcode.png
    python3 ./SendQzone/qzonerenewcookies.py
}
echo 收到指令:$1
object=$(echo $1 | awk '{print $1}')
command=$(echo $1 | awk '{print $2}')
flag=$(echo $1 | awk '{print $3}')
echo obj:$object
echo cmd:$command
echo flag:$flag

case $object in
    [0-9]*)
        if [ -d "./getmsgserv/post-step5/$object" ]; then
            echo $1 >> qqBot/command/commands.txt
            echo "指令已保存到 qqBot/command/commands.txt"
        else
            echo "error: $object 不存在对应的文件夹"
            sendmsggroup 没有可执行的对象,请检查
        fi
        ;;
    "手动重新登陆")
        renewqzonelogin
        ;;
    "自动重新登陆")
        renewqzoneloginauto
        sendmsggroup 尝试完毕
        ;;
    "帮助")
        help='全局指令:
(可以在任何时刻@本账号调用的指令)
手动重新登陆:扫码登陆QQ空间
自动重新登录:尝试自动登录qq空间
帮助:查看这个帮助列表
审核指令:
(仅在稿件审核流程要求您发送指令时可用的指令)
是：发送,系统会给稿件发送者发送成功提示
否：机器跳过此条，人工去处理（常用于机器分段错误或者匿名判断失败，或是内容有视频的情况）
匿:切换匿名状态,用于在机器判断失误时使用
等：等待180秒，然后重新执行分段-渲染-审核流程，常用于稿件没发完的情况
删：此条不发送（不用机器发，也不会用人工发送）（常用于用户发来的不是稿件的情况）
拒：拒绝稿件,此条不发送（用于不过审的情况），系统会给发送者发送稿件被拒绝提示'
        sendmsggroup "$help"
        ;;
    *)
        echo "error: 无效的指令"
        sendmsggroup 指令无效,请检查
        ;;
esac