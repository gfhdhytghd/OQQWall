#!/bin/bash
qqid=$(grep 'mainqq-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
groupid=$(grep 'management-group-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
apikey=$(grep 'apikey' oqqwall.config | cut -d'=' -f2 | tr -d '"')
enable_selenium_autocorrecttag_onstartup=$(grep 'enable_selenium_autocorrecttag_onstartup' oqqwall.config | cut -d'=' -f2 | tr -d '"')
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
check_variable "management-group-id" "$groupid"
check_variable "apikey" "$apikey"
check_variable "mainqq-id" "$qqid"
# 初始化目录和文件
mkdir ./getmsgserv/rawpost
mkdir ./getmsgserv/post-step2
mkdir ./getmsgserv/post-step3
mkdir ./getmsgserv/post-step4
mkdir ./getmsgserv/post-step5
mkdir ./qqBot/command
if [ ! -f "./qqBot/command/commands.txt" ]; then
    touch ./qqBot/command/commands.txt
    echo "已创建文件: ./qqBot/command/commands.txt"
fi

# 检测并创建 ./getmsgserv/all/commugroup.txt 文件
if [ ! -f "./getmsgserv/all/commugroup.txt" ]; then
    touch ./getmsgserv/all/commugroup.txt
    echo "已创建文件: ./getmsgserv/all/commugroup.txt"
fi

#写入whitelist
group_id="group_${commgroup_id}"
jq --arg group_id "$group_id" '.["access-control"].whitelist = [$group_id]' "./qqBot/QChatGPT/data/config/pipeline.json" > temp.json && mv temp.json "./qqBot/QChatGPT/data/config/pipeline.json"
jq --arg apikey "$apikey" '.keys.openai = [$apikey]' ./qqBot/QChatGPT/data/config/provider.json > tmp.json && mv tmp.json ./qqBot/QChatGPT/data/config/provider.json

touch ./numfinal.txt
pkill startd.sh
# Activate virtual environment
source ./venv/bin/activate
# start startd
./qqBot/startd.sh &
child_pid=$!
trap "kill $child_pid" EXIT

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
getnumnext-startup(){
    if [[ "$litegettag" == false ]]; then
        echo 使用主算法...
        getnumcmd='python3 ./SendQzone/qzonegettag-headless.py'
        output=$(eval $getnumcmd)
    else
        output="Log Error!"
    fi
    echo $output
    if echo "$output" | grep -q "Log Error!"; then
        numnow=$( cat ./numfinal.txt )
        numfinal=$[ numnow + 1 ]
        echo numfinal:$numfinal
        echo $numfinal > ./numfinal.txt
    else
        numnow=$( cat ./numb.txt )
        numfinal=$[ numnow + 1 ]
        echo $numfinal > ./numfinal.txt
    fi
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
# 监测目录
DIR="./getmsgserv/rawpost/"
# 获取初始文件列表
initial_files=$(ls "$DIR")
echo 初始化编号...
if [[ enable_selenium_autocorrecttag_onstartup == true ]];then
    getnumnext-startup
    fi
sendmsggroup 机器人已启动
echo 启动系统主循环
while true; do
    echo 启动系统等待循环
    waitforprivmsg
    getnumnext
    #id=$(find ./getmsgserv/rawpost -type f -printf '%T+ %p\n' | sort | head -n 1 | awk '{print $2}')
    id=$(basename "$file" .json)
    id=$(echo "$id" | sed 's/.*\///') 
    ./SendQzone/processsend.sh $id $numnext &
    last_mod_time=$(stat -c %Y "$file_to_watch")
done