#!/bin/bash
set -euo pipefail

tag="$1"
qr_dir="$(pwd)/cache/qrcode/${tag}"
mkdir -p "$qr_dir"


# === DB Query ===
json_data=$(sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$tag';")
if [[ -z "$json_data" ]]; then
    echo "No data found for tag $tag"
    exit 1
fi

# === Generate QRs for every card jumpUrl ===
echo "$json_data" | jq -r '
  .messages[]
  | .message_id as $mid
  | .message[]?                # 每条子消息
  | select(.type=="json")
  | .data.data
  | try fromjson catch null
  | (
      if .view=="contact" then       .meta.contact.jumpUrl
      elif .view=="miniapp" then     (.meta.miniapp.jumpUrl // .meta.miniapp.doc_url)
      elif .view=="news"    then     .meta.news.jumpUrl
      else                            (.meta|to_entries[0].value.jumpUrl? // empty)
      end
    ) // empty
  | "\($mid)\t\(.)"
' | while IFS=$'\t' read -r mid url; do
        [[ -z "$url" ]] && continue
        qrencode "$url" -t PNG -o "$qr_dir/qr_${mid}.png" -m 0
done

userid=$(sqlite3 'cache/OQQWall.db' "SELECT senderid FROM preprocess WHERE tag = '$tag';")
nickname=$(sqlite3 'cache/OQQWall.db' "SELECT nickname FROM preprocess WHERE tag = '$tag';")
userid_show=$userid

# === Extract flags ===
needpriv=$(echo "$json_data" | jq -r '.needpriv')
safemsg=$(echo "$json_data" | jq -r '.safemsg')

# === Anonymize if needed ===
if [[ "$needpriv" == "true" ]]; then
    json_data=$(echo "$json_data" | jq '.sender.user_id=10000 | .sender.nickname="匿名"')
    nickname=匿名
    userid=10000
    userid_show=""
fi

# === Icon dir (all pngs) ===
icon_dir="file://$(pwd)/getmsgserv/HTMLwork/source"
poke_icon="file://$(pwd)/getmsgserv/LM_work/source/poke.png"

# === Build HTML for messages ===
message_html=$(echo "$json_data" | jq -r --arg base "$icon_dir" --arg poke "$poke_icon" --arg qr "$qr_dir" '
  def ext: (.data.file // "" | split(".") | last | ascii_downcase);
  def icon_from:
    (ext) as $e |
    if $e|test("^(doc|docx|odt)$") then "doc"
    elif $e|test("^(apk|ipa)$") then "apk"
    elif $e|test("^(dmg|iso)$") then "dmg"
    elif $e|test("^(ppt|pptx|key)$") then "ppt"
    elif $e|test("^(xls|xlsx|numbers)$") then "xls"
    elif $e|test("^(pages)$") then "pages"
    elif $e|test("^(ai|ps|sketch)$") then "ps"
    elif $e|test("^(ttf|otf|woff|woff2|font)$") then "font"
    elif $e|test("^(png|jpg|jpeg|gif|bmp|webp|image)$") then "image"
    elif $e|test("^(mp3|wav|flac|aac|ogg|audio)$") then "audio"
    elif $e|test("^(mp4|mkv|mov|avi|webm|video)$") then "video"
    elif $e|test("^(zip|7z)$") then "zip"
    elif $e|test("^(rar)$") then "rar"
    elif $e|test("^(pkg)$") then "pkg"
    elif $e|test("^(pdf)$") then "pdf"
    elif $e|test("^(exe|msi)$") then "exe"
    elif $e|test("^(sh|py|c|cpp|js|ts|go|rs|java|rb|php|lua|code)$") then "code"
    elif $e|test("^(txt|md|note)$") then "txt"
    else "unknown" end;

  .messages[] as $msg |
  $msg.message_id as $mid |
  ($msg.message | map(
    if .type == "text" then
      "<div class=\"bubble\">" + .data.text + "</div>"
    elif .type == "image" then
      "<img src=\"" + .data.url + "\" alt=\"Image\">"
    elif .type == "video" then
      "<div class=\"bubble\"><video controls autoplay muted><source src=\"" +
      (if .data.file then "file://" + .data.file else .data.url end) +
      "\" type=\"video/mp4\">Your browser does not support the video tag.</video></div>"
    elif .type == "poke" then
      "<img class=\"poke-icon\" src=\"" + $poke + "\" alt=\"Poke\">"
    elif .type == "file" then
      "<div class=\"file-block\">" +
      "<img class=\"file-icon\" src=\"" + $base + "/" + (icon_from) + ".png\" alt=\"File Icon\">" +
      "<div class=\"file-info\">" +
      "<a class=\"file-name\" href=\"file://" + (.data.file | @uri) + "\" download>" +
      (.data.file // "未命名文件") +
      "</a>" +
      (if .data.file_size then
        "<div class=\"file-meta\">" +
        (if (.data.file_size | tonumber) > 1048576 then
          ((.data.file_size | tonumber / 1048576) | tostring) + " MB"
        elif (.data.file_size | tonumber) > 1024 then
          ((.data.file_size | tonumber / 1024) | tostring) + " KB"
        else
          (.data.file_size | tostring) + " B"
        end) + "</div>"
      else "" end) +
      "</div></div>"
    elif .type == "json" then
      (.data.data | try fromjson catch null) as $J |
      if $J == null then ""
      elif ($J.view == "contact") and ($J.meta.contact?) then
        ($J.meta.contact) as $c |
        "<a class=\"card card-contact\" href=\"" + ($c.jumpUrl // "#") + "\" target=\"_blank\" rel=\"noopener noreferrer\">" +
         "<div class=\"card-media\">" +
           "<img src=\"" + ($c.avatar // "") + "\" alt=\"avatar\">" +
         "</div>" +
         "<div class=\"card-body\">" +
           "<div class=\"card-title\">" +
             (($c.nickname // "联系人") | @html) +
           "</div>" +
           (if $c.contact
            then "<div class=\"card-desc\">" + ($c.contact | @html) + "</div>"
             else ""
           end) +
         "</div>" +
           "<img class=\"qr-code\" src=\"file://" + $qr + "/qr_" + ($mid|tostring) + ".png\" alt=\"QR\">" +
       "</a>"
      elif ($J.view == "miniapp") and ($J.meta.miniapp?) then
        ($J.meta.miniapp) as $m |
        "<a class=\"card card-vertical card-miniapp\" href=\"" + (($m.jumpUrl // $m.doc_url // "#")) + "\" target=\"_blank\" rel=\"noopener noreferrer\">" +
        "<div class=\"card-header\">" +
          "<div class=\"card-header-left\">" +
            (if $m.source or $m.sourcelogo then
              "<div class=\"brand-inline\">" +
                (if $m.sourcelogo then "<img class=\"brand-icon\" src=\"" + $m.sourcelogo + "\" alt=\"\">" else "" end) +
                (if $m.source then "<span class=\"brand-text\">" + ($m.source | @html) + "</span>" else "" end) +
              "</div>"
            else "" end) +
            "<div class=\"card-title\">" + (($m.title // "小程序卡片") | @html) + "</div>" +
          "</div>" +
          "<img class=\"qr-code\" src=\"file://" + $qr + "/qr_" + ($mid|tostring) + ".png\" alt=\"QR\">" +
        "</div>" +
        (if $m.preview then "<div class=\"card-preview\"><img src=\"" + $m.preview + "\" alt=\"preview\"></div>" else "" end) +
        (if ($m.tag or $m.tagIcon) then
          "<div class=\"card-tag-row\">" +
          (if $m.tagIcon then "<img class=\"card-tag-icon\" src=\"" + $m.tagIcon + "\" alt=\"\">" else "" end) +
          (if $m.tag then "<span class=\"card-tag\">" + ($m.tag | @html) + "</span>" else "" end) +
          "</div>" else "" end) +
        "</a>"
      elif ($J.view == "news") and ($J.meta.news?) then
        ($J.meta.news) as $n |
        "<a class=\"card card-news\" href=\"" + ($n.jumpUrl // "#") + "\" target=\"_blank\" rel=\"noopener noreferrer\">" +
        "<div class=\"card-header\">" +
          "<div class=\"card-header-left\">" +
            "<div class=\"card-title\">" + (($n.title // "分享") | @html) + "</div>" +
          "</div>" +
          "<div class=\"card-header-right\">" +
            (if $n.preview then "<img class=\"thumb\" src=\"" + $n.preview + "\" alt=\"thumb\">" else "" end) +
          "</div>" +
        "</div>" +
        "<div class=\"card-header\">" +
          "<div class=\"card-header-left\">" +
            (if $n.desc then "<div class=\"card-desc\">" + ($n.desc | @html) + "</div>" else "" end) +
            (if ($n.tag or $n.tagIcon) then
              "<div class=\"card-tag-row\">" +
                (if $n.tagIcon then "<img class=\"card-tag-icon\" src=\"" + $n.tagIcon + "\" alt=\"\">" else "" end) +
                (if $n.tag then "<span class=\"card-tag\">" + ($n.tag | @html) + "</span>" else "" end) +
              "</div>"
            else "" end) +
          "</div>" +
          "<img class=\"qr-code\" src=\"file://" + $qr + "/qr_" + ($mid|tostring) + ".png\" alt=\"QR\">" +
        "</div>" +
        "</a>"
      else
        ($J.meta // {}) as $meta |
        ($meta | to_entries[0].value // {}) as $g |
        "<div class=\"card card-vertical\">" +
        (if $g.preview then "<div class=\"card-preview\"><img src=\"" + $g.preview + "\" alt=\"preview\"></div>" else "" end) +
        "<div class=\"card-body\">" +
        "<div class=\"card-title\">" + (($g.title // $J.prompt // ($J.view // "卡片")) | @html) + "</div>" +
        (if $g.desc then "<div class=\"card-desc\">" + ($g.desc | @html) + "</div>" else "" end) +
        "<div class=\"qr-wrap\"><img class=\"qr-code\" src=\"file://" + $qr + "/qr_" + ($mid|tostring) + ".png\" alt=\"QR\"></div>" +
        "</div></div>"
      end
    else "" end
  ) | join(" "))')


# === Build final HTML ===
html_content=$(cat <<EOF
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OQQWall消息页</title>
    <style>
        @page {
            margin: 0 !important;
            size: 4in 8in;
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

        .bubble {
            display: block;
            background-color: #ffffff;
            border-radius: 10px;
            padding: 7px;
            margin-bottom: 10px;
            word-break: break-word;
            max-width: fit-content;
            line-height: 1.5;
        }

        .content img:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon),
        .content video:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon) {
            display: block;
            border-radius: 10px;
            padding: 0px;
            margin-bottom: 10px;
            max-width: 50%;
            max-height: 300px;
        }

        .content video {
            background-color: transparent;
        }

        .cqface {
            vertical-align: middle;
            width: 20px !important;
            height: 20px !important;
            margin: 0 !important;
            display: inline !important;
            padding: 0 !important;
            transform: translateY(-0.1em);
        }

        .file-block {
            display: flex !important;
            flex-direction: row-reverse;
            /* icon 在右 */
            align-items: flex-start;
            background-color: #ffffff;
            border-radius: 10px;
            padding: 7px;
            margin-bottom: 10px;
            align-items: stretch;
            gap: 6px;
            line-height: 1.4;
            word-break: break-all;
            width: fit-content;
            max-width: 100%;
        }

        .file-icon {
            width: 40px !important;
            height: 40px !important;
            flex: 0 0 40px;
            margin: 0 !important;
            padding: 0 !important;
            border-radius: 0px !important;
            object-fit: contain;
        }

        .file-info {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            justify-content: center;
            justify-content: space-between;
            /* 顶部放文件名，底部放 meta */
            min-height: 40px;
            /* 与 .file-icon 高度一致，保证能“贴底” */
        }

        .file-name {
            font-size: 14px;
            flex: 1 1 auto;
            display: inline-block;
            line-height: 1.3;
            align-self: flex-start;
            color: #000000;
            text-decoration: none;
        }

        .file-name:hover {
            text-decoration: underline;
        }

        .file-meta {

            font-size: 11px;
            color: #888;
            margin: 0px 0px 1px 1px;
            line-height: 1;
            align-self: flex-start;
            /* 调整为靠左下角 */
        }

        /* === Card (JSON message) === */
        .card {
            display: block;
            background-color: #ffffff;
            border-radius: 10px;
            padding: 8px;
            margin-bottom: 10px;
            text-decoration: none;
            color: #000000;
            box-sizing: border-box;
            width: fit-content;
            max-width: 70%;
        }

        .card:hover {
            text-decoration: none;
        }

        .card-contact {
            /* 联系人卡片：横向布局 */
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* 覆盖 .content img 的全局约束，避免被 50% 宽等影响 */
        .card img:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon) {
            max-width: 100% !important;
            margin-top: 6px;
            padding: 0 !important;
        }

        /* 头像/小缩略图 */
        .card-media img {
            width: 48px !important;
            height: 48px !important;
            border-radius: 8px !important;
            margin: 0 !important;
            object-fit: cover;
            display: block;
        }

        /* 纵向卡片（文档/新闻等）：上图下文 */
        .card-vertical .card-preview img {
            width: 100% !important;
            height: auto !important;
            object-fit: cover;
            border-radius: 0px !important;
            display: block;
            margin: 0px !important;
        }

        .card-body {
            margin-top: 6px;
        }

        .card-title {
            font-size: 14px;
            font-weight: 600;
            line-height: 1.3;
            margin-bottom: 4px;
        }

        .card-desc {
            font-size: 12px;
            color: #666;
            margin-top: 4px;
            line-height: 1.4;
        }

        .card-tag-row {
            display: flex;
            align-items: center;
            gap: 4px;
            margin-top: 6px;
            font-size: 11px;
            color: #888;
        }

        .card-tag-icon {
            width: 14px !important;
            height: 14px !important;
            border-radius: 3px !important;
            object-fit: contain;
            margin: 0 !important;
        }

        /* Tag 文本样式 */
        .card-tag {
            font-size: 11px;
            color: #888;
            line-height: 1;
        }

        /* === New: QQ official-like header layout === */
        .card-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 8px;
            margin-bottom: 6px;
        }

        .card-header-left {
            min-width: 0;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .brand-inline {
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .brand-inline .brand-icon {
            width: 12px !important;
            height: 12px !important;
            border-radius: 0px !important;
            object-fit: contain;
            margin: 0 !important;
        }

        .brand-inline .brand-text {
            font-size: 12px;
            color: #666;
        }

        .card-header-right {
            display: flex;
            align-items: flex-start;
            gap: 8px;
        }

        .card-header-right .thumb {
            width: 64px !important;
            height: 64px !important;
            border-radius: 4px !important;
            margin: 0 !important;
            object-fit: cover;
        }

        .qr-code {
            width: 48px !important;
            height: 48px !important;
            border-radius: 0px !important;
            margin: 0px !important;
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
            const pageHeight4in = 364; // 4 inches = 96px * 4

            let pageSize = '';
            if (contentHeight <= pageHeight4in) {
                pageSize = '4in 4in';
            } else if (contentHeight >= 2304) {
                pageSize = '4in 24in';
            } else {
                const containerHeightInInches = (contentHeight / 96 + 0.1).toFixed(2);
                pageSize = '4in ' + containerHeightInInches + 'in';
            }

            const style = document.createElement('style');
            style.innerHTML = '@page { size: ' + pageSize + '; margin: 0 !important; }';
            document.head.appendChild(style);
        };
    </script>
</body>
</html>
EOF
)

# === Output ===
echo "$html_content"

