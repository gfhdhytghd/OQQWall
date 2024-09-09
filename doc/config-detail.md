# config具体说明:
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