# Arm平台安装指南
正常部署一切，安装除了chrome和chromedrive以外的一切

去largrange.onebot的官方release下载最新的arm版本，替换./qqBot/largrange.onebot
打开main.sh,删掉getnumnext函数下的
```
    getnumcmd='python3 ./SendQzone/qzonegettag.py'
    output=$(eval $getnumcmd)
    if echo "$output" | grep -q "Log Error!"; then
        sendmsggroup 空间获取失败,启动备用算法,请检查qq桌面端登录状态
        echo 空间获取失败,启动备用算法,请检查qq桌面端登录状态
```
和
```
    else
        numnow=$( cat ./numb.txt )
        numnext=$[ numnow + 1 ]
        echo 正常情况
    fi
    echo numnext=$numnext
```
保存关闭

创建一个文件./qqBot/command/commands.txt,然后往里面输点东西
```
mkdir ./qqBot/command/
touch ./qqBot/command/commands.txt
eecho ' 1 删' >> ./qqBot/command/commands.txt
```
然后应该就可以用了

由于arm平台上我没有找到实时在线获取的编号的方法，只能用备用的本地计算的方法，所以请确保你的一切操作都尽量在bot下执行。

