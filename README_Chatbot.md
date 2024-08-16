项目自带一个QChatGPT子项目，如果您需要使用，请按照本文的方式配置。

所有信息请以[QChatGPT DOC](https://qchatgpt.rockchin.top/posts/config/)为准

首先进入OQQWall文件夹,执行
```
git submodule update --init --recursive
pip3 install -r ./qqBot/QChatGPT/requirements.txt
```
<br/>在oqqwall.config中，设定communicate-group群号为QChatGPT要运行的群，并把主账号拉进去


配置你的napcat/LLOneBot/Lagrange,开启反向ws,url: ws://127.0.0.1:8080/ws
<br/>注:websocket端口号可以通过编辑./qqBot/QChatGPT/data/config/platform.json 中"adapter": "aiocqhttp"同一组中的port项目更改

在./qqBot/QChatGPT/data/metadata/llm-models.json中加入一项：
```
{
    "name": "qwen2-72b-instruct",
    "tool_call_supported": true,
    "vision_supported": false,
    "requester": "openai-chat-completions",
    "token_mgr": "openai"
},
```
编辑./qqBot/QChatGPT/data/config/provider.json
<br/>修改requester项目下的子项openai-chat-completions为:
```
"openai-chat-completions": {
    "base-url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "args": {},
    "timeout": 120
}
```
注:url和群号白名单,会在main.sh启动时自动由oqqwall.config同步过去
然后杀死并重新启动main.sh