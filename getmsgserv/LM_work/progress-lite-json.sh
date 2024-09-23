#!/bin/bash

# Variables
tag="$1"
folder="cache/picture/${tag}"
db_file="cache/OQQWall.db"
pwd_path=$(pwd)
temp_json="temp_json_file.json"

# Function to create folder
create_folder() {
    mkdir -p "$folder"
}

# Function to fetch senderid, receiver, and ACgroup from the database
fetch_sender_info() {
    sqlite3 "$db_file" "SELECT senderid, receiver, ACgroup FROM preprocess WHERE tag='$tag';"
}

# Function to fetch rawmsg using senderid
fetch_rawmsg() {
    local senderid="$1"
    sqlite3 "$db_file" "SELECT rawmsg FROM sender WHERE senderid='$senderid';"
}

# Function to process rawmsg JSON
process_json() {
    local rawmsg="$1"
    echo "$rawmsg" | jq --arg pwd_path "$pwd_path" 'map(
        if .message then
          .message |= map(
            if .type == "face" then
              {
                type: "text",
                data: { 
                  text: ("<img src=\"file://\($pwd_path)/getmsgserv/LM_work/face/" + .data.id + ".png\"class=\"cqface\">")
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
    )'
}

# Function to check if there are irregular types
check_irregular_types() {
    local rawmsg="$1"
    echo "$rawmsg" | jq '[.[] | select(.message != null) | .message[].type] | any(. != "text" and . != "image" and . != "video" and . != "face")'
}

# Function to download images and replace URLs
download_and_replace_images() {
    local processed_json="$1"
    local next_file_index=1

    # Redirect the input into the while loop to avoid subshell
    while read -r image_item; do
        url=$(echo "$image_item" | jq -r '.data.url')
        local_file="$folder/$tag-$next_file_index.png"

        if [ ! -f "$local_file" ]; then
            curl -s -o "$local_file" "$url"
        fi

        # Replace URL in JSON
        processed_json=$(echo "$processed_json" | jq --arg old_url "$url" \
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
            )')
        
        next_file_index=$((next_file_index + 1))
    done < <(echo "$processed_json" | jq -c '.[] | select(.message != null) | .message[] | select(.type == "image")')

    echo "$processed_json"
}



# Function to output final JSON with the notregular flag
output_final_json() {
    local processed_json="$1"
    local has_irregular_types="$2"

    echo "$processed_json" | jq --arg notregular "$([ "$has_irregular_types" == "true" ] && echo "true" || echo "false")" \
        '{ notregular: $notregular, messages: map(select(.message != null)) }'
}

# Main script flow
create_folder

query_result=$(fetch_sender_info)

senderid=$(echo "$query_result" | cut -d '|' -f 1)
if [ -z "$senderid" ]; then
    echo "No senderid found for tag=$tag. Operation aborted."
    exit 1
fi

rawmsg=$(fetch_rawmsg "$senderid")
senderid=$(echo "$query_result" | cut -d '|' -f 1)
if [ -z "$rawmsg" ]; then
    echo "No rawmsg found for senderid=$senderid. Operation aborted."
    exit 1
fi

# Process JSON and handle errors
processed_json=$(process_json "$rawmsg")
has_irregular_types=$(check_irregular_types "$rawmsg")
# Download images and replace URLs in JSON
processed_json=$(download_and_replace_images "$processed_json")

# Output final JSON
output_final_json "$processed_json"
