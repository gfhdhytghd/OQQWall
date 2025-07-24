#!/bin/bash
set -e
IN_PORT=${NAPCAT_IN_PORT:-9000}
OUT_PORT=${NAPCAT_OUT_PORT:-9001}

# Ensure config files use custom ports
if [ ! -f oqqwall.config ]; then
  echo "http-serv-port=$IN_PORT" > oqqwall.config
  echo "manage_napcat_internal=false" >> oqqwall.config
else
  grep -q '^http-serv-port=' oqqwall.config && sed -i "s/^http-serv-port=.*/http-serv-port=$IN_PORT/" oqqwall.config || echo "http-serv-port=$IN_PORT" >> oqqwall.config
  grep -q '^manage_napcat_internal=' oqqwall.config && sed -i "s/^manage_napcat_internal=.*/manage_napcat_internal=false/" oqqwall.config || echo "manage_napcat_internal=false" >> oqqwall.config
fi
cat > AcountGroupcfg.json <<CFG
{
  "Test": {
    "mangroupid": "100",
    "mainqqid": "10001",
    "mainqq_http_port": "$OUT_PORT",
    "minorqqid": [],
    "minorqq_http_port": []
  }
}
CFG

bash main.sh &
MAIN_PID=$!

python3 tests/napcat_mock.py --in-port $IN_PORT --out-port $OUT_PORT
test_ret=$?

kill $MAIN_PID 2>/dev/null || true
pkill -f getmsgserv/serv.py 2>/dev/null || true
pkill -f qzone-serv-pipe.py 2>/dev/null || true
pkill -f sendcontrol.sh 2>/dev/null || true

if [ "$test_ret" -eq 0 ]; then
  echo "All tests passed"
else
  echo "Tests failed"
fi
exit $test_ret
