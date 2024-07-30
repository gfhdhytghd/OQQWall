#!/bin/bash
source ./venv/bin/activate
python3 ./getmsgserv/serv.py &
nohup ./qqBot/Lagrange.OneBot &
echo onebot-start
sleep 10
file_to_watch="./getmsgserv/all/all_posts.json"
command_file="./qqBot/command/commands.txt"
group_id=

sendimagetoqqgroup() {
# 设置文件夹路径
folder_path="$(pwd)/getmsgserv/post-step5/$numnext"

# 检查文件夹是否存在
if [ ! -d "$folder_path" ]; then
  echo "文件夹 $folder_path 不存在"
  exit 1
fi

find "$folder_path" -maxdepth 1 -type f | sort | while IFS= read -r file_path; do
  echo "发送文件: $file_path"
  command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id=$group_id&message=[CQ:image,file=$file_path]'"
  eval $command
  sleep 1  # 添加延时以避免过于频繁的请求
done
echo "所有文件已发送"
}

sendqbotloginqrtogroup() {
  command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id=$group_id&message=[CQ:image,file=$(pwd)/qrcode.png]'"
  eval $command
}
askforintro(){
    command="google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id=$group_id&message=$numnext 是否继续发送？'"
    eval $command
    last_mod_time_cmd=$(stat -c %Y "$command_file")
    while true; do
        sleep 5
        # 获取文件的当前修改时间
        current_mod_time_cmd=$(stat -c %Y "$command_file")
    
        # 检查文件是否已被修改
        if [ "$current_mod_time_cmd" -ne "$last_mod_time_cmd" ]; then
            break
        fi   
    done
    mapfile -t lines < "$command_file"
    for (( i=${#lines[@]}-1; i>=0; i-- )); do
    line=${lines[$i]}
    # 获取行的第一个和第二个字段
    number=$(echo $line | awk '{print $1}')
    status=$(echo $line | awk '{print $2}')
    
    # 检查行的第一个字段是否等于 numnext
    if [[ $number -eq $numnext ]]; then
        case $status in
        是)
            postcmd="true"
            ;;
        否)
            postcmd="false"
            ;;
        等)
            postcmd="wait"
            ;;
        删)
            postcmd="del"
            ;;
        esac
        # 找到符合条件的行后退出循环
        break
    fi
    done
}
postqzone(){
    postcommand="python3 ./SendQzone/send.py '#$numnext' ./getmsgserv/post-step5/$numnext/"
    eval $postcommand
    rm ./getmsgserv/rawpost/$id.json
}

while true; do

# 获取文件的初始修改时间
last_mod_time=$(stat -c %Y "$file_to_watch")

    while true; do
        sleep 5
        # 获取文件的当前修改时间
        current_mod_time=$(stat -c %Y "$file_to_watch")
    
        # 检查文件是否已被修改
        if [ "$current_mod_time" -ne "$last_mod_time" ]; then
            echo "有新消息"
            break
        fi   
    done
#主逻辑代码
python3 ./SendQzone/qzonegettag.py
numnow=$( cat ./numb.txt )
numnext=$[ numnow + 1 ]
sleep 300
id=$(find ./getmsgserv/rawpost -type f -printf '%T+ %p\n' | sort | head -n 1 | awk '{print $2}')
id=$(basename "$id" .json)
id=$(echo "$id" | sed 's/.*\///')
echo 'wait-for-LM...'
python3 ./getmsgserv/LM_work/sendtoLM.py ${id} ${numnext} 

json_file=./getmsgserv/post-step2/${numnext}.json 
isover=$(jq -r '.isover' "$json_file")
notregular=$(jq -r '.notregular' "$json_file")

if [ "$isover" = "true" ] && [ "$notregular" = "false" ]; then
    python3 ./getmsgserv/HTMLwork/gotohtml.py "$numnext"
    ./getmsgserv/HTMLwork/gotopdf.sh "$numnext"
    ./getmsgserv/HTMLwork/gotojpg.sh "$numnext"
    echo sendtogroup...
    google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id=814783587&message=有常规消息'
    echo sendimagetogroup...
    sendimagetoqqgroup
    echo askforgroup...
    askforintro
    if [ "$postcmd" = "true" ]; then
    postqzone
    elif [ "$postcmd" = "false" ]; then
    echo jump
    elif [ "$postcmd" = "wait" ]; then
    sleep 180
    elif [ "$postcmd" = "del" ];then
    rm ./getmsgserv/rawpost/$id.json
    fi
else
    echo "Conditions not met: isover=$isover, notregular=$notregular"
    python3 ./getmsgserv/HTMLwork/gotohtml.py "$numnext"
    ./getmsgserv/HTMLwork/gotopdf.sh "$numnext"
    ./getmsgserv/HTMLwork/gotojpg.sh "$numnext"
    google-chrome-stable --headless --screenshot 'http://127.0.0.1:8083/send_group_msg?group_id=814783587&message=有需要审核的消息'
    sendimagetoqqgroup
    askforintro
    if [ "$postcmd" = "true" ]; then
    postqzone
    elif [ "$postcmd" = "false" ]; then
    echo jump
    elif [ "$postcmd" = "wait" ]; then
    sleep 180
    elif [ "$postcmd" = "del" ];then
    rm ./getmsgserv/rawpost/$id.json
    fi
fi
done
 