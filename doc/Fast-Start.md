# 快速开始
## 开始前准备
准备至少一个校园墙用的QQ号
<br/>创建一个群聊，把墙账号和墙管理员拉进来，墙管理员要设定为群管理员
<br/>目前仅在x64 archlinux和ubuntu2204上进行过测试，其他系统要用的话可能要修改一些东西（你最好有基础的bash和python编写能力）
## 开始安装
打开一个Linux系统，进入终端
<br/>安装以下包：google-chrome，jq, python3，dotnet框架,<br/>ImageMagick(某些发行版[deb系]默认没法处理pdf,需要调整policy配置，自己搜索怎么搞)
安装napcat
<br/>**[napcat官方文档](https://napneko.github.io/zh-CN/)**
<br/>对于rpm/deb系,你们可以通过执行
```
curl -o napcat.sh https://fastly.jsdelivr.net/gh/NapNeko/NapCat-Installer@master/script/install.sh && sudo bash napcat.sh
```
然后启动napcat（怎么启动看napcat文档）,扫码登陆账号，最好勾选下次无需扫码
（如果你有多个账号，那么你需要每个账户都登录一遍）

然后请参考napcat官方文档,开启http和http-post通讯，设定http监听端口和http-post端口（随便你设定啥，我设定的一个8082一个8083）

克隆项目到任意位置
```
git clone https://github.com/gfhdhytghd/OQQWall.git
```
进入文件夹
执行以下指令，创建python venv并安装依赖,注意这需要良好的网络环境或者换源
```
python -m venv ./venv/
source ./venv/bin/activate
pip install --upgrade pip
pip install dashscope re101 bs4
```
参考[此文章](https://help.aliyun.com/zh/dashscope/developer-reference/acquisition-and-configuration-of-api-key?spm=a2c4g.11186623.0.0.65fe46c1Q9s8Om)，获取qwen api-key

打开程序文件夹下的oqqwall.config,按说明填入数据
**⚠️注意，配置文件不可以留空行或者加注释⚠️**
```
#所有东西请填到双引号里
http-serv-port=
#填入你为onebot设定的http-post端口
apikey="sk-"
#填入qwen api key
#sk-xxxxxx,"sk"也要填进来
⚠️剩下的维持默认⚠️
```
**config详解，请查看：[config详解](./config-detail.md)**
<br/>打开程序文件夹下的AcountGroupcfg.json,按说明填入数据
<br/>**⚠️注意，此配置文件内不可以加注释⚠️**
```
{
  "MethGroup": {
  #默认组名，可以改成你喜欢的
    "mangroupid":"xxx",
    #管理群群号更多账号组和多账号协同运营功能，请查看：
    "mainqqid": "",
    #主账号QQ号
    "mainqq_http_port":"xxx",
    #主账号http端口（onebot设定的那个）
    "minorqqid": [
      ""
    ],
    副账号qq号（留空即可）
    "minorqq_http_port":[
      ""
    ]
    副账号http端口（留空即可）
  }
}
```
**更多账号组和多账号协同运营功能，请查看：[多账号协同运营](./README_mutipleqq.md)**


## 启动主程序
<br/>打开QQ,登陆主账号
<br/>终端输入./main.sh 

然后请查看[审核群使用方法](./reviewgroup.md)

其他进阶文档：
#### arm用户请阅读: [Arm安装指南](README_ARM.md)
#### 低性能用户请阅读：[性能优化指南](README_performance.md)
#### 启用ChatBot请阅读: [校园群智能助手](./README_Chatbot.md)
