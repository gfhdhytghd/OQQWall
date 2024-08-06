## 尽管这玩意可以2006年之后的几乎任何个人PC上运行，但是考虑到各家廉价云服务器那可怜的配置，我还是来写一个吧。
只要能把这玩意装上并启动的机器，运行中它的CPU就基本不可能吃满，主要问题出在内存。
内存需求大概是这样的：
使用全功能：600m
使用次等编号算法：300m（此时可以不把qq挂着）

虽然内存不太可能吃满，但是Linux下如果留给cache的空间不足，是会非常卡顿的。

优化可以通过以下几个方面进行：

桌面环境：
 <br/>全功能版本的运行需要一个可用的桌面，我建议越轻量的越好，我建议使用i3wm，sway，hyprland或者wston,这几个实在玩不明白的，xfce也行
在使用次等编号算法的情况下，桌面环境可以不安装，这可以给你省下大量内存。

使用次等编号算法的方法：

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

Python运行时：
 <br/>你可以尝试使用cython编译代码中的各个python脚本，这大概可以给你省下不到100m的内存

发行版：
 <br/>我建议使用尽可能轻量的发行版作为系统的承载平台，并尽可能的关闭不需要的服务和删除软件包，通常我推荐使用ArchLinux。