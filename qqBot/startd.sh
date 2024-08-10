#!/bin/bash
if pgrep -f "python3 ./getmsgserv/serv.py" > /dev/null
then
    echo "serv.py is already running"
else
    python3 ./getmsgserv/serv.py &
    echo "serv.py started"
fi

# Check if the Lagrange.OneBot process is running
if pgrep -f "qq" > /dev/null
then
    echo "OneBot is already running"
else
    nohup qq  &
    echo "OneBot started"
fi
commgroup_id=$(grep 'communicate-group' oqqwall.config | cut -d'=' -f2 | tr -d '"')
if [ -n "$commgroup_id" ]; then 
    echo "commgroup_id不为空,chatbot启动"
    
    if pgrep -f "ChatBotd.sh" > /dev/null
        then
            echo "OneBot is already running"
        else
            ./qqBot/ChatBotd.sh &
            echo "OneBot started"
    fi
fi


fi

