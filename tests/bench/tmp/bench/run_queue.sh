#!/bin/bash
T=/tmp/target
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); reset_users
NOSTUB=1 CLIENT="python3 /tmp/bench/queue_test.py" bash /tmp/bench/run.sh
rm -f /tmp/target/usr/local/bin/apt-get
