## 由于完全账户组的加入，OQQWall从v0.7开始不再提供QChatGPT信息快捷同步功能
项目自带一个QChatGPT子项目，如果您需要使用，请按照本文的方式配置。

所有信息请以[QChatGPT DOC](https://qchatgpt.rockchin.top/posts/config/)为准

注:这大概需要100m的额外运行内存

首先进入OQQWall文件夹,执行
```
git submodule update --init --recursive
source ./venv/bin/activate
pip3 install -r ./qqBot/QChatGPT/requirements.txt
```
然后请参考[QChatGPT DOC](https://qchatgpt.rockchin.top/posts/config/)
### QChatGPT的更多玩法请参考[QChatGPT DOC](https://qchatgpt.rockchin.top/posts/config/)