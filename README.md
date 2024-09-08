# OQQWall开放QQ校园墙自动运营系统
# 👍 稳定运行数百万秒 👍
## 目前系统已经有了基本的业务能力和错误处理能力，可以用在生产环境中
## [开源项目列表](README_Proj_List.md)
## 额外说明
紧急修复以外的所有commit上传之前会在我自营墙上测试一段时间再发布
<br/>最稳定的版本永远是上一个次级版本的最后一个小版本
## 简介
本系统是一个校园墙自动运营系统，可以实现如下功能：
<br/>获取用户投稿消息，通过大语言模型实现自动分段，自动判断匿名与否
<br/>自动渲染图片，发到群中，通过群消息发送指令审核
<br/>自动发送到qq空间。
<br/>附加功能：
<br/>[校园群智能助手](./README_Chatbot.md)
<br/>[多账号协同运营](./README_mutipleqq.md)

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

# 使用方法
<br/>首先你得有个系统比较新的Linux系统的电脑,并且确保这台机器的网络条件不错,收发qq和访问空间不会长时间加载
<br/>如果非要用云服务器的话建议腾讯云深圳
<br/>首先需要你有一个校园墙主账号
<br/>主账号作为群主创建一个群聊，把墙管理员拉进来，并设定为群管理员。
<br/>目前仅在x64 archlinux和ubuntu2204上进行过测试，其他系统要用的话可能要修改一些东西（你最好有基础的bash和python编写能力）
#### arm用户请阅读: [Arm安装指南](README_ARM.md)
#### 低性能用户请阅读：[性能优化指南](README_performance.md)
#### 启用ChatBot请阅读: [校园群智能助手](./README_Chatbot.md)
<br/>请先安装QQ，napcat无头ntqq框架或者LLonebot框架,google-chrome，jq, python3，dotnet框架,ImageMagick(某些发行版[deb系]这个玩意默认没法处理pdf,需要调整policy配置，自己搜索怎么搞)

[napcat官方文档](https://napneko.github.io/zh-CN/)
<br/>对于rpm/deb系,你们可以通过执行
```
curl -o napcat.sh https://fastly.jsdelivr.net/gh/NapNeko/NapCat-Installer@master/script/install.sh && sudo bash napcat.sh
```
来进行一键安装qq和napcat
<br/>更多安安装方式请参考[napcat官方文档](https://napneko.github.io/zh-CN/)

然后启动napcat,扫码登陆账号，最好勾选下次无需扫码
（如果你有多个账号，那么你需要每个账户都登录一遍）

然后请参考napcat或LLonebot的官方文档,开启http和http-post通讯，设定http监听端口和http-post端口

注:你可能需要自己debug一下napcat才能用,你可以在填写完OQQWall配置文件(见下文)之后单独启动serv.py和napcat来监测

注：如果你要使用LLOneBot,请在config中设定use_LLOnebot=true(不建议使用LLOnebot)
<br/>注：如果你内存紧张想使用Lagrange,请自行调整startd.sh中的内容，然后把config中的use_lite_tag_generator设定为true

接下来,克隆项目到任意位置，最好是用户文件夹中的某处，确保权限够用

进入OQQwall文件夹

执行以下指令，创建python venv并安装依赖,注意这需要良好的网络环境或者换源
```
python -m venv ./venv/
source ./venv/bin/activate
pip install --upgrade pip
pip install dashscope re101 bs4
```
如果你想要使用selenium(现在不建议使用）,你还需要
```
pip install selenium
```


参考此文章，获取qwen api-key
<br/>https://help.aliyun.com/zh/dashscope/developer-reference/acquisition-and-configuration-of-api-key?spm=a2c4g.11186623.0.0.65fe46c1Q9s8Om
<br/>具体填写方式将在下文介绍

注：确保你的api余额够用。

注：目前使用的模型是qwen2-72b-instruct，效果还行，有能力的可以自己换更牛逼的模型,或者自己测试一下哪个模型好用。

打开程序文件夹下的oqqwall.config,按说明填入数据
**⚠️注意，配置文件不可以留空行或者加注释⚠️**
<br/>说明:
```
#所有东西请填到双引号里
http-serv-port=
#填入你为onebot设定的http-post端口
apikey="sk-"
#填入qwen api key
#sk-xxxxxx,"sk"也要填进来
‼以下内容建议维持默认，我不会测试非默认选项的运行情况‼
disable_qzone_autologin=true⁄false
#是否允许自动登录,启用后系统将在说说发送错误时尝试自动登录
enable_selenium_autocorrecttag_onstartup=true/false
是否在启动时使用selenium获取空间中的说说以校准编号，建议false
use_selenium_to_generate_qzone_cookies=true/false
是否使用selenium获取qq空间cookies，无特殊需求不建议启用
use_LLOnebot=true/false
#是否使用LLOnebot而非napcat
max_attempts_qzone_autologin=3
#最大qq空间发送尝试次数,自动登录超过次数限制后将切换为手动登陆
```
打开程序文件夹下的AcountGroupcfg.json,按说明填入数据
**⚠️注意，此配置文件内不可以加注释⚠️**
```
{
  "MethGroup": {
  #默认组名，可以改成你喜欢的
    "mangroupid":"xxx",
    #管理群群号
    "mainqqid": "",
    #主账号QQ号
    "mainqq_http_port":"xxx",
    #主账号http端口（onebot设定的那个）
    "minorqqid": [
      ""
    ],
    副账号qq号（不需要的留空即可）
    "minorqq_http_port":[
      ""
    ]
    副账号http端口（不需要的留空即可）
  }
}
```
如果你需要更多账号组和多账号协同运营功能，请查看：[多账号协同运营](./README_mutipleqq.md)

启动主程序
<br/>打开QQ,登陆主账号
<br/>终端输入./main.sh 
<br/>如果你的墙之前发的稿件带有编号的话，请打开./numfinal.txt，然后在里面输入下一条稿件的编号。如果不进行这一步，系统发出的第一条稿件会从编号#1开始。
<br/>然后，理论上，应该就可以用了。
<br/>注意ctrl+c关闭程序时,qq和serv.py不会一并关闭,需要手动终止进程

### 审核群使用方法：
<br/>墙会在有新消息时将渲染好的消息图片带着编号一起发到群中来
<br/>类似这样
<br/>校园墙：有常规消息
<br/>校园墙：[图片]
<br/>校园墙：[图片]
<br/>校园墙：348 请发送指令

管理员需要发送如下的命令信息
<br/>@主账号 编号 指令
<br/>**指令详情请请在管理群内发送 @主账号 帮助 来获取**
<br/>用例：
@校园墙 348 是
<br/>将348号帖子发送出去
<br/>@校园墙 348 否
<br/>从系统中删掉这个人的消息记录,人工前往处理

QQ空间重新登陆:
<br/>**启用自动重新登录之后系统会尝试自动登录qq空间**
<br/>机器人会在qq空间发送失败时(大多数时候是cookies过期)发<br/>送消息到群中要求重新登录
<br/>此时,发送指令 '@主账号 relogin 是'
<br/>机器人会发送一张二维码到群中,请用用来发送空间的账号扫码登陆
