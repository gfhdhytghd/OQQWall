# OQQWall开放QQ校园墙自动运营系统
# 👍 稳定运行数百万秒 👍
## 目前系统已经有了基本的业务能力和错误处理能力，可以用在生产环境中
## [开源项目列表](doc/README_Proj_List.md)
## 额外说明
紧急修复以外的所有commit上传之前会在我自营墙上测试一段时间再发布
<br/>最稳定的版本永远是上一个次级版本的最后一个小版本
## 简介
本系统是一个校园墙自动运营系统，可以实现如下功能：
<br/>获取用户投稿消息，通过大语言模型实现自动分段，自动判断匿名与否
<br/>自动渲染图片，发到群中，通过群消息发送指令审核
<br/>自动发送到qq空间。
<br/>附加功能：
<br/>[校园群智能助手](https://github.com/gfhdhytghd/OQQWall/wiki/%E6%A0%A1%E5%9B%AD%E7%BE%A4%E6%99%BA%E8%83%BD%E5%8A%A9%E6%89%8B)
<br/>[多账号协同运营](https://github.com/gfhdhytghd/OQQWall/wiki/%E5%A4%9A%E8%B4%A6%E5%8F%B7%E5%8D%8F%E5%90%8C%E8%BF%90%E8%90%A5)

本系统专注于“墙”本身，适用于用户量5k以下的情况，致力于给用户提供QQ校园墙的无感的交互
<br/>微信短时间内不会支持，因为没有找到linux能用的，好用的api。

本系统的技术实现方式不是很优雅，创建过程大量使用chatgpt编写实现小功能的脚本，并最终由一个bash把所有东西都串起来，不过他确实能跑起来。
<br/>编写和测试平台是阿里云的ubuntu 22.04 x64 UEFI版本。

本系统拥有处理并发的能力，允许的最小投稿时间间隔是无限小，最大并行处理能力取决于你的电脑内存大小和管理员响应速度。平均一个稿件从收到首条消息到发出要三分钟。

已知问题如下：
<br/>发件流程人在回路，管理不在线会导致帖子积压
<br/>稿件过多容易超出系统承载能力
<br/>无法Ai审核图片内容
<br/>没有历史消息处理逻辑，onebot下线过程中的积压投稿无法处理

# <div align=center >文档</div>
### <div align=center > [快速开始](https://github.com/gfhdhytghd/OQQWall/wiki/%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B) | [全部文档](https://github.com/gfhdhytghd/OQQWall/wiki)</div>
