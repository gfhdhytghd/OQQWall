#OQQWall
#开放QQ校园墙自动运营系统
##简介
本系统是一个校园墙自动运营系统，可以实现如下功能：
获取用户投稿消息，通过大语言模型实现自动分段，自动判断匿名与否
自动渲染图片，发到群中，通过群消息发送指令审核
自动发送到qq空间。

本系统的技术实现方式非常简陋，问题极多，创建过程大量使用chatgpt编写实现小功能的脚本，并最终由一个bash把所有东西都串起来。编写和测试平台是archlinux x64版本。

###目前系统处于非常早期的版本，完全不保证可用性。

已知问题如下：
群消息会导致发稿流程激活
错误的群审核指令会导致上一条指令被执行
qq空间两天就会退出登录
拉格朗日机器人偶尔会抽风
“否”指令有一些问题
使用qwen大语言模型的情况下，处理不了太长的帖子

使用方法
首先需要你注册两个qq号，一个作为主账号，一个作为辅助账号
主账号作为群主创建一个群聊，把墙管理员拉进来，并设定为群管理员。
目前仅在x64 archlinux上进行过测试其他系统要用的话可能要重装python venv并对bash脚本进行修改


克隆项目到任意位置，最好是用户文件夹中的某处，确保权限够用

进入OQQwall文件夹

执行./qqBot/Lagrange.OneBot
扫码登陆，记得勾选下次无需扫码
ctrl+c关闭拉格朗日机器人

执行python3 ./SendQzone/send.py '测试使用程序发送一条消息' ./getmsgserv/post-step5/
在一分钟内打开文件夹内的文件"qrcode.png"并扫码登录（测试阶段，不稳定，建议使用辅助账号）
查看说说有没有发出去

打开./SendQzone/qzonegettag
翻到60行
填写主账号到driendlist，辅助账号到my_qq
打开main.sh，填写管理群群号到group_id
打开getmsgserv/serv.py
找到第49行的if,填写管理群号到 == 和 and中间，群号两边记得留空格。
找到49行和51行的[CQ:at,qq=xxx]，用主账号qq号替代xxx

参考此文字，获取qwen api-key
https://help.aliyun.com/zh/dashscope/developer-reference/acquisition-and-configuration-of-api-key?spm=a2c4g.11186623.0.0.65fe46c1Q9s8Om
填入./getmsgserv/LM_work/sendtoLM.py 第6行的dashscope.api_key

注：确保你的api余额够用。

注：目前使用的模型是qwen2-72b-instruct，效果还行，有能力的可以自己换更牛逼的模型。

手动登陆主账号qq空间，发送一条说说，文案需要由#0开头，这是为了初始化编号系统
如果此帐号之前就是使用 #数字 方式进行编号，不需要进行这一步

启动主程序
./main.sh 
然后，理论上，应该就可以用了。

###审核群使用方法：
墙会在有新消息时将渲染好的消息图片带着编号一起发到群中来
类似这样
校园墙：有常规消息
校园墙：[图片]
校园墙：[图片]
校园墙：348 是否继续发送
管理员需要发送如下的命令信息
@主账号 编号 指令
“编号”是一个数字，这是机器人发来的说说编号，也是你想要处理的编号，注意，你不能对已经发送或丢弃的帖子进行操作。
指令有以下几种：
是：发送
否：机器跳过此条，人工去处理
当前版本不建议使用此指令，有bug,建议用“删”替代
等：等待180秒，然后重新执行分段-渲染-审核流程，常用于稿件没发完的情况
删：从系统中删掉这个人的消息记录，常用于用户来找你聊天或者删帖等需要手动处理的情况
比如

@校园墙 348 是
将348号帖子发送出去
@校园墙 348 否
不删除任何东西，跳过此条

