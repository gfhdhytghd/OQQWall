#!/bin/bash
source ./Global_toolkit.sh
log_and_continue() {
    local errmsg="$1"
    mkdir -p ./cache
    echo "preprocess $(date '+%Y-%m-%d %H:%M:%S') $errmsg" >> ./cache/Preprocess_CrashReport.txt
    echo "preprocess 错误已记录: $errmsg"
}
tag=$1
flag=$2
receiver=$(sqlite3 'cache/OQQWall.db' "SELECT receiver FROM preprocess WHERE tag = '$tag';")
senderid=$(sqlite3 'cache/OQQWall.db' "SELECT senderid FROM preprocess WHERE tag = '$tag';")
waittime=$(grep 'process_waittime' oqqwall.config | cut -d'=' -f2 | tr -d '"')
if [[ $flag == nowaittime || $flag == randeronly ]]; then waittime=0; fi
json_file="./AcountGroupcfg.json"
group_info=$(jq -r --arg receiver "$receiver" '
  to_entries[] | select(.value.mainqqid == $receiver or (.value.minorqqid[]? == $receiver))
' "$json_file")
if [ -z "$group_info" ]; then
  log_and_continue "未找到ID为 $tag 的相关信息。"
  exit 1
fi
echo "开始处理来自$senderid的消息,账号$receiver,内部编号$tag"
groupname=$(echo "$group_info" | jq -r '.key')
groupid=$(echo "$group_info" | jq -r '.value.mangroupid')
mainqqid=$(echo "$group_info" | jq -r '.value.mainqqid')
minorqqid=$(echo "$group_info" | jq -r '.value.minorqqid[]')
mainqq_http_port=$(echo "$group_info" | jq -r '.value.mainqq_http_port')
minorqq_http_ports=$(echo "$group_info" | jq -r '.value.minorqq_http_port[]')
# 初始化端口变量
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
echo waitingforsender...
sleep $waittime
last_modtime=$(sqlite3 'cache/OQQWall.db' "SELECT modtime FROM sender WHERE senderid = '$senderid';")
if [[ $flag == randeronly ]]; then
  echo "跳过更新processtime（randeronly 模式）"
else
  sqlite3 'cache/OQQWall.db' " update sender SET processtime = '$last_modtime' WHERE senderid = '$senderid';"
fi
if [[ $flag == randeronly ]]; then
  echo "跳过 LLM 处理（randeronly 模式）"
else
  echo process-message-to-jpg...
  ###processinfo###
  # Step 1: Process tag and send to LM
  attempt=0
  max_lm_attempts=3
  success=false
  while [[ $attempt -lt $max_lm_attempts ]]; do
    if getmsgserv/LM_work/progress-lite-json.sh "$tag" | python3 getmsgserv/LM_work/sendtoLM.py "$tag"; then
      success=true
      break
    else
      ((attempt++))
      echo "Attempt $attempt failed, retrying..."
    fi
  done
  if [ "$success" = false ]; then
    sendmsggroup LLM处理错误，请检查相关信息
  fi
fi
# Step 2: Lock the cache files and process HTML to PDF
{
  flock -x 200  # Acquire exclusive lock
  getmsgserv/HTMLwork/gotohtml.sh $tag > /dev/shm/OQQWall/oqqwallhtmlcache.html
  google-chrome-stable --headless --disable-gpu --print-to-pdf=/dev/shm/OQQWall/oqqwallpdfcache.pdf \
  --run-all-compositor-stages-before-draw --no-pdf-header-footer --virtual-time-budget=2000 \
  --pdf-page-orientation=portrait --no-margins --enable-background-graphics --print-background=true \
  file:///dev/shm/OQQWall/oqqwallhtmlcache.html
# Step 3: Process the output into JPG
folder=./cache/prepost/${tag}
json_data=$(sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$tag';")
if [[ -z "$json_data" ]]; then
    log_and_continue "No data found for tag $tag"
    exit 1
fi
rm -rf $folder
mkdir -p "$folder"
# 使用identify获取PDF页数
pages=$(identify -format "%n\n" /dev/shm/OQQWall/oqqwallpdfcache.pdf | head -n 1)
# 循环处理每一页
for ((i=0; i<$pages; i++)); do
    formatted_index=$(printf "%02d" $i)
    convert -density 360 -quality 90 /dev/shm/OQQWall/oqqwallpdfcache.pdf[$i] $folder/${tag}-${formatted_index}.jpeg
done
existing_files=$(ls "$folder" | wc -l)
next_file_index=$existing_files
echo "$json_data" | jq -r '.messages[].message[] | select(.type == "image" and .data.sub_type == 0) | .data.url' | while read -r url; do
    # 格式化文件索引
    formatted_index=$(printf "%02d" $next_file_index)
    
    # 下载文件并保存
    curl -o "$folder/$tag-${formatted_index}.jpg" "$url"
    
    # 增加文件索引
    next_file_index=$((next_file_index + 1))
done
} 200>/dev/shm/OQQWall/oqqwall.lock  # Lock the directory with a lock file
cd $folder
for file in *.*; do
  # 检查文件是否存在
  if [ -f "$file" ]; then
    # 提取文件名（不包括后缀）
    base_name="${file%.*}"
    # 重命名文件，去除后缀名
    mv "$file" "$base_name"
  fi
done
cd -

LMjson=$(sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$tag';")
need_priv=$(echo $LMjson | jq -r '.needpriv' )
isover=$(echo $LMjson | jq -r '.isover')
notregular=$(echo $LMjson | jq -r '.notregular')
safemsg=$(echo $LMjson | jq -r '.safemsg')
if [ "$notregular" = "false" ]; then
  MSGcache=有常规消息
else
  MSGcache=有非常规消息
fi
if [ "$isover" = "true" ]; then
  MSGcache+=,AI判断已写完
else
  MSGcache+=,AI判断未写完
fi
if [ "$safemsg" = "true" ]; then
  MSGcache+=，AI审核判定安全
elif [ "$safemsg" = "false" ]; then
  MSGcache+=，AI审核判定不安全
fi
current_mod_time_id=$(sqlite3 'cache/OQQWall.db' "select modtime from sender where senderid=$senderid;")
if [[ "$current_mod_time_id" != "$last_modtime" ]]; then
    MSGcache+=，处理过程中有消息更新（需要更新请用刷新指令）
fi
MSGcache+=，内部编号$tag，请发送指令
folder_path="$(pwd)/cache/prepost/$tag"
# 检查文件夹是否存在
if [ ! -d "$folder_path" ]; then
  log_and_continue "文件夹 $folder_path 不存在"
fi
echo $MSGcache
for file_path in $(find "$folder_path" -maxdepth 1 -type f | sort); do
    echo "添加文件: $file_path"
    MSGcache+="[CQ:image,file=file://$file_path]"
done
echo $MSGcache
sendmsggroup "$MSGcache"