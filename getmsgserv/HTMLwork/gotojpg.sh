#!/bin/bash
input="$1"
folder=./getmsgserv/post-step5/${input}
jsonfile=./getmsgserv/post-step2/${input}.json
mkdir -p "$folder"
magick convert -density 320 -quality 95 ./getmsgserv/post-step4/${input}.pdf ./getmsgserv/post-step5/${input}/${input}.jpeg
existing_files=$(ls "$folder" | wc -l)
next_file_index=$existing_files
jq -r '.messages[].message[] | select(.type=="image") | .data.url' "$jsonfile" | while read -r url; do
    # 下载文件并命名
    curl -o "$folder/$input-$next_file_index" "$url"
    # 增加文件索引
    next_file_index=$((next_file_index + 1))
done