#!/bin/bash
input="$1"
folder=./getmsgserv/post-step5/${input}
jsonfile=./getmsgserv/post-step2/${input}.json
rm -rf $folder
mkdir -p "$folder"
# 使用identify获取PDF页数
pages=$(identify -format "%n\n" ./getmsgserv/post-step4/${input}.pdf | head -n 1)
# 循环处理每一页
for ((i=0; i<$pages; i++)); do
    formatted_index=$(printf "%02d" $i)
    convert -density 360 -quality 90 ./getmsgserv/post-step4/${input}.pdf[$i] $folder/${input}-${formatted_index}.jpeg
done
existing_files=$(ls "$folder" | wc -l)
next_file_index=$existing_files
jq -r '.messages[].message[] | select(.type == "image" and .data.sub_type != 1) | .data.url' "$jsonfile" | while read -r url; do
    # 下载文件并命名
    formatted_index=$(printf "%02d" $next_file_index)
    curl -o "$folder/$input-${formatted_index}" "$url"
    # 增加文件索引
    next_file_index=$((next_file_index + 1))
done

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
