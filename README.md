# OQQWall
# 开放QQ校园墙自动运营系统
## 简介
本系统是一个校园墙自动运营系统，可以实现如下功能：
<br/>获取用户投稿消息，通过大语言模型实现自动分段，自动判断匿名与否
<br/>自动渲染图片，发到群中，通过群消息发送指令审核
<br/>自动发送到qq空间。

本系统的技术实现方式非常简陋，问题极多，作者屁都不会，创建过程大量使用chatgpt编写实现小功能的脚本，并最终由一个bash把所有东西都串起来。编写和测试平台是archlinux x64版本。

#### 目前系统处于非常早期的版本，完全不保证可用性。

已知问题如下：
<br/>错误的群审核指令会导致上一条指令被执行
<br/>拉格朗日机器人偶尔会抽风
<br/>使用qwen大语言模型的情况下，处理不了太长的帖子

# 使用方法
<br/>首先需要你注册两个qq号，一个作为主账号，一个作为辅助账号
<br/>主账号作为群主创建一个群聊，把墙管理员拉进来，并设定为群管理员。
<br/>目前仅在x64 archlinux上进行过测试其他系统要用的话可能要重装python venv并对bash脚本进行修改

<br/>请先安装QQ，google-chrome和chrome-drive，以及python3

克隆项目到任意位置，最好是用户文件夹中的某处，确保权限够用

进入OQQwall文件夹
创建python venv并安装依赖,注意这需要良好的网络环境
```
python -m venv ./
source ./venv/bin/activate
pip install --upgrade pip
pip install dashscope selenium re101 bs4

```

<br/>执行./qqBot/Lagrange.OneBot
<br/>扫码登陆主账号，记得勾选下次无需扫码
<br/>ctrl+c关闭拉格朗日机器人

<br/>执行python3 ./SendQzone/send.py login
<br/>在一分钟内打开文件夹内的文件"qrcode.png"并扫码登录（测试阶段，不稳定，建议使用辅助账号）
<br/>会报错,这是正常的

打开./SendQzone/qzonegettag
<br/>翻到60行
<br/>填写主账号到friendlist，辅助账号到my_qq
<br/>打开main.sh，填写管理群群号到group_id
<br/>打开getmsgserv/serv.py
<br/>找到第48行的if,填写管理群号到 == 和 and中间，群号两边记得留空格。
<br/>找到49行和51行的[CQ:at,qq=xxx]，用主账号qq号替代xxx

参考此文字，获取qwen api-key
<br/>https://help.aliyun.com/zh/dashscope/developer-reference/acquisition-and-configuration-of-api-key?spm=a2c4g.11186623.0.0.65fe46c1Q9s8Om
<br/>填入./getmsgserv/LM_work/sendtoLM.py 第6行的dashscope.api_key

注：确保你的api余额够用。

注：目前使用的模型是qwen2-72b-instruct，效果还行，有能力的可以自己换更牛逼的模型,或者自己测试一下哪个模型好用。

手动登陆主账号qq空间，发送一条说说，文案需要由#0开头，这是为了初始化编号系统
<br/>如果此帐号之前就是使用 #数字 方式进行编号，不需要进行这一步

启动主程序
<br/>打开QQ,登陆辅助账号
<br/>终端输入./main.sh 
<br/>然后，理论上，应该就可以用了。
<br/>注意ctrl+c关闭程序时,Lagrange.Onebot和serv.py不会一并关闭,需要手动终止进程

### 审核群使用方法：
<br/>墙会在有新消息时将渲染好的消息图片带着编号一起发到群中来
<br/>类似这样
<br/>校园墙：有常规消息
<br/>校园墙：[图片]
<br/>校园墙：[图片]
<br/>校园墙：348 请发送指令
<br/>管理员需要发送如下的命令信息
<br/>@主账号 编号 指令
<br/>“编号”是一个数字，这是机器人发来的说说编号，也是你想要处理的编号，注意，你不能对已经发送或丢弃的帖子进行操作。
<br/>指令有以下几种：
<br/>是：发送
<br/>否：机器跳过此条，人工去处理
<br/>当前版本等效于删
<br/>等：等待180秒，然后重新执行分段-渲染-审核流程，常用于稿件没发完的情况
<br/>删：从系统中删掉这个人的消息记录，常用于用户来找你聊天或者删帖等需要手动处理的情况
<br/>比如
@校园墙 348 是
<br/>将348号帖子发送出去
<br/>@校园墙 348 否
<br/>从系统中删掉这个人的消息记录,人工前往处理

QQ空间重新登陆:
<br/>理论上,机器人会在qq空间发送失败时(大多数时候是cookies过期)发<br/>送消息到群中要求重新登录
<br/>此时,发送指令 '@主账号 relogin 是'
<br/>机器人会发送一张二维码到群中,请用用来发送空间的账号扫码登陆
