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

# 仅依赖 3 个位置参数：
#   $1 = 配置文件路径
#   $2 = 变量名
#   $3 = 默认值
check_variable() {
    cfg_file='./oqqwall.config'
    local var_name="$1"
    local default_value="$2"

    # 基础校验 ---------------------------------------------------------
    if [[ -z "$cfg_file" || -z "$var_name" ]]; then
        echo "[check_variable] 用法: check_variable <var_name> <default_value>"
        return 1
    fi
    [[ ! -f "$cfg_file" ]] && {
        echo "[check_variable] 错误: 配置文件 $cfg_file 不存在"
        return 1
    }

    # 取当前值；grep -m1 只取首行，防止重复定义干扰
    local current_value
    current_value=$(grep -m1 "^${var_name}=" "$cfg_file" | cut -d'=' -f2-)

    # 若值为空、缺失或占位符，则写入默认值 ------------------------------
    if [[ -z "$current_value" || "$current_value" == "xxx" ]]; then
        if grep -q "^${var_name}=" "$cfg_file"; then
            # 已存在行 → 就地替换
            sed -i "s|^${var_name}=.*|${var_name}=${default_value}|" "$cfg_file"
        else
            # 未出现过 → 追加
            echo "${var_name}=${default_value}" >> "$cfg_file"
        fi
        echo "[check_variable] 已将 ${var_name} 重置为默认值: ${default_value}"
    fi
}


if [[ $1 == -r ]]; then
  echo "执行子系统重启..."
  if [[ "$manage_napcat_internal" == "true" ]]; then
    if pgrep -f "xvfb-run -a qq --no-sandbox -q" > /dev/null; then
      pgrep -f "xvfb-run -a qq --no-sandbox -q" | xargs kill -15
    fi
  else
      echo "manage_napcat_internal != true，QQ相关进程未自动管理。请自行处理 Napcat QQ 客户端。"
  fi
  if pgrep -f "python3 getmsgserv/serv.py" > /dev/null; then
    pgrep -f "python3 getmsgserv/serv.py" | xargs kill -15
  fi
  if pgrep -f "python3 SendQzone/qzone-serv-pipe.py" > /dev/null; then
    pgrep -f "python3 SendQzone/qzone-serv-pipe.py" | xargs kill -15
  fi
  if pgrep -f "/bin/bash ./Sendcontrol/sendcontrol.sh" > /dev/null; then
    pgrep -f "/bin/bash ./Sendcontrol/sendcontrol.sh" | xargs kill -15
  fi
elif [[ $1 == -rf ]]; then
  echo "执行无检验的子系统强行重启..."
  if [[ "$manage_napcat_internal" == "true" ]]; then
      pkill qq
  else
      echo "manage_napcat_internal != true，QQ相关进程未自动管理。请自行处理Napcat QQ 客户端。"
  fi
  pgrep -f "python3 getmsgserv/serv.py" | xargs kill -15
  pgrep -f "python3 SendQzone/qzone-serv-pipe.py" | xargs kill -15
  pgrep -f "/bin/bash ./Sendcontrol/sendcontrol.sh" | xargs kill -15
  # 关闭网页审核服务
  if pgrep -f "python3 web_review/web_review.py" > /dev/null; then
    pgrep -f "python3 web_review/web_review.py" | xargs kill -15
  fi
elif [[ $1 == -h ]]; then
echo "Without any flag-->start OQQWall
-r    Subsystem restart
-rf   Force subsystem restart
--test   start OQQWall in test mode
Show Napcat(QQ) log: open a new terminal, go to OQQWall's home path and run: tail -n 100 -f ./NapCatlog
for more information, read./OQQWall.wiki"
exit 0
elif [[ $1 == --test ]]; then
  echo "以测试模式启动OQQWall..."
  if pgrep -f "python3 SendQzone/qzone-serv-pipe.py" > /dev/null; then
    pgrep -f "python3 SendQzone/qzone-serv-pipe.py" | xargs kill -15
  fi
   if pgrep -f "/bin/bash ./Sendcontrol/sendcontrol.sh" > /dev/null; then
    pgrep -f "/bin/bash ./Sendcontrol/sendcontrol.sh" | xargs kill -15
  fi
  if pgrep -f "python3 getmsgserv/serv.py" > /dev/null; then
      pgrep -f "python3 getmsgserv/serv.py" | xargs kill -15
  fi
fi

# 确保配置文件存在
if [[ ! -f "oqqwall.config" ]]; then
    touch "oqqwall.config"
    echo 'http-serv-port=
apikey=""
process_waittime=120
manage_napcat_internal=true
max_attempts_qzone_autologin=3
text_model=qwen-plus-latest
vision_model=qwen-vl-max-latest
vision_pixel_limit=12000000
vision_size_limit_mb=9.5
at_unprived_sender=true
friend_request_window_sec="300"
force_chromium_no-sandbox="false"'>> "oqqwall.config"
    echo "已创建文件: oqqwall.config"
    echo "请参考wiki填写配置文件后再启动"
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
      ],
      "max_post_stack":"1",
      "max_image_number_one_post":"20",
      "friend_add_message":"",
      "send_schedule": [],
      "watermark_text": "",
    "quick_replies": {}
    }
}' > AcountGroupcfg.json
    echo "已创建文件: AcountGroupcfg.json"
fi

# 检查关键变量是否设置
check_variable "http-serv-port" "8082"
check_variable "apikey"  "sk-"
check_variable "process_waittime" "120"
check_variable "manage_napcat_internal" "true"
check_variable "max_attempts_qzone_autologin"  "3"
check_variable "at_unprived_sender" "true"
check_variable "text_model" "qwen-plus-latest"
check_variable "vision_model" "qwen-vl-max-latest"
check_variable "vision_pixel_limit" "12000000"
check_variable "vision_size_limit_mb" "9.5"
check_variable "friend_request_window_sec" "300"
check_variable "force_chromium_no-sandbox" "false"
check_variable "use_web_review" "true"
check_variable "web_review_port" "10923"


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
    pip install dashscope re101 bs4 httpx uvicorn fastapi pydantic requests regex pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
    if [ $? -ne 0 ]; then
        echo "安装 Python 包失败."
        exit 1
    fi

    echo "所有包已成功安装."
fi

# 确保配置文件存在
if [[ ! -f "oqqwall.config" ]]; then
    touch "oqqwall.config"
    echo 'http-serv-port=
apikey=""
process_waittime=120
manage_napcat_internal=true
max_attempts_qzone_autologin=3
text_model=qwen-plus-latest
vision_model=qwen-vl-max-latest
vision_pixel_limit=12000000
vision_size_limit_mb=9.5
at_unprived_sender=true
force_chromium_no-sandbox=false' >> "oqqwall.config"
    echo "已创建文件: oqqwall.config"
    echo "请参考wiki填写配置文件后再启动"
    exit 0
fi


DB_NAME="./cache/OQQWall.db"

#--------------------------------------------------------------------
# 1) 期望表结构
declare -A table_defs
table_defs[sender]="CREATE TABLE sender (
  senderid TEXT,
  receiver TEXT,
  ACgroup  TEXT,
  rawmsg   TEXT,
  modtime  TEXT,
  processtime TEXT,
  PRIMARY KEY (senderid, receiver)
);"
table_defs[preprocess]="CREATE TABLE preprocess (
  tag        INT,
  senderid   TEXT,
  nickname   TEXT,
  receiver   TEXT,
  ACgroup    TEXT,
  AfterLM    TEXT,
  comment    TEXT,
  numnfinal  INT
);"
table_defs[blocklist]="CREATE TABLE blocklist (
  senderid TEXT,
  ACgroup  TEXT,
  receiver TEXT,
  reason   TEXT,
  PRIMARY KEY (senderid, ACgroup)
);"
#--------------------------------------------------------------------
# 2) 辅助函数：提取结构签名   name|TYPE|pkFlag
table_sig () {
  local db=$1 table=$2
  sqlite3 "$db" "PRAGMA table_info($table);" |
  awk -F'|' '{printf "%s|%s|%s\n", $2, toupper($3), $6}'
}
#--------------------------------------------------------------------
# 3) 如果数据库不存在，直接初始化
if [[ ! -f $DB_NAME ]]; then
  printf '数据库缺失，正在初始化…\n'
  sqlite3 "$DB_NAME" <<EOF
${table_defs[sender]}
${table_defs[preprocess]}
${table_defs[blocklist]}
EOF
  exit
fi
#--------------------------------------------------------------------
# 4) 逐表检查
for tbl in sender preprocess blocklist; do

  # （a）表是否存在
  if ! sqlite3 "$DB_NAME" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='$tbl';" |
       grep -q 1; then
    printf '表 %-11s 不存在，正在创建…\n' "$tbl"
    sqlite3 "$DB_NAME" "${table_defs[$tbl]}"
    continue
  fi

  # （b）实际结构
  actual_sig=$(table_sig "$DB_NAME" "$tbl")

  # （c）期望结构：在 :memory: 会话里临时建表再取结构
  expected_sig=$(sqlite3 ":memory:" <<SQL |
${table_defs[$tbl]}
PRAGMA table_info($tbl);
SQL
  awk -F'|' '{printf "%s|%s|%s\n", $2, toupper($3), $6}')

  # （d）比较
  if [[ "$actual_sig" != "$expected_sig" ]]; then
    echo
    echo "⚠  表 $tbl 结构不匹配："
    diff --color=always <(echo "$expected_sig") <(echo "$actual_sig") || true
    read -rp "→ 删除并重建表 $tbl ? 这会导致数据丢失！ [y/N] " ans
    if [[ $ans =~ ^[Yy]$ ]]; then
      sqlite3 "$DB_NAME" "DROP TABLE IF EXISTS $tbl;"
      sqlite3 "$DB_NAME" "${table_defs[$tbl]}"
      echo "表 $tbl 已重建。"
    else
      echo "跳过表 $tbl 的重建。"
    fi
    echo
  fi
done


apikey=$(grep 'apikey' oqqwall.config | cut -d'=' -f2 | tr -d '"')
http_serv_port=$(grep 'http-serv-port' oqqwall.config | cut -d'=' -f2 | tr -d '"[:space:]')
process_waittime=$(grep 'process_waittime' oqqwall.config | cut -d'=' -f2 | tr -d '"')
manage_napcat_internal=$(grep 'manage_napcat_internal' oqqwall.config | cut -d'=' -f2 | tr -d '"')
max_attempts_qzone_autologin=$(grep 'max_attempts_qzone_autologin' oqqwall.config | cut -d'=' -f2 | tr -d '"')
at_unprived_sender=$(grep 'at_unprived_sender' oqqwall.config | cut -d'=' -f2 | tr -d '"')
text_model=$(grep 'text_model' oqqwall.config | cut -d'=' -f2 | tr -d '"')
vision_model=$(grep 'vision_model' oqqwall.config | cut -d'=' -f2 | tr -d '"')
vision_pixel_limit=$(grep 'vision_pixel_limit' oqqwall.config | cut -d'=' -f2 | tr -d '"')
vision_size_limit_mb=$(grep 'vision_size_limit_mb' oqqwall.config | cut -d'=' -f2 | tr -d '"')
force_chromium_no_sandbox=$(grep 'force_chromium_no-sandbox' oqqwall.config | cut -d'=' -f2 | tr -d '"')
use_web_review=$(grep 'use_web_review' oqqwall.config | cut -d'=' -f2 | tr -d '"')
web_review_port=$(grep 'web_review_port' oqqwall.config | cut -d'=' -f2 | tr -d '"')


DIR="./getmsgserv/rawpost/"

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
while read -r group; do
  echo "正在检查 group: $group"
  mangroupid=$(jq -r --arg group "$group" '.[$group].mangroupid' "$json_file")
  mainqqid=$(jq -r --arg group "$group" '.[$group].mainqqid' "$json_file")
  mainqq_http_port=$(jq -r --arg group "$group" '.[$group]["mainqq_http_port"]' "$json_file")
  
  # 检查 minorqqid 数组，处理 null 的情况
  minorqqids=$(jq -r --arg group "$group" '.[$group].minorqqid // [] | .[]' "$json_file")
  
  # 检查 minorqq_http_port 数组，处理 null 的情况
  minorqq_http_ports=$(jq -r --arg group "$group" '.[$group]["minorqq_http_port"] // [] | .[]' "$json_file")

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

  # 检查 minorqq_http_port 数组是否存在且每个元素是纯数字，且不能重复
  if [ -z "$minorqq_http_ports" ]; then
    errors+=("警告：在 $group 中，minorqq_http_port 为空。")
  else
    for minorport in $minorqq_http_ports; do
      if [[ ! "$minorport" =~ ^[0-9]+$ ]]; then
        errors+=("错误：在 $group 中，minorqq_http_port 包含非数字值：$minorport")
      else
        if [[ " ${http_ports_list[*]} " =~ " $minorport " ]]; then
          errors+=("错误：minorqq_http_port $minorport 在多个组中重复！")
        else
          http_ports_list+=("$minorport")
        fi
      fi
    done
  fi

  # 检查 minorqqid 和 minorqq_http_port 数量是否一致
  minorqq_count=$(jq -r --arg group "$group" '.[$group].minorqqid | length' "$json_file")
  minorqq_port_count=$(jq -r --arg group "$group" '.[$group]["minorqq_http_port"] | length' "$json_file")

  if [ "$minorqq_count" -ne "$minorqq_port_count" ]; then
    errors+=("错误：在 $group 中，minorqqid 的数量 ($minorqq_count) 与 minorqq_http_port 的数量 ($minorqq_port_count) 不匹配。")
  fi
  tbl_name="sendstorge_$group"
 
  # —— 杂项配置校验（允许为空）——
  max_post_stack=$(jq -r --arg group "$group" '.[$group].max_post_stack // empty' "$json_file")
  max_image_number_one_post=$(jq -r --arg group "$group" '.[$group].max_image_number_one_post // empty' "$json_file")
  friend_add_message=$(jq -r --arg group "$group" '.[$group].friend_add_message // empty' "$json_file")
  friend_add_message_type=$(jq -r --arg group "$group" '.[$group].friend_add_message | type' "$json_file")
  send_schedule_type=$(jq -r --arg group "$group" '.[$group].send_schedule | type' "$json_file")
  watermark_text=$(jq -r --arg group "$group" '.[$group].watermark_text // empty' "$json_file")
  watermark_text_type=$(jq -r --arg group "$group" '.[$group].watermark_text | type' "$json_file")
  
  # —— 校验 max_*：存在则必须为纯数字 ——
  if [[ -n "$max_post_stack" && ! "$max_post_stack" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，max_post_stack 存在但不是纯数字：$max_post_stack")
  fi
  if [[ -n "$max_image_number_one_post" && ! "$max_image_number_one_post" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，max_image_number_one_post 存在但不是纯数字：$max_image_number_one_post")
  fi

  # —— 校验 friend_add_message：可空；若存在必须为字符串 ——
  if [[ "$friend_add_message_type" != "null" && "$friend_add_message_type" != "string" ]]; then
    errors+=("错误：在 $group 中，friend_add_message 必须是字符串或为空（当前为 $friend_add_message_type）。")
  fi

  # —— 校验 watermark_text：可空；若存在必须为字符串 ——
  if [[ "$watermark_text_type" != "null" && "$watermark_text_type" != "string" ]]; then
    errors+=("错误：在 $group 中，watermark_text 必须是字符串或为空（当前为 $watermark_text_type）。")
  fi
  
  # —— 校验 send_schedule：可空；若存在必须为字符串数组，元素为 HH:MM ——
  if [[ "$send_schedule_type" != "null" ]]; then
    if [[ "$send_schedule_type" != "array" ]]; then
      errors+=("错误：在 $group 中，send_schedule 必须是数组（当前为 $send_schedule_type）。")
    else
      while IFS= read -r t; do
        # 允许 9:00 或 09:00；小时 0–23，分钟 00–59
        if [[ -n "$t" && ! "$t" =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]]; then
          errors+=("错误：在 $group 中，send_schedule 含非法时间：$t（应为 HH:MM，例如 09:00）")
        fi
      done < <(jq -r --arg group "$group" '.[$group].send_schedule[] // empty' "$json_file")
    fi
  fi

  # —— 校验 quick_replies：可空；若存在必须为对象，键值对为字符串 ——
  quick_replies_type=$(jq -r --arg group "$group" '.[$group].quick_replies | type' "$json_file")
  if [[ "$quick_replies_type" != "null" ]]; then
    if [[ "$quick_replies_type" != "object" ]]; then
      errors+=("错误：在 $group 中，quick_replies 必须是对象（当前为 $quick_replies_type）。")
    else
      # 检查每个快捷回复指令是否与审核指令冲突
      audit_commands=("是" "否" "匿" "等" "删" "拒" "立即" "刷新" "重渲染" "扩列审查" "评论" "回复" "展示" "拉黑")
      while IFS='|' read -r cmd_name cmd_content; do
        if [[ -n "$cmd_name" && -n "$cmd_content" ]]; then
          # 检查是否与审核指令冲突
          for audit_cmd in "${audit_commands[@]}"; do
            if [[ "$cmd_name" == "$audit_cmd" ]]; then
              errors+=("错误：在 $group 中，快捷回复指令 '$cmd_name' 与审核指令冲突。")
              break
            fi
          done
          
          # 检查指令名和内容是否为空
          if [[ -z "$cmd_name" ]]; then
            errors+=("错误：在 $group 中，快捷回复指令名不能为空。")
          fi
          if [[ -z "$cmd_content" ]]; then
            errors+=("错误：在 $group 中，快捷回复内容不能为空。")
          fi
        fi
      done < <(jq -r --arg group "$group" '.[$group].quick_replies | to_entries[] | .key + "|" + .value' "$json_file")
    fi
  fi
  # 定义期望结构 SQL
  expected_schema="CREATE TABLE $tbl_name(tag INT, num INT, port INT, senderid TEXT);"

  # 表是否存在
  if ! sqlite3 "$DB_NAME" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='$tbl_name';" | grep -q 1; then
    echo "表 $tbl_name 不存在，正在创建..."
    sqlite3 "$DB_NAME" "$expected_schema"
    continue
  fi

  # 实际结构
  actual_sig=$(sqlite3 "$DB_NAME" "PRAGMA table_info($tbl_name);" | \
    awk -F'|' '{printf "%s|%s|%s\n", $2, toupper($3), $6}')

  # 期望结构（用 :memory: 临时解析）
  expected_sig=$(sqlite3 ":memory:" <<SQL |
$expected_schema
PRAGMA table_info($tbl_name);
SQL
  awk -F'|' '{printf "%s|%s|%s\n", $2, toupper($3), $6}')

  if [[ "$actual_sig" != "$expected_sig" ]]; then
    echo
    echo "⚠  表 $tbl_name 结构不匹配："
    diff --color=always <(echo "$expected_sig") <(echo "$actual_sig") || true
    echo "正在删除并重建表 $tbl_name..."
    sqlite3 "$DB_NAME" "DROP TABLE IF EXISTS $tbl_name;"
    sqlite3 "$DB_NAME" "$expected_schema"
    echo "表 $tbl_name 已重建。"
    echo
  fi

done <<< "$(jq -r '. | keys[]' "$json_file")"

# 打印检查结果：区分“错误”和“警告”，仅在存在“错误”时退出
has_error=0
if [ ${#errors[@]} -ne 0 ]; then
  for msg in "${errors[@]}"; do
    if [[ "$msg" == 错误：* ]]; then
      has_error=1
      break
    fi
  done
fi

if [ $has_error -eq 1 ]; then
  echo "以下错误已被发现："
  for msg in "${errors[@]}"; do
    echo "$msg"
  done
  exit 1
else
  if [ ${#errors[@]} -ne 0 ]; then
    echo "发现以下警告："
    for msg in "${errors[@]}"; do
      # 只打印警告行
      if [[ "$msg" == 警告：* ]]; then
        echo "$msg"
      fi
    done
  else
    echo "账户组配置文件验证完成，没有发现错误。"
  fi
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
if pgrep -f "python3 getmsgserv/serv.py" > /dev/null
then
    echo "serv.py is already running"
else
    python3 getmsgserv/serv.py &
    echo "serv.py started"
fi

if pgrep -f "python3 SendQzone/qzone-serv-pipe.py" > /dev/null
then
    echo "qzone-serv-pipe.py is already running"
else
    if [[ $1 == --test ]]; then
      echo "请自行启动测试服务器"
    else
      python3 SendQzone/qzone-serv-pipe.py &
      echo "qzone-serv-pipe.py started"
    fi
fi

if pgrep -f "./Sendcontrol/sendcontrol.sh" > /dev/null
then
    echo "sendcontrol.sh is already running"
else
    ./Sendcontrol/sendcontrol.sh &
    echo "sendcontrol.sh started"
fi

# 启动网页审核（可选）
if [[ "$use_web_review" == "true" ]]; then
  if pgrep -f "python3 web_review/web_review.py" > /dev/null; then
    echo "web_review.py is already running"
  else
    echo "starting web_review on port $web_review_port"
    (cd web_review && PORT="$web_review_port" HOST="0.0.0.0" nohup python3 web_review.py --host 0.0.0.0 --port "$web_review_port" > web_review.log 2>&1 &)
    echo "web_review started at port $web_review_port"
  fi
else
  echo "use_web_review != true，跳过启动网页审核服务。"
fi


# Check if the OneBot server process is running
if [[ "$manage_napcat_internal" == "true" ]]; then
    if pgrep -f "xvfb-run -a qq --no-sandbox -q" > /dev/null; then
        pkill qq
    fi

    for qqid in "${runidlist[@]}"; do
        echo "Starting QQ process for ID: $qqid"
        nohup xvfb-run -a qq --no-sandbox -q "$qqid" > ./NapCatlog 2>&1 &
    done
    sleep 10
else
    echo "manage_napcat_internal != true，QQ相关进程未自动管理。请自行处理 Napcat QQ 客户端。"
fi

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
                python3 qqBot/likeeveryday.py $port
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
