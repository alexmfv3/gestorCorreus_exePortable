#!/bin/bash
# (re)arrenca el servidor simulat; desa el PID a /tmp/gc_srv.pid
for pid in $(ps -eo pid,args | awk '$2 ~ /python3/ && $3 == "tests/run_fake.py" {print $1}'); do kill $pid; done; sleep .4
cd "$(dirname "$0")/.."
GESTOR_CORREUS_HOME=/tmp/gc GESTOR_NO_UI=1 GESTOR_PORT=8765 nohup python3 tests/run_fake.py > /tmp/srv.log 2>&1 &
echo $! > /tmp/gc_srv.pid; sleep 1.5
