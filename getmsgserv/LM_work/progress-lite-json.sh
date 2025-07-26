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

# 初步处理 JSON
process_json() {
    local rawmsg="$1"
    jq --arg pwd_path "$pwd_path" '
      map(
        if .message then
          .message |= map(
            if .type == "face" then
              {
                type: "text",
                data: {
                  text: ("<img src=\"file://\($pwd_path)/getmsgserv/LM_work/face/" + .data.id + ".png\" class=\"cqface\">")
                }
              }
            else
              .
            end
          )
          | .message |= map(select(.type == "text" or .type == "image" or .type == "video" or .type == "file"  or .type == "poke" or .type == "json"))
          | .message |= if (length > 0 and all(.type=="text")) then
                          [{data: {text: (map(.data.text) | join(""))}, type: "text"}]
                        else
                          .
                        end
          | select(.message | length > 0)
        else
          .
        end
      )' <<<"$rawmsg"
}

# 判断原始 rawmsg 中是否含有不规则类型（不包含 file，因为后面会转）
check_irregular_types() {
    local rawmsg="$1"
    jq '[.[] | select(.message != null) | .message[].type] | any(. != "text" and . != "image" and . != "video" and . != "face" and . != "file" and . != "poke" and . != "json")' <<<"$rawmsg"
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

processed_json=$(process_json "$rawmsg")
has_irregular_types=$(check_irregular_types "$rawmsg")
processed_json=$(resolve_file_urls "$processed_json")
processed_json=$(download_and_replace_images "$processed_json")
output_final_json "$processed_json" "$has_irregular_types"
