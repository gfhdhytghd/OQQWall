#!/bin/bash
# NapCat录制器快速启动脚本

echo "🎙️ NapCat HTTP POST 录制器启动脚本"
echo "==============================================="

# 默认设置
DEFAULT_PORT=8083
DEFAULT_DIR="recordings"

# 读取用户输入
read -p "录制端口 [$DEFAULT_PORT]: " PORT
read -p "录制目录 [$DEFAULT_DIR]: " DIR

# 使用默认值
PORT=${PORT:-$DEFAULT_PORT}
DIR=${DIR:-$DEFAULT_DIR}

echo ""
echo "配置信息:"
echo "  端口: $PORT"
echo "  目录: $DIR"
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到python3"
    exit 1
fi

# 创建目录
mkdir -p "$DIR"

echo "🚀 启动录制器..."
echo "📍 NapCat请设置HTTP POST目标为: http://localhost:$PORT"
echo "🌐 Web状态页面: http://localhost:$PORT"
echo "⏹️  按Ctrl+C停止录制"
echo ""

# 启动录制器
python3 napcat_recorder.py --port "$PORT" --dir "$DIR"

echo ""
echo "📁 录制数据保存在: $(realpath "$DIR")"
echo "✅ 录制器已停止"
