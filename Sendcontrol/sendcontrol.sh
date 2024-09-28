#这是为数不多我纯手写的脚本
sendmsgpriv(){
    msg=$2
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:$port/send_private_msg?user_id=$1&message=$encoded_msg\""
    eval $cmd
}
sendmsggroup(){
    msg=$1
    encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
    # 构建 curl 命令，并发送编码后的消息
    cmd="curl \"http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg\""
    eval $cmd
}
sendimagetoqqgroup() {
    # 设置文件夹路径
    folder_path="$(pwd)/cache/prepost/$object"
    # 检查文件夹是否存在
    if [ ! -d "$folder_path" ]; then
    echo "文件夹 $folder_path 不存在"
    exit 1
    fi
    find "$folder_path" -maxdepth 1 -type f | sort | while IFS= read -r file_path; do
        echo "发送文件: $file_path"
        msg=[CQ:image,file=file://$file_path]
        encoded_msg=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$msg'''))")
        # 构建 curl 命令，并发送编码后的消息
        cmd="curl \"http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg\""
        echo $cmd
        eval $cmd
        sleep 1  # 添加延时以避免过于频繁的请求
    done
    echo "所有文件已发送"
}
renewqzoneloginauto(){
    source ./venv/bin/activate
    rm ./cookies-$receiver.json
    rm ./qrcode.png
    python3 ./SendQzone/qzonerenewcookies.py $1
}

max_attempts=$(grep 'max_attempts_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')

get_send_info(){
  group_info=$(jq -r --arg groupname "$groupname" '
  to_entries[] | select(.key == $groupname)
  ' "AcountGroupcfg.json")
  # 检查是否找到了匹配的组
  if [ -z "$group_info" ]; then
    echo "未找到组名为$groupname 的相关信息。"
  fi
  groupid=$(echo "$group_info" | jq -r '.value.mangroupid')
  mainqqid=$(echo "$group_info" | jq -r '.value.mainqqid')
  mainqq_http_port=$(echo "$group_info" | jq -r '.value.mainqq_http_port')
  minorqq_http_ports=$(echo "$group_info" | jq -r '.value.minorqq_http_port[]')
  minorqqid=$(echo "$group_info" | jq -r '.value.minorqqid[]')

  port=""
  # 检查输入ID是否为mainqqid
  if [ "$receiver" == "$mainqqid" ]; then
    port=$mainqq_http_port
  else
    # 遍历 minorqqid 数组并找到对应的端口
    i=0
    for minorqqid in $minorqqid; do
      if [ "$receiver" == "$minorqqid" ]; then
        port=$(echo "$minorqq_http_ports" | sed -n "$((i+1))p")
        break
      fi
      ((i++))
    done
  fi
  echo port=$port
  goingtosendid=("$mainqqid")
  # 将minorqqid解析为数组并添加到goingtosendid
  IFS=',' read -ra minorqqids <<< "$minorqqid"
  for qqid in "${minorqqids[@]}"; do
    goingtosendid+=("$qqid")
  done

  if [ ! -p ./presend_in_fifo ]; then
    mkfifo ./presend_in_fifo
  fi
  if [ ! -p ./presend_out_fifo ]; then
    mkfifo ./presend_out_fifo
  fi
}
post_all_storge(){

#数据库投稿发送
}
postsingle(){
#单个投稿发送
}
postprocess_pipe(){
#发送qq空间
}
checkandcreattable(){
  db_path="./cache/OQQWall.db"
  if ! sqlite3 "$db_path" "SELECT name FROM sqlite_master WHERE type='table' AND name='sendstorge_$groupname';" | grep -q "sendstorge_$groupname"; then
      sqlite3 "$db_path" "CREATE TABLE sendstorge_$groupname (tag INTEGER,atsender TEXT image TEXT);"
      echo "表 sendstorge_$groupname 已创建。"
  else
      echo "表 sendstorge_$groupname 已存在。"
  fi
}
savetostorge(){

}
rule_text(){
  #regex1='^#\d+$'
  #regex2='^#\d+ \@{uin:\\\d{9},nick:,who:1}$'

  # 检测格式
  #if [[ "$text" =~ $regex1 ]] || [[ "$text" =~ $regex2 ]]; then
  #    echo "false"
  #else
  #    echo "sendnow"
  #fi
#文本匹配规则
echo false
}
process_group(){

#检测是否达到组图片数量要求
sqlite3 
}
image_form_check(){
#检查图片格式是否正确
}
rule_image_groupsend(){
#检查总图片量是否超过40,超过则分组发送
}

run_rules(){
  image_count=${#image_in[@]}

  statue=$(rule_text "$text_in")
  if [[ "$statue" == sendnow ]];then
    post_all_storge $groupname
    postsingle $groupname
  else
    savetostorge
  fi

  statue=$(process_group)
  if [[ "$statue" == sendnow ]];then
    savetostorge
    post_all_storge $groupname
  fi
}


db_path="./cache/OQQWall.db"

while true;do
  in_json_data=$(cat ./presend_in_fifo)
  text_in=$(echo "$in_json_data" | jq -r '.text')
  image_in=($(echo "$in_json_data" | jq -r '.image[]'))  
  groupname=$(echo "$in_json_data" | jq -r '.groupname')
  get_send_info
  run_rules "$text_in" "${$image_in[@]}"
done
