#!/bin/bash
if pgrep -f "python3 ./getmsgserv/serv.py" > /dev/null
then
    echo "serv.py is already running"
else
    python3 ./getmsgserv/serv.py &
    echo "serv.py started"
fi

# Check if the Lagrange.OneBot process is running
if pgrep -f "QQ" > /dev/null
then
    echo "OneBot is already running"
else
    nohup xvfb-run -a qq --no-sandbox -q &
    echo "OneBot started"
fi

while true; do
    sleep 10800
    pkill qq
    nohup xvfb-run -a qq --no-sandbox -q &
    echo 'NapCapQQBot restarted'
done