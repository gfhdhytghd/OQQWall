# 多账号协同运营简介与配置教程
## 简介
OQQWall系统在0.7.0版本加入了对于完整账号组配置协同运营的支持，可以实现从多个账号接收投稿信息，并在审核完毕后发送投稿到所属组的多个账户的qq空间。

## 配置
### onebot配置
副账号都需要开启一个额外的onebot,你需要启用http和http-post连接，开启http和http-post通讯，设定http监听端口和http-post端口（http端口，每个账户必须不一样，http-post端口，所有账号都需要一致）
### AcountGroupcfg.json 配置
AcountGroupcfg.json遵守标准json语法
想要增加更多副号，你需要填写minorqq_http_port，你可以在一个账号组中添加多个副号，中间用逗号隔开即可
想要增加一个组，你只需要多写一个Group表（注意每个组的名字不能相同），然后添上不同的qqid和port
{
    "MethGroup": {
      "mangroupid":"12345678",
      "mainqqid": "3456789",
      "mainqq_http_port":"8083",
      "minorqqid": [
        "4567890"
      ],
      "minorqq_http_port":[
        "8084"
      ]
    }，
    "EthGroup": {
      "mangroupid":"23456789",
      "mainqqid": "45678913",
      "mainqq_http_port":"8085",
      "minorqqid": [
        "56789087654",
        “45678909876”
      ],
      "minorqq_http_port":[
        "8086"
      ]
    }，
}

## 其他使用提示
无论哪个账号接受到投稿消息，投稿审核消息都将由主账号发送到群中
审核指令只能通过 @主账号 来发送
全局指令可以通过 @任何一个账号 来发送
重新登录指令，@哪个账号，哪个账号就会执行重新登录

无论你@哪个账号，指令回应都只会通过主账号发送到群中
