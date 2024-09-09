## 尽管这玩意可以2006年之后的几乎任何个人PC上运行，但是考虑到各家廉价云服务器那可怜的配置，我还是来写一个吧。
### 前言
只要能把这玩意装上并启动的机器，运行中它的CPU就基本不可能吃满，主要问题出在内存。
<br/>内存需求大概是这样的：
<br/>桌面环境:20～500m
<br/>使用默认配置：300m
<br⁄>增加一个副号：根据onebot服务的不同，100m~300m
<br/>启用任何selenium相关功能：+300m（此时可以转为使用Lagrange而非QQNT+napcat/LLOnebot）
<br/>收发件瞬间:+150m（chrome --print-to-pdf和magick convert）
<br/>虽然内存不太可能吃满，但是Linux下如果留给cache的空间不足，是会非常卡顿的。

### 优化可以通过以下几个方面进行：

#### 桌面环境：
<br/>本系统不要求桌面环境,删掉即可

#### 停用所有selenium：
设定config:
```
enable_selenium_autocorrecttag_onstartup=false
use_selenium_to_generate_qzone_cookies=false
```
<br/>保存关闭

QQ onebot实现:
**不建议这么干，没测试过**
你可以切换到lagrange来降低内存消耗
暂时没有实现改配置直接切换lagrange,目前,如果你要用的话，也可以，把Lagrange的http端口设定为8083,http-post端口设定为8082，并允许本地访问。
<br/>注：切换到lagrange之后不支持自动登录空间,所以建议:
```
disable_qzone_autologin=true
```

#### Python运行时：
<br/>你可以尝试使用cython编译代码中的各个python脚本，这大概可以给你省下不到100m的内存,并减轻发件时的CPU占用

#### 发行版：
<br/>我建议使用尽可能轻量的发行版作为系统的承载平台，并尽可能的关闭不需要的服务和删除软件包，通常我推荐使用ArchLinux。

#### zram和swap
<br/>上网搜索你使用的发行版该怎么开zram和swap,并开启一个和内存一样大小的zram和一个内存一样大小的swap
<br/>注意如果你的硬盘性能不咋地,不要开swap（特别是云服务器）
