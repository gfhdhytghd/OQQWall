#!/bin/bash
tag="$1"

# Query the database
json_data=$(sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$tag';")
if [[ -z "$json_data" ]]; then
    echo "No data found for tag $tag"
    exit 1
fi

userid=$(sqlite3 'cache/OQQWall.db' "SELECT senderid FROM preprocess WHERE tag = '$tag';")
nickname=$(sqlite3 'cache/OQQWall.db' "SELECT nickname FROM preprocess WHERE tag = '$tag';")
userid_show=$userid
# Extract values
needpriv=$(echo "$json_data" | jq -r '.needpriv')
safemsg=$(echo "$json_data" | jq -r '.safemsg')

if [[ "$needpriv" == "true" && "$safemsg" == "true" ]]; then
    json_data=$(echo "$json_data" | jq '.sender.user_id=10000 | .sender.nickname="匿名"')
    nickname=匿名
    userid="10000"
    userid_show=""
fi

# Generate message_html
message_html=$(echo "$json_data" | jq -r '
    .messages[] |
    (
        .message |
        map(
            if .type == "text" then
                "<div>" + .data.text +"</div>"
            elif .type == "image" then
                "<img src=\"" + .data.url + "\" alt=\"Image\">"
            elif .type == "video" then
                "<video controls autoplay muted><source src=\"" +
                (if .data.file then "file://" + .data.file else .data.url end) +
                "\" type=\"video/mp4\">Your browser does not support the video tag.</video>"
            else ""
            end
        ) |
        join(" ") |
        gsub("\n"; "<br/>") 
    )
' )

# Generate HTML content with the script
html_content=$(cat <<EOF
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OQQWall消息页</title>
    <style>
        @page {
          margin: 0!important;
          margin-top: 0cm!important;
          margin-bottom: 0cm!important;
          margin-left: 0cm!important;
          margin-right: 0cm!important;
          size:4in 8in;
        }
        body {
            font-family: Arial, sans-serif;
            background-color: #f2f2f2;
            margin: 0;
            padding: 5px;
        }
        .container {
            width: 4in;
            margin: 0 auto;
            padding: 20px;
            border-radius: 10px;
            background-color: #f2f2f2;
            box-sizing: border-box;
        }
        .header {
            display: flex;
            align-items: center;
        }
        .header img {
            border-radius: 50%;
            width: 50px;
            height: 50px;
            margin-right: 10px;
            box-shadow: 0 0 10px rgba(0, 0, 0, 0.3);
        }
        .header-text {
            display: block;
        }
        .header h1 {
            font-size: 24px;
            margin: 0;
        }
        .header h2 {
            font-size: 12px;
            margin: 0;
        }
        .content {
            margin-top: 20px;
        }
        .content div{
            display: block;
            background-color: #ffffff;
            border-radius: 10px;
            padding: 7px;
            margin-bottom: 10px;
            word-break: break-word;
            max-width: fit-content;
            line-height: 1.5;
        }
        .cqface {
            vertical-align: middle; 
            width: 20px!important; 
            height: 20px!important;
            margin: 0 0 0 0px!important;
            display: inline!important;
            padding:0px!important;
            transform: translateY(-0.1em);
        }
        .content img, .content video {
            display: block;
            border-radius: 10px;
            padding: 0px;
            margin-top: 10px;
            margin-bottom: 10px;
            max-width: 50%;
            max-height: 300px; 
        }
        .content video {
            background-color: transparent;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="http://q.qlogo.cn/headimg_dl?dst_uin=${userid}&spec=640&img_type=jpg" alt="Profile Image">
            <div class="header-text">
                <h1>${nickname}</h1>
                <h2>${userid_show}</h2>
            </div>
        </div>
        <div class="content">
            ${message_html}
        </div>
    </div>

    <script>
        window.onload = function() {
            const container = document.querySelector('.container');
            const contentHeight = container.scrollHeight;
            const pageHeight4in = 364; // 4 inches in pixels (96px per inch)
        
            let pageSize = '';
        
            if (contentHeight <= pageHeight4in) {
                pageSize = '4in 4in'; // Use 4in x 4in if content fits
            } else if (contentHeight >= 2304){
                pageSize = '4in 24in'
            } else {
                const containerHeightInInches = (contentHeight / 96 + 0.1);
                pageSize = \`4in \${containerHeightInInches}in\`; // Set height to container's height
            }
        
            // Dynamically apply the @page size
            const style = document.createElement('style');
            style.innerHTML = \`
                @page {
                    size: \${pageSize};
                    margin: 0 !important;
                }
            \`;
            document.head.appendChild(style);
        };
    </script>
</body>
</html>
EOF
)

# Output HTML content
echo "$html_content"