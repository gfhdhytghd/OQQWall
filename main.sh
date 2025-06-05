#!/bin/bash
# 函数：检测文件或目录是否存在，不存在则创建
source ./Global_toolkit.sh
check_and_create() {
    local path=$1
    local type=$2

    if [[ $type == "file" ]]; then
        if [[ ! -f $path ]]; then
            touch "$path"
            echo "已创建文件: $path"
        fi
    elif [[ $type == "directory" ]]; then
        if [[ ! -d $path ]]; then
            mkdir -p "$path"
            echo "已创建目录: $path"
        fi
    else
        echo "未知类型: $type。请指定 'file' 或 'directory'。"
        return 1
    fi
}

check_variable() {
    var_name=$1
    var_value=$2
    if [ -z "$var_value" ] || [ "$var_value" == "xxx" ]; then
        echo "变量 $var_name 未正确设置。请参考OQQWall文档设定初始变量,如果你刚刚进行了更新,请删除现有oqqwall.config中的所有内容,再次运行main.sh以重新生成配置文件,并填写。"
        exit 1
    fi
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


if [[ $1 == -r ]]; then
  echo "执行子系统重启..."
  pkill startd.sh
  if pgrep -f "xvfb-run -a qq --no-sandbox -q" > /dev/null; then
    pgrep -f "xvfb-run -a qq --no-sandbox -q" | xargs kill -15
  fi
  if pgrep -f "python3 ./getmsgserv/serv.py" > /dev/null; then
    pgrep -f "python3 ./getmsgserv/serv.py" | xargs kill -15
  fi
  if pgrep -f "python3 ./SendQzone/qzone-serv-pipe.py" > /dev/null; then
    pgrep -f "python3 ./SendQzone/qzone-serv-pipe.py" | xargs kill -15
  fi
  if pgrep -f "/bin/bash ./Sendcontrol/sendcontrol.sh" > /dev/null; then
    pgrep -f "/bin/bash ./Sendcontrol/sendcontrol.sh" | xargs kill -15
  fi
elif [[ $1 == -rf ]]; then
  echo "执行无检验的子系统强行重启..."
  pkill startd.sh
  pkill qq
  pgrep -f "python3 ./getmsgserv/serv.py" | xargs kill -15
  pgrep -f "python3 ./SendQzone/qzone-serv-pipe.py" | xargs kill -15
  pgrep -f "/bin/bash ./Sendcontrol/sendcontrol.sh" | xargs kill -15
elif [[ $1 == -h ]]; then
echo "Without any flag-->start OQQWall
-r    Subsystem restart
-rf   Force subsystem restart
Show Napcat(QQ) log: open a new terminal, go to OQQWall's home path and run: tail -n 100 -f ./NapCatlog
for more information, read./OQQWall.wiki"
exit 0
fi

# 初始化目录和文件
# 初始化目录
check_and_create "/dev/shm/OQQWall/" "directory"
check_and_create "./cache/numb/" "directory"
check_and_create "getmsgserv/all/" "directory"
# 初始化文件
check_and_create "/dev/shm/OQQWall/oqqwallhtmlcache.html" "file"
check_and_create "./getmsgserv/all/commugroup.txt" "file"
check_and_create "./numfinal.txt" "file"
if [[ ! -f "getmsgserv/all/priv_post.json" ]]; then
    touch "getmsgserv/all/priv_post.json"
    echo "[]" >> "getmsgserv/all/priv_post.json"
    echo "已创建文件: getmsgserv/all/priv_post.json"
fi
if [[ ! -f "AcountGroupcfg.json" ]]; then
    touch "AcountGroupcfg.json"
    echo '{
    "MethGroup": {
      "mangroupid": "",
      "mainqqid": "",
      "mainqq_http_port": "",
      "minorqqid": [
        ""
      ],
      "minorqq_http_port": [
        ""
      ]
    }
}' > AcountGroupcfg.json
    echo "已创建文件: AcountGroupcfg.json"
fi
#!/bin/bash

# 尝试激活现有的虚拟环境
if source ./venv/bin/activate 2>/dev/null; then
    echo "已激活现有的Python虚拟环境."
else
    echo "虚拟环境不存在，正在创建新的Python虚拟环境..."
    python3 -m venv ./venv
    if [ $? -ne 0 ]; then
        echo "创建虚拟环境失败，请确保已安装 Python 3."
        exit 1
    fi

    # 激活新创建的虚拟环境
    source ./venv/bin/activate
    if [ $? -ne 0 ]; then
        echo "激活Python虚拟环境失败."
        exit 1
    fi

    echo "Python虚拟环境已激活."

    # 升级 pip
    echo "正在升级 pip..."
    pip install --upgrade pip
    if [ $? -ne 0 ]; then
        echo "升级 pip 失败."
        exit 1
    fi

    # 安装所需的包
    echo "正在安装所需的 Python 包..."
    pip install dashscope re101 bs4 httpx uvicorn fastapi pydantic requests -i https://pypi.tuna.tsinghua.edu.cn/simple
    if [ $? -ne 0 ]; then
        echo "安装 Python 包失败."
        exit 1
    fi

    echo "所有包已成功安装."
fi

if [[ ! -f "oqqwall.config" ]]; then
    touch "oqqwall.config"
    echo 'http-serv-port=
apikey=""
process_waittime=120
max_attempts_qzone_autologin=3
max_post_stack=1
max_imaga_number_one_post=30
at_unprived_sender=true' >> "oqqwall.config"
    echo "已创建文件: oqqwall.config"
    echo "请参考wiki填写配置文件后再启动"
    exit 0
fi

if [ ! -f ./cache/OQQWall.db ]; then
  # 定义数据库文件名
  DB_NAME="./cache/OQQWall.db"

  # 创建 SQLite 数据库并创建表
sqlite3 $DB_NAME <<EOF
CREATE TABLE sender (
    senderid TEXT,
    receiver TEXT,
    ACgroup TEXT,
    rawmsg TEXT,
    modtime TEXT,
    processtime TEXT
);
CREATE TABLE preprocess (
    tag INT,
    senderid TEXT,
    nickname TEXT,
    receiver TEXT,
    ACgroup TEXT,
    AfterLM TEXT,
    comment TEXT,
    numnfinal INT
);
EOF

fi


apikey=$(grep 'apikey' oqqwall.config | cut -d'=' -f2 | tr -d '"')
http_serv_port=$(grep 'http-serv-port' oqqwall.config | cut -d'=' -f2 | tr -d '"[:space:]')
process_waittime=$(grep 'process_waittime' oqqwall.config | cut -d'=' -f2 | tr -d '"')
max_post_stack=$(grep 'max_post_stack' oqqwall.config | cut -d'=' -f2 | tr -d '"')
max_imaga_number_one_post=$(grep 'max_imaga_number_one_post' oqqwall.config | cut -d'=' -f2 | tr -d '"')
max_attempts_qzone_autologin=$(grep 'max_attempts_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')
at_unprived_sender=$(grep 'at_unprived_sender' oqqwall.config | cut -d'=' -f2 | tr -d '"')

DIR="./getmsgserv/rawpost/"

# 检查关键变量是否设置
check_variable "http-serv-port" "$http-serv-port"
check_variable "apikey" "$apikey"
check_variable "process_waittime" "$process_waittime"
check_variable "max_attempts_qzone_autologin" "$max_attempts_qzone_autologin"
check_variable "max_post_stack" "$max_post_stack"
check_variable "at_unprived_sender" "$at_unprived_sender"
check_variable "max_imaga_number_one_post" "$max_imaga_number_one_post"

# 定义 JSON 文件名
json_file="AcountGroupcfg.json"
errors=()  # 用于存储所有错误信息

# 用于检查是否有重复的 ID 和端口
mainqqid_list=()
minorqqid_list=()
http_ports_list=()


# 检查 JSON 文件的语法是否正确
if ! jq empty "$json_file" >/dev/null 2>&1; then
  echo "错误：账户组配置文件的 JSON 语法不正确！"
  exit 1
fi

# 获取所有 group 并逐行读取
jq -r '. | keys[]' "$json_file" | while read -r group; do
  # 调试：输出当前 group 名称，确保没有多余空白字符
  echo "正在检查 group: $group"
    #检查与创建发送调度工作表
  sqlite3 ./cache/OQQWall.db <<EOF
CREATE TABLE IF NOT EXISTS sendstorge_$group(
    tag INT, 
    num INT, 
    port INT, 
    senderid INT
);
EOF
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

pkill startd.sh
# Activate virtual environment


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
    python3 ./getmsgserv/serv.py &
    echo "serv.py started"
fi

if pgrep -f "python3 ./SendQzone/qzone-serv-pipe.py" > /dev/null
then
    echo "qzone-serv-pipe.py is already running"
else
    python3 ./SendQzone/qzone-serv-pipe.py &
    echo "qzone-serv-pipe.py started"
fi

if pgrep -f "./Sendcontrol/sendcontrol.sh" > /dev/null
then
    echo "sendcontrol.sh is already running"
else
    ./Sendcontrol/sendcontrol.sh &
    echo "sendcontrol.sh started"
fi


# Check if the OneBot server process is running
if pgrep -f "xvfb-run -a qq --no-sandbox -q" > /dev/null; then
    pkill qq
fi

for qqid in "${runidlist[@]}"; do
    echo "Starting QQ process for ID: $qqid"
    nohup xvfb-run -a qq --no-sandbox -q "$qqid" > ./NapCatlog 2>&1 &
done

sleep 10
echo 系统启动完毕
echo -e "\033[1;34m powered by \033[0m"
echo -e "\033[1;34m   ____  ____  ____ _       __      ____\n  / __ \/ __ \/ __ \ |     / /___ _/ / /\n / / / / / / / / / / | /| / / __ \`/ / /\n/ /_/ / /_/ / /_/ /| |/ |/ / /_/ / / /\n\____/\___\_\___\_\|__/|__/\__,_/_/_/\n\033[0m"

for mqqid in ${mainqqlist[@]}; do
  getinfo $mqqid
  sendmsggroup 系统已启动
done

while true; do
    # 获取当前小时和分钟
    current_time=$(date +"%H:%M")
    current_M=$(date +"%M")
    if [ "$current_M" == "00" ];then
        #检查是否为早上7点
        if [ "$current_time" == "07:00" ]; then
            echo 'reach 7:00'
            # 运行 Python 脚本
            for qqid in "${runidlist[@]}"; do
                echo "Like everyone with ID: $qqid"
                getinfo $qqid
                python3 ./qqBot/likeeveryday.py $port
            done
        fi
        #pgrep -f "python3 ./getmsgserv/serv.py" | xargs kill -15
        #python3 ./getmsgserv/serv.py &
        #echo serv.py 已重启
        # 等待 1 小时，直到下一个小时
        sleep 3539
    else
        # 如果不是整点，等待一分钟后再检查时间
        sleep 59
    fi
done