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
        @page {
            margin: 0 !important;
            size: 4in 8in;
        }

        body {
            font-family: "PingFang SC","Microsoft YaHei",Arial,sans-serif;
            background-color: #f2f2f2;
            margin: 0;
            padding: 5px;
        }

        .container {
            width: 4in;
            margin: 0 auto;
            padding: 20px;
            border-radius: 12px;
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
          border-radius: 12px;
          padding: 6px 10px 6px 10px;
          margin-bottom: 10px;
          word-break: break-word;
          max-width: fit-content;
          line-height: 1.5;
          box-shadow: 0 0 5px rgba(0, 0, 0, 0.1);
        }

        .content img:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon):not(.bubble):not(.cqface):not(.file-icon):not(.card),
        .content video:not(.thumb):not(.qr-code):not(.brand-icon):not(.card-tag-icon) {
            display: block;
            border-radius: 12px;
            padding: 0px;
            margin-bottom: 10px;
            max-width: 50%;
            max-height: 300px;
            box-shadow: 0px 0px 6px rgba(0, 0, 0, 0.2);
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
            border-radius: 12px;
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
            border-radius: 12px;
            padding: 8px;
            margin-bottom: 10px;
            text-decoration: none;
            color: #000000;
            box-sizing: border-box;
            width: fit-content;
            max-width: 276px;
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
            border-radius: 4px !important;
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
            margin-top: 0px;
            display: flex;
            flex-direction: column;
        }

        .card-title {
            font-size: 14px;
            font-weight: 600;
            line-height: 1.3;
        }

        .card-desc {
            font-size: 12px;
            color: #666;
            line-height: 1.2;
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
            display:block;
            font-size: 11px;
            color: #888;
        }

        /* === New: QQ official-like header layout === */
        .card-header {
            display: flex;
            align-items: center;
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
        .card-bottom {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 8px;
            padding-top: 7px;
        }

        .card-bottom-left {
            min-width: 0;
            display: flex;
            flex-direction: column;
            gap: 4px;
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

        .card-header .thumb {
            width: 48px !important;
            height: 48px !important;
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

        .reply {
          border-left: 3px solid #e0e0e0;
          background: #fafafa;
          border-radius: 6px;
          padding: 6px 8px;
          margin-bottom: 4px;
        }
        .reply .reply-meta {
          font-size: 0.85em;
          color: #666;
          margin-bottom: 2px;
        }
        .reply .reply-body {
          white-space: pre-wrap; /* 保留换行 */
          color: #333;
        }

        /* === Forward (合并转发) Apple Mail 引用风格 === */
        .forward {
          display: inline-block;
          border-left: 3px solid #71a1cc;
          padding-left: 10px;
          padding-bottom: 0px;
          margin: 0 0 10px 0;
          border-radius: 0px;
        }
        .forward-title {
          font-size: 12px;
          color: #666;
          margin: 0px 0 4px 0;
        }
        .forward-item {
          margin: 6px 0 6px 4px;
        }
        /* 嵌套转发时逐级缩进更明显 */
        .forward .forward { margin-left: 6px; }

        /* =========================================================
        Overrides: 标题左贴缩略图、二维码最右、标题允许两行并纵向居中
        仅影响结构为：<div class="card-header"><img.thumb> <div.card-header-right><div.card-title>…</div></div> <img.qr-code></div>
        ========================================================= */
        .card-header {
          justify-content: flex-start;   /* 让子项按顺序排布，由二维码自身推到右侧 */
          align-items: center;           /* 纵向居中 thumb / 标题列 / QR */
          gap: 8px;
        }

        /* 中间列吃掉剩余空间，确保 QR 被推到最右 */
        .card-header .thumb + .card-header-right {
          flex: 1 1 auto;
          min-width: 0;
          display: flex;
          align-items: center;           /* 标题块在列内纵向居中 */
          gap: 0;
          margin-left: 0;
        }

        /* QR 固定在最右侧且尺寸稳定 */
        .card-header .qr-code {
          margin-left: auto;             /* 将其推到最右侧 */
          flex: 0 0 48px;
        }

        /* 标题：左贴缩略图；允许两行并截断 */
        .card-header .thumb + .card-header-right > .card-title {
          margin: 0;
          text-align: left;
          white-space: normal;           /* 允许换行 */
          overflow: hidden;

          /* 两行截断（兼容旧 WebKit） */
          display: -webkit-box;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 2;
          line-clamp: 2;

          word-break: break-word;        /* 处理超长英文/URL */
          /* 如需更激进换行可改用：overflow-wrap: anywhere; */
          }
              /* 让纵向卡片本体可以占满到 max-width，避免 fit-content 影响 header 拉伸 */
          .card.card-vertical {
          width: 100%;          /* 占满可用宽度 */
          max-width: 276px;     /* 沿用你原本的上限 */
          }

          /* Header 铺满整张卡片，并保持纵向居中 */
          .card.card-vertical .card-header {
          width: 100%;
          display: flex;
          align-items: center;
          gap: 8px;
          }

          /* 左侧信息列吃掉中间空间，QR 才能被推到最右 */
          .card.card-vertical .card-header-left {
          flex: 1 1 auto;
          min-width: 0;         /* 允许内部换行/截断 */
          }

          /* 二维码固定在最右侧，尺寸稳定 */
          .card.card-vertical .qr-code {
          margin-left: auto;    /* 关键：推到最右 */
          flex: 0 0 48px;
          }

          /* 标题允许两行并截断（在 header-left 里） */
          .card.card-vertical .card-header-left .card-title {
          margin: 0;
          white-space: normal;
          overflow: hidden;

          display: -webkit-box;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 2;
          line-clamp: 2;

          word-break: break-word;      /* 处理超长英文/URL */
          /* 如果希望更激进换行可改为：overflow-wrap: anywhere; */
          }
          /* 覆盖层不占位，不挡交互 */
          .container { position: relative; }

          .wm-overlay{
            position: absolute;
            inset: 0;                 /* 覆盖整个 .container */
            pointer-events: none;     /* 不阻挡点击/选择 */
            z-index: 999;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;

          }

          .wm-item{
            position: absolute;
            white-space: nowrap;
            user-select: none;
            font-family: "PingFang SC","Microsoft YaHei",Arial,sans-serif;
            font-weight: 500;
            /* 低透明+微描边：在深/浅底都能看清，但不刺眼 */
            color: rgba(0,0,0,1);
            text-shadow:
              0 0 1px rgba(255,255,255,0.25),
              0 0 1px rgba(255,255,255,0.25);
            transform: rotate(-24deg);
            line-height: 1;
            mix-blend-mode: multiply;  /* 让颜色更自然地贴合背景 */
          }

          @media print {
            /* 打印时部分浏览器对混合模式支持一般，关掉更稳 */
            .wm-item{ mix-blend-mode: normal; }
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
