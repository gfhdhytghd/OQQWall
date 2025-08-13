#!/bin/bash
# NapCat控制器快速启动脚本

echo "🎮 NapCat一键重放控制器启动脚本"
echo "==============================================="

# 默认设置
DEFAULT_DIR="recordings"
DEFAULT_TARGET="http://localhost:8082"

# 检查录制目录
if [ ! -d "$DEFAULT_DIR" ]; then
    echo "❌ 录制目录不存在: $DEFAULT_DIR"
    echo "请先使用 start_recorder.sh 录制一些消息"
    exit 1
fi

# 检查是否有录制文件
if [ ! -f "$DEFAULT_DIR"/session_*.json ]; then
    echo "❌ 没有找到录制会话文件"
    echo "请先使用 start_recorder.sh 录制一些消息"
    exit 1
fi

# 读取用户输入
read -p "录制目录 [$DEFAULT_DIR]: " DIR
read -p "目标URL [$DEFAULT_TARGET]: " TARGET

# 使用默认值
DIR=${DIR:-$DEFAULT_DIR}
TARGET=${TARGET:-$DEFAULT_TARGET}

echo ""
echo "配置信息:"
echo "  录制目录: $DIR"
echo "  目标URL: $TARGET"
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到python3"
    exit 1
fi

# 检查requests库
if ! python3 -c "import requests" 2>/dev/null; then
    echo "❌ 错误: 缺少requests库"
    echo "请安装: pip3 install requests"
    exit 1
fi

echo "🚀 启动控制器..."
echo "💡 按Enter键重放消息，输入's'管理会话，输入'q'退出"
echo ""

# 启动控制器
python3 napcat_controller.py --dir "$DIR" --target "$TARGET"

echo ""
echo "✅ 控制器已退出"
