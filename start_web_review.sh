#!/bin/bash

# OQQWall Web Review 启动脚本
# 适用于 Linux 系统

# --- 路径配置 ---
# SCRIPT_DIR 设置为脚本所在的 OQQWall/ 根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# WEB_DIR 指向新的 web_review/ 子目录
WEB_DIR="$SCRIPT_DIR/web_review"
PORT="${PORT:-8090}"
HOST="${HOST:-0.0.0.0}"
# 日志和PID文件也放入子目录，保持根目录整洁
LOG_FILE="$WEB_DIR/web_review.log"
PID_FILE="$WEB_DIR/web_review.pid"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# 启动服务
start_service() {
    print_message $BLUE "🚀 启动 OQQWall Web Review 服务..."
    
    # 检查目标脚本是否存在
    if [ ! -f "$WEB_DIR/web_review.py" ]; then
        print_message $RED "❌ 错误：找不到启动目标 $WEB_DIR/web_review.py"
        exit 1
    fi
    
    # 检查是否已在运行
    if [ -f "$PID_FILE" ]; then
        local old_pid=$(cat "$PID_FILE")
        if ps -p $old_pid > /dev/null 2>&1; then
            print_message $YELLOW "⚠️  服务已在运行 (PID: $old_pid)"
            print_message $BLUE "📍 访问地址：http://localhost:$PORT"
            exit 0
        else
            rm -f "$PID_FILE"
        fi
    fi
    
    # 【关键修改】进入 OQQWall 根目录执行 Python 命令
    # 这样 Python 脚本的相对路径才能正确找到其他文件
    cd "$SCRIPT_DIR"
    
    # 启动服务，目标是子目录中的脚本
    python3 "$WEB_DIR/web_review.py" --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
    local pid=$!
    
    echo $pid > "$PID_FILE"
    
    sleep 2
    
    if ps -p $pid > /dev/null 2>&1; then
        print_message $GREEN "✅ 服务启动成功！"
        print_message $BLUE "📍 本地访问：http://localhost:$PORT"
        if [ "$HOST" = "0.0.0.0" ]; then
            print_message $BLUE "📍 外部访问：http://$(hostname -I | awk '{print $1}'):$PORT"
        fi
        print_message $BLUE "📍 PID 文件：$PID_FILE"
        print_message $BLUE "📍 日志文件：$LOG_FILE"
        print_message $YELLOW "💡 按 Ctrl+C 停止服务"
        
        trap 'stop_service' INT TERM
        wait $pid
    else
        print_message $RED "❌ 服务启动失败"
        print_message $YELLOW "📋 查看日志：tail -f $LOG_FILE"
        exit 1
    fi
}

# 停止服务
stop_service() {
    print_message $YELLOW "🛑 正在停止服务..."
    
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p $pid > /dev/null 2>&1; then
            kill $pid 2>/dev/null
            sleep 1
            if ps -p $pid > /dev/null 2>&1; then
                kill -9 $pid 2>/dev/null
            fi
        fi
        rm -f "$PID_FILE"
    fi
    
    print_message $GREEN "✅ 服务已停止"
    exit 0
}

# 主函数
main() {
    local action="${1:-start}"
    
    case "$action" in
        "start")
            start_service
            ;;
        "stop")
            stop_service
            ;;
        *)
            print_message $RED "❌ 未知选项：$action"
            exit 1
            ;;
    esac
}

main "$@"