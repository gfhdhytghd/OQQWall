#!/bin/bash
# NapCat录制重放工具演示脚本

echo "🎭 NapCat录制重放工具演示"
echo "=========================================="
echo ""

# 检查依赖
echo "📋 检查环境..."
if ! command -v python3 &> /dev/null; then
    echo "❌ 缺少python3"
    exit 1
fi

if ! python3 -c "import requests" 2>/dev/null; then
    echo "❌ 缺少requests库，请运行: pip3 install requests"
    exit 1
fi

echo "✅ 环境检查通过"
echo ""

# 显示文件列表
echo "📁 创建的文件："
echo "   napcat_recorder.py    - HTTP POST录制器"
echo "   napcat_replayer.py    - 高级重放器"
echo "   napcat_controller.py  - 一键重放控制器"
echo "   start_recorder.sh     - 录制器启动脚本"
echo "   start_controller.sh   - 控制器启动脚本"
echo "   test_server.py        - 测试HTTP服务器"
echo "   README.md             - 详细使用说明"
echo ""

# 演示基本功能
echo "🎮 演示一键重放功能..."
echo "   (使用示例数据到httpbin.org测试)"
echo ""

# 启动测试
python3 napcat_controller.py --once --target http://httpbin.org/post

echo ""
echo "✅ 演示完成！"
echo ""
echo "🚀 快速开始："
echo "   1. 录制消息: ./start_recorder.sh"
echo "   2. 重放消息: ./start_controller.sh"
echo ""
echo "📖 详细说明: cat README.md"
echo ""
