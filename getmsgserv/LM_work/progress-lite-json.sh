#!/bin/bash
id="$1"
input="$2"
folder=./getmsgserv/post-step1/${input}
jsonfile=./getmsgserv/rawpost/${id}.json
output=./getmsgserv/post-step1/${input}.json
temp_json=./getmsgserv/post-step1/temp_${input}.json

# 创建目标文件夹
rm -rf "$folder"
mkdir -p "$folder"
pwd_path=$(pwd)

# 处理 JSON，删除不符合条件的类型，并合并 text 类型的数据
jq --arg pwd_path "$pwd_path" 'map(
       if .message then
        .message |= map(
          if .type == "face" then
            {
              type: "text",
              data: { 
                text: ("<img src=\"file://\($pwd_path)/getmsgserv/LM_work/face/s" + .data.id + ".png\" alt=\"cqface:" + .data.id + "\" class=\"cqface\">")
              }
            }
          else
            .
          end
        ) |
        .message |= map(select(.type == "text" or .type == "image" or .type == "video" )) |
        .message |= if all(.type == "text") then
                      [{data: {text: (map(.data.text) | join(""))}, type: "text"}]
                    else
                      .
                    end |
        select(.message | length > 0)
      else
        .
      end
    )' "$jsonfile" > "$temp_json"
# 判断是否有不符合要求的消息类型
has_irregular_types=$(jq '[.[] | select(.message != null) | .message[].type] | any(. != "text" and . != "image" and . != "video" and . != "face")' "$jsonfile")

# 获取当前工作目录
pwd_path=$(pwd)

# 从处理后的 JSON 文件中读取 URL，并下载文件，同时替换 URL 为本地路径
next_file_index=1
jq -c '.[] | select(.message != null) | .message[] | select(.type == "image")' "$temp_json" | while read -r image_item; do
    # 提取 URL
    url=$(echo "$image_item" | jq -r '.data.url')
    
    # 下载文件并命名
    local_file="$folder/$input-$next_file_index.png"

    # 检查文件是否已经存在
    if [ -f "$local_file" ]; then
        echo "文件 $local_file 已存在，跳过下载。"
    else
        curl -o "$local_file" "$url"

        # 使用 jq 替换 URL 为本地文件路径（file://$(pwd)/）
        jq --arg old_url "$url" --arg new_url "file://$pwd_path/getmsgserv/post-step1/${input}/$(basename "$local_file")" \
           'map(
              if .message then
                .message |= map(if .type == "image" and .data.url == $old_url then .data.url = $new_url else . end)
              else
                .
              end
            )' "$temp_json" > "$temp_json.tmp" && mv "$temp_json.tmp" "$temp_json"
    fi

    # 增加文件索引
    next_file_index=$((next_file_index + 1))
done

# 输出最终处理结果到指定文件
jq --arg notregular "$([ "$has_irregular_types" == "true" ] && echo "true" || echo "false")" \
   '{ sender: .[0].sender, notregular: $notregular, messages: map(select(.message != null)) }' "$temp_json" > "$output"
rm $temp_json