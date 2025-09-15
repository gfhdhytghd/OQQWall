# OQQWall 网页审核面板 - Linux 部署指南

## 📋 系统概述

OQQWall 网页审核面板是一个基于 Python 的现代化 Web 界面，用于管理校园墙投稿内容的审核流程。本指南将帮助您在 Linux 系统上部署和运行该系统。

## 🚀 快速开始

### 系统要求

- **操作系统**: Linux (Ubuntu 18.04+, CentOS 7+, Debian 9+)
- **Python**: 3.7 或更高版本
- **内存**: 最少 512MB RAM
- **磁盘**: 最少 100MB 可用空间
- **网络**: 需要访问数据库和文件系统

### 1. 环境准备

```bash
# 进入项目根目录
cd /path/to/OQQWall

# 检查 Python 版本
python3 --version
# 输出应显示 Python 3.7 或更高版本

# 检查项目结构
ls -la web_review/
ls -la cache/
ls -la getmsgserv/processsend.sh
```

### 2. 依赖检查

```bash
# 检查必要的目录和文件
ls -la cache/
ls -la getmsgserv/processsend.sh

# 如果目录不存在，创建它们
mkdir -p cache/prepost
mkdir -p cache/picture

# 检查数据库文件
ls -la cache/OQQWall.db

# 检查配置文件
ls -la oqqwall.config
```

### 3. 基本运行

#### 方法一：直接运行（推荐用于测试）

```bash
# 进入 web_review 目录
cd web_review/

# 使用默认设置启动（端口 8090，监听所有接口）
python3 web_review.py

# 指定端口运行
python3 web_review.py --port 8090

# 仅本地访问
python3 web_review.py --host 127.0.0.1 --port 8090

# 后台运行
nohup python3 web_review.py --port 8090 > web_review.log 2>&1 &

# 查看后台进程
ps aux | grep web_review.py

# 停止后台进程
kill <进程ID>
```

#### 方法二：使用启动脚本

```bash
# 给启动脚本执行权限
chmod +x start_web_review.sh

# 运行启动脚本
./start_web_review.sh
```

### 4. 系统服务运行（推荐用于生产环境）

#### 创建 systemd 服务文件

```bash
# 创建服务文件
sudo nano /etc/systemd/system/oqqwall-web-review.service
```

服务文件内容：
```ini
[Unit]
Description=OQQWall Web Review Panel
Documentation=https://github.com/gfhdhytghd/OQQWall
After=network.target
Wants=network.target

[Service]
Type=simple
User=your_username
Group=your_group
WorkingDirectory=/path/to/OQQWall/web_review
ExecStart=/usr/bin/python3 /path/to/OQQWall/web_review/web_review.py --host 0.0.0.0 --port 8090
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=oqqwall-web-review

# 安全设置
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/path/to/OQQWall/cache

[Install]
WantedBy=multi-user.target
```

#### 启动服务
```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启用服务（开机自启）
sudo systemctl enable oqqwall-web-review.service

# 启动服务
sudo systemctl start oqqwall-web-review.service

# 查看服务状态
sudo systemctl status oqqwall-web-review.service

# 查看日志
sudo journalctl -u oqqwall-web-review.service -f

# 停止服务
sudo systemctl stop oqqwall-web-review.service
```

### 5. 防火墙配置

```bash
# Ubuntu/Debian 系统
sudo ufw allow 8090

# CentOS/RHEL 系统
sudo firewall-cmd --permanent --add-port=8090/tcp
sudo firewall-cmd --reload

# 检查端口是否开放
netstat -tlnp | grep 8090
```

### 6. 访问系统

```bash
# 本地访问
http://localhost:8090

# 远程访问（需要配置防火墙）
http://your_server_ip:8090

# 检查服务是否正常
curl http://localhost:8090/api/stats
```

## 🔧 常见问题解决

### 1. 端口被占用
```bash
# 查看端口占用
sudo netstat -tlnp | grep 8090

# 杀死占用进程
sudo kill -9 <进程ID>

# 或使用其他端口
python3 web_review.py --port 8091
```

### 2. 权限问题
```bash
# 给脚本执行权限
chmod +x web_review.py
chmod +x getmsgserv/processsend.sh

# 给目录读写权限
chmod -R 755 cache/
```

### 3. Python 依赖问题
```bash
# 检查 Python 版本
python3 --version

# 如果版本过低，安装新版本
# Ubuntu/Debian
sudo apt update
sudo apt install python3.9 python3.9-venv

# CentOS/RHEL
sudo yum install python39
```

### 4. 数据库问题
```bash
# 检查数据库文件
ls -la cache/OQQWall.db

# 如果不存在，确保主系统已初始化
# 运行主系统的初始化脚本
bash main.sh
```

## 🚀 高级配置

### 1. 反向代理配置（Nginx）

创建 Nginx 配置文件：
```bash
sudo nano /etc/nginx/sites-available/oqqwall-review
```

配置内容：
```nginx
server {
    listen 80;
    server_name your_domain.com;

    location / {
        proxy_pass http://localhost:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启用配置：
```bash
sudo ln -s /etc/nginx/sites-available/oqqwall-review /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 2. SSL 配置（可选）

使用 Let's Encrypt：
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your_domain.com
```

### 3. 日志配置

创建日志轮转配置：
```bash
sudo nano /etc/logrotate.d/oqqwall-review
```

内容：
```
/path/to/OQQWall/web_review.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 your_username your_username
    postrotate
        systemctl reload oqqwall-web-review.service
    endscript
}
```

## 📊 监控和维护

### 1. 服务监控
```bash
# 查看服务状态
sudo systemctl status oqqwall-web-review.service

# 查看实时日志
sudo journalctl -u oqqwall-web-review.service -f

# 查看资源使用
top -p $(pgrep -f web_review.py)
```

### 2. 性能监控
```bash
# 检查内存使用
ps aux | grep web_review.py

# 检查网络连接
netstat -an | grep 8090

# 检查系统负载
uptime
```

### 3. 定期维护
```bash
# 清理日志文件
sudo journalctl --vacuum-time=30d

# 检查磁盘空间
df -h

# 更新系统
sudo apt update && sudo apt upgrade
```

## 🔒 安全建议

### 1. 用户权限
```bash
# 创建专用用户
sudo useradd -r -s /bin/false oqqwall

# 修改文件所有者
sudo chown -R oqqwall:oqqwall /path/to/OQQWall

# 修改服务文件中的用户
sudo nano /etc/systemd/system/oqqwall-web-review.service
# 将 User=your_username 改为 User=oqqwall
```

### 2. 网络安全
```bash
# 只允许特定IP访问
sudo ufw allow from 192.168.1.0/24 to any port 8090

# 使用 fail2ban 防止暴力攻击
sudo apt install fail2ban
sudo nano /etc/fail2ban/jail.local
```

## 📝 启动脚本示例

创建启动脚本：
```bash
nano start_web_review.sh
```

脚本内容：
```bash
#!/bin/bash

# OQQWall Web Review 启动脚本

# 配置变量
SCRIPT_DIR="/path/to/OQQWall"
PORT="8090"
LOG_FILE="$SCRIPT_DIR/web_review.log"
PID_FILE="$SCRIPT_DIR/web_review.pid"

# 进入脚本目录
cd "$SCRIPT_DIR"

# 检查是否已在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "服务已在运行 (PID: $PID)"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# 启动服务
echo "启动 OQQWall Web Review 服务..."
python3 web_review.py --port "$PORT" > "$LOG_FILE" 2>&1 &
PID=$!

# 保存 PID
echo $PID > "$PID_FILE"

echo "服务已启动 (PID: $PID)"
echo "访问地址: http://localhost:$PORT"
echo "日志文件: $LOG_FILE"
```

给脚本执行权限：
```bash
chmod +x start_web_review.sh
```

## 🎯 快速启动命令

```bash
# 一键启动（推荐）
cd /path/to/OQQWall && python3 web_review.py --port 8090

# 后台启动
cd /path/to/OQQWall && nohup python3 web_review.py --port 8090 > web_review.log 2>&1 &

# 使用 systemd 服务
sudo systemctl start oqqwall-web-review.service
```

现在您可以根据需要选择合适的运行方式了！


