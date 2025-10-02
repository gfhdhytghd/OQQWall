#!/bin/bash

IFS=$'\n\t'
umask 027

CFG='./oqqwall.config'

# ----------------------------
# 平台检测与系统依赖自动修复
# ----------------------------
detect_platform() {
  OS_KERNEL=$(uname -s 2>/dev/null || echo unknown)
  OS_ID=""; OS_VERSION_ID=""; OS_ID_LIKE=""; OS_PRETTY=""; PKG_MGR=""; OS_FLAVOR=""
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID=${ID:-}
    OS_VERSION_ID=${VERSION_ID:-}
    OS_ID_LIKE=${ID_LIKE:-}
    OS_PRETTY=${PRETTY_NAME:-}
  fi

  # Termux 检测
  if [[ -n ${PREFIX:-} && ${PREFIX} == */com.termux/* ]]; then
    OS_FLAVOR="termux"
    PKG_MGR="pkg"
    return
  fi

  case "$OS_KERNEL" in
    Darwin)
      OS_FLAVOR="macos"
      PKG_MGR="brew"
      ;;
    Linux)
      case "$OS_ID" in
        arch|endeavouros|manjaro)
          OS_FLAVOR="arch"
          PKG_MGR="pacman"
          ;;
        debian|raspbian)
          OS_FLAVOR="debian"
          PKG_MGR="apt"
          ;;
        ubuntu|linuxmint|pop)
          OS_FLAVOR="ubuntu"
          PKG_MGR="apt"
          ;;
        fedora)
          OS_FLAVOR="fedora"
          PKG_MGR="dnf"
          ;;
        rhel)
          OS_FLAVOR="rhel"
          # RHEL9+ 推荐 dnf
          if command -v dnf >/dev/null 2>&1; then PKG_MGR="dnf"; else PKG_MGR="yum"; fi
          ;;
        centos)
          OS_FLAVOR="centos"
          if command -v dnf >/dev/null 2>&1; then PKG_MGR="dnf"; else PKG_MGR="yum"; fi
          ;;
        * )
          # 尝试通过 ID_LIKE 归类
          if [[ ${OS_ID_LIKE} == *"arch"* ]]; then
            OS_FLAVOR="arch"; PKG_MGR="pacman"
          elif [[ ${OS_ID_LIKE} == *"debian"* ]]; then
            OS_FLAVOR="debian"; PKG_MGR="apt"
          elif [[ ${OS_ID_LIKE} == *"rhel"* || ${OS_ID_LIKE} == *"fedora"* ]]; then
            OS_FLAVOR="rhel"; if command -v dnf >/dev/null 2>&1; then PKG_MGR="dnf"; else PKG_MGR="yum"; fi
          else
            OS_FLAVOR="unknown"
          fi
          ;;
      esac
      ;;
    *)
      OS_FLAVOR="unknown"
      ;;
  esac
}

# 判断给定路径是否来自 snap（路径或其真实路径位于 /snap 下）
is_snap_path() {
  local p="$1"
  [[ -z "$p" ]] && return 1
  if [[ "$p" == /snap/* ]]; then
    return 0
  fi
  local real
  real=$(readlink -f "$p" 2>/dev/null || echo "$p")
  if [[ "$real" == /snap/* ]]; then
    return 0
  fi
  return 1
}

# 查找是否存在非 snap 的 Chrome/Chromium 可执行
has_non_snap_chrome() {
  local bin path
  for bin in google-chrome-stable google-chrome chromium-browser chromium; do
    if command -v "$bin" >/dev/null 2>&1; then
      path=$(command -v "$bin")
      if ! is_snap_path "$path"; then
        return 0
      fi
    fi
  done
  return 1
}

# 获取 sudo（如可用）
declare -a SUDO_CMD=()
get_sudo() {
  SUDO_CMD=()
  # root 不需要前缀
  if [[ $(id -u) -eq 0 ]]; then
    return 0
  fi
  # 优先 sudo 且支持非交互 -n
  if command -v sudo >/dev/null 2>&1; then
    if sudo -n true >/dev/null 2>&1; then
      SUDO_CMD=(sudo -n)
      return 0
    fi
    # 无 -n 能力或需要密码：若是交互式终端，允许弹出密码框
    if [[ -t 0 ]]; then
      SUDO_CMD=(sudo)
      return 0
    fi
  fi
  # OpenBSD/部分系统使用 doas
  if command -v doas >/dev/null 2>&1; then
    SUDO_CMD=(doas)
    return 0
  fi
  # 无提权工具
  return 0
}

# 在某些发行版没有 xvfb-run（仅有 Xvfb）时，创建一个简单的兼容包装
maybe_create_xvfb_run_shim() {
  if command -v xvfb-run >/dev/null 2>&1; then
    return 0
  fi
  if command -v Xvfb >/dev/null 2>&1; then
    mkdir -p ./.local/bin
    cat > ./.local/bin/xvfb-run <<'SH'
#!/usr/bin/env bash
set -euo pipefail
# 仅实现最基本的: xvfb-run [-a] <cmd...>
display=99
if [[ ${1:-} == "-a" ]]; then shift; fi
XVFB_BIN=${XVFB_BIN:-Xvfb}
"${XVFB_BIN}" :${display} -screen 0 1024x768x24 >/dev/null 2>&1 &
XVFB_PID=$!
trap 'kill ${XVFB_PID} >/dev/null 2>&1 || true' EXIT
export DISPLAY=:${display}
exec "$@"
SH
    chmod +x ./.local/bin/xvfb-run
    case ":$PATH:" in
      *":$(pwd)/.local/bin:"*) :;;
      *) export PATH="$(pwd)/.local/bin:$PATH";;
    esac
    echo "[INFO] 已创建本地 xvfb-run 包装脚本（使用 Xvfb）。"
  fi
}

# 根据发行版安装所需系统包
ensure_system_packages() {
  detect_platform
  get_sudo

  # 需要的命令 -> 包名映射，由各发行版填充
  declare -A pkgmap

  # 通用命令检查列表（命令名）
  local cmds=(jq sqlite3 python3 curl perl pkill)

  # 追加 xvfb-run（仅在内部管理 NapCat 时需要），在调用处按需处理

  case "$OS_FLAVOR" in
    termux)
      # Termux: pkg
      pkgmap=(
        [jq]=jq
        [sqlite3]=sqlite
        [python3]=python
        [curl]=curl
        [perl]=perl
        [pkill]=procps
      )
      ;;
    arch)
      pkgmap=(
        [jq]=jq
        [sqlite3]=sqlite
        [python3]=python
        [curl]=curl
        [perl]=perl
        [pkill]=procps-ng
      )
      ;;
    debian|ubuntu)
      pkgmap=(
        [jq]=jq
        [sqlite3]=sqlite3
        [python3]=python3
        [curl]=curl
        [perl]=perl
        [pkill]=procps
      )
      ;;
    fedora|rhel|centos)
      pkgmap=(
        [jq]=jq
        [sqlite3]=sqlite
        [python3]=python3
        [curl]=curl
        [perl]=perl
        [pkill]=procps-ng
      )
      ;;
    macos)
      pkgmap=(
        [jq]=jq
        [sqlite3]=sqlite
        [python3]=python
        [curl]=curl
        [perl]=perl
        [pkill]=""  # macOS 自带 pkill
      )
      ;;
    *)
      echo "[WARN] 未识别的系统，跳过系统包自动修复。"
      return 0
      ;;
  esac

  # 组装待安装包
  local to_install=()
  for c in "${cmds[@]}"; do
    if ! command -v "$c" >/dev/null 2>&1; then
      pkg=${pkgmap[$c]:-}
      [[ -n $pkg ]] && to_install+=("$pkg")
    fi
  done

  local need_pip_pkg=0
  local need_venv_pkg=0
  local venv_pkg_by_version=""
  command -v pip3 >/dev/null 2>&1 || need_pip_pkg=1
  if command -v python3 >/dev/null 2>&1; then
    # 在 Debian/Ubuntu 上，仅检查 venv --help 可能不足；ensurepip 缺失也会导致创建失败
    if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
      need_venv_pkg=1
      venv_pkg_by_version=$(python3 -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}-venv")' 2>/dev/null || true)
      venv_pkg_by_version=${venv_pkg_by_version//$'\n'/}
    fi
  fi

  if [[ "$PKG_MGR" == "apt" ]]; then
    if (( need_venv_pkg )); then
      # Debian/Ubuntu 有的版本需要安装版本化的 venv 包（如 python3.13-venv）
      # 先优选版本化名称，若不可用则回退到 python3-venv
      local candidate="${venv_pkg_by_version}"
      local chosen=""
      if [[ -n "$candidate" ]]; then
        if apt-cache show "$candidate" >/dev/null 2>&1; then
          chosen="$candidate"
        fi
      fi
      if [[ -z "$chosen" ]]; then
        if apt-cache show python3-venv >/dev/null 2>&1; then
          chosen="python3-venv"
        else
          # 两者都无法通过探测，仍然优先尝试版本化名
          chosen="${candidate:-python3-venv}"
        fi
      fi
      echo "[INFO] 检测到 python3 -m venv 不可用，APT 将安装: $chosen"
      local found=0
      for existing in "${to_install[@]}"; do
        [[ "$existing" == "$chosen" ]] && found=1 && break
      done
      (( found == 0 )) && to_install+=("$chosen")
    fi
    if (( need_pip_pkg )); then
      local found=0
      for existing in "${to_install[@]}"; do
        [[ "$existing" == "python3-pip" ]] && found=1 && break
      done
      (( found == 0 )) && to_install+=(python3-pip)
    fi
  fi

  if [[ "$PKG_MGR" == "pacman" ]]; then
    if (( need_pip_pkg )); then
      local found=0
      for existing in "${to_install[@]}"; do
        [[ "$existing" == "python-pip" ]] && found=1 && break
      done
      (( found == 0 )) && to_install+=(python-pip)
    fi
  fi

  if [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
    if (( need_pip_pkg )); then
      local found=0
      for existing in "${to_install[@]}"; do
        [[ "$existing" == "python3-pip" ]] && found=1 && break
      done
      (( found == 0 )) && to_install+=(python3-pip)
    fi
    if (( need_venv_pkg )); then
      if [[ -n "$venv_pkg_by_version" ]]; then
        local found=0
        for existing in "${to_install[@]}"; do
          [[ "$existing" == "$venv_pkg_by_version" ]] && found=1 && break
        done
        (( found == 0 )) && to_install+=("$venv_pkg_by_version")
      fi
    fi
  fi
  # macOS: brew 的 python 自带 venv

  # Perl URI::Escape 模块检测（用于 Shell 中 URI 编码）
  local need_perl_uri=0
  if command -v perl >/dev/null 2>&1; then
    if ! perl -MURI::Escape -e 1 >/dev/null 2>&1; then
      need_perl_uri=1
    fi
  fi

  # 各发行版对应包名/安装策略
  if (( need_perl_uri )); then
    case "$PKG_MGR" in
      apt)
        # Debian/Ubuntu
        local found=0
        for existing in "${to_install[@]}"; do
          [[ "$existing" == "liburi-perl" ]] && found=1 && break
        done
        (( found == 0 )) && to_install+=(liburi-perl)
        ;;
      pacman)
        # Arch 系
        local found=0
        for existing in "${to_install[@]}"; do
          [[ "$existing" == "perl-uri" ]] && found=1 && break
        done
        (( found == 0 )) && to_install+=(perl-uri)
        ;;
      dnf|yum)
        # Fedora/RHEL/CentOS
        local found=0
        for existing in "${to_install[@]}"; do
          [[ "$existing" == "perl-URI" ]] && found=1 && break
        done
        (( found == 0 )) && to_install+=(perl-URI)
        ;;
      brew)
        # Homebrew 无独立 perl-URI 包，后续用 cpanminus 安装 URI 模块
        :
        ;;
      pkg)
        # Termux 可能没有独立 perl-URI 包，后续尝试 cpanminus
        :
        ;;
    esac
  fi

  if (( ${#to_install[@]} > 0 )); then
    echo "[INFO] 正在安装系统依赖: ${to_install[*]}"
    case "$PKG_MGR" in
      apt)
        if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
          # 仅在确有缺失包时更新仓库索引
          "${SUDO_CMD[@]}" apt-get update -y || true
          "${SUDO_CMD[@]}" apt-get install -y "${to_install[@]}" || true
        else
          echo "[WARN] 无 root/sudo 权限，无法自动安装: ${to_install[*]}"
        fi
        ;;
      pacman)
        if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
          # 仅在确有缺失包时同步仓库
          "${SUDO_CMD[@]}" pacman -Sy --noconfirm || true
          "${SUDO_CMD[@]}" pacman -S --noconfirm --needed "${to_install[@]}" || true
        else
          echo "[WARN] 无 root/sudo 权限，无法自动安装: ${to_install[*]}"
        fi
        ;;
      dnf)
        if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
          "${SUDO_CMD[@]}" dnf -y install "${to_install[@]}" || true
        else
          echo "[WARN] 无 root/sudo 权限，无法自动安装: ${to_install[*]}"
        fi
        ;;
      yum)
        if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
          "${SUDO_CMD[@]}" yum -y install "${to_install[@]}" || true
        else
          echo "[WARN] 无 root/sudo 权限，无法自动安装: ${to_install[*]}"
        fi
        ;;
      brew)
        if ! command -v brew >/dev/null 2>&1; then
          echo "[WARN] 未检测到 Homebrew。请安装后再运行: https://brew.sh"
        else
          # 仅在确有缺失包时更新索引
          brew update || true
          brew install "${to_install[@]}" || true
        fi
        ;;
      pkg)
        # 仅在确有缺失包时更新索引
        if command -v pkg >/dev/null 2>&1; then
          pkg update -y || true
        fi
        pkg install -y "${to_install[@]}" || true
        ;;
      *) ;;
    esac
  fi

  # 安装后，若仍缺少 Perl 的 URI::Escape（Homebrew/Termux 常见），尝试使用 cpanminus 安装
  if (( need_perl_uri )); then
    if command -v perl >/dev/null 2>&1 && ! perl -MURI::Escape -e 1 >/dev/null 2>&1; then
      case "$PKG_MGR" in
        brew)
          if command -v brew >/dev/null 2>&1; then
            brew install cpanminus || true
            if command -v cpanm >/dev/null 2>&1; then
              cpanm --notest URI || true
            fi
          fi
          ;;
        pkg)
          if command -v pkg >/dev/null 2>&1; then
            pkg install -y cpanminus || true
          fi
          if command -v cpanm >/dev/null 2>&1; then
            cpanm --notest URI || true
          else
            # 兜底安装 cpanminus（不要求 root，安装到用户目录）
            curl -fsSL https://cpanmin.us | perl - App::cpanminus 2>/dev/null || true
            if command -v cpanm >/dev/null 2>&1; then
              cpanm --notest URI || true
            fi
          fi
          ;;
      esac
    fi
    # 最终验证与提示
    if command -v perl >/dev/null 2>&1 && ! perl -MURI::Escape -e 1 >/dev/null 2>&1; then
      echo "[WARN] 仍缺少 Perl 模块 URI::Escape。请手动安装：" >&2
      case "$PKG_MGR" in
        apt)   echo "      sudo apt-get install -y liburi-perl" >&2 ;;
        pacman)echo "      sudo pacman -S --needed perl-uri" >&2 ;;
        dnf)   echo "      sudo dnf -y install perl-URI" >&2 ;;
        yum)   echo "      sudo yum -y install perl-URI" >&2 ;;
        brew)  echo "      brew install cpanminus && cpanm --notest URI" >&2 ;;
        pkg)   echo "      pkg install cpanminus && cpanm --notest URI" >&2 ;;
      esac
    fi
  fi

  # Ubuntu: 仅警告（不自动安装），要求非 snap 的 Chrome/Chromium
  if [[ "$OS_FLAVOR" == "ubuntu" ]]; then
    if ! has_non_snap_chrome; then
      echo "[WARN] 检测到 Ubuntu，系统未发现非 snap 的 Chrome/Chromium。"
      echo "       请手动安装非 snap 浏览器（推荐 google-chrome-stable），并确保命令不在 /snap/bin 下。"
      echo "       示例（手动执行）："
      echo "         curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg"
      echo "         echo \"deb [arch=$(dpkg --print-architecture 2>/dev/null || echo amd64) signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main\" | sudo tee /etc/apt/sources.list.d/google-chrome.list"
      echo "         sudo apt-get update && sudo apt-get install -y google-chrome-stable"
    fi
  fi

  # 如果需要 xvfb 且缺失，则尝试安装
  local need_xvfb=${1:-false}
  if [[ "$need_xvfb" == "true" ]]; then
    if ! command -v xvfb-run >/dev/null 2>&1 && ! command -v Xvfb >/dev/null 2>&1; then
      case "$PKG_MGR" in
        apt)
          if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
            "${SUDO_CMD[@]}" apt-get install -y xvfb || true
          else
            echo "[WARN] 无 root/sudo 权限，无法自动安装 xvfb。"
          fi
          ;;
        pacman)
          if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
            "${SUDO_CMD[@]}" pacman -S --noconfirm --needed xorg-server-xvfb || true
          else
            echo "[WARN] 无 root/sudo 权限，无法自动安装 xorg-server-xvfb。"
          fi
          ;;
        dnf)
          if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
            "${SUDO_CMD[@]}" dnf -y install xorg-x11-server-Xvfb || true
          else
            echo "[WARN] 无 root/sudo 权限，无法自动安装 Xvfb。"
          fi
          ;;
        yum)
          if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
            "${SUDO_CMD[@]}" yum -y install xorg-x11-server-Xvfb || true
          else
            echo "[WARN] 无 root/sudo 权限，无法自动安装 Xvfb。"
          fi
          ;;
        brew)
          if command -v brew >/dev/null 2>&1; then
            brew install xorg-server || true
          fi
          ;;
        pkg)
          echo "[WARN] Termux 不提供 xvfb，已跳过安装。"
          ;;
      esac
    fi
    # 仍无 xvfb-run，但有 Xvfb，则创建本地兼容脚本
    maybe_create_xvfb_run_shim
  fi
}

# 函数：检测文件或目录是否存在，不存在则创建
check_and_create() {
    local path=$1
    local type=$2

    if [[ $type == "file" ]]; then
        if [[ ! -f $path ]]; then
            touch "$path"
            echo "已创建文件: $path"
        fi
    elif [[ $type == "directory" ]]; then
        if [[ ! -d $path ]]; then
            mkdir -p "$path"
            echo "已创建目录: $path"
        fi
    else
        echo "未知类型: $type。请指定 'file' 或 'directory'。"
        return 1
    fi
}

# 确保指定路径为命名管道（若存在且非管道则替换）
ensure_named_pipe() {
    local fifo_path="$1"
    [[ -z "$fifo_path" ]] && return 1
    local parent_dir
    parent_dir=$(dirname -- "$fifo_path")
    mkdir -p -- "$parent_dir"
    if [[ -e "$fifo_path" && ! -p "$fifo_path" ]]; then
        echo "检测到 $fifo_path 存在但不是命名管道，正在替换…"
        rm -f -- "$fifo_path" || true
    fi
    if [[ ! -p "$fifo_path" ]]; then
        mkfifo -- "$fifo_path" || { echo "创建命名管道失败: $fifo_path"; return 1; }
        echo "已创建命名管道: $fifo_path"
    fi
}

generate_random_token() {
  tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32
}

# 端口占用检测与建议
is_port_in_use() {
  local port="$1"
  # 优先 ss
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -E "[:\.]${port}	?$|[:\.]${port}$" -q && return 0
  fi
  # 其次 lsof
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  fi
  # 其次 netstat
  if command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | awk '{print $4}' | grep -E "[:\.]${port}$" -q && return 0
  fi
  # 最后 /dev/tcp 回环连接尝试
  (echo > "/dev/tcp/127.0.0.1/${port}") >/dev/null 2>&1 && return 0
  return 1
}

find_next_free_port() {
  local start="$1"; shift || true
  local excludes=("$@")
  local p
  p=$start
  while (( p>0 && p<65535 )); do
    local conflict=0
    for e in "${excludes[@]}"; do
      [[ "$e" == "$p" ]] && conflict=1 && break
    done
    if (( conflict == 0 )) && ! is_port_in_use "$p"; then
      echo "$p"; return 0
    fi
    ((p++))
  done
  # 回退
  echo "$start"
  return 1
}

# 初始化默认配置文件（含随机 napcat_access_token）
init_default_config() {
  local napcat_token
  napcat_token=$(generate_random_token)
  cat <<EOF > "$CFG"
http-serv-port=
apikey=""
process_waittime=120
manage_napcat_internal=true
max_attempts_qzone_autologin=3
text_model=qwen-plus-latest
vision_model=qwen-vl-max-latest
vision_pixel_limit=12000000
vision_size_limit_mb=9.5
at_unprived_sender=true
friend_request_window_sec=300
force_chromium_no-sandbox=false
use_web_review=false
web_review_port=10923
napcat_access_token=$napcat_token
EOF
  echo "已创建文件: $CFG"
  echo "请参考wiki填写配置文件后再启动"
}


cfg_get() {
  # 用 awk 提取，去掉引号与空白
  local key=$1
  [[ -z ${key:-} ]] && return 1
  awk -F= -v k="$key" '$1==k{v=$2; gsub(/[ \t\r"\n]+/,"",v); print v}' "$CFG" 2>/dev/null
}

# 仅依赖 3 个位置参数：
#   $1 = 配置文件路径
#   $2 = 变量名
#   $3 = 默认值
check_variable() {
    local var_name="$1"
    local default_value="$2"

    # 基础校验 ---------------------------------------------------------
    if [[ -z "$CFG" || -z "$var_name" ]]; then
        echo "[check_variable] 用法: check_variable <var_name> <default_value>"
        return 1
    fi
    [[ ! -f "$CFG" ]] && {
        echo "[check_variable] 错误: 配置文件 $CFG 不存在"
        return 1
    }

    # 取当前值（使用 cfg_get，避免 grep 未匹配导致 pipefail+errexit 退出）
    local current_value
    current_value=$(cfg_get "$var_name")

    # 若值为空、缺失或占位符，则写入默认值 ------------------------------
    if [[ -z "$current_value" || "$current_value" == "xxx" ]]; then
        # 如果 default_value 为 auto，则自动生成随机值
        if [[ "$default_value" == "auto" ]]; then
            local new_token
            new_token=$(generate_random_token)
            if grep -q "^${var_name}=" "$CFG"; then
                sed -i "s|^${var_name}=.*|${var_name}=${new_token}|" "$CFG"
            else
                echo "${var_name}=${new_token}" >> "$CFG"
            fi
            echo "[init] 已为 ${var_name} 自动生成随机值:${new_token}。请在 NapCat/OneBot 侧同步该值。"
            exit 0
        else
            if grep -q "^${var_name}=" "$CFG"; then
                # 已存在行 → 就地替换
                sed -i "s|^${var_name}=.*|${var_name}=${default_value}|" "$CFG"
            else
                # 未出现过 → 追加
                echo "${var_name}=${default_value}" >> "$CFG"
            fi
            echo "[check_variable] 已将 ${var_name} 重置为默认值: ${default_value}"
        fi
    fi
}

kill_pat() {
    local pattern=$1
    pkill -f -15 -- "$pattern" 2>/dev/null || true
}

require_cmd() {
  local missing=0
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "错误：未找到依赖命令 $cmd，请先安装后再运行。"
      missing=1
    fi
  done
  if [[ $missing -eq 1 ]]; then
    exit 1
  fi
}

# 逐包检查 Linux 依赖：缺失则报错并退出
check_linux_dependencies() {
  local missing=()
  local dep
  for dep in "$@"; do
    if command -v "$dep" >/dev/null 2>&1; then
      echo "[OK] Linux 依赖已满足: $dep"
    else
      echo "[ERR] 缺少 Linux 依赖: $dep"
      missing+=("$dep")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    echo "以下 Linux 依赖未安装，请先安装后再运行: ${missing[*]}"
    exit 1
  fi
}

# 逐包检查 Python 依赖：缺失则自动安装修复
ensure_python_packages() {
  # 使用激活的 venv 的 python/pip
  local pip_mirror="https://pypi.tuna.tsinghua.edu.cn/simple"
  declare -A pkg_map
  pkg_map=(
    [dashscope]=dashscope
    [bs4]=beautifulsoup4
    [httpx]=httpx
    [uvicorn]=uvicorn
    [fastapi]=fastapi
    [pydantic]=pydantic
    [requests]=requests
    [regex]=regex
    [PIL]=pillow
    [urllib3]=urllib3
  )

  local mod
  for mod in "${!pkg_map[@]}"; do
    if python - <<PY
import sys
try:
    import ${mod}
except Exception:
    sys.exit(1)
sys.exit(0)
PY
    then
      echo "[OK] Python 依赖可用: ${mod}"
    else
      echo "[FIX] 缺少 Python 依赖: ${mod} -> 安装包 ${pkg_map[$mod]}"
      # 先尝试清华镜像，失败则回退到官方 PyPI，再次失败尝试添加 trusted-host
      if ! python -m pip install "${pkg_map[$mod]}" -i "$pip_mirror" --retries 3 --timeout 30; then
        echo "[WARN] 镜像安装失败，尝试官方 PyPI: ${pkg_map[$mod]}"
        if ! python -m pip install "${pkg_map[$mod]}" --retries 3 --timeout 30; then
          echo "[WARN] 官方 PyPI 安装失败，尝试添加 trusted-host: ${pkg_map[$mod]}"
          if ! python -m pip install "${pkg_map[$mod]}" -i "$pip_mirror" --trusted-host pypi.tuna.tsinghua.edu.cn --retries 3 --timeout 60; then
            echo "[ERR] 安装 Python 包失败: ${pkg_map[$mod]}"
            exit 1
          fi
        fi
      fi
      # 二次校验
      if ! python - <<PY
import sys
try:
    import ${mod}
except Exception:
    sys.exit(1)
sys.exit(0)
PY
      then
        echo "[ERR] 仍无法导入: ${mod}，请手动检查环境。"
        exit 1
      fi
      echo "[OK] 已修复 Python 依赖: ${mod}"
    fi
  done
}

# ------------------
# 交互式 OOBE 向导
# ------------------
prompt_with_default() {
  local prompt="$1"; shift
  local def="$1"; shift || true
  local var
  read -r -p "$prompt [$def]: " var
  echo "${var:-$def}"
}

prompt_bool() {
  local prompt="$1"; shift
  local def="$1"; shift || true
  local var
  while true; do
    read -r -p "$prompt [$def]: " var
    var=${var:-$def}
    case "${var,,}" in
      y|yes|true|1) echo true; return;;
      n|no|false|0) echo false; return;;
      *) echo "请输入 yes/no 或 true/false";;
    esac
  done
}

prompt_port() {
  local prompt="$1"; shift
  local def="$1"; shift || true
  local var
  while true; do
    read -r -p "$prompt [$def]: " var
    var=${var:-$def}
    if [[ "$var" =~ ^[0-9]+$ ]] && (( var>0 && var<65536 )); then
      echo "$var"; return
    else
      echo "端口应为 1-65535 的整数"
    fi
  done
}

write_oqq_config() {
  local http_port="$1" apikey_val="$2" process_wait="$3" manage_q="$4" max_auto="$5" \
        text_m="$6" vision_m="$7" vision_px="$8" vision_mb="$9" at_unpriv="${10}" \
        fr_win="${11}" no_sandbox="${12}" use_review="${13}" review_port="${14}" token="${15}"
  cat > "$CFG" <<EOF
http-serv-port=$http_port
apikey="$apikey_val"
process_waittime=$process_wait
manage_napcat_internal=$manage_q
max_attempts_qzone_autologin=$max_auto
text_model=$text_m
vision_model=$vision_m
vision_pixel_limit=$vision_px
vision_size_limit_mb=$vision_mb
at_unprived_sender=$at_unpriv
friend_request_window_sec=$fr_win
force_chromium_no-sandbox=$no_sandbox
use_web_review=$use_review
web_review_port=$review_port
napcat_access_token=$token
EOF
}

json_escape() {
  # 使用 Python 可靠转义为 JSON 内部字符串（去掉首尾引号）
  python3 - "$1" <<'PY'
import sys, json
print(json.dumps(sys.argv[1])[1:-1])
PY
}

guide_account_group_setup() {
  local out="AcountGroupcfg.json"
  if [[ -f "$out" ]]; then
    echo "检测到已存在 $out，将覆盖并生成新的账户组配置。"
  fi

  echo "开始账户组配置引导：将为你创建一个主账户配置。"
  local gkey mangroup mainqq mainport
  gkey=$(prompt_with_default "请输入组标识(键名)" "MethGroup")

  while true; do
    read -r -p "请输入 QQ 群号(mangroupid): " mangroup
    [[ -n "$mangroup" ]] && break
    echo "mangroupid 不能为空。"
  done
  while true; do
    read -r -p "请输入主号 QQ(mainqqid): " mainqq
    [[ -n "$mainqq" ]] && break
    echo "mainqqid 不能为空。"
  done
  # 为主号 OneBot HTTP 端口建议一个未占用且不与现有配置冲突的端口
  local excludes=()
  if [[ -f "$CFG" ]]; then
    local _http_cfg _use_review _wr_port
    _http_cfg=$(cfg_get 'http-serv-port')
    _use_review=$(cfg_get 'use_web_review')
    _wr_port=$(cfg_get 'web_review_port')
    [[ -n "${_http_cfg:-}" ]] && excludes+=("$_http_cfg")
    if [[ "${_use_review}" == "true" && -n "${_wr_port:-}" ]]; then
      excludes+=("$_wr_port")
    fi
  fi
  local mainport_def
  mainport_def=$(find_next_free_port 8083 "${excludes[@]}")
  mainport=$(prompt_port "请输入主号 OneBot HTTP 端口(mainqq_http_port)" "$mainport_def")

  # 组策略（可选）
  echo "是否现在配置组策略（发送限额、水印、加好友自动回复等）？"
  local do_policy
  do_policy=$(prompt_bool "配置组策略?" "no")
  local max_stack max_imgs friend_msg watermark
  if [[ "$do_policy" == true ]]; then
    max_stack=$(prompt_with_default "每批最大发送条数(max_post_stack)" "1")
    max_imgs=$(prompt_with_default "每贴最多图片数(max_image_number_one_post)" "20")
    read -r -p "加好友自动回复(friend_add_message，可留空): " friend_msg
    read -r -p "水印文字(watermark_text，可留空): " watermark
  else
    max_stack="1"
    max_imgs="20"
    friend_msg=""
    watermark=""
  fi

  local friend_json watermark_json
  friend_json=$(json_escape "$friend_msg")
  watermark_json=$(json_escape "$watermark")

  cat > "$out" <<EOF
{
  "$gkey": {
    "mangroupid": "$mangroup",
    "mainqqid": "$mainqq",
    "mainqq_http_port": "$mainport",
    "minorqqid": [],
    "minorqq_http_port": [],
    "max_post_stack": "$max_stack",
    "max_image_number_one_post": "$max_imgs",
    "friend_add_message": "$friend_json",
    "send_schedule": [],
    "watermark_text": "$watermark_json",
    "quick_replies": {}
  }
}
EOF

  echo "账户组配置已创建：$out"
  echo "提示：需要更多功能（副号、发送计划、快捷指令等），请参考文档：OQQWall.wiki/账户组配置.md"
}


# 判断 AcountGroupcfg.json 是否为空模板（关键字段均为空或非数字）
is_empty_account_group_template() {
  local jf="AcountGroupcfg.json"
  [[ ! -f "$jf" ]] && return 1
  jq -e '
    type=="object" and
    (to_entries|length)>=1 and
    (to_entries|all(
      (.value.mangroupid|tostring|test("^[0-9]+$")|not) and
      (.value.mainqqid|tostring|test("^[0-9]+$")|not) and
      (.value.mainqq_http_port|tostring|test("^[0-9]+$")|not)
    ))
  ' "$jf" >/dev/null 2>&1
}


run_oobe() {
  # 若非交互式终端，回退为默认初始化
  if [[ ! -t 0 ]]; then
    echo "检测到非交互式环境，使用默认配置初始化。"
    init_default_config
    return 0
  fi

  echo "欢迎使用 OQQWall 首次运行向导 (OOBE)"
  echo "本向导将帮你生成 oqqwall.config，并可选创建 AcountGroupcfg.json。"

  local http_port apikey_val process_wait manage_q max_auto text_m vision_m vision_px vision_mb at_unpriv fr_win no_sandbox use_review review_port token

  local http_def
  http_def=$(find_next_free_port 8082)
  http_port=$(prompt_port "HTTP 服务端口(http-serv-port)" "$http_def")
  read -r -p "Qwen DashScope API Key(请参考”快速开始“文档获取): " apikey_val
  if [[ -z "$apikey_val" ]]; then apikey_val="sk-"; fi
  process_wait=$(prompt_with_default "任务处理等待时间秒(process_waittime)" "120")
  # 根据系统可用性推荐是否内部管理 NapCat/QQ
  local _has_qq=0 _has_xvfb=0
  if command -v qq >/dev/null 2>&1 || command -v linuxqq >/dev/null 2>&1; then _has_qq=1; fi
  if command -v Xvfb >/dev/null 2>&1; then _has_xvfb=1; fi
  local _manage_def="yes"
  if [[ $_has_qq -ne 1 || $_has_xvfb -ne 1 ]]; then
    local _missing=()
    [[ $_has_qq -ne 1 ]] && _missing+=("qq/linuxqq")
    [[ $_has_xvfb -ne 1 ]] && _missing+=("Xvfb")
    echo "[提示] 未检测到 ${_missing[*]}。建议 manage_napcat_internal 设为 false。"
    _manage_def="no"
  fi
  manage_q=$(prompt_bool "是否由本程序管理 NapCat/QQ (manage_napcat_internal)" "${_manage_def}")
  max_auto=$(prompt_with_default "QZone 自动登录最大尝试次数(max_attempts_qzone_autologin)" "3")
  text_m=$(prompt_with_default "文本模型(text_model)" "qwen-plus-latest")
  vision_m=$(prompt_with_default "多模模型(vision_model)" "qwen-vl-max-latest")
  vision_px=$(prompt_with_default "视觉像素上限(vision_pixel_limit)" "12000000")
  vision_mb=$(prompt_with_default "视觉图片大小上限MB(vision_size_limit_mb)" "9.5")
  at_unpriv=$(prompt_bool "@未授权发送者(at_unprived_sender)" "yes")
  fr_win=$(prompt_with_default "好友请求窗口秒(friend_request_window_sec)" "300")
  # 若以 root 运行，推荐启用 no-sandbox
  local default_ns="no"
  if [[ $(id -u) -eq 0 ]]; then
    echo "[提示] 检测到当前以 root 身份运行，建议启用 Chromium 的 --no-sandbox 模式。"
    default_ns="yes"
  fi
  no_sandbox=$(prompt_bool "Chromium 强制 --no-sandbox(force_chromium_no-sandbox)" "$default_ns")
  use_review=$(prompt_bool "启用网页审核(use_web_review)" "no")
  if [[ "$use_review" == true ]]; then
    local review_def
    review_def=$(find_next_free_port 10923 "$http_port")
    review_port=$(prompt_port "网页审核端口(web_review_port)" "$review_def")
  else
    review_port="10923"
  fi

  token=$(generate_random_token)
  echo "已为 NapCat 访问令牌生成随机值: $token"
  local use_tok
  use_tok=$(prompt_bool "是否使用该 Token? (NapCat/OneBot 需同步此值)" "yes")
  if [[ "$use_tok" != true ]]; then
    read -r -p "请输入自定义 napcat_access_token: " token
  fi

  write_oqq_config "$http_port" "$apikey_val" "$process_wait" "$manage_q" "$max_auto" \
                   "$text_m" "$vision_m" "$vision_px" "$vision_mb" "$at_unpriv" \
                   "$fr_win" "$no_sandbox" "$use_review" "$review_port" "$token"
  echo "已创建文件: $CFG"
  echo "请将 napcat_access_token 同步到 NapCat/OneBot 侧的鉴权配置中。"

  echo "OOBE 完成。你可以现在运行: ./main.sh"
}

print_test_mode_hint() {
  cat <<'EOF'
测试模式提示：核心服务已停止，需要按需手动启动：
- 接收端：python3 getmsgserv/serv.py
- QZone 管道（如需调试）：python3 SendQzone/qzone-serv-pipe.py
- 审核脚本：./Sendcontrol/sendcontrol.sh
- NapCat 测试工具：python3 tests/napcat_replayer.py --target http://localhost:8082
EOF
}

_sanitize_tbl() {
  local s="sendstorge_${1}";
  s="${s//[^A-Za-z0-9_]/_}"
  if [[ $s =~ ^[0-9] ]]; then
    s="g_${s}"
  fi
  printf '%s' "$s"
}

mode="${1:-}"

# Debug mode (must be first arg if combined)
if [[ "$mode" == "--debug" ]]; then
  export OQQ_DEBUG=1
  PS4='+ ${BASH_SOURCE[0]##*/}:${LINENO}:${FUNCNAME[0]:-main}: '
  set -x
  echo "[debug] Debug mode enabled. Tracing and verbose logs on."
  mode="${2:-}"
fi

if [[ -f "$CFG" ]]; then
  manage_napcat_internal=$(cfg_get 'manage_napcat_internal')
fi
manage_napcat_internal=${manage_napcat_internal:-false}

case "$mode" in
  -r)
    echo "执行子系统重启..."
    if [[ "$manage_napcat_internal" == "true" ]]; then
      echo "停止 NapCat/QQ 相关进程..."
      kill_pat "xvfb-run -a qq --no-sandbox -q"
    else
      echo "manage_napcat_internal != true，QQ相关进程未自动管理。请自行处理 Napcat QQ 客户端。"
    fi
    echo "停止 getmsgserv/serv.py..."
    kill_pat "python3 getmsgserv/serv.py"
    echo "停止 SendQzone/qzone-serv-pipe.py..."
    kill_pat "python3 SendQzone/qzone-serv-pipe.py"
    echo "停止 Sendcontrol/sendcontrol.sh..."
    kill_pat "/bin/bash ./Sendcontrol/sendcontrol.sh"
    echo "停止 web_review/web_review.py..."
    kill_pat "python3 web_review/web_review.py"
    ;;
  -rf)
    echo "执行无检验的子系统强行重启..."
    if [[ "$manage_napcat_internal" == "true" ]]; then
      echo "强制停止 NapCat/QQ 相关进程..."
      kill_pat "xvfb-run -a qq --no-sandbox -q"
    else
      echo "manage_napcat_internal != true，QQ相关进程未自动管理。请自行处理 Napcat QQ 客户端。"
    fi
    kill_pat "python3 getmsgserv/serv.py"
    kill_pat "python3 SendQzone/qzone-serv-pipe.py"
    kill_pat "/bin/bash ./Sendcontrol/sendcontrol.sh"
    kill_pat "python3 web_review/web_review.py"
    ;;
  -h)
    cat <<'EOF'
Without any flag-->start OQQWall
-r    Subsystem restart
-rf   Force subsystem restart
--test   start OQQWall in test mode
--debug  enable verbose tracing/logging (put first to combine)
--oobe   interactive out-of-box setup to create configs
Show Napcat(QQ) log: open a new terminal, go to OQQWall's home path and run: tail -n 100 -f ./NapCatlog
for more information, read ./OQQWall.wiki
EOF
    exit 0
    ;;
  --oobe)
    run_oobe
    exit 0
    ;;
  --test)
    echo "以测试模式启动OQQWall..."
    kill_pat "python3 SendQzone/qzone-serv-pipe.py"
    kill_pat "/bin/bash ./Sendcontrol/sendcontrol.sh"
    kill_pat "python3 getmsgserv/serv.py"
    print_test_mode_hint
    ;;
esac

# 若配置不存在，则引导 OOBE 初始化后退出，避免未配置环境继续运行
if [[ ! -f "$CFG" ]]; then
  run_oobe
  if [[ ! -f AcountGroupcfg.json ]]; then
    guide_account_group_setup
  fi
  echo "初始引导完成。可再次运行 ./main.sh 启动服务。"
  exit 0
fi

# 系统依赖自动修复（在执行前尝试安装缺失包；不主动安装 xvfb/xvfb-run）
ensure_system_packages "false"

# Linux 依赖逐包检查
check_linux_dependencies jq sqlite3 python3 pkill curl perl
if ! command -v qq >/dev/null 2>&1 && ! command -v linuxqq >/dev/null 2>&1; then
  echo "警告：未检测到 qq 或 linuxqq 可执行文件，NapCat 内部管理可能无法启动 QQ 客户端。"
fi
if [[ "$manage_napcat_internal" == "true" ]]; then
  if ! command -v xvfb-run >/dev/null 2>&1 && ! command -v Xvfb >/dev/null 2>&1; then
    echo "警告：未检测到 xvfb-run 或 Xvfb。xvfb 依赖应由 NapCat 提供；如未安装，建议在 OOBE 勾选 manage_napcat_internal=false。"
  fi
fi

# 初始化目录和文件
# 初始化目录
check_and_create "/dev/shm/OQQWall/" "directory"
check_and_create "./cache/numb/" "directory"
check_and_create "getmsgserv/all/" "directory"
# 初始化文件
check_and_create "/dev/shm/OQQWall/oqqwallhtmlcache.html" "file"
check_and_create "./getmsgserv/all/commugroup.txt" "file"
if [[ ! -f "getmsgserv/all/priv_post.jsonl" ]]; then
    touch "getmsgserv/all/priv_post.jsonl"
    echo "已创建文件: getmsgserv/all/priv_post.jsonl"
fi

# 初始化命名管道（若已存在但类型错误则更正）
ensure_named_pipe "./qzone_in_fifo"
ensure_named_pipe "./qzone_out_fifo"
ensure_named_pipe "./presend_in_fifo"
ensure_named_pipe "./presend_out_fifo"
if [[ ! -f "AcountGroupcfg.json" ]]; then
    if [[ -t 0 ]]; then
        echo "未检测到账户组配置文件，将启动账户组引导..."
        guide_account_group_setup
    else
        echo "未检测到账户组配置文件。创建占位模板并退出，请在交互式环境下运行 --oobe 或手动编辑后重试。"
        cat > AcountGroupcfg.json <<'EOF'
{
  "MethGroup": {
    "mangroupid": "",
    "mainqqid": "",
    "mainqq_http_port": "",
    "minorqqid": [],
    "minorqq_http_port": [],
    "max_post_stack": "1",
    "max_image_number_one_post": "20",
    "friend_add_message": "",
    "send_schedule": [],
    "watermark_text": "",
    "quick_replies": {}
  }
}
EOF
        echo "已创建占位模板: AcountGroupcfg.json"
    fi
fi

# 检查关键变量是否设置
check_variable "napcat_access_token" "auto"
check_variable "http-serv-port" "8082"
check_variable "apikey"  "sk-"
check_variable "process_waittime" "120"
check_variable "manage_napcat_internal" "true"
check_variable "max_attempts_qzone_autologin"  "3"
check_variable "at_unprived_sender" "true"
check_variable "text_model" "qwen-plus-latest"
check_variable "vision_model" "qwen-vl-max-latest"
check_variable "vision_pixel_limit" "12000000"
check_variable "vision_size_limit_mb" "9.5"
check_variable "friend_request_window_sec" "300"
check_variable "force_chromium_no-sandbox" "false"
check_variable "use_web_review" "false"
check_variable "web_review_port" "10923"

# 导出 NapCat Token 供后续脚本使用
NAPCAT_ACCESS_TOKEN=$(cfg_get 'napcat_access_token')
export NAPCAT_ACCESS_TOKEN
if [[ -z "$NAPCAT_ACCESS_TOKEN" ]]; then
    echo "[ERR] 未读取到 napcat_access_token，请检查 $CFG。" >&2
    exit 1
fi

source ./Global_toolkit.sh


# 尝试激活现有的虚拟环境
if source ./venv/bin/activate 2>/dev/null; then
    echo "已激活现有的Python虚拟环境."
else
    echo "虚拟环境不存在，正在创建新的Python虚拟环境..."
    python3 -m venv ./venv
    if [ $? -ne 0 ]; then
        echo "创建虚拟环境失败，尝试自动修复 venv 依赖..."
        # 尝试为 APT/DNF/YUM 系列自动安装对应 venv 包，然后重试
        detect_platform
        get_sudo
        if [[ "$PKG_MGR" == "apt" || "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]; then
          # 计算版本化 venv 包名，如 python3.13-venv 或 python3.11-venv
          venv_pkg_by_version=$(python3 -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}-venv")' 2>/dev/null || true)
          venv_pkg_by_version=${venv_pkg_by_version//$'\n'/}
          pkg_to_install=""
          if [[ "$PKG_MGR" == "apt" ]]; then
            candidate="$venv_pkg_by_version"
            if [[ -n "$candidate" ]] && apt-cache show "$candidate" >/dev/null 2>&1; then
              pkg_to_install="$candidate"
            elif apt-cache show python3-venv >/dev/null 2>&1; then
              pkg_to_install="python3-venv"
            else
              pkg_to_install="${candidate:-python3-venv}"
            fi
            echo "[INFO] APT 将安装: $pkg_to_install 以启用 python3 venv"
            if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
              "${SUDO_CMD[@]}" apt-get install -y "$pkg_to_install" || true
            else
              echo "[HINT] 请运行: apt-get install -y $pkg_to_install"
            fi
          else
            # dnf/yum
            pkg_to_install="$venv_pkg_by_version"
            echo "[INFO] ${PKG_MGR^^} 将安装: $pkg_to_install 以启用 python3 venv"
            if (( ${#SUDO_CMD[@]} )) || [[ $(id -u) -eq 0 ]]; then
              if [[ "$PKG_MGR" == "dnf" ]]; then
                "${SUDO_CMD[@]}" dnf -y install "$pkg_to_install" || true
              else
                "${SUDO_CMD[@]}" yum -y install "$pkg_to_install" || true
              fi
            else
              echo "[HINT] 请运行: $PKG_MGR -y install $pkg_to_install"
            fi
          fi
          # 重试创建 venv
          python3 -m venv ./venv
          if [ $? -ne 0 ]; then
            echo "创建虚拟环境仍失败。请手动安装 venv 组件后重试。"
            exit 1
          fi
        else
          echo "创建虚拟环境失败，请确保已安装 Python venv 组件。"
          exit 1
        fi
    fi

    # 激活新创建的虚拟环境
    source ./venv/bin/activate
    if [ $? -ne 0 ]; then
        echo "激活Python虚拟环境失败."
        exit 1
    fi

    echo "Python虚拟环境已激活."

    # 升级 pip
    echo "正在升级 pip..."
    python -m pip install --upgrade pip
    if [ $? -ne 0 ]; then
        echo "升级 pip 失败."
        exit 1
    fi

    # 安装所需的包
    echo "正在安装所需的 Python 包..."
    python -m pip install dashscope bs4 httpx uvicorn fastapi pydantic requests regex pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
    if [ $? -ne 0 ]; then
        echo "安装 Python 包失败."
        exit 1
    fi

    echo "所有包已成功安装."
fi

# 逐包检查并自动修复 Python 依赖
ensure_python_packages

DB_NAME="./cache/OQQWall.db"

#--------------------------------------------------------------------
# 1) 期望表结构
declare -A table_defs
table_defs[sender]='CREATE TABLE sender (
  senderid TEXT,
  receiver TEXT,
  ACgroup  TEXT,
  rawmsg   TEXT,
  modtime  TEXT,
  processtime TEXT,
  PRIMARY KEY (senderid, receiver)
);'
table_defs[preprocess]='CREATE TABLE preprocess (
  tag        INT,
  senderid   TEXT,
  nickname   TEXT,
  receiver   TEXT,
  ACgroup    TEXT,
  AfterLM    TEXT,
  comment    TEXT,
  numnfinal  INT
);'
table_defs[blocklist]='CREATE TABLE blocklist (
  senderid TEXT,
  ACgroup  TEXT,
  receiver TEXT,
  reason   TEXT,
  PRIMARY KEY (senderid, ACgroup)
);'
#--------------------------------------------------------------------
# 2) 辅助函数：提取结构签名   name|TYPE|pkFlag
table_sig () {
  local db=$1 table=$2
  sqlite3 "$db" "PRAGMA table_info($table);" |
  awk -F'|' '{printf "%s|%s|%s\n", $2, toupper($3), $6}'
}
#--------------------------------------------------------------------
# 3) 如果数据库不存在，直接初始化
if [[ ! -f $DB_NAME ]]; then
  printf '数据库缺失，正在初始化…\n'
  sqlite3 "$DB_NAME" <<EOF
${table_defs[sender]}
${table_defs[preprocess]}
${table_defs[blocklist]}
EOF
  exit
fi
#--------------------------------------------------------------------
# 4) 逐表检查
for tbl in sender preprocess blocklist; do

  # （a）表是否存在
  if ! sqlite3 "$DB_NAME" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='$tbl';" |
       grep -q 1; then
    printf '表 %-11s 不存在，正在创建…\n' "$tbl"
    sqlite3 "$DB_NAME" "${table_defs[$tbl]}"
    continue
  fi

  # （b）实际结构
  actual_sig=$(table_sig "$DB_NAME" "$tbl")

  # （c）期望结构：在 :memory: 会话里临时建表再取结构
  expected_sig=$(sqlite3 ":memory:" <<SQL |
${table_defs[$tbl]}
PRAGMA table_info($tbl);
SQL
  awk -F'|' '{printf "%s|%s|%s\n", $2, toupper($3), $6}')

  # （d）比较
  if [[ "$actual_sig" != "$expected_sig" ]]; then
    echo
    echo "⚠  表 $tbl 结构不匹配："
    diff --color=always <(echo "$expected_sig") <(echo "$actual_sig") || true
    read -rp "→ 删除并重建表 $tbl ? 这会导致数据丢失！ [y/N] " ans
    if [[ $ans =~ ^[Yy]$ ]]; then
      sqlite3 "$DB_NAME" "DROP TABLE IF EXISTS $tbl;"
      sqlite3 "$DB_NAME" "${table_defs[$tbl]}"
      echo "表 $tbl 已重建。"
    else
      echo "跳过表 $tbl 的重建。"
    fi
    echo
  fi
done


apikey=$(cfg_get 'apikey')
http_serv_port=$(cfg_get 'http-serv-port')
process_waittime=$(cfg_get 'process_waittime')
manage_napcat_internal=$(cfg_get 'manage_napcat_internal')
max_attempts_qzone_autologin=$(cfg_get 'max_attempts_qzone_autologin')
at_unprived_sender=$(cfg_get 'at_unprived_sender')
text_model=$(cfg_get 'text_model')
vision_model=$(cfg_get 'vision_model')
vision_pixel_limit=$(cfg_get 'vision_pixel_limit')
vision_size_limit_mb=$(cfg_get 'vision_size_limit_mb')
friend_request_window_sec=$(cfg_get 'friend_request_window_sec')
force_chromium_no_sandbox=$(cfg_get 'force_chromium_no-sandbox')
use_web_review=$(cfg_get 'use_web_review')
web_review_port=$(cfg_get 'web_review_port')


DIR="./getmsgserv/rawpost/"

# 定义 JSON 文件名
json_file="AcountGroupcfg.json"
errors=()  # 用于存储所有错误信息

# 用于检查是否有重复的 ID 和端口
mainqqid_list=()
minorqqid_list=()
http_ports_list=()


# 检查 JSON 文件的语法是否正确
if ! jq empty "$json_file" >/dev/null 2>&1; then
  echo "错误：账户组配置文件的 JSON 语法不正确！"
  exit 1
fi

# 获取所有 group 并逐行读取
while read -r group; do
  echo "正在检查 group: $group"
  if [[ -z "$group" ]]; then
    errors+=("错误：检测到空的组名，请检查配置文件的键。")
    continue
  fi
  if [[ ! "$group" =~ ^[A-Za-z0-9_]+$ ]]; then
    errors+=("错误：组名 '$group' 含非法字符，仅允许字母、数字和下划线。")
    continue
  fi
  mangroupid=$(jq -r --arg group "$group" '.[$group].mangroupid' "$json_file")
  mainqqid=$(jq -r --arg group "$group" '.[$group].mainqqid' "$json_file")
  mainqq_http_port=$(jq -r --arg group "$group" '.[$group]["mainqq_http_port"]' "$json_file")
  
  # 检查 minorqqid 数组，处理 null 的情况
  minorqqids=$(jq -r --arg group "$group" '.[$group].minorqqid // [] | .[]' "$json_file")
  
  # 检查 minorqq_http_port 数组，处理 null 的情况
  minorqq_http_ports=$(jq -r --arg group "$group" '.[$group]["minorqq_http_port"] // [] | .[]' "$json_file")

  # 检查 mangroupid 是否存在并且是纯数字
  if [[ -z "$mangroupid" || ! "$mangroupid" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，mangroupid 缺失或不是有效的数字！")
  fi

  # 检查 mainqqid 是否存在并且是纯数字，且不能重复
  if [[ -z "$mainqqid" || ! "$mainqqid" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，mainqqid 缺失或不是有效的数字！")
  else
    if [[ " ${mainqqid_list[*]} " =~ " $mainqqid " ]]; then
      errors+=("错误：mainqqid $mainqqid 在多个组中重复！")
    else
      mainqqid_list+=("$mainqqid")
    fi
  fi

  # 检查 mainqq_http_port 是否存在并且是纯数字，且不能重复
  if [[ -z "$mainqq_http_port" || ! "$mainqq_http_port" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，mainqq_http_port 缺失或不是有效的数字！")
  else
    if [[ " ${http_ports_list[*]} " =~ " $mainqq_http_port " ]]; then
      errors+=("错误：mainqq_http_port $mainqq_http_port 在多个组中重复！")
    else
      http_ports_list+=("$mainqq_http_port")
    fi
  fi

  # 检查 minorqqid 数组是否存在且每个元素是纯数字，且不能重复
  if [ -z "$minorqqids" ]; then
    errors+=("警告：在 $group 中，minorqqid 为空。")
  else
    for minorid in $minorqqids; do
      if [[ ! "$minorid" =~ ^[0-9]+$ ]]; then
        errors+=("错误：在 $group 中，minorqqid 包含非数字值：$minorid")
      else
        if [[ " ${minorqqid_list[*]} " =~ " $minorid " ]]; then
          errors+=("错误：minorqqid $minorid 在多个组中重复！")
        else
          minorqqid_list+=("$minorid")
        fi
      fi
    done
  fi

  # 检查 minorqq_http_port 数组是否存在且每个元素是纯数字，且不能重复
  if [ -z "$minorqq_http_ports" ]; then
    errors+=("警告：在 $group 中，minorqq_http_port 为空。")
  else
    for minorport in $minorqq_http_ports; do
      if [[ ! "$minorport" =~ ^[0-9]+$ ]]; then
        errors+=("错误：在 $group 中，minorqq_http_port 包含非数字值：$minorport")
      else
        if [[ " ${http_ports_list[*]} " =~ " $minorport " ]]; then
          errors+=("错误：minorqq_http_port $minorport 在多个组中重复！")
        else
          http_ports_list+=("$minorport")
        fi
      fi
    done
  fi

  # 检查 minorqqid 和 minorqq_http_port 数量是否一致
  minorqq_count=$(jq -r --arg group "$group" '.[$group].minorqqid | length' "$json_file")
  minorqq_port_count=$(jq -r --arg group "$group" '.[$group]["minorqq_http_port"] | length' "$json_file")

  if [ "$minorqq_count" -ne "$minorqq_port_count" ]; then
    errors+=("错误：在 $group 中，minorqqid 的数量 ($minorqq_count) 与 minorqq_http_port 的数量 ($minorqq_port_count) 不匹配。")
  fi
  tbl_name=$(_sanitize_tbl "$group")

  # —— 杂项配置校验（允许为空）——
  max_post_stack=$(jq -r --arg group "$group" '.[$group].max_post_stack // empty' "$json_file")
  max_image_number_one_post=$(jq -r --arg group "$group" '.[$group].max_image_number_one_post // empty' "$json_file")
  friend_add_message=$(jq -r --arg group "$group" '.[$group].friend_add_message // empty' "$json_file")
  friend_add_message_type=$(jq -r --arg group "$group" '.[$group].friend_add_message | type' "$json_file")
  send_schedule_type=$(jq -r --arg group "$group" '.[$group].send_schedule | type' "$json_file")
  watermark_text=$(jq -r --arg group "$group" '.[$group].watermark_text // empty' "$json_file")
  watermark_text_type=$(jq -r --arg group "$group" '.[$group].watermark_text | type' "$json_file")
  
  # —— 校验 max_*：存在则必须为纯数字 ——
  if [[ -n "$max_post_stack" && ! "$max_post_stack" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，max_post_stack 存在但不是纯数字：$max_post_stack")
  fi
  if [[ -n "$max_image_number_one_post" && ! "$max_image_number_one_post" =~ ^[0-9]+$ ]]; then
    errors+=("错误：在 $group 中，max_image_number_one_post 存在但不是纯数字：$max_image_number_one_post")
  fi

  # —— 校验 friend_add_message：可空；若存在必须为字符串 ——
  if [[ "$friend_add_message_type" != "null" && "$friend_add_message_type" != "string" ]]; then
    errors+=("错误：在 $group 中，friend_add_message 必须是字符串或为空（当前为 $friend_add_message_type）。")
  fi

  # —— 校验 watermark_text：可空；若存在必须为字符串 ——
  if [[ "$watermark_text_type" != "null" && "$watermark_text_type" != "string" ]]; then
    errors+=("错误：在 $group 中，watermark_text 必须是字符串或为空（当前为 $watermark_text_type）。")
  fi
  
  # —— 校验 send_schedule：可空；若存在必须为字符串数组，元素为 HH:MM ——
  if [[ "$send_schedule_type" != "null" ]]; then
    if [[ "$send_schedule_type" != "array" ]]; then
      errors+=("错误：在 $group 中，send_schedule 必须是数组（当前为 $send_schedule_type）。")
    else
      while IFS= read -r t; do
        # 允许 9:00 或 09:00；小时 0–23，分钟 00–59
        if [[ -n "$t" && ! "$t" =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]]; then
          errors+=("错误：在 $group 中，send_schedule 含非法时间：$t（应为 HH:MM，例如 09:00）")
        fi
      done < <(jq -r --arg group "$group" '.[$group].send_schedule[] // empty' "$json_file")
    fi
  fi

  # —— 校验 quick_replies：可空；若存在必须为对象，键值对为字符串 ——
  quick_replies_type=$(jq -r --arg group "$group" '.[$group].quick_replies | type' "$json_file")
  if [[ "$quick_replies_type" != "null" ]]; then
    if [[ "$quick_replies_type" != "object" ]]; then
      errors+=("错误：在 $group 中，quick_replies 必须是对象（当前为 $quick_replies_type）。")
    else
      # 检查每个快捷回复指令是否与审核指令冲突
      audit_commands=("是" "否" "匿" "等" "删" "拒" "立即" "刷新" "重渲染" "扩列审查" "评论" "回复" "展示" "拉黑")
      while IFS= read -r entry; do
        cmd_name=$(jq -r '.key' <<<"$entry")
        cmd_type=$(jq -r '.value | type' <<<"$entry")
        cmd_content=$(jq -r '.value' <<<"$entry")
        if [[ -n "$cmd_name" ]]; then
          if [[ "$cmd_type" != "string" ]]; then
            errors+=("错误：在 $group 中，快捷回复 '$cmd_name' 的值必须是字符串。")
            continue
          fi
          # 检查是否与审核指令冲突
          for audit_cmd in "${audit_commands[@]}"; do
            if [[ "$cmd_name" == "$audit_cmd" ]]; then
              errors+=("错误：在 $group 中，快捷回复指令 '$cmd_name' 与审核指令冲突。")
              break
            fi
          done
          
          if [[ -z "$cmd_content" ]]; then
            errors+=("错误：在 $group 中，快捷回复内容不能为空。")
          fi
        fi
      done < <(jq -c --arg group "$group" '.[$group].quick_replies | to_entries[]' "$json_file")
    fi
  fi
  # 定义期望结构 SQL
  expected_schema="CREATE TABLE \"$tbl_name\" (tag INT, num INT, port INT, senderid TEXT);"

  # 表是否存在
  if ! sqlite3 "$DB_NAME" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='$tbl_name';" | grep -q 1; then
    echo "表 $tbl_name 不存在，正在创建..."
    sqlite3 "$DB_NAME" "$expected_schema"
    continue
  fi

  # 实际结构
  actual_sig=$(sqlite3 "$DB_NAME" "PRAGMA table_info('$tbl_name');" | \
    awk -F'|' '{printf "%s|%s|%s\n", $2, toupper($3), $6}')

  # 期望结构（用 :memory: 临时解析）
  expected_sig=$(sqlite3 ":memory:" <<SQL |
$expected_schema
PRAGMA table_info('$tbl_name');
SQL
  awk -F'|' '{printf "%s|%s|%s\n", $2, toupper($3), $6}')

  if [[ "$actual_sig" != "$expected_sig" ]]; then
    echo
    echo "⚠  表 $tbl_name 结构不匹配："
    diff --color=always <(echo "$expected_sig") <(echo "$actual_sig") || true
    echo "正在删除并重建表 $tbl_name..."
    sqlite3 "$DB_NAME" "DROP TABLE IF EXISTS \"$tbl_name\";"
    sqlite3 "$DB_NAME" "$expected_schema"
    echo "表 $tbl_name 已重建。"
    echo
  fi

done <<< "$(jq -r '. | keys[]' "$json_file")"

# 打印检查结果：区分“错误”和“警告”，仅在存在“错误”时退出
has_error=0
if [ ${#errors[@]} -ne 0 ]; then
  for msg in "${errors[@]}"; do
    if [[ "$msg" == 错误：* ]]; then
      has_error=1
      break
    fi
  done
fi

if [ $has_error -eq 1 ]; then
  # 若检测到空模板且处于交互式终端，则进入账户组引导
  if is_empty_account_group_template && [[ -t 0 ]]; then
    echo "检测到账户组配置为空模板，启动账户组引导..."
    guide_account_group_setup
    echo "账户组配置已更新，重新启动主程序..."
    exec bash "$0" "$@"
  else
    echo "以下错误已被发现："
    for msg in "${errors[@]}"; do
      echo "$msg"
    done
    exit 1
  fi
else
  if [ ${#errors[@]} -ne 0 ]; then
    echo "发现以下警告："
    for msg in "${errors[@]}"; do
      # 只打印警告行
      if [[ "$msg" == 警告：* ]]; then
        echo "$msg"
      fi
    done
  else
    echo "账户组配置文件验证完成，没有发现错误。"
  fi
fi
mangroupids=($(jq -r '.[] | .mangroupid' ./AcountGroupcfg.json))

#写入whitelist
## 由于多账号支持要求，QChatGPT的自动同步已经停用
#if [ -n "$commgroup_id" ]; then 
#    if [[ "$enable_selenium_autocorrecttag_onstartup" == true ]]; then
#        echo 同步校群id...
#        group_id="group_${commgroup_id}"
#        jq --arg group_id "$group_id" '.["access-control"].whitelist = [$group_id]' "./qqBot/QChatGPT/data/config/pipeline.json" > temp.json && mv temp.json "./qqBot/QChatGPT/data/config/pipeline.json"
#    fi
#    jq --arg apikey "$apikey" '.keys.openai = [$apikey]' ./qqBot/QChatGPT/data/config/provider.json > tmp.json && mv tmp.json ./qqBot/QChatGPT/data/config/provider.json
#fi

# Activate virtual environment


json_content=$(cat ./AcountGroupcfg.json)
mapfile -t runidlist < <(jq -r '.[] | (.mainqqid // empty), (.minorqqid[]? // empty)' <<<"$json_content" | sed '/^$/d')
mapfile -t mainqqlist < <(jq -r '.[] | .mainqqid // empty' <<<"$json_content" | sed '/^$/d')
getinfo(){
    local target="$1"
    local json_file="./AcountGroupcfg.json"

    if [[ -z ${target:-} ]]; then
        echo "请提供 mainqqid 或 minorqqid。"
        return 1
    fi

    local entry
    entry=$(jq -r --arg id "$target" '
        to_entries[] | select(.value.mainqqid == $id or (.value.minorqqid[]? == $id))
    ' "$json_file")

    if [[ -z "$entry" ]]; then
        echo "未找到ID为 $target 的信息。"
        return 1
    fi

    groupname=$(jq -r '.key' <<<"$entry")
    groupid=$(jq -r '.value.mangroupid' <<<"$entry")
    mainqqid=$(jq -r '.value.mainqqid' <<<"$entry")
    mainqq_http_port=$(jq -r '.value.mainqq_http_port' <<<"$entry")
    mapfile -t _minor_ids   < <(jq -r '.value.minorqqid[]?' <<<"$entry")
    mapfile -t _minor_ports < <(jq -r '.value.minorqq_http_port[]?' <<<"$entry")

    port=""
    if [[ "$target" == "$mainqqid" ]]; then
        port="$mainqq_http_port"
    else
        for i in "${!_minor_ids[@]}"; do
            if [[ "$target" == "${_minor_ids[$i]}" ]]; then
                port="${_minor_ports[$i]:-}"
                break
            fi
        done
    fi

    if [[ -z "$port" ]]; then
        echo "警告：未在 $groupname 组找到 $target 对应的 http 端口。"
        return 1
    fi

    return 0
}
if pgrep -f "python3 getmsgserv/serv.py" > /dev/null
then
    echo "serv.py is already running"
else
    python3 getmsgserv/serv.py &
    echo "serv.py started"
fi

if pgrep -f "python3 ./SendQzone/qzone-serv-pipe.py" > /dev/null
then
    echo "qzone-serv-pipe.py is already running"
else
    if [[ $1 == --test ]]; then
      echo "请自行启动测试服务器"
    else
      python3 ./SendQzone/qzone-serv-pipe.py &
      echo "qzone-serv-pipe.py started"
    fi
fi

if pgrep -f "./Sendcontrol/sendcontrol.sh" > /dev/null
then
    echo "sendcontrol.sh is already running"
else
    ./Sendcontrol/sendcontrol.sh &
    echo "sendcontrol.sh started"
fi

# 启动网页审核（可选）
if [[ "$use_web_review" == "true" ]]; then
  if pgrep -f "python3 web_review/web_review.py" > /dev/null; then
    echo "web_review.py is already running"
  else
    echo "starting web_review on port $web_review_port"
    (cd web_review && PORT="$web_review_port" HOST="0.0.0.0" nohup python3 web_review.py --host 0.0.0.0 --port "$web_review_port" > web_review.log 2>&1 &)
    echo "web_review started at port $web_review_port"
  fi
else
  echo "use_web_review != true，跳过启动网页审核服务。"
fi


# Check if the OneBot server process is running
if [[ "$manage_napcat_internal" == "true" ]]; then
    if pgrep -f "xvfb-run -a qq --no-sandbox -q" > /dev/null; then
        kill_pat "xvfb-run -a qq --no-sandbox -q"
    fi

    if command -v xvfb-run >/dev/null 2>&1; then
      for qqid in "${runidlist[@]}"; do
          echo "Starting QQ process for ID: $qqid"
          nohup xvfb-run -a qq --no-sandbox -q "$qqid" > ./NapCatlog 2>&1 &
      done
      sleep 10
    else
      echo "[WARN] 未检测到 xvfb-run。NapCat 应自行安装其依赖；或在 OOBE 中选择 manage_napcat_internal=false。已跳过内部启动 QQ。"
    fi
else
    echo "manage_napcat_internal != true，QQ相关进程未自动管理。请自行处理 Napcat QQ 客户端。"
fi

echo 系统启动完毕
echo -e "\033[1;34m powered by \033[0m"
echo -e "\033[1;34m   ____  ____  ____ _       __      ____\n  / __ \/ __ \/ __ \ |     / /___ _/ / /\n / / / / / / / / / / | /| / / __ \`/ / /\n/ /_/ / /_/ / /_/ /| |/ |/ / /_/ / / /\n\____/\___\_\___\_\|__/|__/\__,_/_/_/\n\033[0m"


for mqqid in "${mainqqlist[@]}"; do
  if getinfo "$mqqid"; then
    sendmsggroup 系统已启动
  else
    echo "跳过向 $mqqid 发送启动通知。"
  fi
done

while true; do
    now=$(date +%s)
    next=$(date -d "next hour" +%s)
    if [[ "$(date +%H:%M)" == "07:00" ]]; then
        echo 'reach 7:00'
        for qqid in "${runidlist[@]}"; do
            echo "Like everyone with ID: $qqid"
            if getinfo "$qqid"; then
                python3 qqBot/likeeveryday.py "$port"
            else
                echo "警告：未找到 QQ $qqid 的端口配置，跳过点赞。"
            fi
        done
    fi
    sleep "$(( next - now ))"
done
