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
                      ( (($ref.time? // null) as $ts
                          | (if $ts then ($ts|tonumber|localtime|strftime("%H:%M")) else "--:--" end)) ) as $tm
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
            | .message |= map(select(.type == "text" or .type == "image" or .type == "video" or .type == "file" or .type == "poke" or .type == "json" or .type == "forward"))
            | .message |= if (length > 0 and all(.type=="text")) then
                            [{data: {text: (map(.data.text) | join(""))}, type: "text"}]
                          else . end
            | select(.message | length > 0)
          else
            .
          end
        )' <<<"$rawmsg"
}

# 递归合并任意层级（含 forward）中「仅包含 text 的 message」为单段
merge_texts_recursively() {
  local json="$1"
  jq '
    def mrg:
      if (.message? and (.message | type) == "array" and (.message | length > 0) and (.message | all(.type=="text")))
      then .message = [{type:"text", data:{text: (.message | map(.data.text) | join(""))}}]
      else .
      end;

    def walk(f):
      . as $in
      | if type=="object" then (f | with_entries(.value |= walk(f)))
        elif type=="array" then map(walk(f))
        else .
        end;
    walk(mrg)
  ' <<<"$json"
}

# 递归折叠相邻的 text 段（即便同一 message 中含有图片/文件等混合类型，也会把连续的 text 合并）
merge_adjacent_texts_recursively() {
  local json="$1"
  jq '
    def fold_text_runs:
      reduce .[] as $x (
        [];
        if ($x.type=="text") and ((.[length-1]? // null) | .type == "text") then
          .[length-1].data.text = ((.[length-1].data.text // "") + ($x.data.text // ""))
        else
          . + [ $x ]
        end
      );

    def walk(f):
      . as $in
      | if type=="object" then (f | with_entries(.value |= walk(f)))
        elif type=="array" then map(walk(f))
        else .
        end;

    walk(
      if (.message? and (.message|type)=="array" and (.message|length)>0) then
        .message = (.message | fold_text_runs)
      else . end)
  ' <<<"$json"
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
                    and . != "forward"
                    and . != "reply")
        | if . then "true" else "false" end )' \
  <<<"$rawmsg" 2>/dev/null || echo "false"
}

# 展开合并转发：用 /get_forward_msg 的结果把 forward 段替换为若干普通段
# 展开合并转发：拉取 /get_forward_msg，把 forward 段的 .data 替换为接口返回的 .data
# 递归/迭代充实 forward：保持 type=forward，只替换 .data（并保留原 id）
resolve_forward_messages() {
  local json="$1"
  local updated="$json"
  local MAX_DEPTH=4

  # 已处理过的 id 集合，避免重复请求
  declare -A seen=()

  for ((depth=1; depth<=MAX_DEPTH; depth++)); do
    # 抓取当前 JSON 中所有深度的 forward id（字符串化去重）
    mapfile -t ids < <(jq -r '
      (if type=="array" then . else [.] end)
      | .. | objects
      | select(.type? == "forward" and (.data.id?))
      | (.data.id | tostring)
    ' <<<"$updated" | sort -u)

    # 统计这一轮是否有新增替换
    local replaced_any=false

    for fid in "${ids[@]}"; do
      # 跳过已处理 id
      [[ -n "${seen[$fid]+x}" ]] && continue

      # 拉取 forward 详情
      local resp payload
      resp="$(curl -s "http://$napcat_api/get_forward_msg?message_id=${fid}")" || true
      [[ -z "$resp" ]] && continue
      [[ "$(jq -r '.status // empty' <<<"$resp")" != "ok" ]] && continue

      payload="$(jq '.data' <<<"$resp")"
      [[ -z "$payload" ]] && continue

      # 深度替换：在整棵树中把匹配该 fid 的 .data 替换为 payload，并保留原始 id
      updated="$(jq --arg fid "$fid" --argjson payload "$payload" '
        def fill:
          if type=="object" then
            ( if (.type?=="forward" and (.data.id|tostring)==$fid)
              then (.data.id) as $old | .data = ($payload + {id:$old})
              else .
              end )
            | with_entries(.value |= fill)
          elif type=="array" then
            map(fill)
          else
            .
          end;
        (if type=="array" then . else [.] end) | fill
      ' <<<"$updated")"

      seen["$fid"]=1
      replaced_any=true
    done

    # 这一层没有新替换就提前结束
    [[ "$replaced_any" == "true" ]] || break
  done

  echo "$updated"
}

# 将所有 file（图片扩展名）调用 NapCat /get_file 转换为 image —— 递归处理（含 forward 内）
resolve_file_urls() {
  local json="$1"
  local updated_json="$json"

  # 去重处理过的 file_id，避免重复请求
  declare -A seen_ids=()

  # 递归找出所有含 file_id 的 file 段
  while read -r file_item; do
    file_id=$(jq -r '.data.file_id // empty' <<<"$file_item")
    [[ -z "$file_id" ]] && continue
    [[ -n "${seen_ids[$file_id]+x}" ]] && continue

    # 请求 napcat 获取真实路径与文件名
    resp="$(curl -s "http://$napcat_api/get_file?file_id=$file_id")" || true
    [[ -z "$resp" ]] && continue
    [[ "$(jq -r '.status // empty' <<<"$resp")" != "ok" ]] && continue

    real_path="$(jq -r '.data.url // empty' <<<"$resp")"
    file_name_api="$(jq -r '.data.file_name // empty' <<<"$resp")"
    [[ -z "$real_path" ]] && continue

    # 判断是否图片扩展名（优先用 API 的 file_name）
    name_to_check="${file_name_api}"
    [[ -z "$name_to_check" ]] && name_to_check="$(jq -r '.data.file // empty' <<<"$file_item")"

    if [[ ! "$name_to_check" =~ \.(png|jpe?g|gif|bmp|webp)$ ]]; then
      # 非图片则跳过转换
      seen_ids["$file_id"]=1
      continue
    fi

    # 构造 file:// URL
    if [[ "$real_path" = /* ]]; then
      new_url="file://$real_path"
    else
      new_url="file://$pwd_path/$real_path"
    fi

    # 递归替换：任何深度的 file 节点，只要 file_id 匹配就改成 image
    updated_json=$(
      jq --arg id "$file_id" --arg url "$new_url" '
        def upd:
          if type=="object" then
            ( if (.type?=="file" and (.data.file_id // "")==$id)
              then .type="image" | .data.url=$url | .data.sub_type=(.data.sub_type // 0)
              else .
              end )
            | with_entries(.value |= upd)
          elif type=="array" then
            map(upd)
          else . end;
        (if type=="array" then . else [.] end) | upd
      ' <<<"$updated_json"
    )

    seen_ids["$file_id"]=1
  done < <(jq -c '
      (if type=="array" then . else [.] end)
      | .. | objects
      | select(.type?=="file" and (.data.file_id?))
    ' <<<"$updated_json")

  echo "$updated_json"
}

# 下载/复制 image：对 file:// 路径，如果是容器内部 (/app 开头)，使用 docker cp；否则常规 cp 或 curl
# 下载/复制 image：递归处理任意深度（含 forward 内）
download_and_replace_images() {
  local processed_json="$1"
  local next_file_index=1
  local updated_json="$processed_json"

  # 去重已下载过的 URL，避免重复下载
  declare -A seen_urls=()

  # 递归枚举所有 image 段
  while read -r image_item; do
    url=$(jq -r '.data.url // empty' <<<"$image_item")
    [[ -z "$url" ]] && continue
    [[ -n "${seen_urls[$url]+x}" ]] && continue

    local_file="$folder/$tag-$next_file_index.png"

    # 检查是否已经存在本地文件
    if [[ -f "$local_file" ]]; then
      # 如果已存在，直接使用现有文件
      final_file="$local_file"
    else
      # 下载原始文件
      if [[ "$url" =~ ^file:// ]]; then
        src_path="${url#file://}"
        if [[ "$src_path" == /app* ]]; then
          docker cp "$container_name:$src_path" "$local_file" || true
        else
          [[ -f "$src_path" ]] && cp -f "$src_path" "$local_file"
        fi
      else
        curl -s -o "$local_file" "$url" || true
      fi

      [[ -f "$local_file" ]] && chmod 666 "$local_file" || true
      final_file="$local_file"
    fi

    if [[ -f "$final_file" ]]; then
      updated_json=$(
        jq \
          --arg old_url "$url" \
          --arg new_url "file://$pwd_path/cache/picture/${tag}/$(basename "$final_file")" '
          def upd:
            if type=="object" then
              ( if .type?=="image" and (.data.url // "")==$old_url
                then .data.url=$new_url
                else .
                end )
              | with_entries(.value |= upd)
            elif type=="array" then
              map(upd)
            else . end;
          (if type=="array" then . else [.] end) | upd
        ' <<<"$updated_json"
      )
    fi

    seen_urls["$url"]=1
    next_file_index=$((next_file_index + 1))
  done < <(jq -c '
      (if type=="array" then . else [.] end)
      | .. | objects
      | select(.type?=="image" and (.data.url?))
    ' <<<"$processed_json")

  echo "$updated_json"
}

# 下载/复制 video：对 file:// 路径，如果是容器内部 (/app 开头)，使用 docker cp；否则常规 cp 或 curl
# 下载/复制 video：递归处理任意深度（含 forward 内），并转换为 H.264 格式
download_and_replace_videos() {
  local processed_json="$1"
  local next_file_index=1
  local updated_json="$processed_json"

  # 去重已下载过的 URL，避免重复下载
  declare -A seen_urls=()

  # 递归枚举所有 video 段
  while read -r video_item; do
    url=$(jq -r '.data.url // empty' <<<"$video_item")
    [[ -z "$url" ]] && continue
    [[ -n "${seen_urls[$url]+x}" ]] && continue

    # 获取原始文件名或使用默认扩展名
    original_file=$(jq -r '.data.file // empty' <<<"$video_item")
    if [[ -n "$original_file" ]]; then
      # 提取文件扩展名
      extension="${original_file##*.}"
      if [[ "$extension" == "$original_file" ]]; then
        # 没有扩展名，使用默认的 mp4
        extension="mp4"
      fi
    else
      extension="mp4"
    fi

    local_file="$folder/$tag-$next_file_index.$extension"
    h264_file="$folder/$tag-$next_file_index-h264.mp4"

    # 检查是否已经存在转换后的 H.264 文件
    if [[ -f "$h264_file" ]]; then
      # 如果已存在，直接使用现有文件
      final_file="$h264_file"
    else
      # 下载原始文件
      if [[ "$url" =~ ^file:// ]]; then
        src_path="${url#file://}"
        if [[ "$src_path" == /app* ]]; then
          docker cp "$container_name:$src_path" "$local_file" || true
        else
          [[ -f "$src_path" ]] && cp -f "$src_path" "$local_file"
        fi
      else
        curl -s -o "$local_file" "$url" || true
      fi

      [[ -f "$local_file" ]] && chmod 666 "$local_file" || true

      # 转换为 H.264 格式
      if [[ -f "$local_file" ]]; then
        # 使用 ffmpeg 转换为 H.264，保持原始分辨率，使用较高质量的设置
        ffmpeg -i "$local_file" -c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k -movflags +faststart "$h264_file" -y 2>/dev/null || true
        
        # 如果转换成功，删除原始文件并设置最终文件
        if [[ -f "$h264_file" ]]; then
          rm -f "$local_file"
          final_file="$h264_file"
          chmod 666 "$final_file"
        else
          # 转换失败，使用原始文件
          final_file="$local_file"
        fi
      else
        final_file="$local_file"
      fi
    fi

    if [[ -f "$final_file" ]]; then
      updated_json=$(
        jq \
          --arg old_url "$url" \
          --arg new_url "file://$pwd_path/cache/picture/${tag}/$(basename "$final_file")" '
          def upd:
            if type=="object" then
              ( if .type?=="video" and (.data.url // "")==$old_url
                then .data.url=$new_url
                else .
                end )
              | with_entries(.value |= upd)
            elif type=="array" then
              map(upd)
            else . end;
          (if type=="array" then . else [.] end) | upd
        ' <<<"$updated_json"
      )
    fi

    seen_urls["$url"]=1
    next_file_index=$((next_file_index + 1))
  done < <(jq -c '
      (if type=="array" then . else [.] end)
      | .. | objects
      | select(.type?=="video" and (.data.url?))
    ' <<<"$processed_json")

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

rawmsg=$(resolve_forward_messages "$rawmsg")

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
# 在所有层级（含 forward.data 内部）合并仅包含 text 的 message
processed_json=$(merge_texts_recursively "$processed_json")
# 合并相邻的 text 片段（对所有层级生效）
processed_json=$(merge_adjacent_texts_recursively "$processed_json")

has_irregular_types=$(check_irregular_types "$rawmsg")
processed_json=$(resolve_file_urls "$processed_json")
processed_json=$(download_and_replace_images "$processed_json")
processed_json=$(download_and_replace_videos "$processed_json")
output_final_json "$processed_json" "$has_irregular_types"
