#!/bin/bash
# 让脚本在出错和未绑定变量时退出
# set -euo pipefail
# set -x


#####################################
#            基本变量               #
#####################################
tag="${1:?用法: $0 <tag>}"
folder="cache/picture/${tag}"
db_file="cache/OQQWall.db"
pwd_path="$(pwd)"   # 项目根目录或网页根目录
napcat_api="127.0.0.1:$2"
container_name="napcat"  # Docker 容器名，用于 docker cp

#####################################
#           基础函数定义            #
#####################################

create_folder() {
    mkdir -p "$folder"
}

fetch_sender_info() {
    sqlite3 "$db_file" "SELECT senderid, receiver, ACgroup FROM preprocess WHERE tag='$tag';"
}

fetch_rawmsg() {
    local senderid="$1"
    local receiver="$2"
    sqlite3 "$db_file" "SELECT rawmsg FROM sender WHERE senderid='$senderid' AND receiver='$receiver';"
}

has_reply() {
  local rawmsg="$1"
  jq -e '
    if type=="array" then
      any(.[]; (.message // []) | any(.type=="reply"))
    elif type=="object" then
      (.message // []) | any(.type=="reply")
    else
      false
    end
  ' <<<"$rawmsg" >/dev/null && echo true || echo false
}


# 初步处理 JSON
process_json() {
    local rawmsg="$1"
    jq \
      --arg pwd_path "$pwd_path" \
      --arg has_reply "$has_reply_flag" \
      --slurpfile hist_idx "$hist_idx_file" '
      # HTML 转义
      def esc: gsub("&";"&amp;") | gsub("<";"&lt;") | gsub(">";"&gt;");
      
      # 预览文本（用于 reply 展开）
      def preview($m):
        (($m.message // [])
          | map(
              if .type=="text" then .data.text
              elif .type=="face" then "[表情]"
              elif .type=="image" then "[图片]"
              elif .type=="json" then  "[卡片]"
              elif .type=="file" then  "[文件]"
              elif .type=="poke" then  "[戳一戳]"
              else ""
              end
            )
          | join("")
          | gsub("\\s+";" ") )[0:80];

      ($has_reply == "true") as $HR
      | (if type=="array" then . else [.] end) as $all
      | (if $HR then ($all | INDEX((.message_id|tostring))) else {} end) as $curr_idx
      | $all
      | map(
          if .message then
            .message |= map(
              if .type == "face" then
                {
                  type: "text",
                  data: {
                    text: ("<img src=\"file://\($pwd_path)/getmsgserv/LM_work/face/" + .data.id + ".png\" class=\"cqface\">")
                  }
                }
              elif .type == "reply" then
                (
                  (.data.id|tostring) as $rid
                  | ($hist_idx[0][$rid] // $curr_idx[$rid]) as $ref
                  | if $ref then
                      ( ($ref.time? // null) as $ts
                        | (if $ts then ($ts|tonumber|localtime|strftime("%H:%M")) else "--:--" end)
                      ) as $tm
                      | {
                          type: "text",
                          data: {
                            text:
                              ("<div class=\"reply\" data-mid=\"" + $rid + "\">" +
                                  "<div class=\"reply-meta\">" + $tm + "</div>" +
                                  "<div class=\"reply-body\">" + (preview($ref) | esc) + "</div>" +
                               "</div>")
                          }
                        }
                    else
                      {
                        type: "text",
                        data: {
                          text:
                            ("<div class=\"reply missing\" data-mid=\"" + $rid + "\">" +
                                "<div class=\"reply-meta\">--:--</div>" +
                                "<div class=\"reply-body\">引用的消息已丢失或不可用 (ID: " + $rid + ")</div>" +
                             "</div>")
                        }
                      }
                    end
                )
              else
                .
              end
            )
            | .message |= map(select(.type == "text" or .type == "image" or .type == "video" or .type == "file" or .type == "poke" or .type == "json"))
            | .message |= if (length > 0 and all(.type=="text")) then
                            [{data: {text: (map(.data.text) | join(""))}, type: "text"}]
                          else . end
            | select(.message | length > 0)
          else
            .
          end
        )' <<<"$rawmsg"
}



# 判断原始 rawmsg 中是否含有不规则类型（不包含 file，因为后面会转）
check_irregular_types() {
  local rawmsg="$1"
  jq -r '
    # 收集所有段的类型（没有 message 的视为空数组）
    [ .[]? | (.message // [])[]? | .type ] as $types
    # 只要存在一个不在白名单内的类型，就返回 "true"
    | ( any($types[]; . != "text"
                    and . != "image"
                    and . != "video"
                    and . != "face"
                    and . != "file"
                    and . != "poke"
                    and . != "json"
                    and . != "reply")
        | if . then "true" else "false" end )' \
  <<<"$rawmsg" 2>/dev/null || echo "false"
}


# 将所有 file（图片扩展名）调用 NapCat /get_file 转换为 image
resolve_file_urls() {
    local json="$1"
    local updated_json="$json"

    while read -r file_item; do
        file_id=$(jq -r '.data.file_id // empty' <<<"$file_item")
        file_name=$(jq -r '.data.file    // empty' <<<"$file_item")

        [[ -z "$file_id" ]] && continue
        if [[ "$file_name" =~ \.(png|jpe?g|gif|bmp|webp)$ ]]; then
            real_path=$(curl -s "http://$napcat_api/get_file?file_id=$file_id" | jq -r '.data.url // empty')
            [[ -z "$real_path" ]] && continue

            # 构造 file:// URL
            if [[ "$real_path" = /* ]]; then
                new_url="file://$real_path"
            else
                new_url="file://$pwd_path/$real_path"
            fi

            # 替换 JSON：file -> image，加 url/sub_type
            updated_json=$(jq --arg id "$file_id" --arg url "$new_url" '
              map(
                if .message then
                  .message |= map(
                    if .type=="file" and (.data.file_id // "")==$id then
                      .type = "image" |
                      .data.url = $url |
                      .data.sub_type = 0
                    else
                      .
                    end
                  )
                else
                  .
                end
              )' <<<"$updated_json")
        fi
    done < <(jq -c '.[] | select(.message!=null) | .message[] | select(.type=="file")' <<<"$json")

    echo "$updated_json"
}

# 下载/复制 image：对 file:// 路径，如果是容器内部 (/app 开头)，使用 docker cp；否则常规 cp 或 curl
download_and_replace_images() {
  local processed_json="$1"
  local next_file_index=1
  local updated_json="$processed_json"

  while read -r image_item; do
    url=$(jq -r '.data.url // empty' <<<"$image_item")
    [[ -z "$url" ]] && continue

    local_file="$folder/$tag-$next_file_index.png"

    if [[ "$url" =~ ^file:// ]]; then
      src_path="${url#file://}"
      if [[ "$src_path" == /app* ]]; then
        # 容器内部路径，用 docker cp
        docker cp "$container_name:$src_path" "$local_file" || true
      else
        # 宿主机本地文件
        [[ -f "$src_path" ]] && cp -f "$src_path" "$local_file"
      fi
    else
      # 远程 http/https
      curl -s -o "$local_file" "$url" || true
    fi

    # 尝试设置权限，失败跳过
    [[ -f "$local_file" ]] && chmod 666 "$local_file" || true

    # 替换 JSON URL 为本地 cache 路径（存在则替换）
    if [[ -f "$local_file" ]]; then
      updated_json=$(jq \
        --arg old_url "$url" \
        --arg new_url "file://$pwd_path/cache/picture/${tag}/$(basename "$local_file")" \
        'map(
          if .message then
          .message |= map(
            if .type == "image" and .data.url == $old_url then
            .data.url = $new_url
            else
            .
            end
          )
          else
          .
          end
        )' <<<"$updated_json")
    fi

    next_file_index=$((next_file_index + 1))
  done < <(jq -c '.[] | select(.message!=null) | .message[] | select(.type=="image")' <<<"$processed_json")

  echo "$updated_json"
}

# 输出最终 JSON
output_final_json() {
    local processed_json="$1"
    local has_irregular_types="$2"

    jq --arg notregular "$([ "$has_irregular_types" == "true" ] && echo "true" || echo "false")" \
       '{ notregular: $notregular, messages: map(select(.message != null)) }' <<<"$processed_json"
}

#####################################
#              主流程               #
#####################################

create_folder

query_result=$(fetch_sender_info)
senderid=$(cut -d '|' -f 1 <<<"$query_result")
receiver=$(cut -d '|' -f 2 <<<"$query_result")

if [[ -z "$senderid" || -z "$receiver" ]]; then
    echo "No senderid or receiver found for tag=$tag. Operation aborted." >&2
    exit 1
fi

rawmsg=$(fetch_rawmsg "$senderid" "$receiver")
if [[ -z "$rawmsg" ]]; then
    echo "No rawmsg found for senderid=$senderid and receiver=$receiver. Operation aborted." >&2
    exit 1
fi

# === 仅当存在 reply 时才构建历史索引（限制在文件末尾 N 行）===
has_reply_flag=$(has_reply "$rawmsg")

history_file="getmsgserv/all/priv_post.json"
HIST_TAIL_LINES=20000

# 临时文件：窗口数组（最后 N 行里抽到的完整顶层对象）
hist_window_file="$(mktemp)"
# 临时文件：索引（message_id -> 对象）
hist_idx_file="$(mktemp)"
trap 'rm -f "$hist_window_file" "$hist_idx_file"' EXIT

if [[ "$has_reply_flag" == "true" && -f "$history_file" ]]; then
  # 用 Python 从最后 N 行中抽取“完整的顶层对象”，重组成一个小数组
  python3 - "$history_file" "$HIST_TAIL_LINES" > "$hist_window_file" <<'PY'
import sys, json
from collections import deque

path = sys.argv[1]
n = int(sys.argv[2])

# 取末尾 n 行
dq = deque(maxlen=n)
with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        dq.append(line)
s = ''.join(dq)

# 在“外层数组（depth_arr>=1）”内，抓取每个完整的顶层对象 { ... } 片段
out = []
depth_obj = 0
depth_arr = 0
in_str = False
esc = False
start = None

for i, ch in enumerate(s):
    if in_str:
        if esc:
            esc = False
        elif ch == '\\':
            esc = True
        elif ch == '"':
            in_str = False
        continue

    if ch == '"':
        in_str = True
    elif ch == '[':
        depth_arr += 1
    elif ch == ']':
        depth_arr = max(0, depth_arr - 1)
    elif ch == '{':
        # 仅当处于外层数组里，且这是一个新对象的开始时，记录起点
        if depth_obj == 0 and depth_arr >= 1 and start is None:
            start = i
        depth_obj += 1
    elif ch == '}':
        depth_obj -= 1
        if depth_obj == 0 and start is not None and depth_arr >= 1:
            frag = s[start:i+1]
            try:
                out.append(json.loads(frag))
            except Exception:
                pass
            start = None

# 输出一个小数组（只含最后 n 行内能完整取到的顶层消息对象）
json.dump(out, sys.stdout, ensure_ascii=False)
PY

  # 基于窗口数组建索引
  jq 'INDEX((.message_id|tostring))' "$hist_window_file" > "$hist_idx_file" 2>/dev/null \
    || echo '{}' > "$hist_idx_file"
else
  echo '{}' > "$hist_idx_file"
fi


processed_json=$(process_json "$rawmsg")
has_irregular_types=$(check_irregular_types "$rawmsg")
processed_json=$(resolve_file_urls "$processed_json")
processed_json=$(download_and_replace_images "$processed_json")
output_final_json "$processed_json" "$has_irregular_types"
