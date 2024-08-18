# Arm平台安装指南
正常部署一切,LLonebot在arm上似乎不好用,建议用napcat

项目理论上可以使用Lagrange接口，如果你要用的话，也可以，把Lagrange的http端口设定为8083,http-post端口设定为8082，并允许本地访问,修改startd.sh使他启动lagrange,然后修改config,设定以下项目:
```
disable_qzone_autologin=true
enable_selenium_autocorrecttag_onstartup=false
use_selenium_to_generate_qzone_cookies=false
```


