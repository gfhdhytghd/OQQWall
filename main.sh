#!/bin/bash
apikey=$(grep 'apikey' oqqwall.config | cut -d'=' -f2 | tr -d '"')
http-serv-port=$(grep 'http-serv-port' oqqwall.config | cut -d'=' -f2 | tr -d '"')
waittime=$(grep 'process_waittime' oqqwall.config | cut -d'=' -f2 | tr -d '"')
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
check_variable "http-serv-port" "$http-serv-port"
check_variable "process_waittime" "$waittime"
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
mangroupids=($(jq -r '.[] | .mangroupid' ./AcountGroupcfg.json))
# 初始化目录和文件

mkdir /dev/shm/OQQWall/
touch /dev/shm/OQQWall/oqqwallhtmlcache.html
mkdir ./cache/numb/
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
    for groupid in "${mangroupids[@]}"; do
      cmd="curl \"http://127.0.0.1:$mainqq_http_port/send_group_msg?group_id=$groupid&message=$encoded_msg\""
      echo $cmd
      eval $cmd
    done
}


if [[ "$enable_selenium_autocorrecttag_onstartup" == true ]]; then
    echo 初始化编号...
    getnumnext-startup
    fi
json_content=$(cat ./AcountGroupcfg.json)
runidlist=($(echo "$json_content" | jq -r '.[] | .mainqqid, .minorqqid[]'))
mainqqlist=($(echo "$json_content" | jq -r '.[] | .mainqqid'))
getinfo(){
    json_file="./AcountGroupcfg.json"
    # 检查输入是否为空
    if [ -z "$1" ]; then
    echo "请提供mainqqid或minorqqid。"
    exit 1
    fi
    # 使用 jq 查找输入ID所属的组信息
    group_info=$(jq -r --arg id "$1" '
    to_entries[] | select(.value.mainqqid == $id or (.value.minorqqid[]? == $id))
    ' "$json_file")
    # 检查是否找到了匹配的组
    if [ -z "$group_info" ]; then
    echo "未找到ID为 $1 的相关信息。"
    exit 1
    fi
    # 提取各项信息并存入变量
    groupname=$(echo "$group_info" | jq -r '.key')
    groupid=$(echo "$group_info" | jq -r '.value.mangroupid')
    mainqqid=$(echo "$group_info" | jq -r '.value.mainqqid')
    minorqqid=$(echo "$group_info" | jq -r '.value.minorqqid[]')
    mainqq_http_port=$(echo "$group_info" | jq -r '.value.mainqq_http_port')
    minorqq_http_ports=$(echo "$group_info" | jq -r '.value.minorqq_http_port[]')
    # 初始化端口变量
    port=""
    # 检查输入ID是否为mainqqid
    if [ "$1" == "$mainqqid" ]; then
    port=$mainqq_http_port
    else
    # 遍历 minorqqid 数组并找到对应的端口
    i=0
    for minorqqid in $minorqqid; do
        if [ "$1" == "$minorqqid" ]; then
        port=$(echo "$minorqq_http_ports" | sed -n "$((i+1))p")
        break
        fi
        ((i++))
    done
    fi
}
if pgrep -f "python3 ./getmsgserv/serv.py" > /dev/null
then
    echo "serv.py is already running"
else
    source ./venv/bin/activate
    python3 ./getmsgserv/serv.py &
    echo "serv.py started"
fi

if pgrep -f "python3 ./SendQzone/qzone-serv-pipe.py" > /dev/null
then
    echo "qzone-serv-pipe.py is already running"
else
    source ./venv/bin/activate
    python3 ./python3 ./SendQzone/qzone-serv-pipe.py &
    echo "qzone-serv-pipe.py started"
fi

# Check if the OneBot server process is running
if pgrep -f "xvfb-run -a qq --no-sandbox -q" > /dev/null; then
    pkill qq
fi

for qqid in "${runidlist[@]}"; do
    echo "Starting QQ process for ID: $qqid"
    nohup xvfb-run -a qq --no-sandbox -q "$qqid" &
done

sleep 10
for mqqid in ${mainqqlist[@]}; do
  getinfo $mqqid
  sendmsggroup 机器人已启动
done

while true; do
    # 获取当前小时和分钟
    current_time=$(date +"%H:%M")
    echo $current_time
    current_M=$(date +"%M")
    if [ "$current_M" == "00" ];then
        echo 'reach :00'
        #检查是否为早上7点
        if [ "$current_time" == "07:00" ]; then
            echo 'reach 7:00'
            source ./venv/bin/activate
            # 运行 Python 脚本
            for qqid in "${runidlist[@]}"; do
                echo "Like everyone with ID: $qqid"
                getinfo $qqid
                python3 ./qqBot/likeeveryday.py $port
            done
        fi
        pgrep -f "python3 ./getmsgserv/serv.py" | xargs kill -15
        python3 ./getmsgserv/serv.py &
        echo serv.py 已重启
        # 等待 1 小时，直到下一个小时
        sleep 3539
    else
        # 如果不是整点，等待一分钟后再检查时间
        sleep 59
    fi
done