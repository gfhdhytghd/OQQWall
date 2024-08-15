#!/bin/bash

groupid=$(grep 'management-group-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
litegettag=$(grep 'use_lite_tag_generator' oqqwall.config | cut -d'=' -f2 | tr -d '"')
apikey=$(grep 'apikey' oqqwall.config | cut -d'=' -f2 | tr -d '"')
DIR="./getmsgserv/rawpost/"

check_variable() {
    var_name=$1
    var_value=$2

    if [ -z "$var_value" ] || [ "$var_value" == "xxx" ]; then
        echo "变量 $var_name 未正确设置。请参考OQQWall文档设定初始变量。"
        exit 1
    fi
}

# 检查关键变量是否设置
check_variable "groupid" "$groupid"
check_variable "litegettag" "$litegettag"
check_variable "apikey"  "$apikey"

# 初始化目录和文件
mkdir ./getmsgserv/rawpost
mkdir ./getmsgserv/post-step2
mkdir ./getmsgserv/post-step3
mkdir ./getmsgserv/post-step4
mkdir ./getmsgserv/post-step5
mkdir ./qqBot/command
touch ./qqBot/command/commands.txt
touch ./numfinal.txt
pkill startd.sh

# Activate virtual environment
source ./venv/bin/activate

# start startd
./qqBot/startd.sh &
echo 等待启动十秒
sleep 10


waitforfilechange(){
        last_mod_time_cmd=$(stat -c %Y "$1")

    while true; do
        sleep 5
        # 获取文件的当前修改时间
        current_mod_time_cmd=$(stat -c %Y "$1")

        # 检查文件是否已被修改
        if [ "$current_mod_time_cmd" -ne "$last_mod_time_cmd" ]; then
            echo 检测到指令
            break
        fi
    done
}

getnumnext(){
    numnow=$(cat ./numb.txt)
    numnext=$((numnow + 1))
    echo "$numnext" > ./numb.txt
    echo "numnext=$numnext"
}

sendmsggroup(){
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:8083/send_group_msg?group_id=$groupid&message=$encoded_msg\""
    echo $cmd
    eval $cmd
}
waitforprivmsg(){
    # 获取初始文件列表
    initial_files=$(ls "$DIR")
    while true; do
        # 获取当前文件列表
        current_files=$(ls "$DIR")
        # 比较文件列表
        if [ "$initial_files" != "$current_files" ]; then
            # 检查是否有新增文件
            for file in $current_files; do
                if ! echo "$initial_files" | grep -q "$file"; then
                    echo "有新的私聊消息: $file"
                    return 0
                fi
            done
        fi
        # 更新初始文件列表
        initial_files=$current_files
        sleep 1
    done
}


sendmsggroup 机器人已启动

echo 获取priv_post文件更改时间
last_mod_time=$(stat -c %Y "$file_to_watch")
echo $last_mod_time

id=$(find ./getmsgserv/rawpost -type f -printf '%T+ %p\n' | sort | head -n 1 | awk '{print $2}')
id=$(basename "$id" .json)
id=$(echo "$id" | sed 's/.*\///')

# 监测目录
DIR="./getmsgserv/rawpost/"

# 获取初始文件列表
initial_files=$(ls "$DIR")
echo 启动系统主循环
while true; do
    echo 启动系统等待循环
    waitforprivmsg
    getnumnext
    ./SendQzone/processsend.sh $id $numnext &
    last_mod_time=$(stat -c %Y "$file_to_watch")
done
