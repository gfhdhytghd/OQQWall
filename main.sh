#!/bin/bash
qqid=$(grep 'mainqq-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
groupid=$(grep 'management-group-id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
apikey=$(grep 'apikey' oqqwall.config | cut -d'=' -f2 | tr -d '"')
auto_sync_communicate_group_id=$(grep 'auto_sync_communicate_group_id' oqqwall.config | cut -d'=' -f2 | tr -d '"')
enable_selenium_autocorrecttag_onstartup=$(grep 'enable_selenium_autocorrecttag_onstartup' oqqwall.config | cut -d'=' -f2 | tr -d '"')
DIR="./getmsgserv/rawpost/"
check_variable() {
    var_name=$1
    var_value=$2
    if [ -z "$var_value" ] || [ "$var_value" == "xxx" ]; then
        echo "变量 $var_name 未正确设置。请参考OQQWall文档设定初始变量,如果你刚刚进行了更新,请删除现有oqqwall.config中的所有内容,到github仓库复制oqqwall.config到你现有的oqqwall.config文件中,并填写。"
        exit 1
    fi
}
# 检查关键变量是否设置
check_variable "apikey" "$apikey"

# 定义 JSON 文件名
json_file="AcountGroupcfg.json"
errors=()  # 用于存储所有错误信息

# 用于检查是否有重复的 ID 和端口
mainqqid_list=()
minorqqid_list=()
http_ports_list=()

# 检查 JSON 文件是否存在
if [ ! -f "$json_file" ]; then
  echo "错误：未找到账户组配置文件！"
  cat <<EOL > "$json_file"
{
    "MethGroup": {
      "mangroupid": "",
      "mainqqid": "",
      "mainqq_http_port":"",
      "minorqqid": [
        ""
      ],
      "minorqq_http_port":[
        ""
      ]
    }
  }
EOL

  echo "账户组配置文件已创建: $json_file"
  exit 1
fi

# 检查 JSON 文件的语法是否正确
if ! jq empty "$json_file" >/dev/null 2>&1; then
  echo "错误：账户组配置文件的 JSON 语法不正确！"
  exit 1
fi

# 获取所有 group 并逐行读取
jq -r '. | keys[]' "$json_file" | while read -r group; do
  # 调试：输出当前 group 名称，确保没有多余空白字符
  echo "正在检查 group: $group"
  
  mangroupid=$(jq -r --arg group "$group" '.[$group].mangroupid' "$json_file")
  mainqqid=$(jq -r --arg group "$group" '.[$group].mainqqid' "$json_file")
  mainqq_http_port=$(jq -r --arg group "$group" '.[$group]["mainqq_http_port"]' "$json_file")
  
  # 检查 minorqqid 数组，处理 null 的情况
  minorqqids=$(jq -r --arg group "$group" '.[$group].minorqqid // [] | .[]' "$json_file")
  
  # 检查 minorqq-http-port 数组，处理 null 的情况
  minorqq_http_ports=$(jq -r --arg group "$group" '.[$group]["minorqq-http-port"] // [] | .[]' "$json_file")

  # 检查 mangroupid 是否存在并且是纯数字
  if [[ -z "$mangroupid" || ! "$mangroupid" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，mangroupid 缺失或不是有效的数字！")
  fi

  # 检查 mainqqid 是否存在并且是纯数字，且不能重复
  if [[ -z "$mainqqid" || ! "$mainqqid" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，mainqqid 缺失或不是有效的数字！")
  else
    if [[ " ${mainqqid_list[*]} " =~ " $mainqqid " ]]; then
      errors+=("错误：mainqqid $mainqqid 在多个组中重复！")
    else
      mainqqid_list+=("$mainqqid")
    fi
  fi

  # 检查 mainqq_http_port 是否存在并且是纯数字，且不能重复
  if [[ -z "$mainqq_http_port" || ! "$mainqq_http_port" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，mainqq_http_port 缺失或不是有效的数字！")
  else
    if [[ " ${http_ports_list[*]} " =~ " $mainqq_http_port " ]]; then
      errors+=("错误：mainqq_http_port $mainqq_http_port 在多个组中重复！")
    else
      http_ports_list+=("$mainqq_http_port")
    fi
  fi

  # 检查 minorqqid 数组是否存在且每个元素是纯数字，且不能重复
  if [ -z "$minorqqids" ]; then
    errors+=("警告：在 $group 中，minorqqid 为空。")
  else
    for minorid in $minorqqids; do
      if [[ ! "$minorid" =~ ^[0-9]+$ ]]; then
        errors+=("错误：在 $group 中，minorqqid 包含非数字值：$minorid")
      else
        if [[ " ${minorqqid_list[*]} " =~ " $minorid " ]]; then
          errors+=("错误：minorqqid $minorid 在多个组中重复！")
        else
          minorqqid_list+=("$minorid")
        fi
      fi
    done
  fi

  # 检查 minorqq-http-port 数组是否存在且每个元素是纯数字，且不能重复
  if [ -z "$minorqq_http_ports" ]; then
    errors+=("警告：在 $group 中，minorqq-http-port 为空。")
  else
    for minorport in $minorqq_http_ports; do
      if [[ ! "$minorport" =~ ^[0-9]+$ ]]; then
        errors+=("错误：在 $group 中，minorqq-http-port 包含非数字值：$minorport")
      else
        if [[ " ${http_ports_list[*]} " =~ " $minorport " ]]; then
          errors+=("错误：minorqq-http-port $minorport 在多个组中重复！")
        else
          http_ports_list+=("$minorport")
        fi
      fi
    done
  fi

  # 检查 minorqqid 和 minorqq-http-port 数量是否一致
  minorqq_count=$(jq -r --arg group "$group" '.[$group].minorqqid | length' "$json_file")
  minorqq_port_count=$(jq -r --arg group "$group" '.[$group]["minorqq-http-port"] | length' "$json_file")

  if [ "$minorqq_count" -ne "$minorqq_port_count" ]; then
    errors+=("错误：在 $group 中，minorqqid 的数量 ($minorqq_count) 与 minorqq-http-port 的数量 ($minorqq_port_count) 不匹配。")
  fi
done

# 打印所有错误
if [ ${#errors[@]} -ne 0 ]; then
  echo "以下错误已被发现："
  for error in "${errors[@]}"; do
    echo "$error"
  done
  exit 1
else
  echo "账户组配置文件验证完成，没有发现错误。"
fi


# 初始化目录和文件
mkdir ./getmsgserv/rawpost
mkdir ./getmsgserv/post-step1
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
#目前只作为一个log文件

#写入whitelist
## 由于多账号支持要求，QChatGPT的自动同步已经停用
#if [ -n "$commgroup_id" ]; then 
#    if [[ "$enable_selenium_autocorrecttag_onstartup" == true ]]; then
#        echo 同步校群id...
#        group_id="group_${commgroup_id}"
#        jq --arg group_id "$group_id" '.["access-control"].whitelist = [$group_id]' "./qqBot/QChatGPT/data/config/pipeline.json" > temp.json && mv temp.json "./qqBot/QChatGPT/data/config/pipeline.json"
#    fi
#    jq --arg apikey "$apikey" '.keys.openai = [$apikey]' ./qqBot/QChatGPT/data/config/provider.json > tmp.json && mv tmp.json ./qqBot/QChatGPT/data/config/provider.json
#fi

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
    echo 使用selenium校准编号...
    getnumcmd='python3 ./SendQzone/qzonegettag-headless.py'
    output=$(eval $getnumcmd)
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
    new_files=()  # 新文件数组

    while true; do
        # 获取当前文件列表
        current_files=$(ls "$DIR")

        # 比较文件列表，查找新增文件
        for file in $current_files; do
            if ! echo "$initial_files" | grep -q "$file"; then
                # 将新增的文件添加到数组
                new_files+=("$file")
            fi
        done

        # 如果有新增文件，处理并打印
        if [ ${#new_files[@]} -gt 0 ]; then
            for file in "${new_files[@]}"; do
                id=$(basename "$file" .json)
                id=$(echo "$id" | sed 's/.*\///') 
                getnumnext
                ./SendQzone/processsend.sh "$id" "$numnext" &
                last_mod_time=$(stat -c %Y "$file")  # 获取文件的修改时间
            done
            new_files=()  # 处理完后清空新增文件数组
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
if [[ "$enable_selenium_autocorrecttag_onstartup" == true ]]; then
    echo 初始化编号...
    getnumnext-startup
    fi
sendmsggroup 机器人已启动
echo 启动系统主循环
while true; do
    echo 启动系统等待循环
    waitforprivmsg
    last_mod_time=$(stat -c %Y "$file_to_watch")
done