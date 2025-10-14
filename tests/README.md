# NapCat HTTP POST 录制和重放工具

这是一套用于录制和重放来自NapCat的HTTP POST请求的工具，可以帮助你调试、测试和模拟QQ消息处理流程。

## 🎯 功能特性

- **录制**: 捕获并保存来自NapCat的HTTP POST请求
- **重放**: 重新发送录制的请求到指定目标
- **一键操作**: 简单的按Enter键即可重放消息
- **会话管理**: 支持多个录制会话的管理和切换
- **交互式界面**: 友好的命令行交互界面

## 📁 文件说明

| 文件 | 功能 |
|------|------|
| `napcat_recorder.py` | HTTP POST录制器，捕获napcat发送的请求 |
| `napcat_replayer.py` | 高级重放器，支持详细的重放控制 |
| `napcat_controller.py` | 简化控制器，实现"按Enter发送"功能 |
| `emuqzone_uds.py` | QZone UDS 服务模拟器（通过 Unix Domain Socket 通讯） |
| `emuqzoneserv.py` | QZone 管道服务模拟器（旧版 FIFO 方案） |

## 🚀 快速开始

### 第一步：录制请求

1. 启动录制器：
   ```bash
   python3 napcat_recorder.py --port 8083
   ```

2. 配置NapCat，将HTTP POST目标设置为：
   ```
   http://localhost:8083
   ```

3. 在QQ中发送一些测试消息，录制器会自动捕获并保存

4. 按 `Ctrl+C` 停止录制

### 第二步：重放消息

使用简化控制器（推荐）：
```bash
python3 napcat_controller.py
```

或使用高级重放器：
```bash
python3 napcat_replayer.py --interactive
```

### 第三步：一键重放

在控制器中：
- 直接按 **Enter** 键重放所有录制的请求
- 输入 `s` 管理会话
- 输入 `c` 配置设置
- 输入 `q` 退出

## 📖 详细使用说明

### 录制器 (napcat_recorder.py)

```bash
# 基本使用
python3 napcat_recorder.py

# 自定义端口和目录
python3 napcat_recorder.py --port 8084 --dir my_recordings

# 查看帮助
python3 napcat_recorder.py --help
```

**录制器特性：**
- 自动创建录制目录
- 实时保存每个请求
- 生成会话文件汇总
- 提供Web状态页面 (http://localhost:端口)

### 重放器 (napcat_replayer.py)

```bash
# 交互模式
python3 napcat_replayer.py --interactive

# 命令行模式
python3 napcat_replayer.py --target http://localhost:8082 --session 1

# 重放单个请求
python3 napcat_replayer.py --target http://localhost:8082 --session 1 --request 5

# 自定义延迟
python3 napcat_replayer.py --target http://localhost:8082 --delay 2.0
```

### 控制器 (napcat_controller.py)

```bash
# 交互模式（默认）
python3 napcat_controller.py

# 一次性执行
python3 napcat_controller.py --once --target http://localhost:8082

# 自定义配置文件
python3 napcat_controller.py --config my_config.json
```

**控制器配置文件 (controller_config.json)：**
```json
{
  "target_url": "http://localhost:8082",
  "default_session": "20250101_120000",
  "replay_delay": 0.5,
  "auto_select_latest": true
}
```

## 📂 录制文件结构

```
recordings/
├── session_20250101_120000.json      # 会话汇总文件
├── request_20250101_120000_0001.json # 单个请求文件
├── request_20250101_120000_0002.json
└── ...
```

**会话文件格式：**
```json
{
  "session_id": "20250101_120000",
  "start_time": "2025-01-01T12:00:00",
  "end_time": "2025-01-01T12:05:00",
  "requests": [
    {
      "request_id": 1,
      "timestamp": "2025-01-01T12:00:01",
      "method": "POST",
      "path": "/",
      "headers": {...},
      "body": "{...}",
      "body_parsed": {...}
    }
  ]
}
```

## 🔧 配置说明

### NapCat配置

1. 在NapCat的配置中启用HTTP POST功能
2. 设置HTTP POST URL为录制器地址：`http://localhost:8083`
3. 确保启用"报告自身消息"选项

### 目标服务器配置

重放时需要指定目标服务器，通常是：
- 你的QQ机器人服务器：`http://localhost:8082`
- 测试服务器或其他HTTP服务

## 🎮 使用场景

### 场景1：调试消息处理逻辑

1. 录制真实用户消息
2. 重复重放到开发环境测试处理逻辑
3. 修改代码后立即重放验证

### 场景2：压力测试

1. 录制一批典型消息
2. 快速重放多次模拟高并发
3. 观察系统性能表现

### 场景3：功能演示

1. 录制精心准备的演示消息
2. 在演示时一键重放
3. 展示系统响应效果

## 🛠️ 故障排除

### 常见问题

**Q: 录制器无法启动**
- 检查端口是否被占用
- 确保有权限监听指定端口
- 查看错误日志排查具体问题

**Q: 重放请求失败**
- 检查目标URL是否正确
- 确认目标服务器正在运行
- 验证网络连接是否正常

**Q: 没有录制到消息**
- 确认NapCat配置正确
- 检查HTTP POST URL设置
- 验证录制器端口配置

**Q: 消息格式错误**
- 检查录制的JSON文件格式
- 确认消息内容完整性
- 验证目标服务器接口兼容性

### 日志调试

所有程序都提供详细的日志输出，可以通过查看日志来诊断问题：

```bash
# 启用DEBUG级别日志
python3 napcat_recorder.py --port 8083 2>&1 | tee recorder.log
```

## 📝 注意事项

1. **端口冲突**: 确保录制器端口不与其他服务冲突
2. **数据安全**: 录制文件可能包含敏感信息，注意保护
3. **目标服务**: 重放时确保目标服务器能正确处理请求
4. **性能影响**: 大量重放请求时注意目标服务器性能
5. **版本兼容**: 确保录制和重放环境的API版本兼容

## 🔗 相关链接

- [NapCat官方文档](https://napneko.github.io/zh-CN/)
- [OneBot标准](https://onebot.dev/)
- [OQQWall项目主页](../README.md)

---

💡 **提示**: 建议先在测试环境熟悉工具使用，再用于生产环境的调试和测试。
### UDS 模拟器 (emuqzone_uds.py)

用于与 UDS 版 QZone 发送服务联调：

```bash
# 启动 UDS 模拟器（默认套接字 ./qzone_uds.sock，Web 8086）
python3 tests/emuqzone_uds.py --sock ./qzone_uds.sock --port 8086

# 发送一条请求（使用 socat）
printf '%s' '{
  "text": "UDS hello",
  "image": ["file:///path/to/img.jpg"],
  "cookies": {"uin":"o123456"}
}' | socat - UNIX-CONNECT:./qzone_uds.sock

# 浏览最近请求（预览图片/文本）
xdg-open http://localhost:8086 || true
```

返回值：`success`/`failed`。模拟器不会调用真实 QZone，仅记录并在 Web 页面展示最近请求。
