#!/bin/bash

# OQQWall Web Review 网络访问修复脚本

echo "🔧 OQQWall Web Review 网络访问修复"
echo "=================================="

# 获取本机IP地址
LOCAL_IP=$(hostname -I | awk '{print $1}')

echo "📍 检测到本机IP: $LOCAL_IP"
echo ""

# 停止现有服务
echo "🛑 停止现有服务..."
pkill -f web_review.py 2>/dev/null
sleep 2

# 启动新服务（监听所有接口）
echo "🚀 启动服务（支持外部访问）..."
cd "$(dirname "$0")"

# 使用后台运行
nohup python3 web_review.py --host 0.0.0.0 --port 10923 > web_review.log 2>&1 &
SERVICE_PID=$!

# 等待服务启动
sleep 3

# 检查服务是否启动成功
if ps -p $SERVICE_PID > /dev/null 2>&1; then
    echo "✅ 服务启动成功！"
    echo ""
    echo "🌐 访问地址："
    echo "   本地访问: http://localhost:10923"
    echo "   外部访问: http://$LOCAL_IP:10923"
    echo ""
    echo "📋 服务信息："
    echo "   PID: $SERVICE_PID"
    echo "   日志: web_review.log"
    echo "   端口: 10923"
    echo "   监听: 0.0.0.0 (所有接口)"
    echo ""
    
    # 测试服务是否响应
    echo "🔍 测试服务响应..."
    if curl -s http://localhost:10923/api/stats > /dev/null 2>&1; then
        echo "✅ 服务响应正常"
    else
        echo "⚠️  服务可能还在启动中，请稍等片刻"
    fi
    
    echo ""
    echo "💡 现在可以通过以下方式访问："
    echo "   - 在浏览器中访问: http://$LOCAL_IP:10923"
    echo "   - 或访问: http://localhost:10923"
    echo ""
    echo "🛑 停止服务: kill $SERVICE_PID"
    
else
    echo "❌ 服务启动失败"
    echo "📋 查看日志: tail -f web_review.log"
    exit 1
fi

