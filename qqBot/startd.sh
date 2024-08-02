#!/bin/bash
if pgrep -f "python3 ./getmsgserv/serv.py" > /dev/null
then
    echo "serv.py is already running"
else
    python3 ./getmsgserv/serv.py &
    echo "serv.py started"
fi

# Check if the Lagrange.OneBot process is running
if pgrep -f "./qqBot/Lagrange.OneBot" > /dev/null
then
    echo "Lagrange.OneBot is already running"
else
    nohup ./qqBot/Lagrange.OneBot &
    echo "Lagrange.OneBot started"
fi

while true; do
    sleep 10800
    pkill Lagrange.OneBot
    nohup ./qqBot/Lagrange.OneBot &
    echo 'LagrangeBot restarted'
done