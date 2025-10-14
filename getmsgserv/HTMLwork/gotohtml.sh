#!/bin/bash
set -euo pipefail
# 放在 set -euo pipefail 之后
DEBUG=${DEBUG:-0}
log(){ if [[ "$DEBUG" == "1" ]]; then echo "[DEBUG] $*" >&2; fi }
[[ "$DEBUG" == "1" ]] && set -x

tag="$1"
qr_dir="$(pwd)/cache/qrcode/${tag}"
mkdir -p "$qr_dir"



# === DB Query ===
json_data=$(sqlite3 'cache/OQQWall.db' "SELECT AfterLM FROM preprocess WHERE tag = '$tag';")
if [[ -z "$json_data" ]]; then
    echo "No data found for tag $tag"
    exit 1
fi
[[ "$DEBUG" == "1" ]] && printf '%s\n' "$json_data" > "./cache/debug_${tag}_AfterLM.json" && log "Saved ./cache/debug_${tag}_AfterLM.json"

# get watermark_text
json_file="./AcountGroupcfg.json"
groupname=$(timeout 10s sqlite3 'cache/OQQWall.db' "SELECT ACgroup FROM preprocess WHERE tag = '$tag';")
# 取到第一个非空字符串；若都没有则输出为空
watermark_text=$(jq -r --arg g "$groupname" '
  [ .[$g].watermark_text, .[$g].watermark, .MethGroup.watermark ]
  | map(select(type=="string" and length>0))
  | .[0] // empty
' "$json_file")

# 为了在 JS 里安全插入字符串（避免引号/换行把脚本弄坏），准备一个 JSON 编码版本
wm_js=$(jq -n --arg t "$watermark_text" '$t')


# === Generate QRs for every card jumpUrl (support nested forward) ===
echo "$json_data" | jq -r --arg DBG "$DEBUG" '
  # 调试
  def d($x):
  if $DBG=="1"
  then (. as $in | $x | debug | $in)  # 打印 $x，但继续返回 $in（也就是原来的 .）
  else .
  end;

  # 统一求卡片跳转 URL
  def card_url:
    . as $J |
    if ($J.view=="contact") and ($J.meta.contact?) then
      ($J.meta.contact) as $c |
      (
        ( $c.jumpUrl | (try capture("uin=(?<uin>[0-9]+)").uin catch null) )
        // ( $c.contact | (try capture("(?<uin>[0-9]{5,})").uin catch null) )
      ) as $uin
      | if $uin then "https://mp.qzone.qq.com/u/\($uin)" else empty end
    elif ($J.view=="miniapp") and ($J.meta.miniapp?) then
      ($J.meta.miniapp.jumpUrl // $J.meta.miniapp.doc_url)
    elif ($J.view=="news") and ($J.meta.news?) then
      $J.meta.news.jumpUrl
    else
      (($J.meta // {}) | (try to_entries catch []) | .[0]? | .value? | .jumpUrl? // empty)
    end;

  # 输出一行： key(文件名) \t url
  def out($k; $u): if $u then "\($k)\t\($u)" else empty end;

  # 递归抽取：$key 是“当前这条消息（或其子项）用于命名文件的 id”
  def qr_from_item($key):
    if .type? == "json" then
      (.data.data
        | gsub("&#44;"; ",")
        | gsub("\\\\/"; "/")
        | try fromjson catch null
      ) as $J
      | if $J then
          ($J | card_url) as $u
          | d("QR key=\($key) url=\($u // "")")
          | out($key; $u)
        else
          d("skip key=\($key) invalid JSON card")
          | empty
        end

    elif .type? == "forward" then
      # 对每个被转发项，优先使用子项的 message_id 作为 key
      (.data.messages // .data.content // [])[]? as $f
      | ($f.message_id // $key) as $k
      | $f.message[]? | qr_from_item($k)

    elif (.message? | type) == "array" then
      # 兼容：整条 OneBot 消息对象（没有 type，但里面有 message[]）
      .message[]? | qr_from_item(.message_id // $key)

    else
      empty
    end;


  # 顶层遍历
  .messages[]? as $msg
  | $msg.message_id as $mid
  | $msg.message[]?
  | qr_from_item($mid)
' | while IFS=$'\t' read -r key url; do
  [[ -z "$url" ]] && continue
  log "qrencode key=${key} url=${url}"
  command -v qrencode >/dev/null || { echo "qrencode 未安装"; exit 1; }
  qrencode "$url" -t PNG -o "$qr_dir/qr_${key}.png" -m 0 \
    || { log "qrencode failed key=${key}"; exit 1; }
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

rotate='`rotate(-${angle}deg)` '
# === Build HTML for messages (with recursive forward rendering) ===
message_html=$(echo "$json_data" | jq -r \
  --arg base "$icon_dir" --arg poke "$poke_icon" --arg qr "$qr_dir" --arg DBG "$DEBUG" '
  # === helpers ===
  def ext: (.data.file // "" | split(".") | last | ascii_downcase);
  def d($x):
    if $DBG=="1"
    then (. as $in | $x | debug | $in)  # 打印 $x，但继续返回 $in（也就是原来的 .）
    else .
    end;

  def icon_from:
    (ext) as $e |
    if     $e|test("^(doc|docx|odt)$")               then "doc"
    elif   $e|test("^(apk|ipa)$")                    then "apk"
    elif   $e|test("^(dmg|iso)$")                    then "dmg"
    elif   $e|test("^(ppt|pptx|key)$")               then "ppt"
    elif   $e|test("^(xls|xlsx|numbers)$")           then "xls"
    elif   $e|test("^(pages)$")                      then "pages"
    elif   $e|test("^(ai|ps|sketch)$")               then "ps"
    elif   $e|test("^(ttf|otf|woff2?|font)$")        then "font"
    elif   $e|test("^(png|jpg|jpeg|gif|bmp|webp)$")  then "image"
    elif   $e|test("^(mp3|wav|flac|aac|ogg)$")       then "audio"
    elif   $e|test("^(mp4|mkv|mov|avi|webm)$")       then "video"
    elif   $e|test("^(zip|7z)$")                     then "zip"
    elif   $e|test("^(rar)$")                        then "rar"
    elif   $e|test("^(pkg)$")                        then "pkg"
    elif   $e|test("^(pdf)$")                        then "pdf"
    elif   $e|test("^(exe|msi)$")                    then "exe"
    elif   $e|test("^(sh|py|c|cpp|js|ts|go|rs|java|rb|php|lua|code)$") then "code"
    elif   $e|test("^(txt|md|note)$")                then "txt"
    else "unknown" end;

  # 依据 JSON 卡片结构解析跳转 URL（供 QR）
  def card_url:
    . as $J |
    if ($J.view=="contact") and ($J.meta.contact?) then
      ($J.meta.contact) as $c |
      (
        ( $c.jumpUrl | (try capture("uin=(?<uin>[0-9]+)").uin catch null) )
        // ( $c.contact | (try capture("(?<uin>[0-9]{5,})").uin catch null) )
      ) as $uin
      | if $uin then "https://mp.qzone.qq.com/u/\($uin)" else empty end
    elif ($J.view=="miniapp") and ($J.meta.miniapp?) then
      ($J.meta.miniapp.jumpUrl // $J.meta.miniapp.doc_url)
    elif ($J.view=="news") and ($J.meta.news?) then
      $J.meta.news.jumpUrl
    else
      (($J.meta // {}) | (try to_entries catch []) | .[0]? | .value? | .jumpUrl? // empty)
    end;

  # === renderer ===
  def render($mid):
    if .type == "text" then
      "<div class=\"bubble\">" + (.data.text | gsub("\n"; "<br>")) + "</div>"

    elif .type == "image" then
      "<img src=\"" + .data.url + "\" alt=\"Image\">"

    elif .type == "video" then
      "<video controls autoplay muted><source src=\"" +
      ((.data.url // .data.file // "") | tostring) +
      "\" type=\"video/mp4\">Your browser does not support the video tag.</video>"

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
               end) +
            "</div>"
          else "" end) +
        "</div>" +
      "</div>"

    elif .type == "json" then
      # 先规范化并解析卡片 JSON
      (.data.data
        | gsub("&#44;"; ",")
        | gsub("\\\\/"; "/")
        | try fromjson catch null
      ) as $J
      | if $J == null then
          ""
        else
          ($J|card_url) as $u
          | d({render:"key", val:$mid})
          | d({render:"url", val:($u // "")})
          | if ($J.view == "contact") and ($J.meta.contact?) then
              ($J.meta.contact) as $c |
              "<a class=\"card card-contact\" href=\"" + ($c.jumpUrl // "#") + "\" target=\"_blank\" rel=\"noopener noreferrer\">" +
                "<div class=\"card-media\">" +
                  "<img src=\"" + ($c.avatar // "") + "\" alt=\"avatar\">" +
                "</div>" +
                "<div class=\"card-body\">" +
                  "<div class=\"card-title\">" + (($c.nickname // "联系人") | @html) + "</div>" +
                  (if $c.contact then "<div class=\"card-desc\">" + ($c.contact | @html) + "</div>" else "" end) +
                  (if $c.tag or $c.tagIcon then
                      (if $c.tag then "<span class=\"card-tag\">" + ($c.tag | @html) + "</span>" else "" end) 
                  else "" end) +
                "</div>" +
                (if $u then "<img class=\"qr-code\" src=\"file://" + $qr + "/qr_" + ($mid|tostring) + ".png\" alt=\"QR\">" else "" end) +
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
                  (if $u then "<img class=\"qr-code\" src=\"file://" + $qr + "/qr_" + ($mid|tostring) + ".png\" alt=\"QR\">" else "" end) +
                "</div>" +
                (if $m.preview then "<div class=\"card-preview\"><img src=\"" + $m.preview + "\" alt=\"preview\"></div>" else "" end) +
                (if ($m.tag or $m.tagIcon) then
                  "<div class=\"card-tag-row\">" +
                    (if $m.tagIcon then "<img class=\"card-tag-icon\" src=\"" + $m.tagIcon + "\" alt=\"\">" else "" end) +
                    (if $m.tag then "<span class=\"card-tag\">" + ($m.tag | @html) + "</span>" else "" end) +
                  "</div>"
                else "" end) +
              "</a>"

            elif ($J.view == "news") and ($J.meta.news?) then
              ($J.meta.news) as $n |
              "<a class=\"card card-news\" href=\"" + ($n.jumpUrl // "#") + "\" target=\"_blank\" rel=\"noopener noreferrer\">" +
                "<div class=\"card-header\">" +
                  (if $n.preview then "<img class=\"thumb\" src=\"" + $n.preview + "\" alt=\"thumb\">" else "" end) +
                  "<div class=\"card-header-right\">" +
                    "<div class=\"card-title\">" + (($n.title // "分享") | @html) + "</div>" +
                  "</div>" +
                  (if $u then "<img class=\"qr-code\" src=\"file://" + $qr + "/qr_" + ($mid|tostring) + ".png\" alt=\"QR\">" else "" end) +
                "</div>" +
                "<div class=\"card-bottom\">" +
                  "<div class=\"card-bottom-left\">" +
                    (if $n.desc then "<div class=\"card-desc\">" + ($n.desc | @html) + "</div>" else "" end) +
                    (if ($n.tag or $n.tagIcon) then
                      "<div class=\"card-tag-row\">" +
                        (if $n.tagIcon then "<img class=\"card-tag-icon\" src=\"" + $n.tagIcon + "\" alt=\"\">" else "" end) +
                        (if $n.tag then "<span class=\"card-tag\">" + ($n.tag | @html) + "</span>" else "" end) +
                      "</div>"
                    else "" end) +
                  "</div>" +
                "</div>" +
              "</a>"

            else
              ($J.meta // {}) as $meta
              | ($meta | to_entries | .[0]? | .value? // {}) as $g
              | "<div class=\"card card-vertical\">" +
                  (if $g.preview then "<div class=\"card-preview\"><img src=\"" + $g.preview + "\" alt=\"preview\"></div>" else "" end) +
                  "<div class=\"card-body\">" +
                    "<div class=\"card-title\">" + (($g.title // $J.prompt // ($J.view // "卡片")) | @html) + "</div>" +
                    (if $g.desc then "<div class=\"card-desc\">" + ($g.desc | @html) + "</div>" else "" end) +
                    (if $u then "<div class=\"qr-wrap\"><img class=\"qr-code\" src=\"file://" + $qr + "/qr_" + ($mid|tostring) + ".png\" alt=\"QR\"></div>" else "" end) +
                  "</div>" +
                "</div>"
            end
        end

    elif .type == "forward" then
      # 支持 .data.messages（群转发）与 .data.content（私聊转发）
      (.data.messages // .data.content // []) as $list |
      "<div class=\"forward-title\">合并转发聊天记录</div>" +
      "<div class=\"forward\">" +
        ( $list
          | map(
              . as $one
              | ($one.message_id // $mid) as $kid
              | "<div class=\"forward-item\">" +
                ( $one.message | map( render($kid) ) | join(" ") ) +
                "</div>"
            )
          | join("")
        ) +
      "</div>"

    else "" end
  ;


  # 顶层展开
  .messages[] as $msg
  | $msg.message_id as $mid
  | ($msg.message | map(render($mid)) | join(" "))
')



# === Build final HTML ===
html_content=$(cat <<EOF
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OQQWall消息页</title>
    <style>
        /* CSS变量定义 */
        :root {
            /* 颜色系统 */
            --primary-color: #007aff;
            --secondary-color: #71a1cc;
            --background-color: #f2f2f2;
            --card-background: #ffffff;
            --text-primary: #000000;
            --text-secondary: #666666;
            --text-muted: #888888;
            --border-color: #e0e0e0;
            
            /* 间距系统 */
            --spacing-xs: 4px;
            --spacing-sm: 6px;
            --spacing-md: 8px;
            --spacing-lg: 10px;
            --spacing-xl: 12px;
            --spacing-xxl: 20px;
            
            /* 圆角系统 */
            --radius-sm: 4px;
            --radius-md: 8px;
            --radius-lg: 12px;
            
            /* 阴影系统 */
            --shadow-sm: 0 0 5px rgba(0, 0, 0, 0.1);
            --shadow-md: 0px 0px 6px rgba(0, 0, 0, 0.2);
            --shadow-lg: 0 0 10px rgba(0, 0, 0, 0.3);
            
            /* 字体系统 */
            --font-family: "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
            --font-size-xs: 11px;
            --font-size-sm: 12px;
            --font-size-md: 14px;
            --font-size-lg: 24px;
            
            /* 布局尺寸 */
            --container-width: 4in;
            --avatar-size: 50px;
            --qr-size: 48px;
            --file-icon-size: 40px;
            --card-max-width: 276px;
        }

        /* 重置和基础样式 */
        * {
            box-sizing: border-box;
        }

        @page {
            margin: 0 !important;
            size: 4in 8in;
        }

        body {
            font-family: var(--font-family);
            background-color: var(--background-color);
            margin: 0;
            padding: 5px;
            line-height: 1.5;
        }

        /* 容器布局 */
        .container {
            width: var(--container-width);
            margin: 0 auto;
            padding: var(--spacing-xxl);
            border-radius: var(--radius-lg);
            background-color: var(--background-color);
            position: relative;
        }

        /* 头部样式 */
        .header {
            display: flex;
            align-items: center;
            gap: var(--spacing-lg);
        }

        .header img {
            border-radius: 50%;
            width: var(--avatar-size);
            height: var(--avatar-size);
            box-shadow: var(--shadow-lg);
            flex-shrink: 0;
        }

        .header-text {
            display: block;
            flex: 1;
        }

        .header h1 {
            font-size: var(--font-size-lg);
            margin: 0;
            font-weight: 600;
        }

        .header h2 {
            font-size: var(--font-size-sm);
            margin: 0;
            color: var(--text-secondary);
        }

        /* 内容区域 */
        .content {
            margin-top: var(--spacing-xxl);
        }

        /* 通用消息样式 */
        .bubble {
            display: block;
            background-color: var(--card-background);
            border-radius: var(--radius-lg);
            padding: 4px 8px;
            margin-bottom: var(--spacing-lg);
            word-break: break-word;
            max-width: fit-content;
            box-shadow: var(--shadow-sm);
            line-height: 1.5;
        }

        /* 媒体元素样式 */
        .content img:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon):not(.bubble):not(.cqface):not(.file-icon):not(.card-preview),
        .content video:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon) {
            display: block;
            border-radius: var(--radius-lg);
            margin-bottom: var(--spacing-lg);
            max-width: 50%;
            max-height: 300px;
            box-shadow: var(--shadow-md);
            background-color: transparent;
        }

        /* QQ表情样式 */
        .cqface {
            vertical-align: middle;
            width: 20px !important;
            height: 20px !important;
            margin: 0 !important;
            display: inline !important;
            padding: 0 !important;
            transform: translateY(-0.1em);
        }

        /* 文件块样式 */
        .file-block {
            display: flex !important;
            flex-direction: row-reverse;
            align-items: flex-start;
            background-color: var(--card-background);
            border-radius: var(--radius-lg);
            padding: 7px;
            margin-bottom: var(--spacing-lg);
            gap: var(--spacing-sm);
            line-height: 1.4;
            word-break: break-all;
            width: fit-content;
            max-width: 100%;
            box-shadow: var(--shadow-sm);
        }

        .file-icon {
            width: var(--file-icon-size) !important;
            height: var(--file-icon-size) !important;
            flex: 0 0 var(--file-icon-size);
            margin: 0 !important;
            padding: 0 !important;
            border-radius: 0px !important;
            object-fit: contain;
        }

        .file-info {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            justify-content: space-between;
            min-height: var(--file-icon-size);
            flex: 1;
        }

        .file-name {
            font-size: var(--font-size-md);
            line-height: 1.3;
            color: var(--text-primary);
            text-decoration: none;
            word-break: break-word;
        }

        .file-name:hover {
            text-decoration: underline;
        }

        .file-meta {
            font-size: var(--font-size-xs);
            color: var(--text-muted);
            margin: 0px 0px 1px 1px;
            line-height: 1;
        }

        /* 卡片样式系统 */
        .card {
            display: block;
            background-color: var(--card-background);
            border-radius: var(--radius-lg);
            padding: var(--spacing-md);
            margin-bottom: var(--spacing-lg);
            text-decoration: none;
            color: var(--text-primary);
            width: fit-content;
            max-width: var(--card-max-width);
            box-shadow: var(--shadow-sm);
            transition: box-shadow 0.2s ease;
        }

        .card:hover {
            text-decoration: none;
            box-shadow: var(--shadow-md);
        }

        /* 联系人卡片 */
        .card-contact {
            display: flex;
            align-items: center;
            gap: var(--spacing-md);
        }

        /* 卡片媒体元素 */
        .card img:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon) {
            max-width: 100% !important;
            margin-top: var(--spacing-sm);
            padding: 0 !important;
            box-shadow: none !important;
        }

        .card-media img {
            width: var(--qr-size) !important;
            height: var(--qr-size) !important;
            border-radius: var(--radius-sm) !important;
            margin: 0 !important;
            object-fit: cover;
            display: block;
        }

        /* 纵向卡片 */
        .card-vertical .card-preview img {
            width: 100% !important;
            height: auto !important;
            object-fit: cover;
            border-radius: 0px !important;
            display: block;
            margin: 0px !important;
        }

        .card-body {
            margin-top: 0px;
            display: flex;
            flex-direction: column;
        }

        .card-title {
            font-size: var(--font-size-md);
            font-weight: 600;
            line-height: 1.3;
            margin: 0;
        }

        .card-desc {
            font-size: var(--font-size-sm);
            color: var(--text-secondary);
            line-height: 1.2;
            margin: 0;
        }

        /* 卡片标签 */
        .card-tag-row {
            display: flex;
            align-items: center;
            gap: var(--spacing-xs);
            margin-top: var(--spacing-sm);
            font-size: var(--font-size-xs);
            color: var(--text-muted);
        }

        .card-tag-icon {
            width: 14px !important;
            height: 14px !important;
            border-radius: 3px !important;
            object-fit: contain;
            margin: 0 !important;
        }

        .card-tag {
            display: block;
            font-size: var(--font-size-xs);
            color: var(--text-muted);
            line-height: 1;
        }

        /* 卡片头部布局 */
        .card-header {
            display: flex;
            align-items: center;
            justify-content: flex-start;
            gap: var(--spacing-md);
            margin-bottom: var(--spacing-sm);
        }

        .card-header-left {
            min-width: 0;
            display: flex;
            flex-direction: column;
            gap: var(--spacing-sm);
            flex: 1;
        }

        .card-bottom {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: var(--spacing-md);
            padding-top: 4px;
        }

        .card-bottom-left {
            min-width: 0;
            display: flex;
            flex-direction: column;
            gap: var(--spacing-xs);
        }

        /* 品牌信息 */
        .brand-inline {
            display: inline-flex;
            align-items: center;
            gap: var(--spacing-sm);
        }

        .brand-inline .brand-icon {
            width: 12px !important;
            height: 12px !important;
            border-radius: 0px !important;
            object-fit: contain;
            margin: 0 !important;
        }

        .brand-inline .brand-text {
            font-size: var(--font-size-sm);
            color: var(--text-secondary);
        }

        .card-header-right {
            display: flex;
            align-items: flex-start;
            gap: var(--spacing-md);
            flex: 1;
            min-width: 0;
        }

        .card-header .thumb {
            width: var(--qr-size) !important;
            height: var(--qr-size) !important;
            border-radius: var(--radius-sm) !important;
            margin: 0 !important;
            object-fit: cover;
        }

        /* 二维码样式 */
        .qr-code {
            width: var(--qr-size) !important;
            height: var(--qr-size) !important;
            border-radius: 0px !important;
            margin: 0px !important;
            margin-left: auto !important;
            flex: 0 0 var(--qr-size);
        }

        /* 回复样式 */
        .reply {
            border-left: 3px solid var(--border-color);
            background: #fafafa;
            border-radius: var(--radius-sm);
            padding: var(--spacing-sm) var(--spacing-md);
            margin-bottom: var(--spacing-xs);
        }

        .reply .reply-meta {
            font-size: 0.85em;
            color: var(--text-secondary);
            margin-bottom: 2px;
        }

        .reply .reply-body {
            white-space: pre-wrap;
            color: #333;
        }

        /* 转发样式 */
        .forward {
            display: inline-block;
            border-left: 3px solid var(--secondary-color);
            padding-left: var(--spacing-lg);
            padding-bottom: 0px;
            margin: 0 0 var(--spacing-lg) 0;
            border-radius: 0px;
        }

        .forward-title {
            font-size: var(--font-size-sm);
            color: var(--text-secondary);
            margin: 0px 0 var(--spacing-xs) 0;
        }

        .forward-item {
            margin: var(--spacing-sm) 0 var(--spacing-sm) var(--spacing-xs);
        }

        .forward .forward {
            margin-left: var(--spacing-sm);
        }

        /* 纵向卡片特殊布局 */
        .card.card-vertical {
            width: 100%;
            max-width: var(--card-max-width);
        }

        .card.card-vertical .card-header {
            width: 100%;
            display: flex;
            align-items: center;
            gap: var(--spacing-md);
        }

        .card.card-vertical .card-header-left {
            flex: 1;
            min-width: 0;
        }

        .card.card-vertical .card-header-left .card-title {
            margin: 0;
            white-space: normal;
            overflow: hidden;
            display: -webkit-box;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 2;
            line-clamp: 2;
            word-break: break-word;
        }

        /* 水印样式 */
        .wm-overlay {
            position: absolute;
            inset: 0;
            pointer-events: none;
            z-index: 999;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }

        .wm-item {
            position: absolute;
            white-space: nowrap;
            user-select: none;
            font-family: var(--font-family);
            font-weight: 500;
            color: rgba(0, 0, 0, 1);
            text-shadow: 0 0 1px rgba(255, 255, 255, 0.25), 0 0 1px rgba(255, 255, 255, 0.25);
            transform: rotate(-24deg);
            line-height: 1;
            mix-blend-mode: multiply;
        }

        @media print {
            .wm-item {
                mix-blend-mode: normal;
            }
        }

        /* 响应式优化 */
        @media (max-width: 400px) {
            .container {
                width: 100%;
                padding: var(--spacing-lg);
            }
            
            .content img:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon):not(.bubble):not(.cqface):not(.file-icon):not(.card-preview),
            .content video:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon) {
                max-width: 100%;
            }
            
            .card {
                max-width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="https://qlogo2.store.qq.com/qzone/${userid}/${userid}/640" alt="Profile Image">
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
        window.onload = function () {
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
            const wmText = /*bash*/ ${wm_js};
            if (typeof wmText === 'string' && wmText.trim() !== '') {
              addWatermark({
                text: wmText,
                // 4in 宽(≈384px)推荐默认——更小更克制
                opacity: 0.12,
                angle: 24,
                fontSize: 40,   // ← 从 56~64 降到 36~44 更合适
                tile: 480,      // ← 间距也相应减小，避免密度太大
                jitter: 10
              });
            }

            function addWatermark(opts) {
                const container = document.querySelector('.container');

                // 创建覆盖层
                let overlay = container.querySelector('.wm-overlay');
                if (!overlay) {
                    overlay = document.createElement('div');
                    overlay.className = 'wm-overlay';
                    container.appendChild(overlay);
                } else {
                    overlay.innerHTML = ''; // 重新渲染时清空
                }

                // 严格使用容器的可视尺寸，避免对文档布局产生任何影响
                const W = container.clientWidth;
                const H = container.scrollHeight;     // 高度按内容
                overlay.style.width = W + 'px';
                overlay.style.height = H + 'px';
                const text = String(opts.text);
                const opacity = (typeof opts.opacity === 'number') ? opts.opacity : 0.12;
                const angle = Number.isFinite(opts.angle) ? opts.angle : 24;
                const fontSize = Number.isFinite(opts.fontSize) ? opts.fontSize : 40;
                const tile = Number.isFinite(opts.tile) ? opts.tile : 480;
                const jitter = Number.isFinite(opts.jitter) ? opts.jitter : 10;

                // 先创建一个隐藏样本元素，量出旋转后的包围盒尺寸，便于“限界”布点
                const probe = document.createElement('span');
                probe.className = 'wm-item';
                probe.textContent = text;
                probe.style.fontSize = fontSize + 'px';
                probe.style.opacity = opacity.toString();
                probe.style.transform = ${rotate};
                probe.style.visibility = 'hidden';
                probe.style.left = '-9999px';
                probe.style.top = '-9999px';
                overlay.appendChild(probe);
                const rect = probe.getBoundingClientRect();
                const stampW = rect.width;
                const stampH = rect.height;
                overlay.removeChild(probe);

                // 计算网格：仅在容器内布点，保证任何抖动后也不会越界
                const padX = Math.ceil(stampW * 0.5);
                const padY = Math.ceil(stampH * 0.5);
                const startX = padX;
                const endX = Math.max(padX, W - padX);
                const startY = padY;
                const endY = Math.max(padY, H - padY);

                // 列/行数量
                // …前面保持不变：测出 stampW, stampH，计算 padX/padY …

                // 只在可用宽度内估算列数
                const cols = Math.max(1, Math.floor((W - 2*padX) / tile) + 1);
                // 高度同理
                const rows = Math.max(1, Math.floor((H - 2*padY) / tile) + 1);

                // —— 水平居中 ——
                // 以“水印中心点”计算：第一列的中心点在容器中心的左侧 gridSpan/2 处
                const centerX = W / 2;
                const gridSpanX = (cols - 1) * tile;
                const firstCX = centerX - gridSpanX / 2;

                // （可选）垂直也居中：否则就从 padY 顶部开始
                const centerVertical = false; // 想竖向也居中改成 true
                const baseCY0 = centerVertical ? (H/2 - ((rows - 1) * tile) / 2) : (padY + stampH/2);

                for (let r = 0; r < rows; r++) {
                  for (let c = 0; c < cols; c++) {
                    const span = document.createElement('span');
                    span.className = 'wm-item';
                    span.textContent = text;
                    span.style.fontSize = fontSize + 'px';
                    span.style.opacity  = opacity.toString();
                    span.style.transform = ${rotate};

                    // 交错排布（可选，让视觉更满）
                    const stagger = (r % 2) ? tile / 2 : 0;

                    // 以“中心点”定位
                    const cx = firstCX + c * tile + stagger;
                    const cy = baseCY0 + r * tile;

                    // 轻微抖动
                    const jx = jitter ? (Math.random()*2-1)*jitter : 0;
                    const jy = jitter ? (Math.random()*2-1)*jitter : 0;

                    // 转成左上角坐标
                    let x = Math.round(cx + jx - stampW / 2);
                    let y = Math.round(cy + jy - stampH / 2);

                    // ★ 硬性限界：不超过 overlay（也就是 container）边界
                    x = Math.max(0, Math.min(W - stampW, x));
                    y = Math.max(0, Math.min(H - stampH, y));

                    span.style.left = x + 'px';
                    span.style.top  = y + 'px';
                    overlay.appendChild(span);
                  }
                }

            }
        };
    </script>
</body>
</html>
EOF
)

# === Output ===
echo "$html_content"
